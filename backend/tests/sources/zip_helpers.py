"""ZIP archives whose directory says one thing of their parts and holds another: the sizes and
flags a ZIP's central directory states are the uploader's to choose, and zipfile believes them.
Taken over from curriculum-extractor (tests/zip_helpers.py)."""

import io
import os
import struct
import zipfile

_DIRECTORY_ENTRY = b"PK\x01\x02"
_END = b"PK\x05\x06"


def make_zip(entries: dict[str, bytes], method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", method) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def commented_parts(parts: int, comment: int, padding: int = 0) -> bytes:
    """A ZIP of ``parts`` tiny parts, each with an entry comment of ``comment`` bytes - a central
    directory of about ``parts`` x (60 + ``comment``) bytes - and, where given, a stored part of
    ``padding`` bytes that do not pack."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index in range(parts):
            info = zipfile.ZipInfo(f"p/{index:05}.xml")
            info.comment = b"c" * comment
            archive.writestr(info, b"<p/>")
        if padding:
            archive.writestr(zipfile.ZipInfo("media/fill.bin"), os.urandom(padding), zipfile.ZIP_STORED)
    return buffer.getvalue()


def with_zip64_locator(data: bytes) -> bytes:
    """``data`` with a ZIP64 end locator before its end record, as a ZIP64 archive has: the record
    of the true counts and sizes is elsewhere, past what the end record states."""
    end = data.rindex(b"PK\x05\x06")
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, 0, 1)
    return data[:end] + locator + data[end:]


def end_signature_in_offset(data: bytes) -> bytes:
    """``data`` (no archive comment) with the end record's signature written into the record's own
    directory-offset field - a later copy of the signature than the record - and every entry's
    local header offset shifted by the same amount: zipfile finds the directory and each part
    through the difference ("concat"), so it reads the archive as before."""
    out = bytearray(data)
    end = len(out) - 22
    size, offset = struct.unpack_from("<2I", out, end + 12)
    planted = struct.unpack("<I", _END)[0]
    entry = offset
    while entry < offset + size:
        name, extra, comment = struct.unpack_from("<3H", out, entry + 28)
        (header,) = struct.unpack_from("<I", out, entry + 42)
        struct.pack_into("<I", out, entry + 42, header + planted - offset)
        entry += 46 + name + extra + comment
    struct.pack_into("<I", out, end + 16, planted)
    return bytes(out)


def fake_end_record(directory_size: int) -> bytes:
    """An end record stating ``directory_size``, to plant where a search may find it first."""
    return struct.pack("<4s4H2IH", _END, 0, 0, 1, 1, directory_size, 0, 0)


def with_fake_end_record_in_an_entry(parts: dict[str, bytes], archive_comment: bytes) -> bytes:
    """A ZIP whose first part's entry comment holds a fake end record (stating a tiny directory),
    and whose true end record has ``archive_comment`` after it - so zipfile searches for the record
    and must take the last one, not the first."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, (name, content) in enumerate(parts.items()):
            info = zipfile.ZipInfo(name)
            if index == 0:
                info.comment = fake_end_record(46)
            archive.writestr(info, content)
        archive.comment = archive_comment
    return buffer.getvalue()


def directory_only(entries: int) -> bytes:
    """A ZIP whose central directory holds ``entries`` parts that all point at one empty local
    header: 47 bytes a part, so a few MB name a million of them."""
    local = b"PK\x03\x04" + b"\0" * 26
    entry = struct.pack("<4s6H3I5H2I", _DIRECTORY_ENTRY, 20, 20, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0)
    directory = entry + b"a"
    end = struct.pack(
        "<4s4H2IH",
        b"PK\x05\x06",
        0,
        0,
        min(entries, 0xFFFF),
        min(entries, 0xFFFF),
        len(directory) * entries,
        len(local),
        0,
    )
    return local + directory * entries + end


def directory_says(data: bytes, *, size: int | None = None, flags: int | None = None) -> bytes:
    """``data`` with every part's entry in the central directory stating ``size`` unpacked bytes
    and ``flags`` as its general-purpose bits, where given. The archive carries no comment, as
    zipfile writes it."""
    out = bytearray(data)
    (entry,) = struct.unpack_from("<I", out, len(out) - 22 + 16)
    while out[entry : entry + 4] == _DIRECTORY_ENTRY:
        if flags is not None:
            struct.pack_into("<H", out, entry + 8, flags)
        if size is not None:
            struct.pack_into("<I", out, entry + 24, size)
        name, extra, comment = struct.unpack_from("<HHH", out, entry + 28)
        entry += 46 + name + extra + comment
    return bytes(out)
