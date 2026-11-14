"""Whatever an archive's own bytes make zipfile raise is a refusal of the archive, never an error of
the service (review of audit 2026-11-14): an upload answers 415/413, not 500, and a URL import
ends instead of being fetched again. The same bytes give the same refusal in memory and in a
spooled file rolled to disk, as an upload's is. A source that breaks on its own - a disk that
fails, a file closed under the check - is not the archive's fault and is not passed off as one.
"""

import errno
import io
import logging
import platform
import tempfile
import zipfile
from collections.abc import Iterator
from typing import Any, BinaryIO, cast

import pytest

from app.sources import archives
from app.sources.archives import ArchiveTooLarge, ArchiveUnreadable
from app.sources.filetype import examine_file
from tests.sources.zip_helpers import make_zip, raw_zip, zip64_locator

PART = [(b"word/document.xml", b"", b"")]
SHAPES = {
    "zip64-locator-of-disk-1": raw_zip(PART, before_end=zip64_locator(disk=1)),
    "zip64-locator-of-two-disks": raw_zip(PART, before_end=zip64_locator(disks=2)),
    "zip64-locator-of-disk-1-and-a-comment": raw_zip(PART, before_end=zip64_locator(disk=1))[:-2]
    + b"\x04\x00note",
    "an-extract-version-zipfile-does-not-read": raw_zip(PART, version=99),
    "a-directory-stated-further-on-than-it-is": raw_zip(PART, shift=100),
}


@pytest.fixture(params=["memory", "disk"])
def held(request: pytest.FixtureRequest) -> Iterator[Any]:
    """Bytes as a source: a BytesIO, or a spooled file rolled to disk."""
    opened: list[Any] = []

    def source(data: bytes) -> BinaryIO:
        if request.param == "memory":
            return io.BytesIO(data)
        spooled = tempfile.SpooledTemporaryFile(max_size=16)  # noqa: SIM115 - closed by the fixture; rolls over
        spooled.write(data)
        spooled.seek(0)
        opened.append(spooled)
        return cast(BinaryIO, spooled)

    yield source
    for spooled in opened:
        spooled.close()


@pytest.mark.parametrize("name", list(SHAPES))
def test_an_archive_that_makes_zipfile_fail_is_refused_alike_in_memory_and_on_disk(
    held: Any, name: str
) -> None:
    source = held(SHAPES[name])

    with pytest.raises(ArchiveUnreadable):
        examine_file("lehrplan.docx", source)
    assert source.tell() == 0


def test_a_true_zip64_archive_is_refused_by_the_record_zipfile_returns(
    held: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # zipfile writes a ZIP64 end record and its locator once the parts pass its count limit
    with monkeypatch.context() as patched:
        patched.setattr(zipfile, "ZIP_FILECOUNT_LIMIT", 1)
        zip64 = make_zip({"word/document.xml": b"<w/>", "[Content_Types].xml": b"<Types/>"})
    assert zipfile._EndRecData(io.BytesIO(zip64))[0] == b"PK\x06\x06"  # type: ignore[attr-defined]

    with pytest.raises(ArchiveTooLarge, match="ZIP64 end record"):
        archives.check_archive_file(held(zip64))


class Failing(io.BytesIO):
    """A source that breaks on its own after ``reads`` reads: its disk fails, or it is closed."""

    def __init__(self, data: bytes, reads: int, closes: bool) -> None:
        super().__init__(data)
        self._left, self._closes = reads, closes

    def read(self, size: int | None = -1, /) -> bytes:
        if self._left == 0:
            if self._closes:
                self.close()
                return super().read(size)  # ValueError: I/O operation on closed file
            raise OSError(errno.EIO, "the disk failed (invented)")
        self._left -= 1
        return super().read(size)


@pytest.mark.parametrize("closes", [False, True], ids=["disk-fails", "closed"])
@pytest.mark.parametrize(
    "reads",
    [2, 7, 8, 10],
    ids=["at-the-end-record", "at-the-directory", "at-a-part-s-header", "at-a-part-s-data"],
)
def test_a_source_that_breaks_on_its_own_is_no_refusal_of_the_archive(reads: int, closes: bool) -> None:
    # reads 1-2 count the signatures; 3 the end record, 8 the directory, 9-10 a part's header, 11 its data
    source = Failing(make_zip({"word/document.xml": b"<w:document/>" * 40}), reads, closes)

    with pytest.raises(OSError if not closes else ValueError) as raised:
        archives.check_archive_file(source)
    assert not isinstance(raised.value, ArchiveUnreadable | ArchiveTooLarge)


def test_a_zipfile_that_changed_is_logged_once_without_the_archive(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(archives, "_told_of_a_changed_zipfile", False)
    monkeypatch.setattr(zipfile, "_EndRecData", lambda source: ("another", "shape"), raising=False)
    caplog.set_level(logging.ERROR, logger=archives.__name__)

    for _ in range(2):
        with pytest.raises(ArchiveUnreadable):
            archives.check_archive_file(io.BytesIO(make_zip({"word/document.xml": b"<w/>"})))

    told = [record for record in caplog.records if record.name == archives.__name__]
    assert len(told) == 1 and told[0].levelno == logging.ERROR
    assert platform.python_version() in told[0].getMessage() and "another" not in told[0].getMessage()


def test_an_archive_without_an_end_record_is_refused_without_a_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger=archives.__name__)

    with pytest.raises(ArchiveUnreadable):
        archives.check_archive_file(io.BytesIO(b"PK\x03\x04" + b"\0" * 40))

    assert [record for record in caplog.records if record.name == archives.__name__] == []
