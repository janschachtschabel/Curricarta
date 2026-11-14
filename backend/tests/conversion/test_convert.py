"""What a conversion asks of a file before and after converting it (plan M1, 3.5)."""

from collections.abc import Collection
from pathlib import Path

import pytest

from app.conversion import convert
from app.conversion.base import Block, Conversion, engine
from app.conversion.convert import ConversionRefused, convert_file
from app.conversion.text_layer import TooDense, TooManyPages, UnreadablePdf, page_text_lengths
from tests.conversion.raw_pdf import SENTENCE, pages_pdf

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_pdf_with_a_text_layer_is_converted() -> None:
    conversion = convert_file(FIXTURES / "prose.pdf", engine("pdfplumber"), max_pages=10)

    assert conversion.pages == 2 and conversion.blocks


@pytest.mark.parametrize(
    ("name", "max_pages", "code"),
    [
        ("scan.pdf", 10, "needs_ocr"),
        ("edges.pdf", 4, "too_many_pages"),
    ],
)
def test_a_file_the_engine_cannot_serve_is_refused_with_its_reason(
    name: str, max_pages: int, code: str
) -> None:
    with pytest.raises(ConversionRefused) as refused:
        convert_file(FIXTURES / name, engine("pdfplumber"), max_pages=max_pages)

    assert refused.value.code == code


@pytest.mark.parametrize(
    "content",
    [
        b"%PDF-1.7\nthis is no document\n",
        pages_pdf([SENTENCE], count=3),
        # the page tree counts one page, its kids are three: pypdfium2 counts one, pdfplumber reads
        # three - past MAX_PDF_PAGES and the density, both counted on the one
        pages_pdf([SENTENCE] * 3, count=1),
    ],
    ids=["no document", "a page lost", "pages counted two ways"],
)
def test_a_file_that_is_no_pdf_is_refused_as_unreadable(tmp_path: Path, content: bytes) -> None:
    broken = tmp_path / "lehrplan.pdf"
    broken.write_bytes(content)

    with pytest.raises(ConversionRefused) as refused:
        convert_file(broken, engine("pdfplumber"), max_pages=10)

    assert refused.value.code == "unreadable"


def test_a_page_of_more_signs_than_any_page_holds_is_refused_as_too_dense(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    densest = max(page.drawn for page in page_text_lengths(FIXTURES / "prose.pdf", max_pages=10))
    monkeypatch.setattr(convert, "MAX_PAGE_SIGNS", densest)
    assert convert_file(FIXTURES / "prose.pdf", engine("pdfplumber"), max_pages=10).pages == 2

    monkeypatch.setattr(convert, "MAX_PAGE_SIGNS", densest - 1)
    with pytest.raises(ConversionRefused) as refused:
        convert_file(FIXTURES / "prose.pdf", engine("pdfplumber"), max_pages=10)

    assert refused.value.code == "too_dense"


def test_signs_set_beyond_the_page_count_towards_its_density(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hidden = b"BT /F1 11 Tf 72 2000 Td (" + b"x" * 5000 + b") Tj ET\n"  # far above the page's box
    dense = tmp_path / "lehrplan.pdf"
    dense.write_bytes(pages_pdf([SENTENCE + hidden]))
    monkeypatch.setattr(convert, "MAX_PAGE_SIGNS", 1000)

    with pytest.raises(ConversionRefused) as refused:
        convert_file(dense, engine("pdfplumber"), max_pages=10)

    assert refused.value.code == "too_dense"


def test_one_text_drawn_many_times_over_is_refused_as_too_dense(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pdfium reads the 30 copies at one place as one, 57 signs; pdfplumber reads each, 1,710
    dense = tmp_path / "lehrplan.pdf"
    dense.write_bytes(pages_pdf([SENTENCE * 30]))
    monkeypatch.setattr(convert, "MAX_PAGE_SIGNS", 1000)
    assert max(page.drawn for page in page_text_lengths(dense, max_pages=10)) < 1000

    with pytest.raises(ConversionRefused) as refused:
        convert_file(dense, engine("pdfplumber"), max_pages=10)

    assert refused.value.code == "too_dense"


class OnlyEdges:
    """An engine that finds nothing but running heads: the text of a document of headers alone."""

    name = "edges"
    version = "1"
    reads_scans = False
    formats = frozenset({".pdf"})

    def convert(
        self, path: Path, *, pages: int, max_signs: int = 0, scanned: Collection[int] = ()
    ) -> Conversion:
        head = Block(
            id="p1-b1",
            page=1,
            kind="page_header",
            text="Rahmenlehrplan",
            bbox=(56, 20, 300, 30),
            font_size=9,
            bold=False,
            italic=False,
        )
        return Conversion(engine="edges", engine_version="1", pages=1, printed_pages=(None,), blocks=(head,))


def test_a_conversion_of_nothing_but_running_heads_and_feet_is_refused_as_empty() -> None:
    with pytest.raises(ConversionRefused) as refused:
        convert_file(FIXTURES / "prose.pdf", OnlyEdges(), max_pages=10)

    assert refused.value.code == "empty"


class ReadingScans:
    """An engine that reads scans by OCR, as Docling does: it notes which pages it is asked to."""

    name = "scans"
    version = "1"
    reads_scans = True
    formats = frozenset({".pdf"})

    def __init__(self) -> None:
        self.asked: list[tuple[int, list[int]]] = []

    def convert(
        self, path: Path, *, pages: int, max_signs: int = 0, scanned: Collection[int] = ()
    ) -> Conversion:
        self.asked.append((pages, list(scanned)))
        text = Block(
            id="p1-b1",
            page=1,
            kind="text",
            text="Die Lernenden planen.",
            bbox=(56, 100, 300, 112),
            font_size=11,
            bold=False,
            italic=False,
        )
        return Conversion(
            engine="scans", engine_version="1", pages=pages, printed_pages=(None,) * pages, blocks=(text,)
        )


def test_an_engine_that_reads_scans_is_handed_a_scan_s_pages_to_read_by_ocr() -> None:
    reader = ReadingScans()

    conversion = convert_file(FIXTURES / "scan.pdf", reader, max_pages=10)

    assert conversion.pages == 4
    assert reader.asked == [(4, [2, 3, 4])]  # its title page carries text


def test_a_born_digital_file_has_no_page_to_read_by_ocr() -> None:
    reader = ReadingScans()

    convert_file(FIXTURES / "prose.pdf", reader, max_pages=10)

    assert reader.asked == [(2, [])]


def test_more_pages_to_read_by_ocr_than_taken_are_refused_before_the_engine_reads_any(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = ReadingScans()
    monkeypatch.setattr(convert, "MAX_OCR_PAGES", 2)

    with pytest.raises(ConversionRefused) as refused:
        convert_file(FIXTURES / "scan.pdf", reader, max_pages=10)

    assert (refused.value.code, refused.value.pages) == ("too_many_ocr_pages", 3)
    assert reader.asked == []


class ReadingFlow:
    """An engine that reads a DOCX and an HTML page as Docling does: it notes what it is asked, and hands back
    what it was told to or raises it."""

    name = "flow"
    version = "1"
    reads_scans = True
    formats = frozenset({".pdf", ".docx", ".html", ".htm"})

    def __init__(self, outcome: Conversion | Exception) -> None:
        self.outcome = outcome
        self.asked: list[tuple[str, int]] = []

    def convert(
        self, path: Path, *, pages: int, max_signs: int = 0, scanned: Collection[int] = ()
    ) -> Conversion:
        raise AssertionError("a DOCX or an HTML page is no PDF")

    def convert_flow(self, path: Path, *, max_pages: int, max_signs: int = 0) -> Conversion:
        self.asked.append((path.name, max_pages))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def flowing(text: str = "Die Lernenden planen.") -> Conversion:
    block = Block(
        id="p1-b1", page=1, kind="text", text=text, bbox=None, font_size=11, bold=False, italic=False
    )
    return Conversion(engine="flow", engine_version="1", pages=1, printed_pages=(None,), blocks=(block,))


@pytest.mark.parametrize("name", ["lehrplan.docx", "lehrplan.html", "lehrplan.HTM"])
def test_a_file_without_pages_is_read_by_an_engine_that_reads_its_type(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"<p>Die Lernenden planen.</p>")
    reader = ReadingFlow(flowing())

    conversion = convert_file(path, reader, max_pages=7)

    assert (conversion, reader.asked) == (flowing(), [(name, 7)])


def test_an_engine_that_reads_no_such_file_refuses_it(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.docx"
    path.write_bytes(b"PK\x03\x04")

    with pytest.raises(ConversionRefused) as refused:
        convert_file(path, engine("pdfplumber"), max_pages=10)

    assert refused.value.code == "not_pdf"


@pytest.mark.parametrize(
    ("raised", "code", "pages"),
    [
        (UnreadablePdf("no DOCX"), "unreadable", None),
        (TooManyPages(12, 10), "too_many_pages", 12),
        (TooDense(1, 200_000, 100_000), "too_dense", None),
    ],
)
def test_a_file_without_pages_is_refused_as_a_pdf_is(
    tmp_path: Path, raised: Exception, code: str, pages: int | None
) -> None:
    path = tmp_path / "lehrplan.html"
    path.write_text("<p>Text.</p>", encoding="utf-8")

    with pytest.raises(ConversionRefused) as refused:
        convert_file(path, ReadingFlow(raised), max_pages=10)

    assert (refused.value.code, refused.value.pages) == (code, pages)


def test_a_file_without_pages_of_no_text_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.html"
    path.write_text("<p></p>", encoding="utf-8")
    nothing = Conversion(engine="flow", engine_version="1", pages=0, printed_pages=(), blocks=())

    with pytest.raises(ConversionRefused) as refused:
        convert_file(path, ReadingFlow(nothing), max_pages=10)

    assert refused.value.code == "empty"
