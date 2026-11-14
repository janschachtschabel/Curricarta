"""A file without pages - a DOCX, an HTML page - as a conversion (app/conversion/flow.py, plan M1 3b-3):
its items in their order on pages made of so many signs, a heading's size by its level, a list item with its
mark, a table with its cells; the text it held hidden a finding of no page."""

from collections import Counter
from collections.abc import Mapping

import pytest

from app.conversion.base import Conversion, DropReason
from app.conversion.flow import (
    FLOW_BODY,
    FLOW_PAGE_SIGNS,
    FlowCell,
    FlowItem,
    flow_conversion,
)
from app.conversion.text_layer import TooDense, TooManyPages


def text(words: str, **given: object) -> FlowItem:
    return FlowItem("text", words, **given)  # type: ignore[arg-type]


def converted(
    items: list[FlowItem], dropped: Mapping[DropReason, int] | None = None, max_pages: int = 800
) -> Conversion:
    return flow_conversion(
        items, Counter(dropped or {}), engine="docling", version="2.117.0", max_pages=max_pages
    )


def test_pages_are_made_of_so_many_signs_and_a_block_is_never_parted() -> None:
    items = [text("x" * 1000) for _ in range(7)]

    conversion = converted(items)

    assert FLOW_PAGE_SIGNS == 3000
    assert [block.id for block in conversion.blocks] == [
        "p1-b1", "p1-b2", "p1-b3", "p2-b1", "p2-b2", "p2-b3", "p3-b1",
    ]  # fmt: skip
    assert (conversion.pages, conversion.printed_pages) == (3, (None, None, None))
    assert all(block.bbox is None for block in conversion.blocks)


def test_a_heading_is_set_larger_the_higher_its_level_and_bold() -> None:
    items = [
        FlowItem("title", "Lehrplan Physik"),
        *(FlowItem("heading", f"Ebene {level}", level=level) for level in range(1, 8)),
        text("Ein Absatz."),
        text("Fett gesetzt.", bold=True),
        text("Kursiv gesetzt.", italic=True),
    ]

    blocks = converted(items).blocks

    assert [(block.font_size, block.bold, block.italic) for block in blocks] == [
        (22.0, True, False),
        (20.0, True, False), (18.0, True, False), (16.0, True, False), (14.0, True, False),
        (13.0, True, False), (13.0, True, False), (13.0, True, False),
        (FLOW_BODY, False, False), (FLOW_BODY, True, False), (FLOW_BODY, False, True),
    ]  # fmt: skip
    # every level is larger than the body as the skeleton weighs it (app/pipeline/skeleton.py, LARGER)
    assert min(block.font_size or 0 for block in blocks[:8]) >= 1.15 * FLOW_BODY


def test_a_list_item_keeps_its_mark() -> None:
    items = [FlowItem("list_item", "Sie planen.", marker="•"), FlowItem("list_item", "Erstens.", marker="1.")]

    assert [block.text for block in converted(items).blocks] == ["• Sie planen.", "1. Erstens."]


def test_a_table_is_a_block_of_its_cells_its_header_row_marked() -> None:
    rows = (
        (FlowCell("Kompetenz", True), FlowCell("Stunden", True)),
        (FlowCell("Planen", False), FlowCell("20 | 30", False)),
        (FlowCell("Prüfen", False), None),  # a place a spanning cell covers
    )

    [table] = converted([FlowItem("table", "", rows=rows)]).blocks

    assert (table.id, table.kind, table.font_size) == ("p1-b1", "table", None)
    assert table.text == "Kompetenz | Stunden\nPlanen | 20 \\| 30\nPrüfen | "
    assert [(cell.id, cell.text, cell.header, cell.page) for cell in table.cells] == [
        ("T1:r1c1", "Kompetenz", True, 1),
        ("T1:r1c2", "Stunden", True, 1),
        ("T1:r2c1", "Planen", False, 1),
        ("T1:r2c2", "20 | 30", False, 1),
        ("T1:r3c1", "Prüfen", False, 1),
    ]


def rows_of(count: int, signs: int) -> tuple[tuple[FlowCell | None, ...], ...]:
    return tuple((FlowCell(f"{number:04d}" + "x" * (signs - 4), False), None) for number in range(count))


def test_a_table_longer_than_a_page_runs_on_over_the_pages_its_cells_on_theirs() -> None:
    # a Word table of a whole curriculum: on the page it begins, its rows on theirs, as a PDF's joined table
    items = [text("x" * 1000), FlowItem("table", "", rows=rows_of(12, 999)), text("Danach.")]

    conversion = converted(items)

    first, table, after = conversion.blocks
    assert (first.id, table.id, after.id) == ("p1-b1", "p1-b2", "p5-b1")
    # a row weighs its signs and one for each cell: 1000 a row
    assert [cell.page for cell in table.cells] == [1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5]
    assert conversion.pages == 5


def test_a_table_is_held_to_the_signs_of_a_page_by_its_rows_not_as_a_whole() -> None:
    within = rows_of(3, 60)  # 183 signs together, no row over 100
    over = rows_of(1, 101)

    def table(rows: tuple[tuple[FlowCell | None, ...], ...]) -> Conversion:
        items = [FlowItem("table", "", rows=rows)]
        return flow_conversion(
            items, Counter(), engine="docling", version="2.117.0", max_pages=800, max_signs=100
        )

    assert len(table(within).blocks[0].cells) == 3
    with pytest.raises(TooDense):
        table(over)


def test_a_table_weighs_its_cells_an_empty_one_too_and_one_of_no_text_is_no_block() -> None:
    # a grid of 9,000 places holding one sign: as many cells to store as a long text has signs
    grid = tuple(
        tuple(FlowCell("x" if (row, column) == (0, 0) else "", False) for column in range(30))
        for row in range(300)
    )
    empty = tuple(tuple(FlowCell("", False) for _ in range(3)) for _ in range(3))

    assert converted([FlowItem("table", "", rows=grid)]).pages == 3
    assert converted([FlowItem("table", "", rows=empty), text("Ziele")]).blocks[0].text == "Ziele"


def test_an_item_of_no_text_is_no_block() -> None:
    assert [block.text for block in converted([text("  \n "), text("Ziele")]).blocks] == ["Ziele"]


def test_the_conversion_says_its_pages_are_made_and_what_it_left_out_hidden() -> None:
    conversion = converted([text("Ziele")], Counter({"hidden": 34, "tiny": 5}))

    assert [(finding.code, finding.params) for finding in conversion.findings] == [
        ("flow_pages", {"signs": FLOW_PAGE_SIGNS}),
        ("text_dropped", {"reason": "tiny", "count": 5, "pages": []}),
        ("text_dropped", {"reason": "hidden", "count": 34, "pages": []}),
    ]


def test_more_pages_than_taken_are_too_many() -> None:
    with pytest.raises(TooManyPages) as refused:
        converted([text("x" * 3000) for _ in range(3)], max_pages=2)

    assert refused.value.pages == 3


def test_a_block_of_more_signs_than_a_page_holds_is_too_dense() -> None:
    with pytest.raises(TooDense):
        flow_conversion(
            [text("x" * 101)], Counter(), engine="docling", version="2.117.0", max_pages=800, max_signs=100
        )


def test_a_sign_no_store_keeps_is_cleaned_as_the_other_engines_clean_it() -> None:
    [block] = converted([text("Ziele\x00 des\x07 Unterrichts")]).blocks

    assert block.text == "Ziele des Unterrichts"


def test_as_many_pages_as_taken_are_taken() -> None:
    assert converted([text("x" * 3000) for _ in range(2)], max_pages=2).pages == 2


def test_a_last_row_of_places_spans_cover_opens_no_page() -> None:
    # a row of a table whose places the cells above cover (Word's vMerge): no cell begins in it
    rows = (*rows_of(3, 999), (None, None))

    assert converted([FlowItem("table", "", rows=rows)]).pages == 1
