"""What a source is, by its bytes: the trust boundary for every file that comes in.

Binary formats are known by their magic bytes, not by the name the sender chose; text formats
(Markdown, HTML, plain text, Turtle), which have no signature, by their name - and only if they
read as UTF-8. Anything else is refused. One check for every way a source comes in (upload, URL
import), so none takes another way round it. Taken over from curriculum-extractor
(services/filetype.py).
"""

import codecs
import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import BinaryIO

from app.core.auth import visible_only
from app.sources.archives import check_archive, check_archive_file

# What the common file systems hold as one file's name
MAX_NAME_SIGNS = 255
# The endings of the types whose files are ZIP packages, as DOCX is (OOXML, ODF): a ZIP with one
# of them keeps it; with any other ending - a dot in a name, "lehrplan-v2.1" - it gets .docx
PACKAGE_ENDINGS = frozenset(
    {
        ".docx", ".docm", ".dotx", ".dotm",
        ".xlsx", ".xlsm", ".xltx", ".xltm",
        ".pptx", ".pptm", ".potx", ".potm", ".ppsx", ".ppsm",
        ".odt", ".ott", ".ods", ".ots", ".odp", ".otp", ".odg", ".otg", ".odf", ".odm",
    }
)  # fmt: skip
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
HTML_MIME = "text/html"
TURTLE_MIME = "text/turtle"
# Name ending -> type, for text without a signature
_TEXT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": HTML_MIME,
    ".htm": HTML_MIME,
    ".txt": "text/plain",
    ".ttl": TURTLE_MIME,  # machine-readable curricula
}


# The endings that name a document's type - an address ending so is no HTML page's, whatever answers; any
# other ending - a script's, a version's, a date's, a section's ("index.php", "biologie-2.0", "sek.i") - none
_DOCUMENT_ENDINGS = frozenset(
    {
        ".pdf", ".rtf", ".doc", ".dot", ".txt", ".md", ".markdown", ".ttl", ".csv", ".json", ".xml",
        ".epub", ".xls", ".ppt", ".zip", ".gz", ".7z", ".rar", ".png", ".jpg", ".jpeg", ".gif", ".svg",
        ".tif", ".tiff", ".odt", *PACKAGE_ENDINGS,
    }
)  # fmt: skip


class UnsupportedType(ValueError):
    """A file of no type a conversion reads."""


@dataclass(frozen=True)
class DetectedType:
    mime: str
    extension: str


PDF_SIGNATURE = b"%PDF"  # what a PDF begins with; the version and a dash may follow
READ_PIECE = 2**20  # what examine_file reads at a time


def detect_type(filename: str | None, data: bytes) -> DetectedType | None:
    """The type, or ``None`` for none a conversion reads.

    A ZIP (``PK\\x03\\x04``) is taken for a DOCX, the only OOXML type in scope; a mislabelled
    XLSX or PPTX fails in the conversion, not here.
    """
    signed = _signed_type(data)
    if signed is not None:
        return signed
    text = _text_type(filename)
    return text if text is not None and _is_utf8(data) else None


def _signed_type(head: bytes) -> DetectedType | None:
    """The type a file's first bytes name, if they name one."""
    if head.startswith(PDF_SIGNATURE):
        return DetectedType(PDF_MIME, ".pdf")
    if head.startswith(b"PK\x03\x04"):
        return DetectedType(DOCX_MIME, ".docx")
    if head.startswith(b"{\\rtf"):
        return DetectedType("application/rtf", ".rtf")
    return None


def _text_type(filename: str | None) -> DetectedType | None:
    """The text type a name names, its bytes yet to read as UTF-8."""
    suffix = PurePosixPath(base_name(filename)).suffix.lower()
    text_mime = _TEXT_TYPES.get(suffix)
    return DetectedType(text_mime, suffix) if text_mime else None


def accepted_type(filename: str | None, data: bytes) -> DetectedType:
    """What a source is, held to everything a source is held to before it is stored: a type a
    conversion reads, and for a ZIP parts within the bounds (app/sources/archives.py).

    Raises UnsupportedType, ArchiveUnreadable or ArchiveTooLarge. The archive check unpacks, so
    a caller on the event loop runs this in a thread.
    """
    detected = detect_type(filename, data)
    if detected is None:
        raise UnsupportedType("not a file type any conversion reads")
    if detected.mime == DOCX_MIME:
        check_archive(data)
    return detected


def examine(filename: str | None, data: bytes) -> tuple[DetectedType, bytes]:
    """``accepted_type`` and the SHA-256 of the bytes: what every way a source comes in asks of a
    file. Unpacks an archive and hashes up to the upload limit, so callers run it in a thread."""
    return accepted_type(filename, data), hashlib.sha256(data).digest()


def examine_file(filename: str | None, source: BinaryIO) -> tuple[DetectedType, bytes, int]:
    """``examine`` of the rest of ``source`` (an upload's spooled file), read a piece at a time: the
    type, the SHA-256 and the size. The same refusals as ``examine``; ``source`` is left where it
    stood, for the store to read it from there. A ZIP is checked whole, so it must stand at 0.

    The file is never held whole. At once it holds two pieces of READ_PIECE; for a text also the
    decoder's output for one piece (CPython sizes it at four bytes a sign: 4 MiB); for a ZIP the
    central directory zipfile reads (at most MAX_DIRECTORY_BYTES) with an object per entry - under
    10 MiB in each case, whatever the file's size (tests/api/test_sources_upload_memory.py).
    Blocks: callers on the event loop run it in a thread."""
    start = source.tell()
    try:
        piece = source.read(READ_PIECE)  # the head, which a signature is in
        signed = _signed_type(piece)
        detected = signed or _text_type(filename)
        if detected is None:
            raise UnsupportedType("not a file type any conversion reads")
        # a text type is UTF-8 throughout: a sign may be split over two pieces
        utf8 = None if signed else codecs.getincrementaldecoder("utf-8")()
        digest, size = hashlib.sha256(), 0
        while piece:
            digest.update(piece)
            size += len(piece)
            _decoded(utf8, piece)
            piece = source.read(READ_PIECE)
        _decoded(utf8, b"", final=True)
        if detected.mime == DOCX_MIME:
            source.seek(start)
            check_archive_file(source)
        return detected, digest.digest(), size
    finally:
        source.seek(start)


def _decoded(utf8: codecs.IncrementalDecoder | None, piece: bytes, final: bool = False) -> None:
    """Nothing, if ``piece`` goes on the text as UTF-8 (or the file is no text); else UnsupportedType."""
    if utf8 is None:
        return
    try:
        utf8.decode(piece, final)
    except UnicodeDecodeError:
        raise UnsupportedType("not a file type any conversion reads") from None


def answer_name(name: str, content_type: str | None, asked: str = "") -> str:
    """The name a fetched file's type is told by: that of the address that answered, but for a page at an
    address that names no type - ``/fachlehrplan/realschule/10/biologie``, a page's script as ``index.php``
    - one ending in ``.html`` where the server says it is HTML; its bytes are held to it (UTF-8) as an
    upload's are. Where the address answering or ``asked`` - the one asked, before it led on - names a type,
    it keeps the name it has: a PDF's answering with a page, or leading on to one - a sign-in, an error - is
    no PDF, nor a curriculum."""
    media = (content_type or "").partition(";")[0].strip().lower()
    if media != HTML_MIME or _names_a_type(name) or _names_a_type(asked):
        return name
    if PurePosixPath(base_name(name)).suffix.lower() in (".html", ".htm"):
        return name
    return f"{name.rstrip('.') or 'source'}.html"


def _names_a_type(name: str) -> bool:
    """Whether a name ends as a document of some type does."""
    return PurePosixPath(base_name(name).rstrip(".")).suffix.lower() in _DOCUMENT_ENDINGS


def stored_name(filename: str | None, detected: DetectedType) -> str:
    """The name a source is filed under: the one it came by, without any folder, ending in what
    its bytes are.

    Every conversion engine decides by the suffix: a download URL that names no file gave a PDF
    called ``source``, which the engines refused. A ZIP keeps the ending of a package type
    (PACKAGE_ENDINGS): the signature is every OOXML and ODF type's, DOCX only the assumption,
    and a ``.pptx`` renamed to ``.docx`` would be a lie of our own making.
    """
    name = base_name(filename)
    suffix = PurePosixPath(name).suffix.lower()
    kept_zip = detected.mime == DOCX_MIME and suffix in PACKAGE_ENDINGS
    if not (suffix == detected.extension or kept_zip):
        name, suffix = f"{name.rstrip('.') or 'source'}{detected.extension}", detected.extension
    if len(name) > MAX_NAME_SIGNS:  # cut the stem, keep the ending every engine decides by
        name = name[: MAX_NAME_SIGNS - len(suffix)] + name[len(name) - len(suffix) :]
    return name


def base_name(filename: str | None) -> str:
    """The last part of a name a sender gave, with either kind of slash, without signs that hide
    what it is (a right-to-left override made ``lehrplan<RLO>fdp.exe`` read as a PDF). A path
    of the sender's disk would also tell the sender's user name."""
    return visible_only(PureWindowsPath(PurePosixPath(filename or "").name).name).strip()


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
