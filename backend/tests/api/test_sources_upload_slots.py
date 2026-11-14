"""The uploads a replica takes at once (audit 2026-11-14): each holds a slot of the process while
its file is read, checked and stored; one past the slots waits a bounded time, then is told to
come back (503 ``uploads_busy``) with nothing of its body read. Whatever ends an upload - stored,
refused, a store that fails, a client gone, the request cancelled - gives its slot back.
"""

import asyncio
import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from starlette.types import Message, Receive

from app.api import sources
from app.api.app import create_app
from tests.api.test_sources_upload import (
    PDF,
    PUBLIC,
    client_for,
    migrated,
    nothing_was_kept,
    owner,
    store,
    upload,
)
from tests.support import make_settings, selector_client

pytestmark = pytest.mark.pg
__all__ = ["migrated", "owner", "store"]  # the fixtures, taken over

BOUNDARY = "curricarta"
HEAD = f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n'.encode()


@pytest.fixture
def one_slot(
    migrated: str, store: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, asyncio.Semaphore]]:
    """A replica with one slot, whose next upload waits only briefly for it."""
    monkeypatch.setattr(sources, "UPLOAD_WAIT_S", 0.05)
    app = create_app(make_settings(database_url=migrated, storage_dir=store, max_upload_mb=1))
    with selector_client(app, base_url=PUBLIC, raise_server_exceptions=False) as client:
        slots = asyncio.Semaphore(1)
        client.app.state.upload_slots = slots  # type: ignore[attr-defined]
        yield client, slots


def the_slot_is_free(client: TestClient, slots: asyncio.Semaphore, header: dict[str, str]) -> bool:
    """The slot is back: the next upload, waiting only briefly, gets it and is stored."""
    return not slots.locked() and upload(client, header, name="next.pdf").status_code == 201


def drive(
    client: TestClient, header: dict[str, str], receive: Receive, *, cancel: asyncio.Event | None
) -> None:
    """A POST of an upload form, its body through ``receive``, as a server drives the app; with
    ``cancel``, the request is cancelled once the event is set, as a server does when its
    connection is lost."""
    headers = [
        (b"host", b"testserver:8000"),
        (b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode()),
        (b"content-length", str(len(HEAD) + len(PDF) + 64).encode()),
    ] + [(k.lower().encode(), v.encode()) for k, v in header.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": sources.UPLOAD_PATH,
        "raw_path": sources.UPLOAD_PATH.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 8000),
        "state": {},
    }

    async def sent(message: Message) -> None:
        pass

    async def answer() -> None:
        # a client gone may end the request in an error; what the tests look at is the slot
        request = asyncio.ensure_future(client.app(scope, receive, sent))
        if cancel is not None:
            await cancel.wait()
            request.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await request

    assert client.portal is not None
    client.portal.call(answer)


def test_an_upload_past_the_replica_s_slots_waits_and_is_then_told_to_come_back(
    migrated: str, store: Path, owner: tuple[UUID, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "UPLOAD_WAIT_S", 0.05)
    reads: list[int] = []
    read = UploadFile.read

    async def counted(self: UploadFile, size: int = -1) -> bytes:
        reads.append(size)
        return await read(self, size)

    monkeypatch.setattr(UploadFile, "read", counted)
    pulled: list[bytes] = []

    def body() -> Iterator[bytes]:
        for piece in (HEAD, PDF, f"\r\n--{BOUNDARY}--\r\n".encode()):
            pulled.append(piece)
            yield piece

    with client_for(migrated, store) as client:
        client.app.state.upload_slots = asyncio.Semaphore(0)  # type: ignore[attr-defined]
        answer = client.post(
            "/api/v1/sources",
            content=body(),
            headers={**owner[1], "Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        )

    assert answer.status_code == 503
    assert answer.json()["code"] == "uploads_busy"
    assert answer.headers["Retry-After"] == "5"
    assert reads == [] and pulled == []
    assert nothing_was_kept(migrated, store)


def test_an_upload_takes_a_slot_and_gives_it_back_whatever_becomes_of_it(
    one_slot: tuple[TestClient, asyncio.Semaphore], owner: tuple[UUID, dict[str, str]]
) -> None:
    client, slots = one_slot
    header = owner[1]
    stored = upload(client, header)
    too_large = upload(client, header, data=PDF + b"x" * 2**20)
    of_no_type = upload(client, header, data=b"MZ\x90\x00 an executable")

    assert [stored.status_code, too_large.status_code, of_no_type.status_code] == [201, 413, 415]
    assert the_slot_is_free(client, slots, header)


def test_an_upload_whose_store_fails_gives_its_slot_back(
    one_slot: tuple[TestClient, asyncio.Semaphore],
    owner: tuple[UUID, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, slots = one_slot
    storage = client.app.state.storage  # type: ignore[attr-defined]
    put = storage.put

    async def failing(key: str, data: bytes) -> None:
        raise OSError("the store is full")

    monkeypatch.setattr(storage, "put", failing)
    assert upload(client, owner[1]).status_code == 500
    monkeypatch.setattr(storage, "put", put)

    assert the_slot_is_free(client, slots, owner[1])


def test_an_upload_whose_client_goes_gives_its_slot_back(
    one_slot: tuple[TestClient, asyncio.Semaphore], owner: tuple[UUID, dict[str, str]]
) -> None:
    client, slots = one_slot
    messages: list[Message] = [
        {"type": "http.request", "body": HEAD + PDF[:100], "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> Message:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    drive(client, owner[1], receive, cancel=None)

    assert not messages  # the form was being read when the client went
    assert the_slot_is_free(client, slots, owner[1])


def test_an_upload_cancelled_while_its_form_is_read_gives_its_slot_back(
    one_slot: tuple[TestClient, asyncio.Semaphore], owner: tuple[UUID, dict[str, str]]
) -> None:
    client, slots = one_slot
    reading = asyncio.Event()
    asked: list[int] = []

    async def receive() -> Message:
        asked.append(1)
        if len(asked) == 1:
            return {"type": "http.request", "body": HEAD + PDF[:100], "more_body": True}
        reading.set()  # the rest of the body never comes: the request is cancelled waiting for it
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    drive(client, owner[1], receive, cancel=reading)

    assert len(asked) == 2
    assert the_slot_is_free(client, slots, owner[1])


def test_a_refused_upload_costs_no_slot(
    migrated: str, store: Path, owner: tuple[UUID, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # the account's uploads of the minute are counted before a slot is taken
    taken: list[Any] = []

    class Counting(asyncio.Semaphore):
        async def acquire(self) -> Literal[True]:
            taken.append(1)
            return await super().acquire()

    with client_for(migrated, store, uploads_per_minute=1) as client:
        client.app.state.upload_slots = Counting(1)  # type: ignore[attr-defined]
        answers = [upload(client, owner[1], name=f"plan{index}.pdf") for index in range(2)]

    assert [answer.status_code for answer in answers] == [201, 429]
    assert answers[1].json()["code"] == "too_many_uploads"
    assert taken == [1]
