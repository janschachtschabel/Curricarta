"""What taking nodes away does to the placements of other nodes (plan M3a K; migration placement): a placement
at one of them goes with it (cur:inNode, ON DELETE CASCADE), and the node it placed counts its revision one up
- the token of a set of its placements - so a view of it read before is stale, not one with a placement gone.
Called by app/db/node_drop.py ``drop_node``, under the tree's lock, before the nodes go."""

from collections.abc import Sequence
from uuid import UUID

import psycopg

_PLACED_AT = """
UPDATE node SET revision = revision + 1 WHERE id IN (
    SELECT p.node_id FROM placement p WHERE p.document_id = %(document)s AND p.in_node_id = ANY(%(nodes)s)
        AND NOT p.node_id = ANY(%(nodes)s)
)
"""


async def count_placed_at(
    connection: psycopg.AsyncConnection, document_id: UUID, nodes: Sequence[UUID]
) -> None:
    """Count one up the revision of each node of the document placed at one of ``nodes`` but among them."""
    await connection.execute(_PLACED_AT, {"document": document_id, "nodes": list(nodes)})
