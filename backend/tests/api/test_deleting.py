"""A document taken away through the API (DELETE /api/v1/documents/{id}): by its owner, the editors and the
admins, with all it holds - its raw answers in the store at once, or by the next sweep where the store is
away -, never a frozen one nor one whose job waits or runs; its entry, its conversion and the ledger's
bookings stay. The register entry's taking away: test_deleting_sources.py."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.retention import Policy, sweep
from tests.api.test_document_tree import a_document
from tests.api.test_documents import an_account, client, rows, url
from tests.api.test_freeze import freezing, ready
from tests.db.l1 import add_run
from tests.db.retention_rows import add_usage
from tests.db.test_l1_lifecycle import TABLES, fill

pytestmark = pytest.mark.pg
__all__ = ["client", "freezing", "url"]  # the fixtures, taken over

HELD = (*TABLES, "extraction_unit", "gold_sample", "gold_item", "gold_judgement")
POLICY = Policy(jobs_days=90, audit_days=365, raw_answers_days=30)


def path(document: str) -> str:
    return f"/api/v1/documents/{document}"


def held(url: str) -> dict[str, int]:
    counted = {}
    for table in HELD:
        [(count,)] = rows(url, f"SELECT count(*) FROM {table}")  # noqa: S608 - the tests' own names
        counted[table] = count
    return counted


def filled(url: str, document: str) -> UUID:
    """The document full of what it may hold - a run's nodes, statements, anchors and findings, a unit, a
    judged gold sample -; its run."""
    with psycopg.connect(url, autocommit=True) as connection:
        [(conversion, owner)] = connection.execute(
            "SELECT conversion_id, owner_id FROM document WHERE id = %s", (document,)
        ).fetchall()
        # its profile again as fill writes it
        connection.execute("DELETE FROM document_profile WHERE document_id = %s", (document,))
        run = fill(connection, {"document": UUID(document), "conversion": conversion})["run"]
        connection.execute(
            "INSERT INTO extraction_unit (document_id, unit_key, run_id, statements)"
            " VALUES (%s, 'E1', %s, 1)",
            (document, run),
        )
        [(sample,)] = connection.execute(
            "INSERT INTO gold_sample (kind, document_id, label, seed, size, frame, drawn_by)"
            " VALUES ('statement', %s, 'probe', 's1', 1, '{}', %s) RETURNING id",
            (document, owner),
        ).fetchall()
        [(item,)] = connection.execute(
            "INSERT INTO gold_item (sample_id, stratum, place, statement_id) VALUES (%s, 'content', 1, %s)"
            " RETURNING id",
            (sample, run),
        ).fetchall()
        connection.execute(
            "INSERT INTO gold_judgement (item_id, judged_by, verdict) VALUES (%s, %s, 'correct')",
            (item, owner),
        )
    return run


def a_raw_run(url: str, store: Path, document: str, *numbers: int) -> UUID:
    """A run of the document whose raw answers lie in the store, as app/db/runs.py names them."""
    with psycopg.connect(url, autocommit=True) as connection:
        run = add_run(connection, UUID(document))
        connection.execute(
            "UPDATE extraction_run SET raw_response_key = 'runs/' || id || '/x4' WHERE id = %s", (run,)
        )
    files = FileSystemStorage(store)
    for number in numbers:
        files.put(f"runs/{run}/x4/{number}.json", b'[{"kind": "response"}]')
    return run


def kept(store: Path) -> list[str]:
    return sorted(FileSystemStorage(store).list("runs/")) if (store / "runs").exists() else []


def test_the_owner_takes_a_draft_away_with_all_it_holds(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    filled(url, document)
    [(source, conversion)] = rows(
        url, "SELECT source_id, conversion_id FROM document WHERE id = %s", document
    )

    answer = client.delete(path(document), headers=owner)

    assert answer.status_code == 204, answer.text
    assert held(url) == dict.fromkeys(HELD, 0)
    assert rows(url, "SELECT count(*) FROM document") == [(0,)]
    # the entry and its conversion stay: another document may be made of them
    assert rows(url, "SELECT (SELECT count(*) FROM source WHERE id = %s), (SELECT count(*) FROM conversion"
                " WHERE id = %s)", source, conversion) == [(1, 1)]  # fmt: skip
    assert client.get(path(document), headers=owner).status_code == 404
    assert client.delete(path(document), headers=owner).json()["code"] == "no_document"


def test_its_raw_answers_leave_the_store(client: TestClient, url: str, tmp_path: Path) -> None:
    document, owner = a_document(client, url)
    run = a_raw_run(url, tmp_path, document, 1, 3)
    other, _ = a_document(client, url, name="Andere", digest=b"\x02" * 32)
    kept_run = a_raw_run(url, tmp_path, other, 1)

    answer = client.delete(path(document), headers=owner)

    assert answer.status_code == 204, answer.text
    assert kept(tmp_path) == [f"runs/{kept_run}/x4/1.json"]
    assert rows(url, "SELECT prefix FROM storage_garbage") == []
    assert run != kept_run


class Away(FileSystemStorage):
    """A store that answers nothing: every call fails, as a service away does."""

    def list(self, prefix: str) -> Iterator[str]:
        raise OSError("the store is away (invented)")

    def delete(self, key: str) -> None:
        raise OSError("the store is away (invented)")


def test_a_store_away_leaves_the_prefixes_for_the_sweep(client: TestClient, url: str, tmp_path: Path) -> None:
    document, owner = a_document(client, url)
    runs_before = {f"runs/{run}/" for (run,) in rows(url, "SELECT id FROM extraction_run")}  # X4's
    run = a_raw_run(url, tmp_path, document, 1, 2)
    client.app.state.storage = AsyncStorage(Away(tmp_path))  # type: ignore[attr-defined]

    answer = client.delete(path(document), headers=owner)

    assert answer.status_code == 204, answer.text
    assert {prefix for (prefix,) in rows(url, "SELECT prefix FROM storage_garbage")} == {
        f"exports/{document}/", f"runs/{run}/", *runs_before,
    }  # fmt: skip
    assert len(kept(tmp_path)) == 2

    swept = asyncio.run(swept_once(url, tmp_path), loop_factory=asyncio.SelectorEventLoop)

    assert swept == 2
    assert kept(tmp_path) == []
    assert rows(url, "SELECT prefix FROM storage_garbage") == []


async def swept_once(url: str, store: Path) -> int:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
        swept = await sweep(connection, AsyncStorage(FileSystemStorage(store)), POLICY, dry_run=False)
    return swept.objects


def test_another_account_finds_no_document(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url)
    _, stranger = an_account(url, "Fremd")

    answer = client.delete(path(document), headers=stranger)

    assert (answer.status_code, answer.json()["code"]) == (404, "no_document")
    assert rows(url, "SELECT count(*) FROM document") == [(1,)]
    assert rows(url, "SELECT count(*) FROM storage_garbage") == [(0,)]


@pytest.mark.parametrize("role", ["redaktion", "admin"])
def test_an_editor_and_an_admin_take_any_draft_away(client: TestClient, url: str, role: str) -> None:
    document, _ = a_document(client, url)
    _, editor = an_account(url, "Redaktion", (role,))

    answer = client.delete(path(document), headers=editor)

    assert answer.status_code == 204, answer.text
    assert rows(url, "SELECT count(*) FROM document") == [(0,)]


def test_a_frozen_document_is_never_taken_away(freezing: TestClient, url: str) -> None:
    _, admin = an_account(url, "Admin", ("admin",))
    document, owner = ready(freezing, url, admin)
    assert freezing.post(f"{path(document)}/freeze", headers=admin, json={}).status_code == 200

    answers = [freezing.delete(path(document), headers=header) for header in (owner, admin)]

    assert [(answer.status_code, answer.json()["code"]) for answer in answers] == [(409, "frozen")] * 2
    assert rows(url, "SELECT count(*) FROM document") == [(1,)]
    assert rows(url, "SELECT count(*) FROM audit_log WHERE action = 'document.delete'") == [(0,)]


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_document_whose_job_waits_or_runs_is_not_taken_away(
    client: TestClient, url: str, status: str
) -> None:
    document, owner = a_document(client, url, ended=False)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    [(job,)] = rows(url, "SELECT id FROM job WHERE status = 'queued'")
    if status == "running":
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(
                "UPDATE job SET status = 'running', lease_owner = 'worker-1',"
                " lease_token = gen_random_uuid(), lease_expires_at = now() + interval '1 minute'"
                " WHERE id = %s",
                (job,),
            )

    by_owner = client.delete(path(document), headers=owner)
    by_editor = client.delete(path(document), headers=editor)

    assert (by_owner.status_code, by_owner.json()["code"]) == (409, "job_open")
    assert by_owner.json()["details"] == {"job_id": str(job)}  # named to the owner
    assert (by_editor.status_code, by_editor.json()["code"], by_editor.json()["details"]) == (
        409, "job_open", {},
    )  # fmt: skip
    assert rows(url, "SELECT count(*) FROM document") == [(1,)]
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "UPDATE job SET status = 'done', finished_at = now(), lease_owner = NULL, lease_token = NULL,"
            " lease_expires_at = NULL WHERE id = %s",
            (job,),
        )
    assert client.delete(path(document), headers=owner).status_code == 204


def test_a_draft_copy_taken_away_leaves_the_revision_it_copied_and_room_for_a_new_copy(
    freezing: TestClient, url: str
) -> None:
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    document, _ = ready(freezing, url, editor)
    assert freezing.post(f"{path(document)}/freeze", headers=editor, json={}).status_code == 200
    copying = f"{path(document)}/draft-copy"
    copy = freezing.post(copying, headers=editor).json()["id"]

    answer = freezing.delete(path(copy), headers=editor)

    assert answer.status_code == 204, answer.text
    assert rows(url, "SELECT id::text, frozen_at IS NOT NULL FROM document") == [(document, True)]
    assert freezing.get(path(document), headers=editor).status_code == 200
    again = freezing.post(copying, headers=editor)
    assert again.status_code == 201, again.text
    assert rows(url, "SELECT revision FROM document WHERE id = %s", again.json()["id"]) == [(2,)]


def test_the_taking_away_is_audited_without_a_wording(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("UPDATE document SET title = 'Lehrplan Physik' WHERE id = %s", (document,))
    [(source,)] = rows(url, "SELECT source_id::text FROM document WHERE id = %s", document)

    assert client.delete(path(document), headers=owner).status_code == 204

    assert rows(url, "SELECT subject, details FROM audit_log WHERE action = 'document.delete'") == [
        (f"document:{document}", {"source": source, "revision": 1})
    ]


def test_what_the_ledger_booked_for_it_stays(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    [(account, job)] = rows(
        url,
        "SELECT d.owner_id, j.id FROM document d, job j WHERE d.id = %s AND j.kind = 'extract.run'",
        document,
    )
    with psycopg.connect(url, autocommit=True) as connection:
        add_usage(connection, account, job)
    booked = rows(url, "SELECT account_id, job_id, input_tokens, output_tokens FROM llm_usage")

    assert client.delete(path(document), headers=owner).status_code == 204

    assert rows(url, "SELECT account_id, job_id, input_tokens, output_tokens FROM llm_usage") == booked
    assert rows(url, "SELECT count(*) FROM job WHERE id = %s", job) == [(1,)]


def test_a_visitor_needs_a_token(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url)

    answer = client.delete(path(document))

    assert answer.status_code == 401
    assert rows(url, "SELECT count(*) FROM document") == [(1,)]


def test_the_route_names_the_refusals_it_gives(client: TestClient) -> None:
    spec: dict[str, Any] = client.get("/openapi.json").json()

    answers = spec["paths"]["/api/v1/documents/{document_id}"]["delete"]["responses"]

    assert set(answers) >= {"204", "404", "409"}
    assert "no_document" in answers["404"]["description"]
    for code in ("frozen", "job_open"):
        assert code in answers["409"]["description"]
