"""The time an upload's form is read while it holds a slot (UPLOAD_READ_TIMEOUT_S): a client that
trickles its body is told 408 ``upload_too_slow`` once its time is up, its slot is given back,
nothing of it stays, and the server ends its connection instead of reading the rest at the
client's pace. The wait for the slot is not part of that time.

The deadlines here are a fraction of a second: below the setting's bound, so the tests set them
on a copy of the app's settings.
"""

import asyncio
import errno
import io
import json
import re
import socket
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from starlette import formparsers
from starlette.datastructures import UploadFile
from starlette.types import Message

from app.api import sources
from app.core.logging import configure_logging
from tests.api.test_sources_upload import PDF, migrated, nothing_was_kept, owner, store
from tests.api.test_sources_upload_slots import BOUNDARY, HEAD, TAIL, drive, one_slot, the_slot_is_free
from tests.support import make_settings
from tests.test_serve import serving, two_free_ports

pytestmark = pytest.mark.pg
__all__ = ["migrated", "one_slot", "owner", "store"]  # the fixtures, taken over

TRICKLE_S = 0.5  # the deadline of a client that stalls
PACED_S = 1.0  # the deadline of a client that sends in pieces, in time
STALL_S = 10 * TRICKLE_S  # how long a stalled client stays


def with_deadline(client: TestClient, seconds: float) -> TestClient:
    """The client's app, reading an upload's form for ``seconds`` at most."""
    state = client.app.state  # type: ignore[attr-defined]
    state.settings = state.settings.model_copy(update={"upload_read_timeout_s": seconds})
    return client


def stalling(first: bytes) -> Any:
    """A body whose first piece is ``first``; the rest never comes - the client goes after
    ``STALL_S``, so that an app without a deadline fails the test instead of hanging it."""
    sent: list[int] = []

    async def receive() -> Message:
        if not sent:
            sent.append(1)
            return {"type": "http.request", "body": first, "more_body": True}
        await asyncio.sleep(STALL_S)
        return {"type": "http.disconnect"}

    return receive


def paced(pause_s: float) -> Any:
    """The form of PDF in four pieces, ``pause_s`` before each but the first."""
    middle = len(PDF) // 2
    pieces = [HEAD, PDF[:middle], PDF[middle:], TAIL]

    async def receive() -> Message:
        if len(pieces) < 4:
            await asyncio.sleep(pause_s)
        piece = pieces.pop(0)
        return {"type": "http.request", "body": piece, "more_body": bool(pieces)}

    return receive


def refusal(answered: list[Message]) -> tuple[int, str]:
    return answered[0]["status"], json.loads(answered[1]["body"])["code"]


def test_an_upload_that_trickles_is_refused_when_its_time_is_up(
    one_slot: tuple[TestClient, asyncio.Semaphore], owner: tuple[UUID, dict[str, str]]
) -> None:
    client = with_deadline(one_slot[0], TRICKLE_S)

    started = time.monotonic()
    answered = drive(client, owner[1], stalling(HEAD + PDF[:100]), cancel=None)
    took = time.monotonic() - started

    assert refusal(answered) == (408, "upload_too_slow")
    assert TRICKLE_S <= took < 10 * TRICKLE_S


def test_the_slot_of_a_refused_upload_is_free_again(
    one_slot: tuple[TestClient, asyncio.Semaphore], owner: tuple[UUID, dict[str, str]]
) -> None:
    client, slots = one_slot
    with_deadline(client, TRICKLE_S)

    assert refusal(drive(client, owner[1], stalling(HEAD + PDF[:100]), cancel=None))[0] == 408
    assert the_slot_is_free(client, slots, owner[1])


def test_a_refused_upload_leaves_nothing_behind(
    one_slot: tuple[TestClient, asyncio.Semaphore],
    owner: tuple[UUID, dict[str, str]],
    migrated: str,
    store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = with_deadline(one_slot[0], TRICKLE_S)
    made: list[tempfile.SpooledTemporaryFile[bytes]] = []

    class Counted(tempfile.SpooledTemporaryFile[bytes]):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", Counted)
    first = HEAD + PDF + b"x" * (3 * 2**19)  # past the parser's MiB in memory: spooled to disk

    answered = drive(client, owner[1], stalling(first), cancel=None, file_size=2**20 + 2**19 + 2**18)

    assert refusal(answered) == (408, "upload_too_slow")
    assert [spooled._rolled for spooled in made] == [True]  # type: ignore[attr-defined]
    assert all(spooled.closed for spooled in made)
    # a named file on disk where the system names it (Windows); elsewhere it never had a name
    assert not [
        spooled.name for spooled in made if isinstance(spooled.name, str) and Path(spooled.name).exists()
    ]
    assert nothing_was_kept(migrated, store)


def read_answer(connection: socket.socket) -> tuple[bytes, dict[str, Any]]:
    """The status line and JSON body of the answer on ``connection``."""
    data = b""
    while b"\r\n\r\n" not in data:
        piece = connection.recv(65536)
        assert piece, "closed before an answer"
        data += piece
    head, _, body = data.partition(b"\r\n\r\n")
    length = re.search(rb"(?im)^content-length: *(\d+)", head)
    assert length is not None
    while len(body) < int(length.group(1)):
        piece = connection.recv(65536)
        assert piece, "closed within the answer"
        body += piece
    return head.split(b"\r\n", 1)[0], json.loads(body)


def test_the_server_ends_the_connection_of_a_refused_upload(
    migrated: str, store: Path, owner: tuple[UUID, dict[str, str]], restore_logging: None
) -> None:
    configure_logging("INFO", "json", stream=io.StringIO())
    public_port, internal_port = two_free_ports()
    settings = make_settings(
        host="127.0.0.1",
        public_port=public_port,
        internal_port=internal_port,
        database_url=migrated,
        storage_dir=store,
        max_upload_mb=1,
        max_concurrent_uploads=1,
    ).model_copy(update={"upload_read_timeout_s": TRICKLE_S})
    head = (
        f"POST {sources.UPLOAD_PATH} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        f"Authorization: {owner[1]['Authorization']}\r\n"
        f"Content-Type: multipart/form-data; boundary={BOUNDARY}\r\n"
        f"Content-Length: {len(HEAD) + 2**19 + len(TAIL)}\r\n\r\n"
    ).encode()

    with serving(settings), socket.create_connection(("127.0.0.1", public_port), timeout=10) as connection:
        connection.sendall(head + HEAD + PDF[:100])
        status, body = read_answer(connection)
        # the rest of the body, a byte at a time: a server still reading it would never end
        connection.settimeout(0.2)
        closed = False
        until = time.monotonic() + 10
        while not closed and time.monotonic() < until:
            try:
                connection.sendall(b"x")
                closed = connection.recv(1) == b""
            except TimeoutError:
                continue
            except ConnectionError:
                closed = True

    assert (status.split(b" ")[1], body["code"]) == (b"408", "upload_too_slow")
    assert closed


def test_a_timeout_of_the_server_s_own_is_no_slow_upload(
    one_slot: tuple[TestClient, asyncio.Semaphore],
    owner: tuple[UUID, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a spool write to a /tmp that stalls fails with ETIMEDOUT, which Python raises as TimeoutError
    stalled = OSError(errno.ETIMEDOUT, "the spool's disk did not answer")
    assert isinstance(stalled, TimeoutError)

    async def failing(self: UploadFile, data: bytes) -> None:
        raise stalled

    monkeypatch.setattr(UploadFile, "write", failing)

    async def receive() -> Message:
        return {"type": "http.request", "body": HEAD + PDF + TAIL, "more_body": False}

    answered = drive(one_slot[0], owner[1], receive, cancel=None)

    assert answered[0]["status"] == 500


def test_an_upload_that_arrives_in_time_is_not_touched_by_the_deadline(
    one_slot: tuple[TestClient, asyncio.Semaphore], owner: tuple[UUID, dict[str, str]]
) -> None:
    client = with_deadline(one_slot[0], PACED_S)

    answered = drive(client, owner[1], paced(PACED_S / 6), cancel=None)  # half the deadline in all

    assert answered[0]["status"] == 201


def test_waiting_for_a_slot_is_not_counted_against_the_reading(
    one_slot: tuple[TestClient, asyncio.Semaphore],
    owner: tuple[UUID, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, slots = one_slot
    with_deadline(client, PACED_S)
    monkeypatch.setattr(sources, "UPLOAD_WAIT_S", 10.0)
    assert client.portal is not None
    client.portal.call(slots.acquire)  # another upload holds the only slot

    async def other_upload_ends() -> None:
        await asyncio.sleep(0.8 * PACED_S)
        slots.release()

    client.portal.start_task_soon(other_upload_ends)
    # half the deadline to read, once the slot is had: wait and reading together pass the deadline
    answered = drive(client, owner[1], paced(PACED_S / 6), cancel=None)

    assert answered[0]["status"] == 201
