"""A register entry taken away through the API (DELETE /api/v1/sources/{id}): by its owner, or by an editor
or an admin where it has an owner; never a seed entry, one with documents, or one whose fetch or a
conversion of its file waits or runs. Its file goes where no other entry holds it - its row and conversions
at once, its object by the next sweep -, and the same bytes uploaded again are stored again. The document's
taking away: test_deleting.py."""

import asyncio
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.retention import Policy, Swept, sweep
from tests.api.test_sources_upload import PDF, client, migrated, owner, rows, store, upload
from tests.db.l1 import add_conversion, add_document, add_entity, seed_vocabulary
from tests.db.retention_rows import add_job
from tests.support import seed_account

pytestmark = pytest.mark.pg
__all__ = ["client", "migrated", "owner", "store"]  # the fixtures, taken over

POLICY = Policy(jobs_days=90, audit_days=365, raw_answers_days=30)
DIGEST = b"\x01" * 32
KEY = f"sources/{DIGEST.hex()}"


def path(source: Any) -> str:
    return f"/api/v1/sources/{source}"


@pytest.fixture
def made(migrated: str, owner: tuple[UUID, dict[str, str]], store: Path) -> dict[str, Any]:
    """The owner's entry with a file in the store, how it came, and the file's finished conversion."""
    with psycopg.connect(migrated, autocommit=True) as connection:
        seed_vocabulary(connection)
        made: dict[str, Any] = add_conversion(connection, DIGEST, owner[0])
        [(file_id,)] = connection.execute(
            "SELECT file_id FROM source WHERE id = %s", (made["source"],)
        ).fetchall()
        connection.execute(
            "INSERT INTO acquisition (id, source_id, file_id, method, account_id)"
            " VALUES (gen_random_uuid(), %s, %s, 'upload', %s)",
            (made["source"], file_id, owner[0]),
        )
    FileSystemStorage(store).put(KEY, b"%PDF")
    return made | {"file": file_id}


def stored(store: Path) -> list[str]:
    return sorted(FileSystemStorage(store).list("sources/")) if (store / "sources").exists() else []


def swept(url: str, store: Path) -> Swept:
    async def once() -> Swept:
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
            return await sweep(connection, AsyncStorage(FileSystemStorage(store)), POLICY, dry_run=False)

    return asyncio.run(once(), loop_factory=asyncio.SelectorEventLoop)


def test_the_owner_takes_an_entry_away_and_its_file_leaves_the_store(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], made: dict[str, Any], store: Path
) -> None:
    answer = client.delete(path(made["source"]), headers=owner[1])

    assert answer.status_code == 204, answer.text
    counts = "SELECT (SELECT count(*) FROM source), (SELECT count(*) FROM acquisition),"
    counts += " (SELECT count(*) FROM source_file), (SELECT count(*) FROM conversion),"
    counts += " (SELECT count(*) FROM document_block)"
    assert rows(migrated, counts) == [(0, 0, 0, 0, 0)]
    assert rows(migrated, "SELECT prefix FROM storage_garbage") == [(KEY,)]
    assert client.get(path(made["source"]), headers=owner[1]).status_code == 404

    assert swept(migrated, store).objects == 1
    assert stored(store) == []
    assert rows(migrated, "SELECT count(*) FROM storage_garbage") == [(0,)]


def test_a_file_another_entry_holds_stays_with_its_conversion(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], made: dict[str, Any], store: Path
) -> None:
    other, _ = seed_account(migrated, "Andere", ["nutzer"])
    with psycopg.connect(migrated, autocommit=True) as connection:
        held = add_entity(connection, "source")
        connection.execute(
            "INSERT INTO source (id, owner_id, provenance, register_status, file_id, file_name, mime)"
            " VALUES (%s, %s, 'upload', 'acquired', %s, 'plan.pdf', 'application/pdf')",
            (held, other, made["file"]),
        )

    assert client.delete(path(made["source"]), headers=owner[1]).status_code == 204

    assert rows(migrated, "SELECT id FROM source") == [(held,)]
    assert rows(migrated, "SELECT (SELECT count(*) FROM source_file), (SELECT count(*) FROM conversion)") == [
        (1, 1)
    ]
    assert rows(migrated, "SELECT count(*) FROM storage_garbage") == [(0,)]
    swept(migrated, store)
    assert stored(store) == [KEY]


def test_an_entry_with_documents_is_not_taken_away(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], made: dict[str, Any]
) -> None:
    with psycopg.connect(migrated, autocommit=True) as connection:
        add_document(connection, made)

    answer = client.delete(path(made["source"]), headers=owner[1])

    assert (answer.status_code, answer.json()["code"]) == (409, "has_documents")
    assert answer.json()["details"] == {"documents": 1}
    assert rows(migrated, "SELECT count(*) FROM source") == [(1,)]


@pytest.mark.parametrize("role", ["nutzer", "admin"])
def test_an_entry_of_no_account_is_not_taken_away(
    client: TestClient, migrated: str, made: dict[str, Any], role: str
) -> None:
    with psycopg.connect(migrated, autocommit=True) as connection:
        connection.execute("UPDATE source SET owner_id = NULL WHERE id = %s", (made["source"],))
    _, header = seed_account(migrated, "Jemand", [role])

    answer = client.delete(path(made["source"]), headers=header)

    assert (answer.status_code, answer.json()["code"]) == (409, "seed_entry")
    assert rows(migrated, "SELECT count(*) FROM source") == [(1,)]


def test_another_account_finds_no_entry(client: TestClient, migrated: str, made: dict[str, Any]) -> None:
    _, stranger = seed_account(migrated, "Fremd", ["nutzer"])

    answer = client.delete(path(made["source"]), headers=stranger)

    assert answer.status_code == 404
    assert rows(migrated, "SELECT count(*) FROM source") == [(1,)]
    assert client.delete(path(UUID(int=7)), headers=stranger).status_code == 404


@pytest.mark.parametrize("role", ["redaktion", "admin"])
def test_an_editor_takes_any_account_s_entry_away(
    client: TestClient, migrated: str, made: dict[str, Any], role: str
) -> None:
    _, editor = seed_account(migrated, "Redaktion", [role])

    assert client.delete(path(made["source"]), headers=editor).status_code == 204

    assert rows(migrated, "SELECT count(*) FROM source") == [(0,)]


def test_an_entry_being_fetched_or_converted_is_not_taken_away(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], made: dict[str, Any]
) -> None:
    imported = client.post(
        "/api/v1/sources/import", headers=owner[1], json={"url": "https://example.org/a.pdf"}
    )
    assert imported.status_code == 202, imported.text
    fetching = imported.json()
    with psycopg.connect(migrated, autocommit=True) as connection:
        job = add_job(connection, status="queued")
        connection.execute(
            "UPDATE conversion SET status = 'pending', pages = NULL, printed_pages = NULL,"
            " finished_at = NULL, job_id = %s WHERE id = %s",
            (job, made["conversion"]),
        )
    _, editor = seed_account(migrated, "Redaktion", ["redaktion"])

    fetched = client.delete(path(fetching["source"]["id"]), headers=owner[1])
    converted = client.delete(path(made["source"]), headers=owner[1])
    by_editor = client.delete(path(made["source"]), headers=editor)

    assert (fetched.status_code, fetched.json()["code"]) == (409, "job_open")
    assert fetched.json()["details"] == {"job_id": fetching["job_id"]}
    assert (converted.status_code, converted.json()["details"]) == (409, {"job_id": str(job)})
    assert (by_editor.json()["code"], by_editor.json()["details"]) == ("job_open", {})
    assert rows(migrated, "SELECT count(*) FROM source") == [(2,)]


def test_a_conversion_waiting_without_its_job_holds_the_entry_too(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], made: dict[str, Any]
) -> None:
    # its job swept or never named: the file would stay as long as the conversion waits
    with psycopg.connect(migrated, autocommit=True) as connection:
        connection.execute(
            "UPDATE conversion SET status = 'pending', pages = NULL, printed_pages = NULL,"
            " finished_at = NULL, job_id = NULL WHERE id = %s",
            (made["conversion"],),
        )

    answer = client.delete(path(made["source"]), headers=owner[1])

    assert (answer.status_code, answer.json()["code"], answer.json()["details"]) == (409, "job_open", {})


def test_the_pages_booked_for_its_conversion_stay_booked(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], made: dict[str, Any]
) -> None:
    booked = (made["conversion"], owner[0], "pdfplumber", 7, True)
    with psycopg.connect(migrated, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO conversion_usage (conversion_id, account_id, engine, pages, billable)"
            " VALUES (%s, %s, %s, %s, %s)",
            booked,
        )

    assert client.delete(path(made["source"]), headers=owner[1]).status_code == 204

    assert rows(migrated, "SELECT count(*) FROM conversion") == [(0,)]
    assert rows(
        migrated, "SELECT conversion_id, account_id, engine, pages, billable FROM conversion_usage"
    ) == [booked]


def uploaded(client: TestClient, header: dict[str, str]) -> str:
    answer = upload(client, header)
    assert answer.status_code == 201, answer.text
    return str(answer.json()["id"])


@pytest.mark.parametrize("swept_first", [False, True], ids=["noted", "swept"])
def test_the_same_bytes_uploaded_again_are_stored_again(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], store: Path, swept_first: bool
) -> None:
    # the note on the object outlives the request; the upload of the same bytes takes it away, else the
    # next sweep would take the bytes now named again. Or the sweep came first: the upload stores anew
    key = f"sources/{hashlib.sha256(PDF).hexdigest()}"
    assert client.delete(path(uploaded(client, owner[1])), headers=owner[1]).status_code == 204
    assert rows(migrated, "SELECT prefix FROM storage_garbage") == [(key,)]
    if swept_first:
        swept(migrated, store)
        assert stored(store) == []

    again = uploaded(client, owner[1])

    assert rows(migrated, "SELECT count(*) FROM storage_garbage") == [(0,)]
    assert swept(migrated, store).objects == 0
    assert stored(store) == [key]
    assert FileSystemStorage(store).get(key) == PDF
    assert client.get(f"{path(again)}/file", headers=owner[1]).content == PDF


class TakenAfterTheLook(FileSystemStorage):
    """A store whose first answer that an object is there is out of date by the time the row is written,
    as a sweep emptying the note of a file taken away before would make it."""

    looked = False

    def exists(self, key: str) -> bool:
        if not self.looked:
            self.looked = True
            return True
        return super().exists(key)


def test_an_upload_whose_object_left_the_store_meanwhile_is_stored_again(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], store: Path
) -> None:
    client.app.state.storage = AsyncStorage(TakenAfterTheLook(store))  # type: ignore[attr-defined]

    uploaded(client, owner[1])

    assert FileSystemStorage(store).get(f"sources/{hashlib.sha256(PDF).hexdigest()}") == PDF


def test_the_taking_away_is_audited(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], made: dict[str, Any]
) -> None:
    with psycopg.connect(migrated, autocommit=True) as connection:
        connection.execute("UPDATE source SET title = 'Lehrplan Physik' WHERE id = %s", (made["source"],))

    assert client.delete(path(made["source"]), headers=owner[1]).status_code == 204

    assert rows(
        migrated, "SELECT actor_id, subject, details FROM audit_log WHERE action = 'source.delete'"
    ) == [(owner[0], f"source:{made['source']}", {"sha256": DIGEST.hex()})]


def test_a_visitor_needs_a_token(client: TestClient, migrated: str, made: dict[str, Any]) -> None:
    assert client.delete(path(made["source"])).status_code == 401
    assert rows(migrated, "SELECT count(*) FROM source") == [(1,)]


def test_the_route_names_the_refusals_it_gives(client: TestClient) -> None:
    spec: dict[str, Any] = client.get("/openapi.json").json()

    answers = spec["paths"]["/api/v1/sources/{source_id}"]["delete"]["responses"]

    assert set(answers) >= {"204", "404", "409"}
    for code in ("seed_entry", "has_documents", "job_open"):
        assert code in answers["409"]["description"]
