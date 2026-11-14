"""What the gold standard's report reads besides the judgements (plan H-3 §3.4): the statements found in a
judged block now, and what a document's entry says of it - counts, codes and notations alone."""

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

import psycopg

from app.db.runs import STAGE_PREFIX

CV = "https://w3id.org/wlo/curriculum/vocab#"
# The model's statements whose anchors name the block, each once, however reviewed since - the statement
# sample's population (app/db/measures.py); an editor's rewording makes one the editor's. Live: a replay
# since changes them without a new judgement
_FOUND = """
SELECT ab.block_id, count(DISTINCT s.id) FROM anchor a
JOIN anchor_block ab ON ab.anchor_id = a.id
JOIN statement s ON s.id = a.statement_id
WHERE a.document_id = %s AND ab.block_id = ANY (%s) AND s.origin_iri = %s
GROUP BY ab.block_id
"""
_DOCUMENT = """
SELECT d.regions, v.notation, c.pages FROM document d
JOIN conversion c ON c.id = d.conversion_id
LEFT JOIN vocab_concept v ON v.iri = d.sector_iri
WHERE d.id = %s
"""
# The last run of each stage that ended done
_RUNS = """
SELECT DISTINCT ON (stage_iri) stage_iri, model, prompt_version, lexicon_release FROM extraction_run
WHERE document_id = %s AND outcome = 'done'
ORDER BY stage_iri, started_at DESC, id DESC
"""


@dataclass(frozen=True)
class Run:
    model: str | None
    prompt: str | None
    lexicon_release: int | None


@dataclass(frozen=True)
class Head:
    regions: tuple[str, ...]
    sector: str | None  # the sector's notation
    pages: int | None
    runs: dict[str, Run]  # by stage notation (X4, IM)


async def found_in_blocks(
    connection: psycopg.AsyncConnection, document_id: UUID, blocks: Collection[str]
) -> dict[str, int]:
    """How many of the model's statements each block holds now, by their anchors; a block without any
    absent."""
    cursor = await connection.execute(_FOUND, (document_id, list(blocks), CV + "orig_model"))
    return {block: int(found) for block, found in await cursor.fetchall()}


async def head_of(connection: psycopg.AsyncConnection, document_id: UUID) -> Head:
    cursor = await connection.execute(_DOCUMENT, (document_id,))
    row = await cursor.fetchone()
    if row is None:
        raise LookupError(f"no document {document_id}")
    regions, sector, pages = row
    cursor = await connection.execute(_RUNS, (document_id,))
    runs = {
        stage.removeprefix(STAGE_PREFIX): Run(model, prompt, release)
        for stage, model, prompt, release in await cursor.fetchall()
    }
    return Head(tuple(regions), sector, pages, runs)
