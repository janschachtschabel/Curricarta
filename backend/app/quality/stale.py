"""Items of a gold sample that are no longer what was drawn: ``gone`` - the statement or node the item points
at is no more in the document (replaced, taken away) - or ``changed`` - the hash of its wording now is not
the one kept when drawn (an editor reworded it). Neither can be judged as drawn: the judging sheet marks
them, the importer refuses a judgement of one, the report counts them apart, outside ``open`` and outside
every denominator. A block is the conversion's, which a document keeps: a block item is never stale."""

from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import UUID

import psycopg

from app.db.gold import Item
from app.db.gold_rows import Shown, nodes_shown, statements_shown
from app.domain.wording import text_hash

Stale = Literal["gone", "changed"]
STALE: tuple[Stale, ...] = ("gone", "changed")


def state_of(item: Item, shown: Shown | None) -> Stale | None:
    """Whether the item is no longer what was drawn, by its row as the document ``shown`` holds it now
    (None where it holds none): its wording hashed as the sample hashed it (app/db/measures.py)."""
    if item.block_id is not None:
        return None
    if shown is None:
        return "gone"
    now = None if shown.wording is None else text_hash(shown.wording)
    return "changed" if now != item.text_hash else None


async def stale_items(
    connection: psycopg.AsyncConnection, document_id: UUID, items: Sequence[Item]
) -> dict[int, Stale]:
    """The items no longer what was drawn, by id, each with how."""
    statements = await statements_shown(
        connection, document_id, [i.statement_id for i in items if i.statement_id is not None]
    )
    nodes = await nodes_shown(connection, document_id, [i.node_id for i in items if i.node_id is not None])
    found: dict[int, Stale] = {}
    for item in items:
        shown = _shown(item, statements, nodes)
        if (state := state_of(item, shown)) is not None:
            found[item.id] = state
    return found


def _shown(item: Item, statements: Mapping[UUID, Shown], nodes: Mapping[UUID, Shown]) -> Shown | None:
    if item.statement_id is not None:
        return statements.get(item.statement_id)
    return nodes.get(item.node_id) if item.node_id is not None else None
