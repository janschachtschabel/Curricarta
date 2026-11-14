"""An upload stored from its spooled file, in both stores (audit 2026-11-14): the object's checksum
is the one its row names, and however the upload ends early - the client gone, a body past the
limit found while it streams, a store that fails half-way - nothing is left in the database, and
nothing half-written under the object's key, where a later upload of the same bytes would take
it for stored.
"""

import hashlib
import json
import threading
from collections.abc import Iterator
from typing import Any, BinaryIO
from uuid import UUID

import psycopg
import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from starlette.types import Message

from app.api.app import create_app
from tests.api.test_sources_upload import PUBLIC, migrated, owner, rows, upload
from tests.api.test_sources_upload_slots import HEAD, drive
from tests.api.upload_stores import UploadStore, upload_store
from tests.support import make_settings, seed_account, selector_client

pytestmark = pytest.mark.pg
__all__ = ["migrated", "owner", "upload_store"]  # the fixtures, taken over

FILE = b"%PDF-1.7\n" + bytes(range(256)) * (12 * 2**10)  # 3 MiB and a little: four pieces


@pytest.fixture
def client(migrated: str, upload_store: UploadStore) -> Iterator[TestClient]:
    settings = make_settings(database_url=migrated, max_upload_mb=4, **upload_store.settings)
    with selector_client(create_app(settings), base_url=PUBLIC, raise_server_exceptions=False) as client:
        yield client


def no_entry(url: str) -> bool:
    return rows(url, "SELECT (SELECT count(*) FROM source), (SELECT count(*) FROM source_file)") == [(0, 0)]


def stored_as_its_row_says(url: str, store: UploadStore) -> bool:
    ((key, sha256, size),) = rows(url, "SELECT storage_key, sha256, size_bytes FROM source_file")
    held = store.storage.get(key)
    return store.stored_keys() == [key] and (hashlib.sha256(held).digest(), len(held)) == (
        bytes(sha256),
        size,
    )


def test_an_upload_is_stored_under_the_checksum_its_row_names(
    client: TestClient,
    migrated: str,
    upload_store: UploadStore,
    owner: tuple[UUID, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[int] = []
    read = UploadFile.read

    async def counted(self: UploadFile, size: int = -1) -> bytes:
        reads.append(size)
        return await read(self, size)

    monkeypatch.setattr(UploadFile, "read", counted)
    answer = upload(client, owner[1], data=FILE)

    assert answer.status_code == 201
    assert reads == []  # examined and stored from the spooled file, never read through UploadFile
    assert answer.json()["file"]["sha256"] == hashlib.sha256(FILE).hexdigest()
    assert stored_as_its_row_says(migrated, upload_store)


def test_an_upload_whose_client_goes_leaves_nothing(
    client: TestClient, migrated: str, upload_store: UploadStore, owner: tuple[UUID, dict[str, str]]
) -> None:
    messages: list[Message] = [{"type": "http.request", "body": HEAD + FILE[: 2**20], "more_body": True}]

    async def receive() -> Message:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    drive(client, owner[1], receive, cancel=None, file_size=len(FILE))

    assert not messages
    assert no_entry(migrated) and upload_store.stored_keys() == []


def test_a_body_past_the_limit_found_while_it_streams_leaves_nothing(
    client: TestClient, migrated: str, upload_store: UploadStore, owner: tuple[UUID, dict[str, str]]
) -> None:
    # a MiB a message and no stated length: the body limit (MAX_UPLOAD_MB + 1 MiB) counts as it reads
    pieces: list[Message] = [{"type": "http.request", "body": HEAD, "more_body": True}]
    pieces += [{"type": "http.request", "body": FILE[: 2**20], "more_body": True} for _ in range(8)]

    async def receive() -> Message:
        return pieces.pop(0) if pieces else {"type": "http.disconnect"}

    answered = drive(client, owner[1], receive, cancel=None, file_size=None)

    start = next(message for message in answered if message["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in answered if m["type"] == "http.response.body")
    assert (start["status"], json.loads(body)["code"]) == (413, "content_too_large")
    assert 0 < len(pieces) < 8  # refused while the body came in, before its end
    assert no_entry(migrated) and upload_store.stored_keys() == []


class Breaking:
    """The spooled file, whose reading breaks a MiB in, as a full disk or a dropped connection would."""

    def __init__(self, inner: BinaryIO) -> None:
        self._inner = inner
        self._end = inner.tell() + 2**20

    def read(self, size: int = -1) -> bytes:
        if self._inner.tell() >= self._end:
            raise OSError("the store broke off (invented)")
        return self._inner.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._inner.seek(offset, whence)

    def tell(self) -> int:
        return self._inner.tell()


def test_a_stream_that_breaks_while_the_store_reads_it_leaves_nothing_under_the_key(
    client: TestClient,
    migrated: str,
    upload_store: UploadStore,
    owner: tuple[UUID, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The file system store breaks off half-way through its temporary file. The S3 store reads the
    # whole body for its signature before it sends it (SigV4 over http): it breaks before a PUT
    # goes out - and a PUT is whole or nothing anyway
    store = client.app.state.storage.sync  # type: ignore[attr-defined]
    put_file = store.put_file
    sent = sends_of(store)

    def breaking(key: str, source: BinaryIO, size: int) -> Any:
        return put_file(key, Breaking(source), size)

    monkeypatch.setattr(store, "put_file", breaking)
    assert upload(client, owner[1], data=FILE).status_code == 500
    assert no_entry(migrated) and upload_store.stored_keys() == []
    assert "PutObject" not in sent

    # the same bytes again find no object under their key, and are stored whole
    monkeypatch.setattr(store, "put_file", put_file)
    assert upload(client, owner[1], data=FILE).status_code == 201
    assert stored_as_its_row_says(migrated, upload_store)
    assert sent.count("PutObject") == (1 if hasattr(store, "client") else 0)  # the count sees a PUT


def sends_of(store: Any) -> list[str]:
    """The requests an S3 store sends from now on, by operation; none for the file system store."""
    sent: list[str] = []

    def noted(event_name: str, **kwargs: Any) -> None:  # before-send.s3.<operation>
        sent.append(event_name.rsplit(".", 1)[-1])

    if hasattr(store, "client"):
        store.client.meta.events.register("before-send.s3", noted)
    return sent


REFUSING_AUDIT = """
CREATE FUNCTION refuse_upload_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'the database refused the entry (invented)'; END $$;
CREATE TRIGGER refuse_upload_audit BEFORE INSERT ON audit_log
FOR EACH ROW WHEN (NEW.action = 'source.upload') EXECUTE FUNCTION refuse_upload_audit();
"""
# every table an upload writes to, in its one transaction
UPLOAD_ROWS = (
    "SELECT (SELECT count(*) FROM source_file), (SELECT count(*) FROM entity WHERE kind = 'source'),"
    " (SELECT count(*) FROM source), (SELECT count(*) FROM acquisition),"
    " (SELECT count(*) FROM audit_log WHERE action = 'source.upload')"
)


def test_a_failed_insert_leaves_the_object_which_the_next_upload_adopts(
    client: TestClient,
    migrated: str,
    upload_store: UploadStore,
    owner: tuple[UUID, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Stored, then the database refuses the upload's last insert, its audit entry: the transaction
    # takes back every row it wrote, the object stays, whole, without a row - addressed by its
    # bytes, nothing in this package sweeps it - and the same bytes take it over
    with psycopg.connect(migrated, autocommit=True) as connection:
        connection.execute(REFUSING_AUDIT)
    try:
        assert upload(client, owner[1], data=FILE).status_code == 500
    finally:
        with psycopg.connect(migrated, autocommit=True) as connection:
            connection.execute("DROP TRIGGER refuse_upload_audit ON audit_log")
            connection.execute("DROP FUNCTION refuse_upload_audit()")
    key = f"sources/{hashlib.sha256(FILE).hexdigest()}"
    assert rows(migrated, UPLOAD_ROWS) == [(0, 0, 0, 0, 0)]
    assert upload_store.stored_keys() == [key]

    store = client.app.state.storage.sync  # type: ignore[attr-defined]
    writes: list[str] = []
    put_file = store.put_file

    def noted(key: str, source: BinaryIO, size: int) -> None:
        writes.append(key)
        put_file(key, source, size)

    monkeypatch.setattr(store, "put_file", noted)
    assert upload(client, owner[1], data=FILE).status_code == 201
    assert writes == []  # found under its key, not written again
    assert stored_as_its_row_says(migrated, upload_store)


def test_an_empty_text_is_stored_empty(
    client: TestClient, migrated: str, upload_store: UploadStore, owner: tuple[UUID, dict[str, str]]
) -> None:
    # nothing to read: on S3 a PUT of length 0 from a stream at its end
    answer = upload(client, owner[1], data=b"", name="notiz.txt")

    assert answer.status_code == 201
    assert answer.json()["file"]["size"] == 0
    assert stored_as_its_row_says(migrated, upload_store)


def test_two_replicas_storing_the_same_bytes_at_once_keep_one_whole_object(
    migrated: str, upload_store: UploadStore, owner: tuple[UUID, dict[str, str]]
) -> None:
    # both find no object under the key and write it from their own spooled file at the same time
    other = seed_account(migrated, "Andere", ["nutzer"])[1]
    settings = make_settings(database_url=migrated, max_upload_mb=4, **upload_store.settings)
    apps = [create_app(settings) for _ in range(2)]
    for app in apps:  # built before the threads start (tests/api/test_mem_import.py, send_at_once)
        list(iter_route_contexts(app.routes))
    both_write = threading.Barrier(2, timeout=30)
    answers: list[int] = []

    def replica(app: Any, header: dict[str, str]) -> None:
        with selector_client(app, base_url=PUBLIC) as client:
            store = app.state.storage.sync
            put_file = store.put_file

            def together(key: str, source: BinaryIO, size: int) -> None:
                both_write.wait()
                put_file(key, source, size)

            store.put_file = together
            answers.append(upload(client, header, data=FILE).status_code)

    threads = [
        threading.Thread(target=replica, args=pair) for pair in zip(apps, (owner[1], other), strict=True)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert answers == [201, 201]
    assert rows(migrated, "SELECT count(*) FROM source") == [(2,)]
    assert stored_as_its_row_says(migrated, upload_store)
