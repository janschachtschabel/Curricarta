"""Both stores an upload writes to: the file system's, and S3's on the test service (MinIO), with
a bucket of its own that is emptied and removed after the test. As tests/core/test_s3_integration.py,
S3 is skipped without CURRICARTA_TEST_S3_URL, unless CURRICARTA_REQUIRE_S3 or CI is set."""

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.core.storage import FileSystemStorage, Storage
from app.core.storage_s3 import S3Storage, s3_client
from tests.support import make_settings

BACKENDS = [pytest.param("fs", id="fs"), pytest.param("s3", id="s3", marks=pytest.mark.s3)]


@dataclass
class UploadStore:
    """The settings that name the store, and the store itself, to look into."""

    settings: dict[str, Any]
    storage: Storage

    def stored_keys(self) -> list[str]:
        """Every key the store holds, temporary files of the file system store included."""
        if isinstance(self.storage, FileSystemStorage):
            root = self.storage.root
            return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
        assert isinstance(self.storage, S3Storage)
        pages = self.storage.client.get_paginator("list_objects_v2").paginate(Bucket=self.storage.bucket)
        return sorted(item["Key"] for page in pages for item in page.get("Contents", []))


def s3_settings() -> dict[str, Any]:
    url = os.environ.get("CURRICARTA_TEST_S3_URL")
    if not url:
        if os.environ.get("CURRICARTA_REQUIRE_S3") or os.environ.get("CI"):
            pytest.fail("CURRICARTA_TEST_S3_URL is not set, but the S3 tests are required")
        pytest.skip("CURRICARTA_TEST_S3_URL is not set")
    return {
        "storage_backend": "s3",
        "s3_endpoint_url": url,
        "s3_bucket": f"curricarta-t-{uuid.uuid4().hex[:12]}",
        "s3_access_key": os.environ["CURRICARTA_TEST_S3_ACCESS_KEY"],
        "s3_secret_key": os.environ["CURRICARTA_TEST_S3_SECRET_KEY"],
    }


@pytest.fixture(params=BACKENDS)
def upload_store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[UploadStore]:
    if request.param == "fs":
        root = tmp_path / "store"
        yield UploadStore({"storage_dir": root}, FileSystemStorage(root))
        return
    settings = s3_settings()
    client = s3_client(make_settings(**settings))
    bucket = settings["s3_bucket"]
    client.create_bucket(Bucket=bucket)
    store = UploadStore(settings, S3Storage(client, bucket))
    try:
        yield store
    finally:
        for key in store.stored_keys():
            client.delete_object(Bucket=bucket, Key=key)
        client.delete_bucket(Bucket=bucket)
