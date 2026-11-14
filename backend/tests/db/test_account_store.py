"""Accounts, roles and API keys in the database; keys only as their hash."""

from collections.abc import AsyncIterator

import psycopg
import pytest

from app.core.tokens import token_hash
from app.db.accounts import (
    AccountExists,
    admin_exists,
    create_account,
    issue_key,
    keys_of,
    list_accounts,
    principal_for,
    recent_failures,
    record_audit,
    record_failure,
    revoke_key,
    set_disabled,
)
from app.db.migrate import migrate

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

PEPPER = "invented-pepper-for-tests-0123456789abcdef"


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    migrate(database_url)
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as connection:
        yield connection


async def test_a_token_names_its_account_and_roles(db: psycopg.AsyncConnection) -> None:
    account = await create_account(db, "Redaktion Optik", ["redaktion", "nutzer"])
    _, token = await issue_key(db, account, "laptop", PEPPER)

    principal = await principal_for(db, token_hash(token, PEPPER))

    assert principal is not None
    assert (principal.account_id, principal.name, principal.roles) == (
        account,
        "Redaktion Optik",
        frozenset({"redaktion", "nutzer"}),
    )


async def test_the_database_keeps_the_hash_and_never_the_token(db: psycopg.AsyncConnection) -> None:
    account = await create_account(db, "Lehrkraft", ["nutzer"])
    _, token = await issue_key(db, account, "", PEPPER)

    cursor = await db.execute("SELECT key_hash FROM api_key")
    [(stored,)] = await cursor.fetchall()
    dump = await db.execute("SELECT row_to_json(k)::text FROM api_key k")

    assert bytes(stored) == token_hash(token, PEPPER)
    assert token not in str(await dump.fetchall())


async def test_a_revoked_key_or_a_disabled_account_names_no_one(db: psycopg.AsyncConnection) -> None:
    first = await create_account(db, "Eins", ["nutzer"])
    key, revoked = await issue_key(db, first, "", PEPPER)
    second = await create_account(db, "Zwei", ["nutzer"])
    _, disabled = await issue_key(db, second, "", PEPPER)

    assert await revoke_key(db, key) is True
    assert await set_disabled(db, second, True) is True

    assert await principal_for(db, token_hash(revoked, PEPPER)) is None
    assert await principal_for(db, token_hash(disabled, PEPPER)) is None
    await set_disabled(db, second, False)
    assert await principal_for(db, token_hash(disabled, PEPPER)) is not None


async def test_an_unknown_hash_names_no_one(db: psycopg.AsyncConnection) -> None:
    assert await principal_for(db, b"\x00" * 32) is None


async def test_account_names_are_unique_whatever_their_case(db: psycopg.AsyncConnection) -> None:
    await create_account(db, "Redaktion", ["redaktion"])

    with pytest.raises(AccountExists):
        await create_account(db, "REDAKTION", ["nutzer"])


async def test_an_unknown_role_is_refused(db: psycopg.AsyncConnection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        await create_account(db, "Gast", ["superuser"])


async def test_failures_are_counted_per_source_within_the_window(db: psycopg.AsyncConnection) -> None:
    for _ in range(3):
        await record_failure(db, "192.0.2.1")
    await record_failure(db, "192.0.2.2")
    await db.execute("UPDATE auth_failure SET at = now() - interval '1 hour' WHERE source = '192.0.2.2'")

    assert await recent_failures(db, "192.0.2.1", 900) == 3
    assert await recent_failures(db, "192.0.2.2", 900) == 0


async def test_an_admin_is_known_to_exist_once_granted_with_a_key(db: psycopg.AsyncConnection) -> None:
    assert await admin_exists(db) is False
    admin = await create_account(db, "Admin", ["admin"])
    assert await admin_exists(db) is False
    await issue_key(db, admin, "", PEPPER)

    assert await admin_exists(db) is True


async def test_the_audit_log_keeps_who_did_what(db: psycopg.AsyncConnection) -> None:
    account = await create_account(db, "Admin", ["admin"])

    await record_audit(db, account, "Admin", "key.issue", "key:123", {"label": "laptop"}, "req-1")

    cursor = await db.execute(
        "SELECT actor_id, actor_name, action, subject, details, request_id FROM audit_log"
    )
    assert await cursor.fetchall() == [
        (account, "Admin", "key.issue", "key:123", {"label": "laptop"}, "req-1")
    ]


async def test_an_admin_without_a_live_key_or_blocked_counts_for_no_admin(
    db: psycopg.AsyncConnection,
) -> None:
    # the bootstrap must stay possible when no admin can sign in any more
    keyless = await create_account(db, "Admin ohne Schlüssel", ["admin"])
    key, _ = await issue_key(db, keyless, "", PEPPER)
    await revoke_key(db, key)
    blocked = await create_account(db, "Gesperrte Admin", ["admin"])
    await issue_key(db, blocked, "", PEPPER)
    await set_disabled(db, blocked, True)

    assert await admin_exists(db) is False


async def test_accounts_are_listed_by_name_whatever_its_case_in_pages(db: psycopg.AsyncConnection) -> None:
    for name in ("berta", "Carla", "anna", "Admin"):
        await create_account(db, name, ["nutzer"])

    first, total = await list_accounts(db, limit=3, offset=0)
    rest, again = await list_accounts(db, limit=3, offset=3)
    beyond, still = await list_accounts(db, limit=3, offset=10)

    assert [record.name for record in first] == ["Admin", "anna", "berta"]
    assert [record.name for record in rest] == ["Carla"]
    assert (total, again, beyond, still) == (4, 4, [], 4)


async def test_an_account_s_keys_are_read_without_their_hash_or_token(db: psycopg.AsyncConnection) -> None:
    account = await create_account(db, "Lehrkraft", ["nutzer"])
    other = await create_account(db, "Andere", ["nutzer"])
    first, _ = await issue_key(db, account, "laptop", PEPPER)
    second, _ = await issue_key(db, account, "", PEPPER)
    await issue_key(db, other, "fremd", PEPPER)
    await revoke_key(db, first)

    keys = await keys_of(db, account)

    assert [(key.id, key.label) for key in keys] == [(first, "laptop"), (second, "")]
    assert keys[0].revoked_at is not None and keys[1].revoked_at is None
    assert set(keys[0].__dict__) == {"id", "label", "created_at", "last_used_at", "revoked_at"}
