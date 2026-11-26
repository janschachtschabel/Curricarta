"""A document's placements read (plan M3a K; migration placement, app/domain/placements.py), as the Kern graph
states them and the editors see them: each with its time spans and workloads, those of one node in their
order; and named when the document is frozen (``name_placements``) - the IRIs a frozen graph states. Written
in app/db/placements.py."""

from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.db.counted_names import name_by_counter
from app.db.value_rows import values_of
from app.domain.l2 import HeldValues, Holder, Stated, Values
from app.domain.placements import PlacementRow

_PLACEMENTS = """
SELECT id, node_id, position, specification_id, variant_id, in_node_id, obligation_iri, grade_weight, iri,
    origin_iri, review_status_iri, rule_id, revision
FROM placement WHERE document_id = %s ORDER BY node_id, position
"""


async def placements_of(
    connection: psycopg.AsyncConnection, document_id: UUID, *, values: Values | None = None
) -> list[PlacementRow]:
    """The document's placements, by node and in each node's order, in one snapshot - of a read-only
    transaction of its own, or of the caller's; their time spans and workloads from ``values``, the document's
    values where the caller read them already in that snapshot (app/exports/kern_rows.py, app/db/tree.py), so
    they are read once."""
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        return await _read(connection, document_id, values)
    async with connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return await _read(connection, document_id, values)


async def name_placements(connection: psycopg.AsyncConnection, document_id: UUID, iri: str) -> int:
    """Give each placement of the document without an IRI its own, ``<iri>/placement-<n>`` under the
    document's IRI ``iri``, by the document's counter (app/db/counted_names.py); how many were named. Within
    the freeze."""
    return await name_by_counter(connection, "placement", document_id, iri)


async def _read(
    connection: psycopg.AsyncConnection, document_id: UUID, values: Values | None
) -> list[PlacementRow]:
    async with connection.cursor(row_factory=dict_row) as rows:
        await rows.execute(_PLACEMENTS, (document_id,))
        found = await rows.fetchall()
    if values is None:
        values = await values_of(connection, document_id)
    return [
        PlacementRow(
            id=row["id"],
            node_id=row["node_id"],
            position=row["position"],
            specification_id=row["specification_id"],
            variant_id=row["variant_id"],
            in_node_id=row["in_node_id"],
            obligation=row["obligation_iri"],
            grade_weight=row["grade_weight"],
            iri=row["iri"],
            stated=Stated(row["origin_iri"], row["review_status_iri"], row["rule_id"], row["revision"]),
            values=values.get(Holder("placement", row["id"]), HeldValues()),
        )
        for row in found
    ]
