"""A node dropped by an editor (plan M1 9.3; Paket 9 G6): with its subtree - its children, statements and the
anchors of all -, the placements of other nodes at them (plan M3a K), whose nodes count their revisions one up
(app/db/placement_cascade.py), and the findings on all of it. As every change of the tree (app/db/editing.py):
under the tree's lock, on the node's revision, and noting the document edited.
"""

from dataclasses import dataclass
from uuid import UUID

import psycopg

from app.db.editing import (
    DOCUMENT_OF_NODE,
    NODE,
    check_revision,
    drop_findings,
    guard,
    mark_edited,
    row_of,
    target_of,
)
from app.db.findings import drop_value_findings
from app.db.placement_cascade import count_placed_at
from app.db.source_queries import Reader

# Each access names the document, so each goes by an index: the children by (document_id, parent_id), the
# anchors by node and by statement apart - one OR of the two read the whole table (audit 2026-11-14)
_SUBTREE = """
WITH RECURSIVE under (id) AS (
    SELECT id FROM node WHERE id = %(id)s
    UNION ALL SELECT n.id FROM node n JOIN under u ON n.document_id = %(document)s AND n.parent_id = u.id
), said AS (
    SELECT s.id FROM statement s JOIN under u ON s.document_id = %(document)s AND s.node_id = u.id
)
SELECT array(SELECT id FROM under), array(SELECT id FROM said),
    array(SELECT a.id FROM anchor a JOIN under u ON a.document_id = %(document)s AND a.node_id = u.id
          UNION
          SELECT a.id FROM anchor a JOIN said s ON a.document_id = %(document)s AND a.statement_id = s.id)
"""


@dataclass(frozen=True)
class Dropped:
    nodes: int  # the node and its subtree's
    statements: int


async def drop_node(
    connection: psycopg.AsyncConnection, reader: Reader, node_id: UUID, revision: int
) -> Dropped | None:
    """Take the node away with its subtree - its children, statements and the anchors of all, the placements
    of other nodes at them, whose nodes count their revisions one up (app/db/placement_cascade.py) - and the
    findings on them; what went. None where ``reader`` sees no such node. StaleRevision or a refusal of
    ``guard``, and then nothing goes."""
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT_OF_NODE, reader, node_id)
        if target is None:
            return None
        await guard(connection, target.document_id)
        row = await row_of(connection, NODE, node_id)
        if row is None:
            return None
        check_revision(row, revision)
        cursor = await connection.execute(_SUBTREE, {"id": node_id, "document": target.document_id})
        found = await cursor.fetchone()
        assert found is not None  # noqa: S101 - arrays of a node that stands
        nodes, statements, anchors = found
        await drop_findings(connection, target.document_id, [*nodes, *statements, *anchors])
        await drop_value_findings(connection, target.document_id, nodes=nodes, statements=statements)
        # the placements of other nodes at one of these go with them (plan M3a K): those nodes count on
        await count_placed_at(connection, target.document_id, nodes)
        await connection.execute("DELETE FROM node WHERE id = %s", (node_id,))
        await mark_edited(connection, target.document_id)
        return Dropped(nodes=len(nodes), statements=len(statements))
