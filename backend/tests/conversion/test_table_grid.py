"""A table's grid is capped (audit 2026-11-14): a table that states more than MOST_GRID_CELLS places is
refused as too dense before its grid is laid out - by both of the engine docling's readers, a PDF's and
a DOCX's or HTML page's - and one of as many places as taken is read. Docling stands in as in
test_docling_blocks.py and test_docling_flow.py; whether its own HTML backend lays out a stated grid
first is tried in its image (test_docling_e2e.py)."""

from types import SimpleNamespace as Shape
from typing import Any

import pytest

from app.conversion.docling_flow import MOST_GRID_CELLS, flow_items
from app.conversion.text_layer import TooDense
from tests.conversion import test_docling_blocks as pdf
from tests.conversion import test_docling_flow as flow

VAST = 10**6  # rows by columns: a million each, a million million places


class Unlaid:
    """Cells of a table no test reads: a grid refused is never laid out."""

    def __iter__(self) -> Any:
        raise AssertionError("the grid was laid out")


def a_pdf_table(page: int, data: Shape) -> Shape:
    return pdf.item("table", (page, pdf.bbox(68, 744, 330, 700)), data=data)


def test_the_cap_is_two_hundred_thousand_places() -> None:
    assert MOST_GRID_CELLS == 200_000


def test_a_pdf_table_that_states_a_grid_past_any_page_s_is_refused_before_it_is_laid_out() -> None:
    vast = Shape(num_rows=VAST, num_cols=VAST, table_cells=Unlaid())
    convert, _ = pdf.answering(pdf.result(range(1, 3), [a_pdf_table(2, vast)]))

    with pytest.raises(TooDense) as dense:
        pdf.read_document_(convert, pages=2, max_signs=100, layers=pdf.LAYERS)

    assert dense.value.page == 2
    assert str(dense.value) == "page 2 holds 1000000000000 places of a table, more than the 200000 taken"


def test_a_pdf_table_of_as_many_places_as_taken_is_read() -> None:
    full = Shape(num_rows=1, num_cols=MOST_GRID_CELLS, table_cells=[])
    convert, _ = pdf.answering(pdf.result(range(1, 2), [a_pdf_table(1, full)]))

    [page] = pdf.read_document_(convert, pages=1, max_signs=100, layers=pdf.LAYERS)

    assert len(page.items[0].rows[0]) == MOST_GRID_CELLS


def test_a_docx_or_html_table_that_states_a_grid_past_any_page_s_is_refused_before_it_is_laid_out() -> None:
    table = flow.item("table", data=Shape(num_rows=VAST, num_cols=VAST, table_cells=Unlaid()))

    with pytest.raises(TooDense) as dense:
        flow_items(flow.Document(table), flow.LAYERS)

    assert dense.value.page is None
    assert str(dense.value) == "the file holds 1000000000000 places of a table, more than the 200000 taken"


def test_a_docx_or_html_table_of_as_many_places_as_taken_is_read() -> None:
    table = flow.item("table", data=Shape(num_rows=MOST_GRID_CELLS, num_cols=1, table_cells=[]))

    [read] = flow_items(flow.Document(table), flow.LAYERS)

    assert len(read.rows) == MOST_GRID_CELLS
