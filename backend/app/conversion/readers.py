"""Which engines read which register file (plan M1 3b-3): by its type, named here, as the API imports no
engine (a test compares each engine's formats, tests/conversion/test_base.py). The job writes the file with
the type's ending for its engine (app/conversion/job.py).

Every ZIP is taken for a DOCX by its signature, but the register keeps the ending of a package of another type
- an XLSX, an ODT - (app/sources/filetype.py, stored_name): such a file no engine reads.
"""

from collections.abc import Sequence
from pathlib import PurePosixPath

from app.sources.filetype import DOCX_MIME, HTML_MIME, PDF_MIME

# The types a conversion reads, by the ending the job writes the file with for its engine
ENDINGS = {PDF_MIME: ".pdf", DOCX_MIME: ".docx", HTML_MIME: ".html"}
# The types each engine reads (the engine's formats, by type)
READS: dict[str, frozenset[str]] = {"pdfplumber": frozenset({PDF_MIME}), "docling": frozenset(ENDINGS)}


def readers(offered: Sequence[str], mime: str | None, file_name: str | None) -> list[str]:
    """The engines of ``offered``, in their order, that read an entry's file of type ``mime`` filed as
    ``file_name``; none for an entry without its file."""
    if mime is None:
        return []
    if mime == DOCX_MIME and PurePosixPath(file_name or "").suffix.lower() != ".docx":
        return []  # a package of another type
    return [engine for engine in offered if mime in READS.get(engine, frozenset())]
