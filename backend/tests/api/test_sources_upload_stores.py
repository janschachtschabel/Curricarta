"""An upload stored from its spooled file, in both stores (audit 2026-11-14): the object's checksum
is the one its row names, and however the upload ends early - the client gone, a body past the
limit found while it streams, a store that fails half-way - nothing is left in the database, and
nothing half-written under the object's key, where a later upload of the same bytes would take
it for stored.
"""

import hashlib
import tempfile
import threading
import tracemalloc
from collections.abc import Iterator
from typing import Any, BinaryIO
from uuid import UUID

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from starlette.types import Message

from app.api import sources
from app.api.app import create_app
from tests.api.test_sources_upload import PDF, PUBLIC, migrated, owner, rows, upload
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
    client: TestClient, migrated: str, upload_store: UploadStore, owner: tuple[UUID, dict[str, str]]
) -> None:
    answer = upload(client, owner[1], data=FILE)

    assert answer.status_code == 201
    assert answer.json()["file"]["sha256"] == hashlib.sha256(FILE).hexdigest()
    assert stored_as_its_row_says(migrated, upload_store)


def test_an_upload_is_never_held_whole_in_memory(upload_store: UploadStore) -> None:
    # examined and stored from the file the form parser spooled, a piece at a time (audit 2026-11-14)
    size = 8 * 2**20
    with tempfile.SpooledTemporaryFile(max_size=2**20) as spooled:  # as the form parser spools it
        spooled.write(PDF + b"x" * (size - len(PDF)))
        spooled.seek(0)
        upload_file = UploadFile(spooled, size=size, filename="lehrplan.pdf")  # type: ignore[arg-type]

        tracemalloc.start()
        try:
            detected, digest, examined = sources._examined(upload_file, 50 * 2**20)
            upload_store.storage.put_file("sources/big", upload_file.file, examined)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    assert (detected.mime, examined) == ("application/pdf", size)
    assert hashlib.sha256(upload_store.storage.get("sources/big")).digest() == digest
    assert peak < 3 * 2**20


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
    # sent in pieces without a length: the body limit (MAX_UPLOAD_MB + 1 MiB) counts as it reads
    def body() -> Iterator[bytes]:
        yield HEAD
        for _ in range(6):
            yield FILE[: 2**20]

    answer = client.post(
        "/api/v1/sources",
        content=body(),
        headers={**owner[1], "Content-Type": "multipart/form-data; boundary=curricarta"},
    )

    assert answer.status_code == 413
    assert answer.json()["code"] == "content_too_large"
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


def test_a_store_that_fails_half_way_leaves_nothing_under_the_key(
    client: TestClient,
    migrated: str,
    upload_store: UploadStore,
    owner: tuple[UUID, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = client.app.state.storage.sync  # type: ignore[attr-defined]
    put_file = store.put_file

    def breaking(key: str, source: BinaryIO, size: int) -> Any:
        return put_file(key, Breaking(source), size)

    monkeypatch.setattr(store, "put_file", breaking)
    assert upload(client, owner[1], data=FILE).status_code == 500
    assert no_entry(migrated) and upload_store.stored_keys() == []

    # the same bytes again find no object under their key, and are stored whole
    monkeypatch.setattr(store, "put_file", put_file)
    assert upload(client, owner[1], data=FILE).status_code == 201
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
