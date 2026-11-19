"""The second layer's values at their holders (plan M3a D2, E11; migration l2_values): read by document,
and set as a holder's whole - its levels, time spans and workloads with their periods - in one change.

A set is made on the holder's revision under the tree's lock, as an editor's change of a node is
(app/db/editing.py): it refuses a frozen document, one beside its open job and one whose extraction has
not read every package; StaleRevision where the holder stands at another revision. A draft naming an
``id`` keeps that row - one of the holder's, of the draft's kind; a period one of that workload's - and
anything else named by id refuses the whole set (UnknownValue). A row the set leaves out goes, with the
findings on it; a new one is an editor's proposal (origin human, proposed), and a kept one whose content
changes becomes one, on its next revision. A set that changes something counts the holder's revision
one up and notes the document edited, which owes X5 a check; one that changes nothing leaves all as it
was. What the store refuses of a value - a concept of another vocabulary, no level, numbers out of order
- refuses the set (ValueRefused, ``check`` the constraint's name); a statement holds levels alone, and a
time span or workload set at one is refused as ``not_held``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, LiteralString
from uuid import UUID

import psycopg
from psycopg import sql

from app.db.anchors import new_entity
from app.db.documents import DOCUMENT_VISIBLE
from app.db.editing import (
    DOCUMENT_OF_NODE,
    HUMAN,
    PROPOSED,
    SECTOR,
    StaleRevision,
    drop_findings,
    guard,
    mark_edited,
    target_of,
)
from app.db.source_queries import Reader
from app.db.statement_editing import DOCUMENT_OF_STATEMENT
from app.db.value_rows import (
    COLUMN_OF,
    HOLDERS_OF,
    TABLES,
    level_content,
    read_rows,
    row_content,
    time_content,
    values_of,
    workload_content,
)
from app.domain.l2 import Holder, HolderKind, ValueDrafts

__all__ = ["DOCUMENT_OF_SPECIFICATION", "UnknownValue", "ValueRefused", "replace_values", "values_of"]

CV = "https://w3id.org/wlo/curriculum/vocab#"
DOCUMENT_OF_SPECIFICATION = f"""
SELECT d.id, sector.notation FROM specification s JOIN document d ON d.id = s.document_id {SECTOR}
WHERE s.id = %(id)s AND {DOCUMENT_VISIBLE}
"""  # noqa: S608 - fixed parts
_DOCUMENT_OF: Final[dict[HolderKind, str]] = {
    "node": DOCUMENT_OF_NODE,
    "statement": DOCUMENT_OF_STATEMENT,
    "specification": DOCUMENT_OF_SPECIFICATION,
}
_POSITIONS: Final = "SET CONSTRAINTS level_assignment_position, time_span_position, workload_position"
_PROPOSAL: Final = sql.SQL(
    "origin_iri = %s, rule_id = NULL, review_status_iri = %s, revision = revision + 1, updated_at = now()"
)
# A row as it stands: its holder's column and row, its position, what it says
Standing = tuple[tuple[str, UUID], int, dict[str, Any]]


class UnknownValue(Exception):
    """A draft names by id a row that is no value of its kind at its place in the set."""

    def __init__(self, value_id: UUID) -> None:
        super().__init__(f"{value_id} is no value of its kind at this holder")
        self.value_id = value_id


class ValueRefused(Exception):
    """The store refuses a value of the set: ``check`` names the constraint it breaks."""

    def __init__(self, check: str | None) -> None:
        super().__init__(f"a value breaks {check}")
        self.check = check


@dataclass(frozen=True)
class _Row:
    """A value as the set has it: where it stands (``table``, its holder's column and row, its position)
    and what it says; ``id`` its kept row's, None for a new one - a new workload with the contents of its
    periods, which stand under it once it is written."""

    table: LiteralString
    id: UUID | None
    holder: tuple[LiteralString, UUID]
    position: int
    content: dict[str, Any]
    periods: tuple[dict[str, Any], ...] = ()


async def replace_values(
    connection: psycopg.AsyncConnection,
    reader: Reader,
    holder: Holder,
    expected_revision: int,
    drafts: ValueDrafts,
) -> int | None:
    """Set the holder's values to ``drafts``, on its revision ``expected_revision``, as above; the holder's
    revision after, None where ``reader`` sees no such holder. StaleRevision, UnknownValue, ValueRefused or a
    refusal of ``guard``, and then nothing is changed."""
    table = sql.Identifier(holder.kind)
    column = COLUMN_OF[holder.kind]
    async with connection.transaction():
        target = await target_of(connection, _DOCUMENT_OF[holder.kind], reader, holder.id)
        if target is None:
            return None
        await guard(connection, target.document_id)
        cursor = await connection.execute(
            sql.SQL("SELECT revision FROM {} WHERE id = %s FOR UPDATE").format(table), (holder.id,)
        )
        found = await cursor.fetchone()
        if found is None:  # dropped meanwhile
            return None
        if found[0] != expected_revision:
            raise StaleRevision(found[0])
        current = await _current(connection, column, holder.id)
        wanted = _planned(drafts, (column, holder.id), current)
        kept = {row.id for row in wanted if row.id is not None}
        gone = [value_id for value_id in current if value_id not in kept]
        if not gone and all(
            row.id is not None and current[row.id] == (row.holder, row.position, row.content)
            for row in wanted
        ):
            return expected_revision
        try:
            await _write(connection, target.document_id, wanted, current, gone)
        except psycopg.errors.IntegrityError as refused:
            raise ValueRefused(refused.diag.constraint_name) from refused
        cursor = await connection.execute(
            sql.SQL("UPDATE {} SET revision = revision + 1 WHERE id = %s RETURNING revision").format(table),
            (holder.id,),
        )
        raised = await cursor.fetchone()
        assert raised is not None  # noqa: S101 - the row locked above
        await mark_edited(connection, target.document_id)
        return int(raised[0])


async def _current(
    connection: psycopg.AsyncConnection, column: LiteralString, holder_id: UUID
) -> dict[UUID, Standing]:
    """The holder's rows of every kind and its workloads' periods, locked, by id."""
    found: dict[UUID, Standing] = {}
    workloads = []
    for table in (each for each in TABLES if column in HOLDERS_OF[each]):
        where = sql.SQL("{} = %s").format(sql.Identifier(column))
        for row in await read_rows(connection, table, where, holder_id, lock=True):
            found[row["id"]] = ((column, holder_id), row["position"], row_content(table, row))
            if table == "workload":
                workloads.append(row["id"])
    for row in await read_rows(
        connection, "time_span", sql.SQL("workload_id = ANY(%s)"), workloads, lock=True
    ):
        found[row["id"]] = (
            ("workload_id", row["workload_id"]),
            row["position"],
            row_content("time_span", row),
        )
    return found


def _planned(
    drafts: ValueDrafts, holder: tuple[LiteralString, UUID], current: dict[UUID, Standing]
) -> list[_Row]:
    """The rows the set asks for. UnknownValue where a draft's id is none of ``current`` of its kind and
    place, or is named twice; ValueRefused where the holder has no column for a kind of them."""
    planned: list[_Row] = []
    if holder[0] not in HOLDERS_OF["workload"] and (drafts.time_spans or drafts.workloads):
        raise ValueRefused("not_held")

    def row(table: LiteralString, value_id: UUID | None, at: tuple[LiteralString, UUID], place: int,
            content: dict[str, Any]) -> _Row:  # fmt: skip
        if value_id is not None and (
            value_id not in current
            or current[value_id][0] != at
            or current[value_id][2].keys() != content.keys()  # another kind's row
            or any(each.id == value_id for each in planned)
        ):
            raise UnknownValue(value_id)
        return _Row(table, value_id, at, place, content)

    for place, level in enumerate(drafts.levels, 1):
        planned.append(row("level_assignment", level.id, holder, place, level_content(level)))
    for place, span in enumerate(drafts.time_spans, 1):
        planned.append(row("time_span", span.id, holder, place, time_content(span)))
    for place, workload in enumerate(drafts.workloads, 1):
        if workload.id is None:  # its periods are new as it is
            if (
                named := next((each.id for each in workload.periods if each.id is not None), None)
            ) is not None:
                raise UnknownValue(named)
            periods = tuple(time_content(period) for period in workload.periods)
            planned.append(_Row("workload", None, holder, place, workload_content(workload), periods))
            continue
        planned.append(row("workload", workload.id, holder, place, workload_content(workload)))
        for at, period in enumerate(workload.periods, 1):
            planned.append(
                row("time_span", period.id, ("workload_id", workload.id), at, time_content(period))
            )
    return planned


async def _write(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    wanted: Sequence[_Row],
    current: dict[UUID, Standing],
    gone: Sequence[UUID],
) -> None:
    """Take the rows ``gone`` away with the findings on them, change the kept ones that changed, write the
    new ones; the positions are checked at the end, once all stand."""
    await connection.execute(f"{_POSITIONS} DEFERRED")
    if gone:
        await drop_findings(connection, document_id, gone)
        for table in TABLES:
            await connection.execute(
                sql.SQL("DELETE FROM {} WHERE id = ANY(%s)").format(sql.Identifier(table)), (list(gone),)
            )
    for row in wanted:
        if row.id is None:
            made = await _insert(connection, document_id, row)
            for at, period in enumerate(row.periods, 1):
                await _insert(
                    connection, document_id, _Row("time_span", None, ("workload_id", made), at, period)
                )
            continue
        _, position, content = current[row.id]
        if content != row.content:
            await _update(connection, row, proposal=True)
        elif position != row.position:
            await _update(connection, row, proposal=False)
    await connection.execute(f"{_POSITIONS} IMMEDIATE")


async def _insert(connection: psycopg.AsyncConnection, document_id: UUID, row: _Row) -> UUID:
    """The new row ``row``, an editor's proposal; its id."""
    made = await new_entity(connection, row.table)
    values = {
        "id": made, "document_id": document_id, row.holder[0]: row.holder[1], "position": row.position,
        "origin_scheme": CV + "Origins", "origin_iri": HUMAN,
        "review_status_scheme": CV + "ReviewStatuses", "review_status_iri": PROPOSED,
    } | row.content  # fmt: skip
    await connection.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(row.table),
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() * len(values)),
        ),
        tuple(values.values()),
    )
    return made


async def _update(connection: psycopg.AsyncConnection, row: _Row, *, proposal: bool) -> None:
    """The kept row at its new position; changed, as an editor's proposal on its next revision."""
    assert row.id is not None  # noqa: S101 - a kept row
    values = {"position": row.position} | (row.content if proposal else {})
    columns: list[sql.Composable] = [sql.SQL("{} = %s").format(sql.Identifier(key)) for key in values]
    if proposal:
        columns.append(_PROPOSAL)
    params = (*values.values(), *((HUMAN, PROPOSED) if proposal else ()), row.id)
    await connection.execute(
        sql.SQL("UPDATE {} SET {} WHERE id = %s").format(
            sql.Identifier(row.table), sql.SQL(", ").join(columns)
        ),
        params,
    )
