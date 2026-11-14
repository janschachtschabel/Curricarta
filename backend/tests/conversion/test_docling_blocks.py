"""The engine docling's reading of Docling's result (plan M1 3b), on stand-ins shaped as Docling 2.117 hands
it over (probed in the converter's image on 2026-11-06): the pages in blocks of eight, boxes turned to the
page's top, a table's grid, and a result that is not whole taken for a file Docling cannot read. Docling
itself runs in tests/conversion/test_docling_e2e.py, where it is installed."""

import logging
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace as Shape
from typing import Any

import pytest

from app.conversion import docling_blocks
from app.conversion.base import EngineUnavailable
from app.conversion.convert import ConversionRefused, convert_file
from app.conversion.docling_blocks import PAGES_AT_ONCE, DoclingEngine, read_blocks
from app.conversion.docling_pages import DoclingItem, DoclingTableCell, DoclingWord
from app.conversion.text_layer import TooDense, UnreadablePdf

HEIGHT = 842.0
LAYERS = {"body", "furniture"}


def origin(name: str) -> Shape:
    return Shape(value=name)


def bbox(l: float, t: float, r: float, b: float, at: str = "BOTTOMLEFT") -> Shape:  # noqa: E741 - Docling's names
    return Shape(l=l, t=t, r=r, b=b, coord_origin=origin(at))


def rect(x0: float, top: float, x1: float, bottom: float) -> Shape:
    # docling-parse's words: from the page's top, the rectangle's first corner at its bottom left
    return Shape(
        r_x0=x0, r_y0=bottom, r_x1=x1, r_y1=bottom, r_x2=x1, r_y2=top, r_x3=x0, r_y3=top,
        coord_origin=origin("TOPLEFT"),
    )  # fmt: skip


def word_cell(text: str, box: tuple[float, float, float, float], font: str = "/F+ArialMT") -> Shape:
    return Shape(text=text, rect=rect(*box), font_name=font)


def item(label: str, *provs: tuple[int, Shape], data: Shape | None = None) -> Shape:
    return Shape(label=Shape(value=label), prov=[Shape(page_no=no, bbox=box) for no, box in provs], data=data)


class Document:
    def __init__(self, numbers: range, items: list[Shape]) -> None:
        self.pages = {number: Shape(size=Shape(width=595.0, height=HEIGHT)) for number in numbers}
        self.items = items
        self.asked: Any = None

    def iterate_items(self, *, included_content_layers: Any) -> list[tuple[Shape, int]]:
        self.asked = included_content_layers
        return [(each, 1) for each in self.items]


def result(
    numbers: range,
    items: list[Shape] | None = None,
    words: dict[int, list[Shape]] | None = None,
    *,
    status: str = "success",
    counted: int | None = None,
    lines: dict[int, list[Shape]] | None = None,
) -> Shape:
    return Shape(
        status=Shape(value=status),
        errors=[Shape(component_type=Shape(value="user_input"), category=Shape(value="backend_failure"))],
        input=Shape(page_count=numbers.stop - 1 if counted is None else counted),
        document=Document(numbers, items or []),
        pages=[
            Shape(
                page_no=no,
                parsed_page=Shape(
                    word_cells=(words or {}).get(no, []), textline_cells=(lines or {}).get(no, [])
                ),
            )
            for no in numbers
        ],
    )


def read_document_(convert: Callable[..., Shape], **asked: Any) -> list[Any]:
    return [page for block in read_blocks(convert, **asked) for page in block]


def answering(*results: Shape) -> tuple[Callable[[tuple[int, int], bool], Shape], list[tuple[int, int]]]:
    asked: list[tuple[int, int]] = []

    def convert(pages: tuple[int, int], ocr: bool) -> Shape:
        asked.append(pages)
        return results[len(asked) - 1]

    return convert, asked


def test_the_pages_are_read_eight_at_a_time_each_once_in_order() -> None:
    blocks = [result(range(first, min(first + 8, 18))) for first in (1, 9, 17)]
    for each in blocks:
        each.input.page_count = 17
    convert, asked = answering(*blocks)

    pages = read_document_(convert, pages=17, max_signs=100, layers=LAYERS)

    assert PAGES_AT_ONCE == 8
    assert asked == [(1, 8), (9, 16), (17, 17)]
    assert [page.number for page in pages] == list(range(1, 18))
    assert blocks[0].document.asked == LAYERS  # the running heads and feet too


def test_boxes_are_measured_from_the_page_s_top_and_words_keep_their_font() -> None:
    heading = item("section_header", (1, bbox(70, 762, 447, 739)))
    # "Entwurf" set upwards in the margin, as docling-parse gave it: its baseline runs down the page
    upwards = Shape(
        r_x0=32, r_y0=542, r_x1=32, r_y1=511, r_x2=24, r_y2=511, r_x3=24, r_y3=542,
        coord_origin=origin("TOPLEFT"),
    )  # fmt: skip
    words = {
        1: [
            word_cell("Ziele", (70, 80, 120, 96), "/F+Arial-BoldMT"),
            Shape(text="Entwurf", rect=upwards, font_name="/Helvetica"),
        ]
    }
    convert, _ = answering(result(range(1, 2), [heading], words))

    [page] = read_document_(convert, pages=1, max_signs=100, layers=LAYERS)

    assert page.height == HEIGHT
    assert page.items == [DoclingItem("section_header", (70, HEIGHT - 762, 447, HEIGHT - 739))]
    assert page.words == [
        DoclingWord("Ziele", (70, 80, 120, 96), "/F+Arial-BoldMT"),
        DoclingWord("Entwurf", (24, 511, 32, 542), "/Helvetica", upright=False),
    ]


def test_words_of_a_page_measured_from_its_bottom_are_turned_to_its_top() -> None:
    from_bottom = Shape(
        r_x0=70, r_y0=750, r_x1=120, r_y1=750, r_x2=120, r_y2=762, r_x3=70, r_y3=762,
        coord_origin=origin("BOTTOMLEFT"),
    )  # fmt: skip
    convert, _ = answering(
        result(range(1, 2), [], {1: [Shape(text="Ziele", rect=from_bottom, font_name="")]})
    )

    [page] = read_document_(convert, pages=1, max_signs=100, layers=LAYERS)

    assert page.words == [DoclingWord("Ziele", (70, HEIGHT - 762, 120, HEIGHT - 750), "")]


def test_a_table_is_its_grid_a_spanned_place_empty_a_cell_without_a_box_without_one() -> None:
    def table_cell(row: int, column: int, text: str, box: Shape | None) -> Shape:
        return Shape(start_row_offset_idx=row, start_col_offset_idx=column, text=text, bbox=box)

    cells = [
        table_cell(0, 0, "Lernfeld", bbox(70, 100, 300, 120, "TOPLEFT")),
        table_cell(1, 0, "1", bbox(70, 120, 180, 140, "TOPLEFT")),
        table_cell(1, 1, "80 ", None),
    ]
    table = item("table", (1, bbox(68, 744, 330, 700)), data=Shape(num_rows=2, num_cols=2, table_cells=cells))
    convert, _ = answering(result(range(1, 2), [table]))

    [page] = read_document_(convert, pages=1, max_signs=100, layers=LAYERS)

    box = (68, HEIGHT - 744, 330, HEIGHT - 700)
    assert page.items == [
        DoclingItem(
            "table",
            box,
            (
                (DoclingTableCell("Lernfeld", (70, 100, 300, 120)), None),
                (DoclingTableCell("1", (70, 120, 180, 140)), DoclingTableCell("80 ", None)),
            ),
        )
    ]


def test_a_paragraph_docling_carried_over_a_page_is_an_item_on_each() -> None:
    carried = item("text", (1, bbox(70, 100, 500, 80)), (2, bbox(70, 800, 500, 780)))
    convert, _ = answering(result(range(1, 3), [carried]))

    pages = read_document_(convert, pages=2, max_signs=100, layers=LAYERS)

    assert [[each.box for each in page.items] for page in pages] == [
        [(70, HEIGHT - 100, 500, HEIGHT - 80)],
        [(70, HEIGHT - 800, 500, HEIGHT - 780)],
    ]


def test_a_page_of_more_signs_than_taken_is_too_dense() -> None:
    words = {2: [word_cell("x" * 60, (0, 0, 10, 10)), word_cell("y" * 41, (0, 20, 10, 30))]}
    convert, _ = answering(result(range(1, 3), [], words))

    with pytest.raises(TooDense) as dense:
        read_document_(convert, pages=2, max_signs=100, layers=LAYERS)

    assert dense.value.page == 2


@pytest.mark.parametrize(
    "broken",
    [
        result(range(1, 3), status="partial_success"),
        result(range(1, 3), status="failure"),
        result(range(1, 3), counted=3),  # the file's pages counted otherwise than the text layer did
        Shape(**{**vars(result(range(1, 3))), "pages": [Shape(page_no=1, parsed_page=Shape(word_cells=[]))]}),
        Shape(
            **{**vars(result(range(1, 3))), "pages": [Shape(page_no=no, parsed_page=None) for no in (1, 2)]}
        ),
    ],
    ids=["partial", "failed", "counted_otherwise", "page_lost", "page_unparsed"],
)
def test_a_result_short_of_the_pages_asked_is_a_file_docling_cannot_read(broken: Shape) -> None:
    convert, _ = answering(broken)

    with pytest.raises(UnreadablePdf):
        read_document_(convert, pages=2, max_signs=100, layers=LAYERS)


def test_what_docling_raises_on_a_file_makes_it_unreadable_said_without_its_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def raising(pages: tuple[int, int], ocr: bool) -> Shape:
        raise RuntimeError("cannot parse /tmp/source-x/source.pdf at offset 9")

    with caplog.at_level(logging.WARNING), pytest.raises(UnreadablePdf) as unreadable:
        read_document_(raising, pages=2, max_signs=100, layers=LAYERS)

    assert "source.pdf" not in str(unreadable.value) and "source.pdf" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_a_block_s_result_is_let_go_before_the_next_is_read() -> None:
    # Docling's result of eight pages weighs some 30 times the pages the engine maps of it
    blocks = [result(range(1, 9)), result(range(9, 10))]
    for each in blocks:
        each.input.page_count = 9
    convert, asked = answering(*blocks)

    reading = read_blocks(convert, pages=9, max_signs=100, layers=LAYERS)
    first = next(reading)

    assert (len(first), asked) == (8, [(1, 8)])
    assert [page.number for page in next(reading)] == [9]


def test_a_page_missing_from_docling_s_document_alone_is_a_file_it_cannot_read() -> None:
    lost = result(range(1, 3))
    del lost.document.pages[2]  # parsed, but not in the document
    convert, _ = answering(lost)

    with pytest.raises(UnreadablePdf):
        read_document_(convert, pages=2, max_signs=100, layers=LAYERS)


def test_a_table_is_read_on_the_page_it_begins() -> None:
    table = item(
        "table",
        (1, bbox(68, 744, 330, 700)),
        (2, bbox(68, 800, 330, 700)),
        data=Shape(num_rows=1, num_cols=1, table_cells=[]),
    )
    convert, _ = answering(result(range(1, 3), [table]))

    pages = read_document_(convert, pages=2, max_signs=100, layers=LAYERS)

    assert [len(page.items) for page in pages] == [1, 0]


def test_a_page_of_as_many_signs_as_taken_is_read() -> None:
    convert, _ = answering(result(range(1, 2), [], {1: [word_cell("x" * 100, (0, 0, 10, 10))]}))

    [page] = read_document_(convert, pages=1, max_signs=100, layers=LAYERS)

    assert len(page.words) == 1


def test_an_error_item_without_a_category_still_makes_the_file_unreadable() -> None:
    failed = result(range(1, 2), status="failure")
    failed.errors = [Shape(component_type=Shape(value="user_input"))]
    convert, _ = answering(failed)

    with pytest.raises(UnreadablePdf):
        read_document_(convert, pages=1, max_signs=100, layers=LAYERS)


def test_a_want_of_memory_is_no_verdict_on_the_file() -> None:
    def short(pages: tuple[int, int], ocr: bool) -> Shape:
        raise MemoryError

    with pytest.raises(MemoryError):
        read_document_(short, pages=1, max_signs=100, layers=LAYERS)


@pytest.fixture
def loads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Docling's models stood in for: each load of them noted, and failing - no Docling here."""
    loaded: list[Path] = []

    def load(models: Path, ocr: bool) -> Any:
        loaded.append(models)
        raise OSError("a model file of other bytes")

    monkeypatch.setattr(docling_blocks, "version", lambda name: "2.117.0")
    monkeypatch.setattr(docling_blocks, "_converter", load)
    return loaded


def test_the_models_load_at_the_first_conversion_not_when_the_engine_is_made(loads: list[Path]) -> None:
    DoclingEngine(Path("/models"))

    assert loads == []


def test_a_file_refused_before_the_engine_reads_it_costs_no_model(loads: list[Path]) -> None:
    with pytest.raises(ConversionRefused) as refused:
        convert_file(Path(__file__).parent / "fixtures" / "prose.pdf", DoclingEngine(), max_pages=1)

    assert (refused.value.code, loads) == ("too_many_pages", [])


def test_models_that_do_not_load_are_no_verdict_on_the_file(loads: list[Path]) -> None:
    with pytest.raises(EngineUnavailable, match="OSError"):
        convert_file(
            Path(__file__).parent / "fixtures" / "prose.pdf", DoclingEngine(Path("/models")), max_pages=800
        )

    assert loads == [Path("/models")]


class OutOfMemoryError(RuntimeError):
    """torch's, by its name: torch is not installed here."""


def test_torch_s_want_of_memory_is_one_too() -> None:
    def short(pages: tuple[int, int], ocr: bool) -> Shape:
        raise OutOfMemoryError("CPU allocator")

    with pytest.raises(MemoryError):
        read_document_(short, pages=1, max_signs=100, layers=LAYERS)


class Result:
    """A result that can be watched for being let go: SimpleNamespace takes no weak reference."""

    def __init__(self, shape: Shape) -> None:
        self.__dict__.update(vars(shape))


def test_a_block_s_result_is_no_longer_held_once_its_pages_are_handed_over() -> None:
    import gc
    import weakref

    watched: list[weakref.ref[Result]] = []

    def convert(pages: tuple[int, int], ocr: bool) -> Result:
        made = Result(result(range(1, 2)))
        watched.append(weakref.ref(made))
        return made

    reading = read_blocks(convert, pages=1, max_signs=100, layers=LAYERS)
    next(reading)
    gc.collect()

    assert watched[0]() is None


def test_a_prov_on_a_page_of_another_block_is_passed_over() -> None:
    stray = item("text", (1, bbox(70, 100, 500, 80)), (5, bbox(70, 800, 500, 780)))
    convert, _ = answering(result(range(1, 2), [stray]))

    [page] = read_document_(convert, pages=1, max_signs=100, layers=LAYERS)

    assert len(page.items) == 1


FIXTURES = Path(__file__).parent / "fixtures"


def prose_result(numbers: range) -> Shape:
    """Docling's result for prose.pdf as the stand-ins shape it: the heading's words and item where
    pdfplumber finds them (set at 14 points, their boxes some 13 high)."""
    import pdfplumber

    with pdfplumber.open(FIXTURES / "prose.pdf") as pdf:
        page = pdf.pages[0]
        height = page.height
        line = [w for w in page.extract_words() if w["top"] < page.extract_words()[0]["bottom"]]
    words = {1: [word_cell(w["text"], (w["x0"], w["top"], w["x1"], w["bottom"] - 1)) for w in line]}
    x0, top = min(w["x0"] for w in line), min(w["top"] for w in line)
    x1, bottom = max(w["x1"] for w in line), max(w["bottom"] for w in line)
    heading = item("section_header", (1, bbox(x0, height - top, x1, height - bottom)))
    made = result(numbers, [heading], words)
    for each in made.document.pages.values():
        each.size.height = height
    return made


class Converting:
    def __init__(self, made: Shape) -> None:
        self.made, self.asked = made, 0

    def convert(self, path: Path, *, page_range: tuple[int, int], raises_on_error: bool) -> Shape:
        self.asked += 1
        return self.made


def test_the_engine_measures_each_word_by_pdfplumber_s_signs_under_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    converting = Converting(prose_result(range(1, 3)))
    monkeypatch.setattr(docling_blocks, "version", lambda name: "2.117.0")
    monkeypatch.setattr(docling_blocks, "_converter", lambda models, ocr: (converting, LAYERS))

    conversion = DoclingEngine(Path("/models")).convert(FIXTURES / "prose.pdf", pages=2)

    assert (conversion.blocks[0].text, conversion.blocks[0].font_size) == (
        "1 Lernfeld Steuerungstechnik",
        14.0,
    )


def test_pages_pdfplumber_counts_otherwise_make_the_file_unreadable_before_docling_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the text layer counted three, pdfplumber's tree holds two: sizes would come from other pages
    converting = Converting(prose_result(range(1, 4)))
    monkeypatch.setattr(docling_blocks, "version", lambda name: "2.117.0")
    monkeypatch.setattr(docling_blocks, "_converter", lambda models, ocr: (converting, LAYERS))

    with pytest.raises(UnreadablePdf, match="counted two ways"):
        DoclingEngine(Path("/models")).convert(FIXTURES / "prose.pdf", pages=3)

    assert converting.asked == 0
