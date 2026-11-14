"""What a conversion asks of a file before and after converting it (plan M1, 3.5).

Before: that it opens as a PDF (``unreadable``), has no more pages than the service takes
(``too_many_pages``, MAX_PDF_PAGES), no page of more signs than a page holds (``too_dense``: a
file made to fill the database) and carries a text layer the engine can read (``needs_ocr``:
pdfplumber reads no scan). An engine that reads scans (Docling) is handed the pages to read by OCR
(text_layer.scanned), as many as MAX_OCR_PAGES (``too_many_ocr_pages``). The signs are counted by
pdfium first, cheaply, and again by the engine as it reads each page: pdfium reads one text drawn many
times at one place as one, pdfminer each time. After: that the engine found text or a table beyond running
heads and feet (``empty``). Each is a refusal with its code, which the job records as the
conversion's reason; it runs in the converting child (app/conversion/runners.py).
"""

from pathlib import Path
from typing import Literal

from app.conversion.base import Conversion, Engine, FlowReader
from app.conversion.text_layer import (
    TooDense,
    TooManyPages,
    UnreadablePdf,
    needs_ocr,
    page_text_lengths,
    scanned,
)

RefusalCode = Literal[
    "unreadable", "too_many_pages", "too_dense", "needs_ocr", "too_many_ocr_pages", "empty", "not_pdf"
]
# A dense page of a Lehrplan - small print, a table without rules - holds some 6,000 signs; this
# is many times that, and bounds what one page's blocks weigh in the database and in an answer
MAX_PAGE_SIGNS = 100_000
# OCR takes some 16 s a page on four cores (Docling with EasyOCR, measured on scans of the acceptance
# curricula, 14-30 s): these are near an hour, the converter's time (CONVERT_TIMEOUT_S=3600, Compose). The
# file's other pages add their own (some 4 s each): the deadline stays the bound of the whole.
# simplify: no setting - one where an operator's converter runs faster or slower
MAX_OCR_PAGES = 200


class ConversionRefused(ValueError):
    def __init__(self, code: RefusalCode, message: str, *, pages: int | None = None) -> None:
        super().__init__(message)
        self.code: RefusalCode = code
        self.pages = pages  # too many pages: how many it has (too_many_ocr_pages: how many are scans)


def convert_file(path: Path, engine: Engine, *, max_pages: int) -> Conversion:
    """The conversion of ``path`` by ``engine``, by the file's ending: a PDF read with its text layer's
    checks, a DOCX or an HTML page (app/conversion/flow.py) by an engine that reads them; ConversionRefused
    with its code where the file is none the engine serves."""
    suffix = path.suffix.lower()
    refused = ConversionRefused("not_pdf", f"the engine converts no {suffix or 'such'} file")
    if suffix not in engine.formats:
        raise refused
    if suffix == ".pdf":
        conversion = _pdf(path, engine, max_pages)
    elif isinstance(engine, FlowReader):
        conversion = _flow(path, engine, max_pages)
    else:
        raise refused
    if not any(block.kind in ("text", "table") for block in conversion.blocks):
        raise ConversionRefused("empty", "the conversion found no text beyond running heads and feet")
    return conversion


def _flow(path: Path, engine: FlowReader, max_pages: int) -> Conversion:
    try:
        return engine.convert_flow(path, max_pages=max_pages, max_signs=MAX_PAGE_SIGNS)
    except UnreadablePdf:
        raise ConversionRefused("unreadable", "the file cannot be read") from None
    except TooManyPages as counted:
        raise ConversionRefused("too_many_pages", str(counted), pages=counted.pages) from None
    except TooDense as dense:
        raise ConversionRefused("too_dense", str(dense)) from None


def _pdf(path: Path, engine: Engine, max_pages: int) -> Conversion:
    try:
        pages = page_text_lengths(path, max_pages=max_pages, images=engine.reads_scans)
    except UnreadablePdf:
        raise ConversionRefused("unreadable", "the file cannot be read as a PDF") from None
    except TooManyPages as counted:
        raise ConversionRefused("too_many_pages", str(counted), pages=counted.pages) from None
    if any(page.drawn > MAX_PAGE_SIGNS for page in pages):
        raise ConversionRefused("too_dense", f"a page holds more than the {MAX_PAGE_SIGNS} signs taken")
    if not engine.reads_scans and needs_ocr(pages):
        raise ConversionRefused("needs_ocr", "too few pages carry a text layer; the file needs OCR")
    scans = scanned(pages) if engine.reads_scans else []
    if len(scans) > MAX_OCR_PAGES:
        said = f"{len(scans)} pages to read by OCR, more than the {MAX_OCR_PAGES} taken"
        raise ConversionRefused("too_many_ocr_pages", said, pages=len(scans))
    try:
        return engine.convert(path, pages=len(pages), max_signs=MAX_PAGE_SIGNS, scanned=scans)
    except UnreadablePdf:
        raise ConversionRefused("unreadable", "the file cannot be read as a PDF") from None
    except TooDense as dense:
        raise ConversionRefused("too_dense", str(dense)) from None
