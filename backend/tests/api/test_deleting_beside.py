"""Taking away beside another request on the same rows, two sessions at once: a conversion asked for beside
the entry's taking away either stands - and the entry stays, 409 ``job_open`` - or finds no entry; two
takings away of one document or entry take it once. Each request is held in its transaction by a step that
waits (``held_at``) while the other comes to wait for its lock. Fixtures: test_deleting_sources.py."""

import asyncio
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import conversions, deleting
from tests.api.test_deleting_sources import made, path
from tests.api.test_sources_edit import until_waiting
from tests.api.test_sources_upload import client, client_for, migrated, owner, rows, store
from tests.db.l1 import add_document

pytestmark = pytest.mark.pg
__all__ = ["client", "made", "migrated", "owner", "store"]  # the fixtures, taken over


@contextmanager
def held_at(monkeypatch: pytest.MonkeyPatch, module: Any, name: str) -> Iterator[threading.Event]:
    """``module.name`` (an async step of a route, inside its transaction) waits until the event is set;
    yields once the first call has begun."""
    began, go = threading.Event(), threading.Event()
    step = getattr(module, name)

    async def waiting(*arguments: Any, **keywords: Any) -> Any:
        began.set()
        await asyncio.to_thread(go.wait, 30)
        return await step(*arguments, **keywords)

    monkeypatch.setattr(module, name, waiting)
    yield began
    go.set()


def in_thread(send: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
    answers: list[Any] = []
    thread = threading.Thread(target=lambda: answers.append(send()), daemon=True)
    thread.start()
    return thread, answers


def failed_conversion(url: str, made: dict[str, Any]) -> None:
    """The file's conversion failed: asking for it again sets it pending under a new job."""
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "UPDATE conversion SET status = 'failed', error_code = 'unreadable', pages = NULL,"
            " printed_pages = NULL WHERE id = %s",
            (made["conversion"],),
        )


@pytest.fixture
def other(migrated: str, store: Path) -> Iterator[TestClient]:
    """A second replica of the service."""
    with client_for(migrated, store) as test_client:
        yield test_client


def test_a_conversion_asked_first_keeps_the_entry_it_waits_for(
    client: TestClient,
    other: TestClient,
    migrated: str,
    owner: tuple[UUID, dict[str, str]],
    made: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_conversion(migrated, made)
    source = made["source"]
    with held_at(monkeypatch, conversions, "record_audit") as began:
        asking, asked = in_thread(lambda: client.post(f"{path(source)}/conversions", headers=owner[1]))
        assert began.wait(10)
        taking, taken = in_thread(lambda: other.delete(path(source), headers=owner[1]))
        until_waiting(migrated, 1)
    asking.join(30)
    taking.join(30)

    assert asked[0].status_code == 202, asked[0].text
    assert (taken[0].status_code, taken[0].json()["code"]) == (409, "job_open")
    assert rows(migrated, "SELECT status FROM conversion WHERE id = %s", made["conversion"]) == [("pending",)]
    assert rows(migrated, "SELECT count(*) FROM source WHERE id = %s", source) == [(1,)]
    assert rows(migrated, "SELECT count(*) FROM storage_garbage") == [(0,)]


def test_a_conversion_asked_beside_the_taking_away_finds_no_entry(
    client: TestClient,
    other: TestClient,
    migrated: str,
    owner: tuple[UUID, dict[str, str]],
    made: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_conversion(migrated, made)
    source = made["source"]
    with held_at(monkeypatch, deleting, "audit") as began:
        taking, taken = in_thread(lambda: other.delete(path(source), headers=owner[1]))
        assert began.wait(10)
        asking, asked = in_thread(lambda: client.post(f"{path(source)}/conversions", headers=owner[1]))
        until_waiting(migrated, 1)
    taking.join(30)
    asking.join(30)

    assert taken[0].status_code == 204, taken[0].text
    assert asked[0].status_code == 404, asked[0].text
    assert rows(migrated, "SELECT (SELECT count(*) FROM conversion), (SELECT count(*) FROM source_file)") == [
        (0, 0)
    ]


def test_two_takings_away_of_an_entry_take_it_once(
    client: TestClient,
    other: TestClient,
    migrated: str,
    owner: tuple[UUID, dict[str, str]],
    made: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with held_at(monkeypatch, deleting, "audit") as began:
        first, firsts = in_thread(lambda: client.delete(path(made["source"]), headers=owner[1]))
        assert began.wait(10)
        second, seconds = in_thread(lambda: other.delete(path(made["source"]), headers=owner[1]))
        until_waiting(migrated, 1)
    first.join(30)
    second.join(30)

    assert sorted(answer.status_code for answer in (*firsts, *seconds)) == [204, 404]
    assert rows(migrated, "SELECT count(*) FROM audit_log WHERE action = 'source.delete'") == [(1,)]
    assert rows(migrated, "SELECT prefix FROM storage_garbage") == [(f"sources/{(b'\x01' * 32).hex()}",)]


def test_two_takings_away_of_a_document_take_it_once(
    client: TestClient,
    other: TestClient,
    migrated: str,
    owner: tuple[UUID, dict[str, str]],
    made: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with psycopg.connect(migrated, autocommit=True) as connection:
        document = add_document(connection, made)
    with held_at(monkeypatch, deleting, "audit") as began:
        first, firsts = in_thread(lambda: client.delete(f"/api/v1/documents/{document}", headers=owner[1]))
        assert began.wait(10)
        second, seconds = in_thread(lambda: other.delete(f"/api/v1/documents/{document}", headers=owner[1]))
        until_waiting(migrated, 1)
    first.join(30)
    second.join(30)

    answers = sorted((answer.status_code, answer.json().get("code") if answer.content else None)
                     for answer in (*firsts, *seconds))  # fmt: skip
    assert answers == [(204, None), (404, "no_document")]
    assert rows(migrated, "SELECT count(*) FROM audit_log WHERE action = 'document.delete'") == [(1,)]
