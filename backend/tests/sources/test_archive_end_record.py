"""An archive's end record, as zipfile itself will take it (review of audit 2026-11-14).

The directory bound is checked on the record zipfile reads its directory by - zipfile's own
_EndRecData - so no crafted file can show the check one record and zipfile another: a record that
carries the signature in its own fields, a signature in a comment, a fake record where a search
would find it first, bytes after the record, a ZIP64 locator.
"""

import io
import tracemalloc
import zipfile
from typing import Any

import pytest

from app.sources import archives
from app.sources.archives import ArchiveTooLarge, ArchiveUnreadable
from app.sources.filetype import examine_file
from tests.sources.zip_helpers import (
    commented_parts,
    end_signature_in_offset,
    make_zip,
    with_fake_end_record_in_an_entry,
    with_zip64_locator,
)

PARTS = {"word/document.xml": b"<w:document/>" * 50, "[Content_Types].xml": b"<Types/>"}
ZIPPED = make_zip(PARTS)


def with_comment(data: bytes, comment: bytes) -> bytes:
    with zipfile.ZipFile(buffer := io.BytesIO(data), "a") as archive:
        archive.comment = comment
    return buffer.getvalue()


def directory_read_by_zipfile(data: bytes) -> int:
    """The bytes of central directory zipfile read: each entry's 46 bytes, name, extra, comment."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return sum(
            46
            + len(info.orig_filename.encode("utf-8" if info.flag_bits & 0x800 else "cp437"))
            + len(info.extra)
            + len(info.comment)
            for info in archive.infolist()
        )


# a directory of 4,900 parts with 2,000-byte comments: about four times the bound
HEAVY = commented_parts(4900, comment=2000)
PLANTED = end_signature_in_offset(HEAVY)
CRAFTED = {
    "honest": make_zip(PARTS),
    "honest-with-comment": with_comment(make_zip(PARTS), b"made by a tool"),
    "honest-many-parts": commented_parts(300, comment=100),
    "signature-in-the-record-s-offset": PLANTED,
    "fake-record-in-an-entry": with_fake_end_record_in_an_entry(PARTS, b"an archive comment"),
    "fake-record-in-a-heavy-archive": with_fake_end_record_in_an_entry(
        {f"p/{index:05}.xml": b"<p/>" * 3 for index in range(400)}, b"note"
    ),
}


def test_zipfile_s_end_record_is_what_the_check_reads() -> None:
    # a private name of zipfile: a Python whose zipfile changes it fails here, loudly
    data = with_comment(make_zip(PARTS), b"note")
    record: Any = zipfile._EndRecData(io.BytesIO(data))  # type: ignore[attr-defined]

    assert isinstance(record, list) and len(record) == 10
    assert (zipfile._ECD_SIGNATURE, zipfile._ECD_SIZE, zipfile._ECD_OFFSET) == (0, 5, 6)  # type: ignore[attr-defined]
    assert (zipfile._ECD_COMMENT_SIZE, zipfile._ECD_COMMENT, zipfile._ECD_LOCATION) == (7, 8, 9)  # type: ignore[attr-defined]
    assert record[0] == b"PK\x05\x06" and record[7] == 4 and record[8] == b"note"
    assert record[9] == len(data) - 22 - 4
    assert record[5] == directory_read_by_zipfile(data)


@pytest.mark.parametrize("name", list(CRAFTED))
def test_the_check_reads_the_directory_size_zipfile_reads(name: str) -> None:
    data = CRAFTED[name]

    assert archives.end_record(io.BytesIO(data)).directory_size == directory_read_by_zipfile(data)


def test_a_signature_planted_in_the_record_s_offset_is_refused_with_little_held() -> None:
    # the last copy of the signature is in the record's own offset field: a search finds it there
    tracemalloc.start()
    try:
        with pytest.raises(ArchiveTooLarge):
            examine_file("lehrplan.docx", io.BytesIO(PLANTED))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert peak < 9 * 2**20  # the DOCX bound of tests/api/test_sources_upload_memory.py
    with pytest.raises(ArchiveTooLarge):
        archives.check_archive_file(io.BytesIO(PLANTED))


@pytest.mark.parametrize(
    ("data", "refusal"),
    [
        (with_comment(make_zip(PARTS), b"PK\x05\x06" + b"x" * 30), ArchiveUnreadable),
        (with_comment(make_zip(PARTS), b"x" * 10 + b"PK\x05\x06"), ArchiveUnreadable),
        (make_zip(PARTS) + b"trailing bytes", ArchiveUnreadable),
        (with_zip64_locator(make_zip(PARTS)), ArchiveTooLarge),
        (ZIPPED[:-12] + b"\xff\xff" + ZIPPED[-10:], ArchiveTooLarge),  # its count of parts
    ],
    ids=[
        "signature-in-the-comment",
        "signature-ending-the-comment",
        "bytes-after-the-record",
        "zip64-locator",
        "zip64-marker-in-the-count",
    ],
)
def test_a_record_zipfile_would_take_otherwise_than_it_seems_is_refused(
    data: bytes, refusal: type[Exception]
) -> None:
    with pytest.raises(refusal):
        archives.check_archive_file(io.BytesIO(data))


def test_a_record_zipfile_finds_none_of_or_shapes_otherwise_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # fail closed: a zipfile that changed is no reason to skip the check
    for answer in (None, ["PK"] * 3, "not a record"):
        monkeypatch.setattr(zipfile, "_EndRecData", lambda source, answer=answer: answer, raising=False)
        with pytest.raises(ArchiveUnreadable):
            archives.check_archive_file(io.BytesIO(make_zip(PARTS)))
    monkeypatch.delattr(zipfile, "_EndRecData")
    with pytest.raises(ArchiveUnreadable):
        archives.check_archive_file(io.BytesIO(make_zip(PARTS)))
