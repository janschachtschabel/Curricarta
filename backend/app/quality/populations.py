"""The populations the gold standard's samples are drawn from (plan H-3 §3.2), each unit an item to judge:

- ``statement``: the statements the model wrote, by their kind, whatever a reviewer did with them since: a
  confirmed and a rejected one are the model's output as much as the rest (a review counts the revision up
  and keeps the origin, app/db/review.py); one an editor reworded is the editor's (``orig_human``) and
  stays out.
- ``block``: the blocks of the running text - no header or footer, none of the contents, none on the title
  pages, no node's heading, 40 signs at least - by the third of the document they stand in and whether
  they are text or a table.
- ``anchor``: the rows of an import still as imported, by how their anchor was found and whether it is a
  node's or a statement's; a row whose first anchor block lies on the title pages in a stratum of its own,
  ``front:node`` or ``front:statement``, as the import counts them apart (E15).

The contents, and with them the title pages, are found as the MEM import finds them, by the document's cues
as they stand now (app/pipeline/ground.py ``contents_of``). Where they end no title pages, those are unknown:
no block is left out for them and no anchor set apart, and the population says so (``title_pages``)."""

import asyncio
from dataclasses import dataclass, replace

import psycopg

from app.db.conversions import all_blocks
from app.db.documents import Document
from app.db.gold import ItemDraft, SampleKind, TitlePages
from app.db.measures import imported_anchors, model_statements, title_blocks
from app.pipeline.ground import contents_of, ground_of
from app.pipeline.toc import OUTSIDE, title_page_blocks

SHORTEST_BLOCK = 40  # signs: a shorter block holds a statement seldom
FRONT = "front"  # the stratum of the anchors on the title pages, before node or statement


@dataclass(frozen=True)
class Population:
    items: list[ItemDraft]  # in a fixed order: by id, a block by its place
    title_pages: TitlePages | None  # a block's or anchor's population: whether the title pages were found


async def population_of(
    connection: psycopg.AsyncConnection, document: Document, kind: SampleKind
) -> Population:
    if kind == "statement":
        return Population(await model_statements(connection, document.id), None)
    blocks = await all_blocks(connection, document.conversion_id)
    ground = await ground_of(connection, document)
    contents = await asyncio.to_thread(contents_of, ground, blocks, document.document_type_iri)
    front = title_page_blocks(blocks, contents.front_end)
    title_pages: TitlePages = "unknown" if front is None else "left_out"
    front = front or frozenset()
    if kind == "anchor":
        anchors = await imported_anchors(connection, document.id)
        return Population([_set_apart(item, front) for item in anchors], title_pages)
    headings = await title_blocks(connection, document.id)
    pages = max((block.page for block in blocks), default=1)
    items = [
        ItemDraft(stratum=f"t{1 + 3 * (block.page - 1) // pages}:{block.kind}", block_id=block.id)
        for position, block in enumerate(blocks)
        if block.kind not in OUTSIDE
        and block.id not in front
        and position not in contents.positions
        and block.id not in headings
        and len(block.text.strip()) >= SHORTEST_BLOCK
    ]
    return Population(items, title_pages)


def _set_apart(item: ItemDraft, front: frozenset[str]) -> ItemDraft:
    if item.first_block is None or item.first_block not in front:
        return item
    return replace(item, stratum=f"{FRONT}:{'node' if item.node_id is not None else 'statement'}")
