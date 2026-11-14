"""The pages as an engine read them become a conversion (plan M1, 3.2).

Each page's blocks in reading order - columns left to right, each top down, at one height left to
right (app/conversion/reading_order.py); running heads and feet marked and the printed page
numbers read (app/conversion/page_edges.py); tables continued over a page joined to their first
part (app/conversion/tables.py); the signs of symbol fonts
mapped and a broken text layer noticed (app/conversion/symbols.py, encoding.py), both as findings,
and so the text the engine dropped: a finding for each reason, with its signs and their pages;
then the names: ``p<page>-b<n>`` for each page's blocks, the tables counted across the document,
a cell ``T<n>:r<i>c<j>`` by its row and column in the joined table. A place a spanning cell covers
has no cell. A table's text is its rows, line by line, its cells parted by " | " (a bar within a
cell escaped).
"""

from collections import Counter
from collections.abc import Iterator, Sequence
from typing import get_args

from app.conversion.base import Block, Cell, Conversion, DropReason, Finding, block_id, cell_id
from app.conversion.encoding import encoding_findings
from app.conversion.layout import RawBlock, RawPage
from app.conversion.page_edges import mark_edges
from app.conversion.reading_order import reading_order
from app.conversion.symbols import map_symbols
from app.conversion.tables import merge_across_pages


def assemble(pages: list[RawPage], *, engine: str, version: str) -> Conversion:
    for page in pages:
        page.blocks[:] = reading_order(page.blocks)
    printed = mark_edges(pages)  # before the joining: running heads and feet do not part a table
    merge_across_pages(pages)
    findings = [*map_symbols(pages), *encoding_findings(pages), *_dropped(pages), *_read_by_ocr(pages)]
    return Conversion(
        engine=engine,
        engine_version=version,
        pages=len(pages),
        printed_pages=printed,
        blocks=tuple(_named(pages, placed=True)),
        findings=tuple(findings),
    )


def assemble_flow(
    pages: list[RawPage],
    *,
    engine: str,
    version: str,
    first: Sequence[Finding],
    dropped: Counter[DropReason],
) -> Conversion:
    """The pages made of a file without pages (app/conversion/flow.py) as a conversion: their blocks in the
    order made, of no place and no printed page; the signs of symbol fonts mapped and a broken text noticed as
    a PDF's; ``first``, then the text left out before converting, by why, of no page."""
    findings = [*first, *map_symbols(pages), *encoding_findings(pages), *_dropped_before(dropped)]
    return Conversion(
        engine=engine,
        engine_version=version,
        pages=len(pages),
        printed_pages=(None,) * len(pages),
        blocks=tuple(_named(pages, placed=False)),
        findings=tuple(findings),
    )


def _named(pages: list[RawPage], *, placed: bool) -> Iterator[Block]:
    """The blocks named ``p<page>-b<n>``, the tables counted across the document; without their places where
    not ``placed``."""
    tables = 0
    for page in pages:
        for number, raw in enumerate(page.blocks, start=1):
            cells: tuple[Cell, ...] = ()
            if raw.kind == "table":
                tables += 1
                cells = _cells(raw, tables)
            yield Block(
                id=block_id(page.number, number),
                page=page.number,
                kind=raw.kind,
                text=_table_text(raw) if raw.kind == "table" else raw.text,
                bbox=raw.bbox if placed else None,
                font_size=raw.font_size,
                bold=raw.bold,
                italic=raw.italic,
                cells=cells,
            )


def _read_by_ocr(pages: list[RawPage]) -> list[Finding]:
    """The pages OCR read - their words may be misread -, and how sure it was on the least sure of them."""
    read = [page for page in pages if page.ocr is not None]
    if not read:
        return []
    least = min(page.ocr for page in read if page.ocr is not None)
    return [Finding(code="ocr_read", params={"pages": [page.number for page in read], "confidence": least})]


def _dropped(pages: list[RawPage]) -> list[Finding]:
    return [
        Finding(
            code="text_dropped",
            params={
                "reason": reason,
                "count": sum(page.dropped[reason] for page in pages),
                "pages": sorted(page.number for page in pages if page.dropped[reason]),
            },
        )
        for reason in get_args(DropReason)
        if any(page.dropped[reason] for page in pages)
    ]


def _dropped_before(dropped: Counter[DropReason]) -> list[Finding]:
    return [
        Finding(code="text_dropped", params={"reason": reason, "count": dropped[reason], "pages": []})
        for reason in get_args(DropReason)
        if dropped[reason]
    ]


def _cells(table: RawBlock, number: int) -> tuple[Cell, ...]:
    return tuple(
        Cell(
            id=cell_id(number, row, column),
            page=cell.page,
            row=row,
            column=column,
            text=cell.text,
            header=cell.header,
        )
        for row, cells in enumerate(table.rows, start=1)
        for column, cell in enumerate(cells, start=1)
        if cell is not None
    )


def _table_text(table: RawBlock) -> str:
    return "\n".join(
        " | ".join("" if cell is None else cell.text.replace("|", "\\|") for cell in row)
        for row in table.rows
    )
