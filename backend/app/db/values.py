"""The second layer's values at their holders (plan M3a D2, E11; migration l2_values): read by document,
and set as a holder's whole - its levels, time spans and workloads with their periods, a specification's
applicability contexts with the time spans and levels each holds (plan M3a H1) - in one change.

A set is made on the holder's revision under the tree's lock, as an editor's change of a node is
(app/db/editing.py): it refuses a frozen document, one beside its open job and one whose extraction has
not read every package; StaleRevision where the holder stands at another revision. A draft naming an
``id`` keeps that row - one of the holder's, of the draft's kind; a period one of that workload's, a
context's value one of that context's - and anything else named by id refuses the whole set
(UnknownValue). A row the set leaves out goes, with the findings on it - a context with its values -; a new
one is an editor's proposal (origin human, proposed), and a kept one whose content changes becomes one, on
its next revision. A set that changes something counts the holder's revision one up and notes the document
edited, which owes X5 a check; one that changes nothing leaves all as it was. What the store refuses of a
value - a concept of another vocabulary, no level, numbers out of order - refuses the set (ValueRefused,
``check`` the constraint's name; none for a number beyond its column's type); a statement holds levels
alone, and a time span or workload set at one is refused as ``not_held``, as is a context set at any holder
but a specification; a placement holds time spans and workloads alone (plan M3a K), a level set at one so too.
"""

from collections.abc import Sequence
from typing import Final, LiteralString
from uuid import UUID

import psycopg
from psycopg import sql

from app.db.anchors import new_entity
from app.db.assessments import DOCUMENT_OF_ASSESSMENT
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
from app.db.placements import DOCUMENT_OF_PLACEMENT
from app.db.source_queries import Reader
from app.db.statement_editing import DOCUMENT_OF_STATEMENT
from app.db.value_plans import Planned, Standing, UnknownValue, planned
from app.db.value_rows import COLUMN_OF, HOLDERS_OF, NESTED, TABLES, read_rows, row_content, values_of
from app.domain.l2 import Holder, HolderKind, ValueDrafts, ValueRefused

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
    "assessment": DOCUMENT_OF_ASSESSMENT,
    "placement": DOCUMENT_OF_PLACEMENT,
}
_POSITIONS: Final = (
    "SET CONSTRAINTS level_assignment_position, time_span_position, workload_position,"
    " applicability_context_position"
)
_PROPOSAL: Final = sql.SQL(
    "origin_iri = %s, rule_id = NULL, review_status_iri = %s, revision = revision + 1, updated_at = now()"
)


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
        wanted = planned(drafts, (column, holder.id), current)
        kept = {row.id for row in wanted if row.id is not None}
        gone = [value_id for value_id in current if value_id not in kept]
        if not gone and all(
            row.id is not None and current[row.id] == (row.holder, row.position, row.content)
            for row in wanted
        ):
            return expected_revision
        try:
            await _write(connection, target.document_id, wanted, current, gone)
        except (
            psycopg.errors.IntegrityError,
            psycopg.errors.DataError,
        ) as refused:  # a DataError has no name
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
    """The holder's rows of every kind, its workloads' periods and its contexts' values, locked, by id."""
    found: dict[UUID, Standing] = {}
    outer: dict[str, list[UUID]] = {table: [] for table in NESTED}
    for table in (each for each in TABLES if column in HOLDERS_OF[each]):
        where = sql.SQL("{} = %s").format(sql.Identifier(column))
        for row in await read_rows(connection, table, where, holder_id, lock=True):
            found[row["id"]] = ((column, holder_id), row["position"], row_content(table, row))
            if table in outer:
                outer[table].append(row["id"])
    for table, (inner_column, inner_tables) in NESTED.items():
        if not outer[table]:
            continue
        where = sql.SQL("{} = ANY(%s)").format(sql.Identifier(inner_column))
        for inner in inner_tables:
            for row in await read_rows(connection, inner, where, outer[table], lock=True):
                found[row["id"]] = (
                    (inner_column, row[inner_column]),
                    row["position"],
                    row_content(inner, row),
                )
    return found


async def _write(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    wanted: Sequence[Planned],
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
        try:
            await _written(connection, document_id, row, current)
        except (
            psycopg.errors.IntegrityError,
            psycopg.errors.DataError,
        ) as refused:  # a DataError has no name
            raise ValueRefused(refused.diag.constraint_name, row.context) from refused
    await connection.execute(f"{_POSITIONS} IMMEDIATE")


async def _written(
    connection: psycopg.AsyncConnection, document_id: UUID, row: Planned, current: dict[UUID, Standing]
) -> None:
    """The row as the set has it: new - with what it holds -, changed, or moved."""
    if row.id is None:
        made = await _insert(connection, document_id, row)
        for table, at, content in row.inner:
            await _insert(
                connection, document_id, Planned(table, None, (NESTED[row.table][0], made), at, content)
            )
        return
    _, position, content = current[row.id]
    if content != row.content:
        await _update(connection, row, proposal=True)
    elif position != row.position:
        await _update(connection, row, proposal=False)


async def _insert(connection: psycopg.AsyncConnection, document_id: UUID, row: Planned) -> UUID:
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


async def _update(connection: psycopg.AsyncConnection, row: Planned, *, proposal: bool) -> None:
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
