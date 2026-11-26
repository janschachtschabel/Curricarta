"""The editors' review of a document's nodes and statements (plan M1 9.5; Paket 9 G8) and of its values -
levels, time spans and workloads, a workload's periods among them (plan M3a E; app/db/values.py), a
specification's applicability contexts (plan M3a H1) and the time spans and workloads of a placement (plan M3a
K), each a row with its own origin and review status: one review status for many rows at once, all or nothing
- each row on the revision it was read at, else none is set (StaleItems names those that stand otherwise, or
no more). A row set counts its revision one up and keeps its origin: a review is no edit. A value set counts
its holder's revision one up as well - a node's, a statement's, a specification's or a placement's, a period's
through its workload, a context and its values through the context's specification; once a holder, and not
where the holder's own review counted it -, as the holder's revision is the token a set of its values is made
on (app/db/values.py): a set read before the review is stale. It holds the tree's lock and refuses beside an
open job, before X4 is done and once the document is frozen, as every change does (app/db/editing.py,
``guard``).

A review changes not what the document says, but a statement rejected, or taken back from rejected, enters or
leaves the curriculum (the Kern export and X5 leave rejected ones out): that edits the document
(``document.edited_at``). A node rejected stays in both, but X5 reads its title as a heading no more
(app/pipeline/x5_checks.py): that owes the document its checks too - as a value rejected, or taken back, does.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, LiteralString, get_args
from uuid import UUID

import psycopg

from app.db.editing import CV, guard, mark_edited

ReviewKind = Literal[
    "node", "statement", "level_assignment", "time_span", "workload", "applicability_context"
]  # by their tables
REJECTED = CV + "rev_rejected"
_KINDS: tuple[ReviewKind, ...] = get_args(ReviewKind)
_CURRENT = (
    "SELECT id, revision, review_status_iri FROM {table} WHERE document_id = %s AND id = ANY(%s){only}"
    " FOR UPDATE"
)
# a level at a rules frame part is the rules' (plan M3a I), which no reader shows yet: none reviews it; nor
# one at an assessment, which is reviewed with its assessment, once assessments are (plan M3a J)
_ONLY = {"level_assignment": " AND frame_part_id IS NULL AND assessment_id IS NULL"}
_SET = """
UPDATE {table} SET review_status_iri = %s, revision = revision + 1, updated_at = now()
WHERE id = ANY(%s) RETURNING id, revision
"""
# a value's holder by its table: the row of its own holder's column - a period's, its workload's holder's; a
# context's value's, its context's specification
_HOLDER_OF: dict[str, LiteralString] = {
    "level_assignment": (
        "SELECT l.id, l.node_id, l.statement_id, coalesce(l.specification_id, c.specification_id), NULL::uuid"
        " FROM level_assignment l LEFT JOIN applicability_context c ON c.id = l.applicability_context_id"
        " WHERE l.id = ANY(%s)"
    ),
    "time_span": (
        "SELECT t.id, coalesce(t.node_id, w.node_id), NULL::uuid, coalesce(t.specification_id,"
        " w.specification_id, c.specification_id), coalesce(t.placement_id, w.placement_id) FROM time_span t"
        " LEFT JOIN workload w ON w.id = t.workload_id"
        " LEFT JOIN applicability_context c ON c.id = t.applicability_context_id WHERE t.id = ANY(%s)"
    ),
    "workload": (
        "SELECT id, node_id, NULL::uuid, specification_id, placement_id FROM workload WHERE id = ANY(%s)"
    ),
    "applicability_context": (
        "SELECT id, NULL::uuid, NULL::uuid, specification_id, NULL::uuid FROM applicability_context"
        " WHERE id = ANY(%s)"
    ),
}
# in the order _HOLDER_OF names their columns
_HOLDER_TABLES = ("node", "statement", "specification", "placement")
_LOCK = "SELECT FROM {table} WHERE document_id = %s AND id = ANY(%s) ORDER BY id FOR UPDATE"
_RAISE = "UPDATE {table} SET revision = revision + 1 WHERE id = ANY(%s) RETURNING id, revision"


@dataclass(frozen=True)
class ReviewItem:
    kind: ReviewKind
    id: UUID
    revision: int  # the row's, as it was read


@dataclass(frozen=True)
class Stale:
    kind: ReviewKind
    id: UUID
    current: int | None  # the row's revision now; none where the document holds no such row


class StaleItems(Exception):
    """Rows of a review that stand at another revision than it was made on, or no more: none was set."""

    def __init__(self, stale: list[Stale]) -> None:
        super().__init__(f"{len(stale)} rows stand otherwise")
        self.stale = stale


async def set_review(
    connection: psycopg.AsyncConnection, document_id: UUID, status: str, items: Sequence[ReviewItem]
) -> dict[UUID, int]:
    """Set the review status ``status`` (an IRI of cv:ReviewStatuses) of the document's rows ``items``; the
    revision of each after - one already at the status stays as it is, unless it holds a value set. A row
    named twice is set once, on the revision named first. StaleItems or a refusal of ``guard``, and then
    none is set."""
    first: dict[tuple[str, UUID], ReviewItem] = {}
    for item in items:
        first.setdefault((item.kind, item.id), item)
    named = list(first.values())
    async with connection.transaction():
        await guard(connection, document_id)
        # the values' holders, which a set locks before its values (app/db/values.py): so here too
        holders = await _holders(connection, document_id, named)
        found: dict[tuple[str, UUID], tuple[int, str]] = {}
        for kind in _KINDS:
            ids = [item.id for item in named if item.kind == kind]
            if ids:
                cursor = await connection.execute(
                    _CURRENT.format(table=kind, only=_ONLY.get(kind, "")), (document_id, ids)
                )
                found |= {(kind, row): (revision, now) for row, revision, now in await cursor.fetchall()}
        stale = []
        for item in named:
            current = found.get((item.kind, item.id))
            if current is None or current[0] != item.revision:
                stale.append(Stale(item.kind, item.id, None if current is None else current[0]))
        if stale:
            raise StaleItems(stale)
        revisions = {item.id: found[(item.kind, item.id)][0] for item in named}
        edited = False
        changed: set[UUID] = set()
        for kind in _KINDS:
            changing = [
                item.id for item in named if item.kind == kind and found[(kind, item.id)][1] != status
            ]
            if not changing:
                continue
            cursor = await connection.execute(_SET.format(table=kind), (status, changing))
            revisions |= {row: revision for row, revision in await cursor.fetchall()}
            changed.update(changing)
            was = {found[(kind, row)][1] for row in changing}
            edited = edited or REJECTED in {status, *was}
        # each holder of a value changed one up, once - one whose own review changed it counted already
        held = {holder for value, holder in holders.items() if value in changed and holder[1] not in changed}
        for table in _HOLDER_TABLES:
            if raised := sorted(row for of, row in held if of == table):
                cursor = await connection.execute(_RAISE.format(table=table), (raised,))
                revisions |= {row: revision for row, revision in await cursor.fetchall() if row in revisions}
        if edited:
            await mark_edited(connection, document_id)
        return revisions


async def _holders(
    connection: psycopg.AsyncConnection, document_id: UUID, named: Sequence[ReviewItem]
) -> dict[UUID, tuple[str, UUID]]:
    """The holder of each value ``named`` of the document - by its table and id -, locked: before the values
    are, as a set of values locks them (app/db/values.py). A value of none (a rule's level) is not there."""
    holders: dict[UUID, tuple[str, UUID]] = {}
    for kind, query in _HOLDER_OF.items():
        ids = [item.id for item in named if item.kind == kind]
        if ids:
            cursor = await connection.execute(query, (ids,))
            for value, *columns in await cursor.fetchall():
                holder = next(
                    ((table, row) for table, row in zip(_HOLDER_TABLES, columns, strict=True) if row), None
                )
                if holder is not None:
                    holders[value] = holder
    for table in _HOLDER_TABLES:
        rows = sorted({row for of, row in holders.values() if of == table})
        if rows:
            await connection.execute(_LOCK.format(table=table), (document_id, rows))
    return holders
