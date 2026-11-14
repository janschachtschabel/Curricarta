"""What a judging sheet shows of the gold standard's items (plan H-3 §3.3): the rows they point at as the
document holds them now - a statement's or a node title's wording, its first anchor's quote and page, a
block's text. The sheet is the only reader: it holds wordings, and goes to the local folder alone."""

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

_FIRST_ANCHOR = (
    "(SELECT a.{column} FROM anchor a WHERE a.{owner} = {row}.id ORDER BY a.created_at, a.id LIMIT 1)"
)
_STATEMENTS = f"""
SELECT s.id, s.verbatim AS wording, s.lead_in, k.notation AS kind, s.node_id AS under,
    {_FIRST_ANCHOR.format(column="quote", owner="statement_id", row="s")} AS quote,
    {_FIRST_ANCHOR.format(column="page_start", owner="statement_id", row="s")} AS page
FROM statement s JOIN vocab_concept k ON k.iri = s.statement_kind_iri
WHERE s.document_id = %s AND s.id = ANY (%s)
"""  # noqa: S608 - fixed parts
_NODES = f"""
SELECT n.id, n.original_title AS wording, NULL AS lead_in, f.notation AS kind, n.parent_id AS under,
    {_FIRST_ANCHOR.format(column="quote", owner="node_id", row="n")} AS quote,
    {_FIRST_ANCHOR.format(column="page_start", owner="node_id", row="n")} AS page
FROM node n JOIN vocab_concept f ON f.iri = n.function_iri
WHERE n.document_id = %s AND n.id = ANY (%s)
"""  # noqa: S608 - fixed parts
_TREE = "SELECT id, parent_id, code, original_title FROM node WHERE document_id = %s"
_BLOCKS = """
SELECT block_id, page, kind, text FROM document_block WHERE conversion_id = %s AND block_id = ANY (%s)
"""


@dataclass(frozen=True)
class Shown:
    """A statement or node as it stands: its wording, kind, the node it lies under, its first anchor's."""

    wording: str | None
    lead_in: str | None
    kind: str
    under: UUID | None  # a statement's node, a node's parent
    quote: str | None
    page: int | None


@dataclass(frozen=True)
class ShownBlock:
    page: int
    kind: str
    text: str


async def statements_shown(
    connection: psycopg.AsyncConnection, document_id: UUID, ids: Collection[UUID]
) -> dict[UUID, Shown]:
    return await _shown(connection, _STATEMENTS, document_id, ids)


async def nodes_shown(
    connection: psycopg.AsyncConnection, document_id: UUID, ids: Collection[UUID]
) -> dict[UUID, Shown]:
    return await _shown(connection, _NODES, document_id, ids)


async def _shown(
    connection: psycopg.AsyncConnection, query: str, document_id: UUID, ids: Collection[UUID]
) -> dict[UUID, Shown]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(query, (document_id, list(ids)))
        rows = await cursor.fetchall()
    return {row.pop("id"): Shown(**row) for row in rows}


async def node_names(
    connection: psycopg.AsyncConnection, document_id: UUID
) -> dict[UUID, tuple[UUID | None, str]]:
    """Each node of the document by id: its parent and how a path names it - its title, else its code."""
    cursor = await connection.execute(_TREE, (document_id,))
    return {node: (parent, title or code or "") for node, parent, code, title in await cursor.fetchall()}


async def blocks_shown(
    connection: psycopg.AsyncConnection, conversion_id: UUID, ids: Collection[str]
) -> dict[str, ShownBlock]:
    cursor = await connection.execute(_BLOCKS, (conversion_id, list(ids)))
    return {block: ShownBlock(page, kind, text) for block, page, kind, text in await cursor.fetchall()}
