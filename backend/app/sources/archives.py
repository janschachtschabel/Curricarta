"""A ZIP that comes in (a DOCX, an OOXML file) held to bounds before anything unpacks it.

Taken over from curriculum-extractor (services/filetype.py), with what its audits found:
python-docx holds every part in memory, so a 200 KiB upload that expanded to 200 MiB peaked at
438 MiB in 0.6 s, and about 3 MB of DOCX reached the container's limit. A real curriculum is
far below all three bounds.
"""

import copy
import io
import struct
import sys
import zipfile
import zlib
from typing import BinaryIO

MAX_ARCHIVE_ENTRIES = 5000
MAX_ARCHIVE_EXPANDED = 256 * 2**20
# A part over a MiB that expands more than a hundredfold is a bomb, not a text
_BOMB_MIN_SIZE = 2**20
_BOMB_RATIO = 100
# How every document packs its parts. zipfile unpacks what it reads of a BZIP2 or LZMA part
# whole, however small a block it is asked for, so no measurement in blocks bounds those
_PACKED_WITH = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_ENCRYPTED = 0x1  # general-purpose bit 0
_MEASURING_BLOCK = 2**16
_DIRECTORY_ENTRY = b"PK\x01\x02"  # the signature each part's entry in the central directory starts with
COUNTING_PIECE = 2**20  # the signatures are counted a piece at a time, never in the whole file
# zipfile reads the central directory whole, by the size the end record states, and makes an object
# of each entry. An entry is 46 bytes and the part's name, extra field and comment; a document's
# names are short (an OOXML part's longest, "word/glossary/stylesWithEffects.xml", is 36 bytes), its
# extra fields a few dozen bytes, and it has no comments: 512 bytes a part is a fivefold margin on
# about 100. So the directory of MAX_ARCHIVE_ENTRIES parts is 5,000 x 512 B = 2.44 MiB at most -
# a real DOCX's has some 20 to 200 parts, a few KiB to 20 KiB.
MAX_DIRECTORY_BYTES = MAX_ARCHIVE_ENTRIES * 512
# A document's archive carries no comment of its own; zipfile reads up to 64 KiB of one
MAX_ARCHIVE_COMMENT = 2**10
_END = b"PK\x05\x06"  # the end record's signature; the record is 22 bytes and the comment
_END_RECORD = struct.Struct("<4s4H2IH")
_ZIP64_LOCATOR = b"PK\x06\x07"  # 20 bytes right before the end record of a ZIP64 archive


class ArchiveUnreadable(ValueError):
    """A ZIP whose directory or parts cannot be read: not a document to convert."""


class ArchiveTooLarge(ValueError):
    """A ZIP that would expand beyond what one conversion may hold."""


def check_archive(data: bytes) -> None:
    """``check_archive_file`` of bytes held in memory (a URL import's)."""
    check_archive_file(io.BytesIO(data))


def check_archive_file(source: BinaryIO) -> None:
    """Refuse a ZIP whose parts would expand past the bounds above. The archive is ``source``
    whole (zipfile reads it from its end), so ``source`` must stand at its start, and is left
    there; ValueError if not.

    The central directory first: how many parts, the sizes they state, the bomb ratio, how
    they are packed. Then every part unpacked in blocks and counted, for those sizes are the
    uploader's to state, and zipfile unpacks a part - up to a GiB at a time - before it cuts it
    to the size stated: 112 bytes stating 16 held 205 MiB at once. A part holding more than it
    states is refused here, so nothing that reads the archive after unpacks more than the
    stated sizes allow. That unpacks up to the bound on the sum - 1.3 s of CPU for 256 MiB of
    text, measured: a caller on the event loop runs it in a thread.

    Before all that, the parts are counted by their signature in the bytes: zipfile reads the
    whole directory into objects first, and 50 MiB naming 1.1 million parts took 4.3 s and
    330 MiB. The count is at least the true one, as packed bytes may hold the signature too.
    Then the end record: zipfile reads the directory whole by the size it states, so a directory
    past MAX_DIRECTORY_BYTES, a comment past MAX_ARCHIVE_COMMENT and a ZIP64 archive (whose sizes
    and counts are past every bound here, and which no document needs) are refused before it.
    """
    if source.tell() != 0:
        raise ValueError("an archive is read whole: the source must stand at its start")
    try:
        _check(source)
    finally:
        source.seek(0)


def _check(source: BinaryIO) -> None:
    if _signatures(source) > MAX_ARCHIVE_ENTRIES:
        raise ArchiveTooLarge(f"more than {MAX_ARCHIVE_ENTRIES} parts")
    _check_end_record(source)
    source.seek(0)
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, ValueError) as error:
        raise ArchiveUnreadable("not a readable archive") from error
    with archive:
        parts = archive.infolist()
        if len(parts) > MAX_ARCHIVE_ENTRIES:
            raise ArchiveTooLarge(f"more than {MAX_ARCHIVE_ENTRIES} parts")
        if sum(part.file_size for part in parts) > MAX_ARCHIVE_EXPANDED:
            raise ArchiveTooLarge("expands beyond the size limit")
        if any(
            part.file_size > _BOMB_MIN_SIZE and part.file_size > _BOMB_RATIO * max(part.compress_size, 1)
            for part in parts
        ):
            raise ArchiveTooLarge("a part expands beyond any document's")
        if any(part.compress_type not in _PACKED_WITH for part in parts):
            raise ArchiveUnreadable("a part is packed in a way no document is")
        if any(part.flag_bits & _ENCRYPTED for part in parts):
            raise ArchiveUnreadable("a part is encrypted")
        for part in parts:
            if _unpacks_past_its_size(archive, part):
                raise ArchiveTooLarge("a part unpacks past the size it states")


def _check_end_record(source: BinaryIO) -> None:
    """Refuse an archive whose end record states a directory or a comment past its bound, or that
    is a ZIP64 archive. An archive without an end record is left to zipfile to refuse."""
    size = source.seek(0, io.SEEK_END)
    tail_start = max(0, size - _END_RECORD.size - 0xFFFF)
    source.seek(tail_start)
    tail = source.read()
    at = tail.rfind(_END)
    if at < 0 or len(tail) - at < _END_RECORD.size:
        return
    *_, entries, directory_size, directory_offset, comment = _END_RECORD.unpack_from(tail, at)
    if comment > MAX_ARCHIVE_COMMENT or len(tail) - at - _END_RECORD.size > MAX_ARCHIVE_COMMENT:
        raise ArchiveTooLarge("the archive's comment is longer than a document's")
    zip64 = tail_start + at >= len(_ZIP64_LOCATOR) + 16 and _locator_before(source, tail_start + at)
    if zip64 or entries == 0xFFFF or 0xFFFFFFFF in (directory_size, directory_offset):
        raise ArchiveTooLarge("a ZIP64 archive: past every bound a document keeps to")
    if directory_size > MAX_DIRECTORY_BYTES:
        raise ArchiveTooLarge("the archive's directory is larger than a document's")


def _locator_before(source: BinaryIO, end: int) -> bool:
    """Whether a ZIP64 end locator stands right before the end record at ``end``."""
    source.seek(end - 20)
    return source.read(len(_ZIP64_LOCATOR)) == _ZIP64_LOCATOR


def _signatures(source: BinaryIO) -> int:
    """How often the directory entry's signature occurs in the rest of ``source``, counted a piece
    at a time: each piece with the last three bytes of the one before, so a signature across two
    pieces is counted once (it cannot overlap itself)."""
    count, tail = 0, b""
    while piece := source.read(COUNTING_PIECE):
        joined = tail + piece
        count += joined.count(_DIRECTORY_ENTRY)
        tail = joined[-(len(_DIRECTORY_ENTRY) - 1) :]
    return count


def _unpacks_past_its_size(archive: zipfile.ZipFile, part: zipfile.ZipInfo) -> bool:
    """Whether the part unpacks to more bytes than it states, counted a block at a time and
    given up a block past them. Opened as told no size: told its own, zipfile would cut it
    there - after unpacking it."""
    untold = copy.copy(part)
    untold.file_size = sys.maxsize
    unpacked = 0
    try:
        with archive.open(untold) as stream:
            while block := stream.read(_MEASURING_BLOCK):
                unpacked += len(block)
                if unpacked > part.file_size:
                    return True
    except (zipfile.BadZipFile, EOFError, ValueError, NotImplementedError, zlib.error) as error:
        raise ArchiveUnreadable("a part cannot be unpacked") from error
    return False
