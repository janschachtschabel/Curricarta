"""The engine docling: a PDF's layout, tables and text by Docling's models, on the CPU (plan M1 3b).

Docling reads the file eight pages at a time - the old app's measure, near 1.8 GB at its height - with the
layout model and TableFormer (accurate, its own cell boxes) from MODELS_DIR, never from the net
(app/conversion/models.py), on page images pdfium draws (app/conversion/docling_images.py), and
docling-parse's words of each page kept (``generate_parsed_pages``). Each
block's result becomes the app's own pages (app/conversion/docling_pages.py) before the next is read, and
those a conversion as the other engine's do (app/conversion/assemble.py); each word's size is that of
pdfplumber's signs under it (``sized``), as the other engine measures - docling-parse gives none.

The pages to read by OCR (text_layer.scanned) go through a pipeline of their own, Docling's with EasyOCR
(German): it reads the page's images, and keeps its text layer where there is one. They are read in runs of
their own, eight pages at most, and that pipeline loads only for a file that has such a page. OCR gives lines,
not words, and no font: their words and sizes are app/conversion/ocr_words.py's, measured on the page's image
as pdfium renders it, and the page says how sure OCR was (a finding, app/conversion/assemble.py).

The models load at the first conversion, after the file's checks (app/conversion/convert.py): a file
refused there costs no model. Loading them is ours - a fault there is no verdict on the file, and another
attempt may find them whole (EngineUnavailable). The file is untrusted: whatever Docling raises on it but
a want of memory, or a result not whole - a block of pages it converted in part or not at all, the file's
pages counted otherwise than the text layer did, a page missing - makes it unreadable, said without its
path. A page of more signs than the service takes is too dense, counted on docling-parse's words. The boxes
Docling hands over are turned to the page's top here: its items' boxes stand from the page's bottom,
docling-parse's words from its top.
"""

import logging
import statistics
from collections import defaultdict
from collections.abc import Callable, Collection, Iterator, Set
from contextlib import contextmanager
from dataclasses import replace
from importlib.metadata import version
from itertools import islice
from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfpage import PDFPage

from app.conversion.assemble import assemble
from app.conversion.base import Conversion, EngineUnavailable
from app.conversion.convert import MAX_PAGE_SIGNS
from app.conversion.docling_flow import FLOW_SUFFIXES, ConvertBytes, flow_converter, read_flow
from app.conversion.docling_images import pdfium_image_backend
from app.conversion.docling_pages import DoclingItem, DoclingPage, DoclingTableCell, DoclingWord, raw_pages
from app.conversion.flow import flow_conversion
from app.conversion.layout import Box, RawPage
from app.conversion.models import MODELS_DIR
from app.conversion.ocr_words import OcrLine, PageImages, words_of
from app.conversion.text_layer import TooDense, UnreadablePdf
from app.conversion.word_sizes import Sign, sized

log = logging.getLogger(__name__)
PAGES_AT_ONCE = 8
THREADS = 4  # the old app's: more gained little on its measures
_TABULAR = frozenset({"table", "document_index"})

# the first and last page, from 1, and whether OCR reads them: Docling's result
ConvertPages = Callable[[tuple[int, int], bool], Any]
Render = Callable[[int], tuple[Any, float]]  # a page's image, grey (PIL), and its pixels to a point


class DoclingEngine:
    name = "docling"
    reads_scans = True
    formats = frozenset({".pdf", *FLOW_SUFFIXES})

    def __init__(self, models: Path = MODELS_DIR) -> None:
        self.version = version("docling")
        self._models = models
        self._loaded: dict[bool, tuple[Any, Collection[Any]]] = {}  # by whether it reads by OCR
        self._flowing: tuple[ConvertBytes, Collection[Any]] | None = None

    def convert(
        self, path: Path, *, pages: int, max_signs: int = MAX_PAGE_SIGNS, scanned: Collection[int] = ()
    ) -> Conversion:
        scans = frozenset(scanned)
        # each pipeline the file needs, loaded before it is read: a load failing there is ours, not the file's
        for ocr in sorted({number in scans for number in range(1, pages + 1)} or {False}):
            _, layers = self._ready(ocr)  # the layers are both's

        def convert_pages(first_last: tuple[int, int], ocr: bool) -> Any:
            converter, _ = self._ready(ocr)
            return converter.convert(path, page_range=first_last, raises_on_error=False)

        with _reading("pdfplumber"):
            pdf = pdfplumber.open(path)
        built: list[Any] | None = None
        images: PageImages | None = None
        try:
            if scans:
                with _reading("pypdfium2"):
                    images = PageImages(path)
            # pdfplumber builds every page its tree holds: counted first, as far as one more
            with _reading("pdfplumber"):
                held = sum(1 for _ in islice(PDFPage.create_pages(pdf.doc), pages + 1))
            if held != pages:
                log.warning("pdfminer found %s pages where the text layer counted %d", held, pages)
                raise UnreadablePdf("the file's pages are counted two ways")
            with _reading("pdfplumber"):
                built = pdf.pages
            read: list[RawPage] = []
            render = None if images is None else _rendering(images)
            for block in read_blocks(
                convert_pages, pages=pages, max_signs=max_signs, layers=layers, scanned=scans, render=render
            ):
                # mapped now: a block's words weigh some 30 times its raw pages
                read += raw_pages(
                    [
                        replace(
                            page,
                            words=sized(page.words, _signs(built[page.number - 1], page.number, max_signs)),
                        )
                        for page in block
                    ]
                )
        finally:
            if images is not None:
                with _reading("pypdfium2"):
                    images.close()
            with _reading("pdfplumber"):
                if built is None:  # closing builds every page where none was
                    pdf.stream.close()
                else:
                    pdf.close()
        return assemble(read, engine=self.name, version=self.version)

    def convert_flow(self, path: Path, *, max_pages: int, max_signs: int = MAX_PAGE_SIGNS) -> Conversion:
        """A DOCX or an HTML page (app/conversion/docling_flow.py, flow.py): no model is loaded for it."""
        if self._flowing is None:
            try:
                self._flowing = flow_converter()
            except Exception as error:  # ours, not the file's: its library
                log.exception("Docling could not set up its reading of DOCX and HTML")
                raise EngineUnavailable(f"Docling could not set up: {type(error).__name__}") from None
        convert, layers = self._flowing
        with _reading(kind="a DOCX or an HTML page"):
            items, dropped = read_flow(path, convert, layers)
        return flow_conversion(
            items, dropped, engine=self.name, version=self.version, max_pages=max_pages, max_signs=max_signs
        )

    def _ready(self, ocr: bool) -> tuple[Any, Collection[Any]]:
        if ocr not in self._loaded:
            try:
                self._loaded[ocr] = _converter(self._models, ocr)
            except Exception as error:  # ours, not the file's: its library or its models
                log.exception("Docling could not load its models")  # its frames: no file of a user in them
                said = type(error).__name__
                raise EngineUnavailable(f"Docling could not load its models: {said}") from None
        return self._loaded[ocr]


def _rendering(images: PageImages) -> Render:
    """The pages' images, pdfium's faults on the file the file's."""

    def render(number: int) -> tuple[Any, float]:
        with _reading("pypdfium2"):
            return images.render(number)

    return render


def _converter(models: Path, ocr: bool) -> tuple[Any, Collection[Any]]:
    """Docling's converter for PDFs, its models loaded - EasyOCR's (German) too where ``ocr`` -, and the
    layers of a page it reads. Its OCR reads a page's images, those over a twentieth of it, and keeps its
    text layer (force_full_page_ocr off)."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice,
        AcceleratorOptions,
        EasyOcrOptions,
        PdfPipelineOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc import ContentLayer

    options = PdfPipelineOptions(
        artifacts_path=models,
        do_ocr=ocr,
        do_table_structure=True,
        generate_parsed_pages=True,
        accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=THREADS),
    )
    if ocr:
        options.ocr_options = EasyOcrOptions(lang=["de"], download_enabled=False)
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.table_structure_options.do_cell_matching = False
    backend = pdfium_image_backend()  # the page images the models were measured on (docling_images.py)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options, backend=backend)}
    )
    converter.initialize_pipeline(InputFormat.PDF)
    return converter, {ContentLayer.BODY, ContentLayer.FURNITURE}


def read_blocks(
    convert: ConvertPages,
    *,
    pages: int,
    max_signs: int,
    layers: Collection[Any],
    scanned: Set[int] = frozenset(),
    render: Render | None = None,
) -> Iterator[list[DoclingPage]]:
    """The document's ``pages``, read by ``convert`` a block of PAGES_AT_ONCE at a time, block by block:
    Docling's result of one is let go before the next is read. The pages ``scanned`` are read by OCR, in
    blocks of their own, their lines measured on ``render``'s images."""
    for first, last, ocr in _runs(pages, scanned):
        with _reading():
            result = convert((first, last), ocr)
        numbers = range(first, last + 1)
        lines = render if ocr else None
        read = _pages_of(result, numbers, pages=pages, max_signs=max_signs, layers=layers, render=lines)
        del result
        yield read


def _runs(pages: int, scanned: Set[int]) -> Iterator[tuple[int, int, bool]]:
    """The first and last page of each block, whether OCR reads it: pages alike, PAGES_AT_ONCE at most."""
    first = 1
    while first <= pages:
        ocr = first in scanned
        last = first
        while last < pages and last - first + 1 < PAGES_AT_ONCE and ((last + 1) in scanned) == ocr:
            last += 1
        yield first, last, ocr
        first = last + 1


def _pages_of(
    result: Any,
    numbers: range,
    *,
    pages: int,
    max_signs: int,
    layers: Collection[Any],
    render: Render | None = None,
) -> list[DoclingPage]:
    if result.status.value != "success":
        said = sorted(
            {(_named(error, "component_type"), _named(error, "category")) for error in result.errors}
        )
        log.warning("Docling read a file %s: %s", result.status.value, said)
        raise UnreadablePdf("Docling could not read the file whole")
    if result.input.page_count != pages:
        log.warning(
            "Docling counted %d pages where the text layer counted %d", result.input.page_count, pages
        )
        raise UnreadablePdf("the file's pages are counted two ways")
    parsed = {page.page_no: page.parsed_page for page in result.pages}
    heights: dict[int, float] = {}
    words: dict[int, list[DoclingWord]] = {}
    sure: dict[int, float] = {}
    for number in numbers:
        if number not in result.document.pages or parsed.get(number) is None:
            raise UnreadablePdf("Docling lost a page of the file")
        heights[number] = height = result.document.pages[number].size.height
        cells = parsed[number].word_cells
        lines = [] if render is None else _ocr_lines(parsed[number], height)
        signs = sum(len(cell.text) for cell in cells) + sum(len(line.text) for line in lines)
        if signs > max_signs:
            raise TooDense(number, signs, max_signs)
        words[number] = [
            DoclingWord(cell.text, _corners(cell.rect, height), cell.font_name, _upright(cell.rect))
            for cell in cells
        ]
        if render is not None and lines:
            words[number] += words_of(lines, *render(number))
            sure[number] = round(statistics.median(line.confidence for line in lines), 2)
    items: dict[int, list[DoclingItem]] = defaultdict(list)
    for item, _level in result.document.iterate_items(included_content_layers=layers):
        label = item.label.value
        for prov in item.prov[:1] if label in _TABULAR else item.prov:  # a paragraph Docling carried over
            if prov.page_no not in heights:  # a page of another block: none in Docling 2.117
                continue
            box = _box(prov.bbox, heights[prov.page_no])
            rows = _rows(item.data, heights[prov.page_no]) if label in _TABULAR else ()
            items[prov.page_no].append(DoclingItem(label, box, rows))
    return [
        DoclingPage(number, heights[number], items[number], words[number], sure.get(number))
        for number in numbers
    ]


def _ocr_lines(parsed: Any, height: float) -> list[OcrLine]:
    """The lines OCR read on the page; the text layer's lines are its words'."""
    return [
        OcrLine(cell.text, _corners(cell.rect, height), float(cell.confidence))
        for cell in parsed.textline_cells
        if cell.from_ocr
    ]


def _signs(page: Any, number: int, max_signs: int) -> list[Sign]:
    """The page's signs as pdfplumber reads them - the other engine's measure of a size -, its cache let
    go; TooDense past ``max_signs``, as the other engine counts them."""
    with _reading("pdfplumber"):
        chars = page.chars
    if len(chars) > max_signs:
        raise TooDense(number, len(chars), max_signs)
    signs = [((c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2, c["size"], c["text"]) for c in chars]
    with _reading("pdfplumber"):
        page.close()
    return signs


def _named(error: Any, part: str) -> str:
    """An error item's component or category, by its value: neither says the file's text."""
    return str(getattr(getattr(error, part, None), "value", "-"))


def _rows(data: Any, height: float) -> tuple[tuple[DoclingTableCell | None, ...], ...]:
    """The table's grid, a cell at the first place it takes: None at the others a span covers."""
    grid: list[list[DoclingTableCell | None]] = [[None] * data.num_cols for _ in range(data.num_rows)]
    for cell in data.table_cells:
        place = None if cell.bbox is None else _box(cell.bbox, height)
        grid[cell.start_row_offset_idx][cell.start_col_offset_idx] = DoclingTableCell(cell.text, place)
    return tuple(tuple(row) for row in grid)


def _box(box: Any, height: float) -> Box:
    """A box of Docling's (l, t, r, b), from the page's top."""
    if box.coord_origin.value == "BOTTOMLEFT":
        return (box.l, height - box.t, box.r, height - box.b)
    return (box.l, box.t, box.r, box.b)


def _corners(rect: Any, height: float) -> Box:
    """The box around a rectangle of docling-parse's four corners, from the page's top."""
    xs = (rect.r_x0, rect.r_x1, rect.r_x2, rect.r_x3)
    ys = (rect.r_y0, rect.r_y1, rect.r_y2, rect.r_y3)
    if rect.coord_origin.value == "BOTTOMLEFT":
        ys = tuple(height - y for y in ys)
    return (min(xs), min(ys), max(xs), max(ys))


def _upright(rect: Any) -> bool:
    """Whether the word's baseline - from its rectangle's first corner to its second - runs across."""
    across: bool = abs(rect.r_y1 - rect.r_y0) <= abs(rect.r_x1 - rect.r_x0)
    return across


@contextmanager
def _reading(library: str = "Docling", kind: str = "a PDF") -> Iterator[None]:
    """Around Docling's call on the file of ``kind``: what it raises makes it unreadable, but a want of
    memory, which is the conversion's, not the file's (the kernel's kill says it so: ConversionDied)."""
    try:
        yield
    except (MemoryError, UnreadablePdf):  # the latter said why already
        raise
    except Exception as error:  # an untrusted file: whatever the library raises on it
        if type(error).__name__ == "OutOfMemoryError":  # torch's, which is a RuntimeError
            raise MemoryError from None
        log.warning("%s could not read a file: %s", library, type(error).__name__)
        raise UnreadablePdf(f"{library} could not read the file as {kind}") from None
