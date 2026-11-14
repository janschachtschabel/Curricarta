"""Items of a gold sample that are no longer what was drawn: ``gone`` - the statement or node the item points
at is no more in the document (replaced, taken away) - or ``changed`` - the row is there, but measured as
the draw measured it (app/db/measures.py) it differs from the item: its wording's hash, its origin (the
model's for a statement sample, the import's for an anchor sample: an editor's change makes the row the
editor's) or its first block. The judging sheet marks them and gives no judgement of them a proof
(app/quality/sheet.py); the report leaves out those not judged and counts the judged ones beside the rates
(app/quality/report.py). A block is the conversion's, which a document keeps: a block item is never stale."""

from collections.abc import Sequence
from typing import Literal

import psycopg

from app.db.gold import Item, Sample
from app.db.measures import CV, RowNow, rows_now

Stale = Literal["gone", "changed"]
STALE: tuple[Stale, ...] = ("gone", "changed")
ORIGIN = {"statement": CV + "orig_model", "anchor": CV + "orig_import"}  # of the rows a sample is drawn from


def state_of(sample: Sample, item: Item, row: RowNow | None) -> Stale | None:
    """Whether the item of ``sample`` is no longer what was drawn, by its row as it stands (None: gone)."""
    if item.block_id is not None:
        return None
    if row is None:
        return "gone"
    first = row.first_block if sample.kind == "statement" else row.found_block
    same = (row.origin, row.text_hash, first) == (ORIGIN[sample.kind], item.text_hash, item.first_block)
    return None if same else "changed"


async def stale_items(
    connection: psycopg.AsyncConnection, sample: Sample, items: Sequence[Item]
) -> dict[int, Stale]:
    """The sample's items no longer what was drawn, by id, each with how."""
    rows = await rows_now(
        connection,
        sample.document_id,
        [item.statement_id for item in items if item.statement_id is not None],
        [item.node_id for item in items if item.node_id is not None],
    )
    found: dict[int, Stale] = {}
    for item in items:
        key = item.statement_id or item.node_id
        if (state := state_of(sample, item, None if key is None else rows.get(key))) is not None:
            found[item.id] = state
    return found
