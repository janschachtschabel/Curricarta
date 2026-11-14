"""The S3 store against a real service: MinIO in a container for tests only.

CURRICARTA_TEST_S3_URL names it (locally the container curricarta-test-minio, in CI a step that starts one),
with CURRICARTA_TEST_S3_ACCESS_KEY and CURRICARTA_TEST_S3_SECRET_KEY - invented credentials of that
container. Each test gets a bucket of its own and leaves nothing behind. Without the variable
the tests are skipped, unless CURRICARTA_REQUIRE_S3 or CI is set.
"""

import hashlib
import io
import os
import tempfile
import uuid
from collections.abc import Iterator
from typing import Any, BinaryIO, cast

import pytest
from botocore.awsrequest import AWSResponse  # type: ignore[import-untyped]

from app.core.settings import Settings
from app.core.storage import ObjectNotFound, StorageNotConfigured, open_storage
from app.core.storage_s3 import S3Storage, s3_client
from tests.support import make_settings

pytestmark = pytest.mark.s3


@pytest.fixture
def service_settings() -> Settings:
    """Settings for the test service, with a bucket name of their own that nothing holds yet."""
    url = os.environ.get("CURRICARTA_TEST_S3_URL")
    if not url:
        if os.environ.get("CURRICARTA_REQUIRE_S3") or os.environ.get("CI"):
            pytest.fail("CURRICARTA_TEST_S3_URL is not set, but the S3 tests are required")
        pytest.skip("CURRICARTA_TEST_S3_URL is not set")
    return make_settings(
        storage_backend="s3",
        s3_endpoint_url=url,
        s3_bucket=f"curricarta-t-{uuid.uuid4().hex[:12]}",
        s3_access_key=os.environ["CURRICARTA_TEST_S3_ACCESS_KEY"],
        s3_secret_key=os.environ["CURRICARTA_TEST_S3_SECRET_KEY"],
    )


@pytest.fixture
def storage(service_settings: Settings) -> Iterator[S3Storage]:
    settings = service_settings
    assert settings.s3_bucket is not None
    bucket = settings.s3_bucket
    client = s3_client(settings)
    client.create_bucket(Bucket=bucket)
    try:
        yield S3Storage(client, bucket)
    finally:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                client.delete_object(Bucket=bucket, Key=item["Key"])
        client.delete_bucket(Bucket=bucket)


def test_an_object_is_written_read_replaced_and_deleted(storage: S3Storage) -> None:
    storage.put("sources/ab/abc.pdf", b"%PDF-1.7 first")
    assert storage.exists("sources/ab/abc.pdf")
    assert storage.get("sources/ab/abc.pdf") == b"%PDF-1.7 first"

    storage.put("sources/ab/abc.pdf", b"%PDF-1.7 second")
    assert storage.get("sources/ab/abc.pdf") == b"%PDF-1.7 second"

    storage.delete("sources/ab/abc.pdf")
    assert not storage.exists("sources/ab/abc.pdf")


def test_a_missing_object_is_not_found_the_way_the_file_system_store_says_it(storage: S3Storage) -> None:
    with pytest.raises(ObjectNotFound):
        storage.get("runs/missing.json")
    with pytest.raises(ObjectNotFound):
        storage.delete("runs/missing.json")
    assert storage.exists("runs/missing.json") is False


def test_the_service_lists_what_was_put(storage: S3Storage) -> None:
    for key in ("runs/a/x4/1.json", "runs/a/x4/3.json", "runs/ab/x4/1.json"):
        storage.put(key, b"{}")

    assert sorted(storage.list("runs/a/")) == ["runs/a/x4/1.json", "runs/a/x4/3.json"]
    assert list(storage.list("runs/none/")) == []


def test_bytes_come_back_as_they_went_in(storage: S3Storage) -> None:
    data = bytes(range(256)) * 4096  # 1 MiB with every byte value

    storage.put("blob.bin", data)

    assert storage.get("blob.bin") == data


def test_an_object_comes_back_in_pieces_with_its_size(storage: S3Storage) -> None:
    data = bytes(range(256)) * (10 * 2**10)  # 2.5 MiB
    storage.put("sources/big.pdf", data)

    stream = storage.open_stream("sources/big.pdf")
    pieces = list(stream)

    assert stream.size == len(data)
    assert max(len(piece) for piece in pieces) <= 2**20
    assert b"".join(pieces) == data
    with pytest.raises(ObjectNotFound):
        storage.open_stream("sources/missing.pdf")


def test_a_stream_of_several_mib_is_stored_whole(storage: S3Storage) -> None:
    data = os.urandom(5 * 2**20)
    with tempfile.SpooledTemporaryFile(max_size=2**20) as spooled:  # as the form parser spools an upload
        spooled.write(b"form head" + data)
        spooled.seek(len(b"form head"))

        storage.put_file("sources/big.pdf", cast(BinaryIO, spooled), len(data))

    assert hashlib.sha256(storage.get("sources/big.pdf")).digest() == hashlib.sha256(data).digest()


def test_a_retried_put_sends_the_stream_from_where_it_stood_again(storage: S3Storage) -> None:
    # The first attempt reads the body and is answered 500, as a service may answer; botocore
    # rewinds the body (seek(0)) and sends it again, here to the local test service
    data = os.urandom(2 * 2**20)
    attempts: list[int] = []

    def first_fails(request: Any, **kwargs: Any) -> AWSResponse | None:
        attempts.append(1)
        if len(attempts) > 1:
            return None
        while request.body.read(2**16):  # sent, as far as the client knows
            pass
        return AWSResponse(request.url, 500, {}, Raw(b"<Error><Code>InternalError</Code></Error>"))

    storage.client.meta.events.register("before-send.s3.PutObject", first_fails)
    try:
        with tempfile.SpooledTemporaryFile(max_size=2**20) as spooled:
            spooled.write(b"form head" + data + b"--boundary--")
            spooled.seek(len(b"form head"))

            storage.put_file("sources/big.pdf", cast(BinaryIO, spooled), len(data))
    finally:
        storage.client.meta.events.unregister("before-send.s3.PutObject", first_fails)

    assert len(attempts) == 2
    assert hashlib.sha256(storage.get("sources/big.pdf")).digest() == hashlib.sha256(data).digest()


def test_an_empty_stream_at_its_end_is_stored_empty(storage: S3Storage) -> None:
    source = io.BytesIO(b"form head")
    source.seek(0, io.SEEK_END)

    storage.put_file("sources/empty.txt", source, 0)

    assert storage.get("sources/empty.txt") == b""


class Raw:
    """The raw answer AWSResponse reads its content from."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def stream(self, **kwargs: Any) -> Iterator[bytes]:
        yield self._content


def test_a_bucket_the_service_does_not_hold_stops_the_opening(service_settings: Settings) -> None:
    # on a HEAD, MinIO answers a missing bucket as it does a missing key: 404
    with pytest.raises(StorageNotConfigured, match="S3_BUCKET"):
        open_storage(service_settings)


def test_the_store_opens_on_a_bucket_the_service_holds(
    storage: S3Storage, service_settings: Settings
) -> None:
    assert isinstance(open_storage(service_settings), S3Storage)
