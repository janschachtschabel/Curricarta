"""An admin creates accounts and hands out, revokes and blocks their tokens; all audited."""

import asyncio
import io
from collections.abc import Iterator
from typing import Any

import httpx2
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.logging import configure_logging
from app.db.accounts import create_account, issue_key
from app.db.migrate import migrate
from tests.support import FAKE_PEPPER, make_settings, selector_client

pytestmark = pytest.mark.pg

PUBLIC = "http://testserver:8000"


async def seed(url: str, name: str, roles: list[str]) -> str:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
        account = await create_account(connection, name, roles)
        _, token = await issue_key(connection, account, "seed", FAKE_PEPPER)
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def fetch(url: str, query: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(query).fetchall()


@pytest.fixture
def migrated(database_url: str) -> str:
    migrate(database_url)
    return database_url


@pytest.fixture
def log(restore_logging: None) -> io.StringIO:
    stream = io.StringIO()
    configure_logging("INFO", "json", stream=stream)
    return stream


@pytest.fixture
def client(migrated: str) -> Iterator[TestClient]:
    with selector_client(create_app(make_settings(database_url=migrated)), base_url=PUBLIC) as test_client:
        yield test_client


@pytest.fixture
def admin(migrated: str) -> dict[str, str]:
    return bearer(asyncio.run(seed(migrated, "Admin", ["admin"]), loop_factory=asyncio.SelectorEventLoop))


def test_an_admin_creates_an_account_and_hands_out_its_token(
    client: TestClient, admin: dict[str, str], migrated: str, log: io.StringIO
) -> None:
    created = client.post(
        "/api/v1/accounts", json={"name": "Lehrkraft Optik", "roles": ["nutzer"]}, headers=admin
    )
    account = created.json()
    issued = client.post(f"/api/v1/accounts/{account['id']}/keys", json={"label": "Laptop"}, headers=admin)
    token = issued.json()["token"]

    me = client.get("/api/v1/me", headers=bearer(token))

    assert created.status_code == 201
    assert (account["name"], account["roles"], account["disabled"]) == ("Lehrkraft Optik", ["nutzer"], False)
    assert issued.status_code == 201
    assert issued.headers["Cache-Control"] == "no-store"
    assert me.json() == {"id": account["id"], "name": "Lehrkraft Optik", "roles": ["nutzer"]}
    actions = [action for (action,) in fetch(migrated, "SELECT action FROM audit_log ORDER BY id")]
    assert actions == ["account.create", "key.issue"]
    assert token not in str(fetch(migrated, "SELECT row_to_json(a)::text FROM audit_log a"))
    assert token not in log.getvalue()


def test_only_an_admin_manages_accounts(client: TestClient, migrated: str) -> None:
    user = bearer(
        asyncio.run(seed(migrated, "Lehrkraft", ["nutzer"]), loop_factory=asyncio.SelectorEventLoop)
    )

    assert (
        client.post("/api/v1/accounts", json={"name": "X", "roles": ["admin"]}, headers=user).status_code
        == 403
    )
    assert client.post("/api/v1/accounts", json={"name": "X", "roles": ["admin"]}).status_code == 401
    reads = [
        "/api/v1/accounts",
        f"/api/v1/accounts/{me_id(client, user)}",
        f"/api/v1/accounts/{me_id(client, user)}/keys",
        # an unknown one too: 403 before any 404, so a non-admin learns not which accounts exist
        "/api/v1/accounts/01890000-0000-7000-8000-000000000000",
        "/api/v1/accounts/01890000-0000-7000-8000-000000000000/keys",
    ]
    assert [client.get(path, headers=user).status_code for path in reads] == [403] * 5
    assert [client.get(path).status_code for path in reads] == [401] * 5


def test_an_admin_lists_the_accounts_with_their_roles_and_whether_blocked(
    client: TestClient, admin: dict[str, str]
) -> None:
    editor = client.post(
        "/api/v1/accounts", json={"name": "Redaktion", "roles": ["redaktion", "nutzer"]}, headers=admin
    ).json()
    blocked = client.post(
        "/api/v1/accounts", json={"name": "Gesperrt", "roles": ["nutzer"]}, headers=admin
    ).json()
    client.post(f"/api/v1/accounts/{blocked['id']}/keys", json={}, headers=admin)
    client.patch(f"/api/v1/accounts/{blocked['id']}", json={"disabled": True}, headers=admin)

    listed = client.get("/api/v1/accounts", headers=admin)

    assert listed.status_code == 200
    page = listed.json()
    assert (page["total"], page["limit"], page["offset"]) == (3, 50, 0)
    shown = [(entry["name"], entry["roles"], entry["disabled"]) for entry in page["accounts"]]
    assert shown == [
        ("Admin", ["admin"], False),
        ("Gesperrt", ["nutzer"], True),
        ("Redaktion", ["nutzer", "redaktion"], False),
    ]
    assert page["accounts"][2]["id"] == editor["id"]
    assert all(entry["created_at"] for entry in page["accounts"])
    one = client.get(f"/api/v1/accounts/{blocked['id']}", headers=admin)
    assert one.json() == page["accounts"][1]


def test_the_list_comes_in_pages_and_says_how_many_there_are(
    client: TestClient, admin: dict[str, str]
) -> None:
    for name in ("berta", "Carla", "anna"):
        client.post("/api/v1/accounts", json={"name": name, "roles": ["nutzer"]}, headers=admin)

    first = client.get("/api/v1/accounts", params={"limit": 2}, headers=admin).json()
    second = client.get("/api/v1/accounts", params={"limit": 2, "offset": 2}, headers=admin).json()
    too_many = client.get("/api/v1/accounts", params={"limit": 201}, headers=admin)

    assert [entry["name"] for entry in first["accounts"]] == ["Admin", "anna"]
    assert [entry["name"] for entry in second["accounts"]] == ["berta", "Carla"]
    assert (first["total"], second["total"], second["offset"]) == (4, 4, 2)
    assert too_many.status_code == 422


def test_an_admin_reads_an_account_s_keys_and_never_a_token_or_a_hash(
    client: TestClient, admin: dict[str, str], migrated: str, log: io.StringIO
) -> None:
    account = client.post(
        "/api/v1/accounts", json={"name": "Eins", "roles": ["nutzer"]}, headers=admin
    ).json()
    issued = client.post(f"/api/v1/accounts/{account['id']}/keys", json={"label": "Laptop"}, headers=admin)

    keys = client.get(f"/api/v1/accounts/{account['id']}/keys", headers=admin)

    assert keys.status_code == 200
    [entry] = keys.json()
    assert set(entry) == {"id", "label", "created_at", "last_used_at", "revoked_at"}
    assert (entry["id"], entry["label"]) == (issued.json()["id"], "Laptop")
    hashes = [bytes(stored).hex() for (stored,) in fetch(migrated, "SELECT key_hash FROM api_key")]
    assert "curricarta_" not in keys.text
    assert len(hashes) == 2 and not any(hashed in keys.text.lower() for hashed in hashes)
    assert issued.json()["token"] not in log.getvalue()


def test_a_revoked_key_is_listed_with_when_it_was_revoked_and_a_used_one_with_when(
    client: TestClient, admin: dict[str, str]
) -> None:
    account = client.post(
        "/api/v1/accounts", json={"name": "Eins", "roles": ["nutzer"]}, headers=admin
    ).json()
    revoked = client.post(f"/api/v1/accounts/{account['id']}/keys", json={}, headers=admin).json()
    used = client.post(f"/api/v1/accounts/{account['id']}/keys", json={}, headers=admin).json()
    client.delete(f"/api/v1/keys/{revoked['id']}", headers=admin)
    client.get("/api/v1/me", headers=bearer(used["token"]))

    keys = {
        entry["id"]: entry
        for entry in client.get(f"/api/v1/accounts/{account['id']}/keys", headers=admin).json()
    }

    assert keys[revoked["id"]]["revoked_at"] is not None and keys[revoked["id"]]["last_used_at"] is None
    assert keys[used["id"]]["last_used_at"] is not None and keys[used["id"]]["revoked_at"] is None


def test_an_unknown_account_has_nothing_to_read(client: TestClient, admin: dict[str, str]) -> None:
    nobody = "01890000-0000-7000-8000-000000000000"

    answers = [
        client.get(path, headers=admin)
        for path in (f"/api/v1/accounts/{nobody}", f"/api/v1/accounts/{nobody}/keys")
    ]

    assert [(answer.status_code, answer.json()["code"]) for answer in answers] == [(404, "no_account")] * 2


def test_a_second_account_of_the_same_name_is_refused(client: TestClient, admin: dict[str, str]) -> None:
    client.post("/api/v1/accounts", json={"name": "Redaktion", "roles": ["redaktion"]}, headers=admin)

    again = client.post("/api/v1/accounts", json={"name": "redaktion", "roles": ["nutzer"]}, headers=admin)

    assert again.status_code == 409
    assert again.json()["code"] == "conflict"


def test_an_account_whose_audit_entry_fails_is_not_created(
    migrated: str, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # one transaction: no account without its entry, and the same request passes once the cause is gone
    async def broken(*args: Any) -> None:
        raise psycopg.errors.DiskFull("the audit entry could not be written")

    body = {"name": "Redaktion", "roles": ["redaktion"]}
    app = create_app(make_settings(database_url=migrated))
    with selector_client(app, base_url=PUBLIC, raise_server_exceptions=False) as failing:
        with monkeypatch.context() as patched:
            patched.setattr("app.api.accounts.store.record_audit", broken)
            assert failing.post("/api/v1/accounts", json=body, headers=admin).status_code >= 500

        assert fetch(migrated, "SELECT count(*) FROM account WHERE name = 'Redaktion'") == [(0,)]
        assert failing.post("/api/v1/accounts", json=body, headers=admin).status_code == 201


@pytest.mark.parametrize(
    "body",
    [{"name": "", "roles": ["nutzer"]}, {"name": "X", "roles": []}, {"name": "X", "roles": ["superuser"]}],
    ids=["empty-name", "no-role", "unknown-role"],
)
def test_an_account_needs_a_name_and_known_roles(
    client: TestClient, admin: dict[str, str], body: dict[str, Any]
) -> None:
    assert client.post("/api/v1/accounts", json=body, headers=admin).status_code == 422


def test_a_revoked_token_and_a_blocked_account_lose_access(client: TestClient, admin: dict[str, str]) -> None:
    account = client.post(
        "/api/v1/accounts", json={"name": "Eins", "roles": ["nutzer"]}, headers=admin
    ).json()
    first = client.post(f"/api/v1/accounts/{account['id']}/keys", json={}, headers=admin).json()
    second = client.post(f"/api/v1/accounts/{account['id']}/keys", json={}, headers=admin).json()

    assert client.delete(f"/api/v1/keys/{first['id']}", headers=admin).status_code == 204
    assert client.get("/api/v1/me", headers=bearer(first["token"])).status_code == 401
    assert client.get("/api/v1/me", headers=bearer(second["token"])).status_code == 200

    blocked = client.patch(f"/api/v1/accounts/{account['id']}", json={"disabled": True}, headers=admin)
    assert blocked.json()["disabled"] is True
    assert client.get("/api/v1/me", headers=bearer(second["token"])).status_code == 401
    client.patch(f"/api/v1/accounts/{account['id']}", json={"disabled": False}, headers=admin)
    assert client.get("/api/v1/me", headers=bearer(second["token"])).status_code == 200


def test_unknown_accounts_and_keys_are_not_found(client: TestClient, admin: dict[str, str]) -> None:
    nobody = "01890000-0000-7000-8000-000000000000"

    assert client.post(f"/api/v1/accounts/{nobody}/keys", json={}, headers=admin).status_code == 404
    assert client.delete(f"/api/v1/keys/{nobody}", headers=admin).status_code == 404
    assert (
        client.patch(f"/api/v1/accounts/{nobody}", json={"disabled": True}, headers=admin).status_code == 404
    )


def test_me_needs_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/me").status_code == 401


def me_id(client: TestClient, headers: dict[str, str]) -> str:
    return str(client.get("/api/v1/me", headers=headers).json()["id"])


def test_the_last_admin_key_cannot_be_revoked(
    client: TestClient, admin: dict[str, str], migrated: str
) -> None:
    [(key_id,)] = fetch(migrated, "SELECT id FROM api_key")

    refused = client.delete(f"/api/v1/keys/{key_id}", headers=admin)

    assert refused.status_code == 409
    assert client.get("/api/v1/me", headers=admin).status_code == 200


def test_the_last_admin_cannot_block_themselves(client: TestClient, admin: dict[str, str]) -> None:
    refused = client.patch(f"/api/v1/accounts/{me_id(client, admin)}", json={"disabled": True}, headers=admin)

    assert refused.status_code == 409
    assert client.get("/api/v1/me", headers=admin).status_code == 200


def test_with_a_second_admin_the_first_one_may_go(client: TestClient, admin: dict[str, str]) -> None:
    other = client.post(
        "/api/v1/accounts", json={"name": "Zweite Admin", "roles": ["admin"]}, headers=admin
    ).json()
    client.post(f"/api/v1/accounts/{other['id']}/keys", json={}, headers=admin)

    blocked = client.patch(f"/api/v1/accounts/{me_id(client, admin)}", json={"disabled": True}, headers=admin)

    assert blocked.status_code == 200


@pytest.mark.anyio
async def test_two_admins_blocking_each_other_at_once_leave_one(migrated: str) -> None:
    # each would see the other still active and pass; the lock lets one through, then refuses
    app = create_app(make_settings(database_url=migrated, db_pool_min_size=4, db_pool_max_size=4))
    first, second = await seed(migrated, "Erste", ["admin"]), await seed(migrated, "Zweite", ["admin"])
    ids = {name: account for account, name in fetch(migrated, "SELECT id, name FROM account")}
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url=PUBLIC) as client,
    ):
        await app.state.pool.wait(timeout=10)
        answers = await asyncio.gather(
            client.patch(f"/api/v1/accounts/{ids['Zweite']}", json={"disabled": True}, headers=bearer(first)),
            client.patch(f"/api/v1/accounts/{ids['Erste']}", json={"disabled": True}, headers=bearer(second)),
        )

    assert sorted(answer.status_code for answer in answers) == [200, 409]
