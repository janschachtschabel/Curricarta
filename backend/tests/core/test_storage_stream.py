"""An object written from a stream on the file system: read in pieces from where the stream
stands, never held whole, and - as a write of bytes - whole or not at all, inside the root."""

import io
from pathlib import Path

import pytest

from app.core.storage import CHUNK_BYTES, FileSystemStorage, InvalidKey
from tests.core.test_storage import LEAVING_KEYS


@pytest.fixture
def storage(tmp_path: Path) -> FileSystemStorage:
    return FileSystemStorage(tmp_path / "objects")


class Noting(io.BytesIO):
    """A stream that notes the size of each read; ``fails_after`` bytes in, a read fails."""

    def __init__(self, data: bytes, fails_after: int | None = None) -> None:
        super().__init__(data)
        self.reads: list[int | None] = []
        self._fails_after = fails_after

    def read(self, size: int | None = -1, /) -> bytes:
        self.reads.append(size)
        if self._fails_after is not None and self.tell() >= self._fails_after:
            raise OSError("the connection broke (invented)")
        return super().read(size)


def test_a_stream_is_written_in_pieces_and_reads_back_whole(storage: FileSystemStorage) -> None:
    data = bytes(range(256)) * (10 * 2**10)  # 2.5 MiB
    source = Noting(b"form head" + data)
    source.seek(len(b"form head"))  # read from where the stream stands

    storage.put_file("sources/big.pdf", source, len(data))

    assert storage.get("sources/big.pdf") == data
    assert source.reads and all(size is not None and 0 < size <= CHUNK_BYTES for size in source.reads)


@pytest.mark.parametrize(
    ("source", "size"),
    [(Noting(b"x" * (3 * CHUNK_BYTES), fails_after=CHUNK_BYTES), 3 * CHUNK_BYTES), (Noting(b"short"), 10)],
    ids=["read-fails", "ends-before-its-size"],
)
def test_a_stream_that_breaks_leaves_the_old_object_and_no_stray_file(
    storage: FileSystemStorage, source: Noting, size: int
) -> None:
    storage.put("runs/1.json", b"old")

    with pytest.raises(OSError):
        storage.put_file("runs/1.json", source, size)

    assert storage.get("runs/1.json") == b"old"
    assert [path.name for path in (storage.root / "runs").iterdir()] == ["1.json"]


@pytest.mark.parametrize("key", LEAVING_KEYS)
def test_a_stream_under_a_key_that_could_leave_the_root_is_refused(
    storage: FileSystemStorage, tmp_path: Path, key: str
) -> None:
    source = Noting(b"x")

    with pytest.raises(InvalidKey):
        storage.put_file(key, source, 1)

    assert not (tmp_path / "outside.txt").exists()
    assert source.reads == []
