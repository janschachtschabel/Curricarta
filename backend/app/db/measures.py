"""The populations the gold standard's samples are drawn from (plan H-3 §3.2), each unit as an item to be
judged - by its stratum, and what names it beyond its row: the hash of its wording and its first block.

A unit's first block is the first of its anchors' blocks in reading order, None where they name none (an
editor's or the import's notFound)."""

from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.db.gold import ItemDraft
from app.domain.wording import text_hash

CV = "https://w3id.org/wlo/curriculum/vocab#"
_FIRST_BLOCK = """
    SELECT ab.block_id FROM anchor_block ab
    JOIN document_block b ON b.conversion_id = ab.conversion_id AND b.block_id = ab.block_id
    WHERE ab.anchor_id = ANY ({anchors}) ORDER BY b.seq LIMIT 1
"""
# The model's statements, however reviewed since (a review keeps the origin, an edit makes it orig_human);
# their stratum the notation of their kind
_OF_STATEMENT = "ARRAY(SELECT a.id FROM anchor a WHERE a.statement_id = s.id)"
_STATEMENTS = f"""
SELECT s.id, k.notation AS stratum, s.text_hash, ({_FIRST_BLOCK.format(anchors=_OF_STATEMENT)}) AS first_block
FROM statement s
JOIN vocab_concept k ON k.iri = s.statement_kind_iri
WHERE s.document_id = %(document)s AND s.origin_iri = %(model)s
ORDER BY s.id
"""  # noqa: S608 - fixed parts
# The rows of an import still as imported, with a match kind - a node's title, a statement not rejected;
# their stratum how they were found and of what. One anchor each: its first
_IMPORTED = f"""
SELECT DISTINCT ON (coalesce(a.statement_id, a.node_id)) a.statement_id, a.node_id, m.notation AS found,
    s.text_hash, n.original_title, ({_FIRST_BLOCK.format(anchors="ARRAY[a.id]")}) AS first_block
FROM anchor a
JOIN vocab_concept m ON m.iri = a.match_kind_iri
LEFT JOIN statement s ON s.id = a.statement_id
LEFT JOIN node n ON n.id = a.node_id
WHERE a.document_id = %(document)s AND coalesce(s.origin_iri, n.origin_iri) = %(imported)s
    AND s.review_status_iri IS DISTINCT FROM %(rejected)s
ORDER BY coalesce(a.statement_id, a.node_id), a.created_at, a.id
"""  # noqa: S608 - fixed parts
_TITLE_BLOCKS = """
SELECT DISTINCT ab.block_id FROM anchor a JOIN anchor_block ab ON ab.anchor_id = a.id
WHERE a.document_id = %s AND a.node_id IS NOT NULL
"""


async def model_statements(connection: psycopg.AsyncConnection, document_id: UUID) -> list[ItemDraft]:
    """The statements of the document the model wrote, confirmed and rejected ones too, by id: an editor's
    rewording makes a statement the editor's."""
    values = {"document": document_id, "model": CV + "orig_model"}
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_STATEMENTS, values)
        rows = await cursor.fetchall()
    return [
        ItemDraft(
            stratum=row["stratum"],
            statement_id=row["id"],
            text_hash=row["text_hash"],
            first_block=row["first_block"],
        )
        for row in rows
    ]


async def imported_anchors(connection: psycopg.AsyncConnection, document_id: UUID) -> list[ItemDraft]:
    """The anchored rows of the document's import, by id: stratum ``<match kind>:node`` or ``:statement``."""
    values = {"document": document_id, "imported": CV + "orig_import", "rejected": CV + "rev_rejected"}
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_IMPORTED, values)
        rows = await cursor.fetchall()
    found: list[ItemDraft] = []
    for row in rows:
        node = row["statement_id"] is None
        title = row["original_title"]
        found.append(
            ItemDraft(
                stratum=f"{row['found']}:{'node' if node else 'statement'}",
                statement_id=row["statement_id"],
                node_id=row["node_id"],
                text_hash=(text_hash(title) if title is not None else None) if node else row["text_hash"],
                first_block=row["first_block"],
            )
        )
    return found


async def title_blocks(connection: psycopg.AsyncConnection, document_id: UUID) -> set[str]:
    """The blocks the anchors of the document's nodes name: their headings."""
    cursor = await connection.execute(_TITLE_BLOCKS, (document_id,))
    return {block for (block,) in await cursor.fetchall()}


async def conversion_pages(connection: psycopg.AsyncConnection, conversion_id: UUID) -> int | None:
    """How many pages the conversion counted, where it holds a count."""
    cursor = await connection.execute("SELECT pages FROM conversion WHERE id = %s", (conversion_id,))
    found = await cursor.fetchone()
    return None if found is None else found[0]
