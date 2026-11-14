"""A file without pages - a DOCX, an HTML page - as a conversion (plan M1 3b-3).

Its items come in their order, headings with their levels, text with its weight and slant, list items with
their marks, tables with their cells - but with no page, no place and no size (Docling reads them so,
app/conversion/docling_flow.py). Pages are made: a block opens a new one where the page already holds
FLOW_PAGE_SIGNS signs - a printed page's worth -, never parting a block, so the blocks keep their names
(``p<page>-b<n>``), X1 its units and the account its pages to pay as a PDF's. A table runs on over the pages
by its rows, as a PDF's table joined over its pages: it stands on the page it begins, its cells on theirs. A
cell weighs its signs and one, an empty one too: a grid of empty places is as many cells to store. A
heading's size follows its level, the larger the higher, every one larger than the body by more than the
skeleton's measure (app/pipeline/skeleton.py, LARGER): the skeleton finds the levels as it finds them in a
PDF. The conversion says its pages are made (``flow_pages``), and what the file held hidden, of no page
(``text_dropped``).
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.conversion.assemble import assemble_flow
from app.conversion.base import Conversion, DropReason, Finding
from app.conversion.convert import MAX_PAGE_SIGNS
from app.conversion.layout import Box, RawBlock, RawCell, RawPage, clean_text
from app.conversion.text_layer import TooDense, TooManyPages

FLOW_PAGE_SIGNS = 3000  # a printed page of a curriculum holds some 2,000-4,000 signs
FLOW_BODY = 11.0  # the body's size: the sizes below are set against it
TITLE_SIZE = 22.0
HEADING_SIZES = (20.0, 18.0, 16.0, 14.0)  # levels 1 to 4
DEEPEST_SIZE = 13.0  # level 5 and deeper: still larger than the body by more than 1.15
_NO_PLACE: Box = (0.0, 0.0, 0.0, 0.0)  # within the raw pages alone: the blocks get none (assemble_flow)

FlowKind = Literal["title", "heading", "text", "list_item", "table"]


@dataclass(frozen=True)
class FlowCell:
    text: str
    header: bool


@dataclass(frozen=True)
class FlowItem:
    kind: FlowKind
    text: str  # a table's is its cells'
    level: int = 0  # a heading's, from 1
    bold: bool = False
    italic: bool = False
    marker: str = ""  # a list item's: "•", "1."
    # a table's rows; None where a spanning cell covers the place
    rows: tuple[tuple[FlowCell | None, ...], ...] = ()


def flow_conversion(
    items: Sequence[FlowItem],
    dropped: Counter[DropReason],
    *,
    engine: str,
    version: str,
    max_pages: int,
    max_signs: int = MAX_PAGE_SIGNS,
) -> Conversion:
    """The items on pages of FLOW_PAGE_SIGNS signs; TooManyPages past ``max_pages``, TooDense for a block - a
    table's row - of more than ``max_signs`` signs. ``dropped``: the signs left out before, hidden, by why."""
    paging = _Paging()
    for item in items:
        if item.kind == "table":
            _table(item, paging, max_signs)
            continue
        signs = len(clean_text(item.text).strip())
        if not signs:
            continue
        page = paging.page()
        if signs > max_signs:
            raise TooDense(page.number, signs, max_signs)
        page.blocks.append(_block(item, page.number))
        paging.held += signs
    if len(paging.pages) > max_pages:
        raise TooManyPages(len(paging.pages), max_pages)
    said = Finding(code="flow_pages", params={"signs": FLOW_PAGE_SIGNS})
    return assemble_flow(paging.pages, engine=engine, version=version, first=[said], dropped=dropped)


class _Paging:
    """The pages made so far, and the signs the last holds."""

    def __init__(self) -> None:
        self.pages: list[RawPage] = []
        self.held = FLOW_PAGE_SIGNS  # the first block opens the first page

    def page(self) -> RawPage:
        """The page what comes next goes on: a new one where the last holds its signs."""
        if self.held >= FLOW_PAGE_SIGNS:
            self.pages.append(RawPage(len(self.pages) + 1, 0.0))
            self.held = 0
        return self.pages[-1]


def _table(item: FlowItem, paging: _Paging, max_signs: int) -> None:
    """The table on the page it begins, its rows run on over the pages; a table of no text is none."""
    texts = [[None if cell is None else clean_text(cell.text).strip() for cell in row] for row in item.rows]
    if not any(text for row in texts for text in row):
        return
    start = paging.page()
    rows: list[tuple[RawCell | None, ...]] = []
    for cells, texts_of_row in zip(item.rows, texts, strict=True):
        if all(cell is None for cell in cells):  # all its places covered from above: no cell to put on a page
            rows.append(tuple(None for _ in cells))
            continue
        page = paging.page() if rows else start
        weight = sum(len(text) + 1 for text in texts_of_row if text is not None)
        if weight > max_signs:
            raise TooDense(page.number, weight, max_signs)
        rows.append(
            tuple(
                None if cell is None or text is None else RawCell(text, cell.header, page.number)
                for cell, text in zip(cells, texts_of_row, strict=True)
            )
        )
        paging.held += weight
    start.blocks.append(RawBlock(start.number, "table", "", _NO_PLACE, None, False, False, tuple(rows)))


def _block(item: FlowItem, page: int) -> RawBlock:
    text = clean_text(item.text).strip()
    if item.kind == "list_item" and item.marker:
        text = f"{item.marker} {text}"
    heading = item.kind in ("title", "heading")
    return RawBlock(page, "text", text, _NO_PLACE, _size(item), item.bold or heading, item.italic)


def _size(item: FlowItem) -> float:
    if item.kind == "title":
        return TITLE_SIZE
    if item.kind == "heading":
        return HEADING_SIZES[item.level - 1] if 1 <= item.level <= len(HEADING_SIZES) else DEEPEST_SIZE
    return FLOW_BODY
