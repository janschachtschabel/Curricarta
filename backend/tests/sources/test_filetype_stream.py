"""A file examined as it is read, a piece at a time (audit 2026-11-14): an upload's spooled file is
never held whole, and comes to what its bytes would - the same type, checksum and refusals."""

import io
import zipfile
from collections.abc import Callable
from typing import Any, NoReturn

import pytest

from app.sources import archives
from app.sources.archives import ArchiveTooLarge, ArchiveUnreadable
from app.sources.filetype import UnsupportedType, examine, examine_file
from tests.sources.zip_helpers import directory_only, directory_says, make_zip

UTF8_ACROSS = ("a" + "ä" * 2**19).encode()  # 1 MiB and a byte: the last sign split over two pieces
TEXTS = ("lp.md", "page.html", "note.txt", "lp.ttl")
EXAMINED = [
    pytest.param("x.pdf", b"%PDF-1.7 ...", id="pdf"),
    pytest.param("x.rtf", b"{\\rtf1\\ansi", id="rtf"),
    pytest.param("spoof.md", b"%PDF-1.4", id="magic-over-name"),
    *(pytest.param(name, "# Titel äöü\n".encode(), id=name) for name in TEXTS),
    pytest.param("long.txt", UTF8_ACROSS, id="utf8-across-pieces"),
    pytest.param("empty.txt", b"", id="empty-text"),
    pytest.param("evil.bin", b"\x00\x01\x02rubbish", id="unknown-binary"),
    pytest.param("broken.md", b"\xff\xfe\x00bad", id="text-not-utf8"),
    pytest.param("cut.txt", "ä".encode()[:1], id="text-cut-in-a-sign"),
    pytest.param(None, b"plain text", id="no-name-no-magic"),
    pytest.param("evil.exe", b"MZ\x90\x00", id="executable"),
    pytest.param("x.docx", make_zip({"word/document.xml": b"<w:document/>" * 200}), id="ordinary-archive"),
    pytest.param("bomb.docx", make_zip({"word/document.xml": b"\0" * (4 * 2**20)}), id="bomb"),
    pytest.param(
        "many.docx", make_zip({f"p{index}.xml": b"x" for index in range(5001)}), id="too-many-parts"
    ),
    pytest.param("dir.docx", directory_only(6000), id="too-many-in-the-directory"),
    pytest.param("x.docx", b"PK\x03\x04" + b"\0" * 20, id="unreadable-archive"),
    pytest.param(
        "lying.docx",
        directory_says(make_zip({"word/document.xml": b"\0" * (2 * 2**20)}), size=16),
        id="part-past-its-size",
    ),
    pytest.param("bz.docx", make_zip({"word/document.xml": b"<w/>"}, zipfile.ZIP_BZIP2), id="bzip2"),
    pytest.param(
        "enc.docx", directory_says(make_zip({"word/document.xml": b"<w/>"}), flags=0x1), id="encrypted"
    ),
]


def outcome(examined: Callable[[], Any]) -> Any:
    """What an examination came to: its answer, or the kind of its refusal."""
    try:
        return examined()
    except (UnsupportedType, ArchiveUnreadable, ArchiveTooLarge) as refused:
        return type(refused)


@pytest.mark.parametrize(("name", "data"), EXAMINED)
def test_a_file_is_examined_as_its_bytes_are(name: str | None, data: bytes) -> None:
    source = io.BytesIO(data)

    by_file = outcome(lambda: examine_file(name, source))

    by_bytes = outcome(lambda: examine(name, data))
    assert by_file == (by_bytes if isinstance(by_bytes, type) else (*by_bytes, len(data)))
    assert source.tell() == 0  # left where it stood, for the store to read it


def test_a_directory_signature_split_over_two_pieces_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    # counted piece by piece, a signature across two pieces is counted, before the directory is read
    def unread(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("the directory was read")

    monkeypatch.setattr(archives, "MAX_ARCHIVE_ENTRIES", 1)
    monkeypatch.setattr(zipfile, "ZipFile", unread)
    entry = b"PK\x01\x02"
    split = b"x" * (archives.COUNTING_PIECE - 2) + entry + b"x" * 10 + entry

    with pytest.raises(ArchiveTooLarge):
        archives.check_archive_file(io.BytesIO(split))


def test_text_that_stops_being_utf8_in_a_later_piece_is_no_text() -> None:
    with pytest.raises(UnsupportedType):
        examine_file("lehrplan.txt", io.BytesIO(b"a" * (3 * 2**20) + b"\xff"))
