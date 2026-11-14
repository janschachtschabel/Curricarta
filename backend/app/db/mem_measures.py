"""What the measurement of a MEM import reads (plan H-3, A10): the document's last import run done, its
findings by rule, and the wordings of its rows the import did not find - read, never printed: the report
counts them."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from app.db.runs import stage_iri

CV = "https://w3id.org/wlo/curriculum/vocab#"
_RUN = """
SELECT id, result, extract(epoch FROM finished_at - started_at)::float, finished_at FROM extraction_run
WHERE document_id = %s AND stage_iri = %s AND outcome = 'done' AND finished_at IS NOT NULL
ORDER BY finished_at DESC, id DESC LIMIT 1
"""
_FINDINGS = (
    "SELECT rule, count(*)::int FROM validation_finding WHERE document_id = %s GROUP BY rule ORDER BY rule"
)
# The rows of the import still as imported - a node's title, a statement not rejected, as the anchor
# sample takes them (app/db/measures.py) -, by their first anchor with a match kind: those not found
_NOT_FOUND = """
SELECT mem_iri, wording FROM (
    SELECT DISTINCT ON (coalesce(a.statement_id, a.node_id)) a.match_kind_iri,
        coalesce(s.mem_iri, n.mem_iri) AS mem_iri, coalesce(s.verbatim, n.original_title) AS wording
    FROM anchor a
    LEFT JOIN statement s ON s.id = a.statement_id
    LEFT JOIN node n ON n.id = a.node_id
    WHERE a.document_id = %(document)s AND coalesce(s.origin_iri, n.origin_iri) = %(imported)s
        AND s.review_status_iri IS DISTINCT FROM %(rejected)s AND a.match_kind_iri IS NOT NULL
    ORDER BY coalesce(a.statement_id, a.node_id), a.created_at, a.id
) first WHERE match_kind_iri = %(not_found)s AND wording IS NOT NULL
"""


@dataclass(frozen=True)
class ImportRun:
    id: UUID
    result: dict[str, Any]
    duration_s: float | None
    finished_at: datetime


async def import_run(connection: psycopg.AsyncConnection, document_id: UUID) -> ImportRun | None:
    """The document's last run of IM that ended done, where one did."""
    cursor = await connection.execute(_RUN, (document_id, stage_iri("IM")))
    found = await cursor.fetchone()
    return None if found is None else ImportRun(found[0], found[1] or {}, found[2], found[3])


async def findings_by_rule(connection: psycopg.AsyncConnection, document_id: UUID) -> dict[str, int]:
    cursor = await connection.execute(_FINDINGS, (document_id,))
    return {rule: count for rule, count in await cursor.fetchall()}


async def not_found_wordings(
    connection: psycopg.AsyncConnection, document_id: UUID
) -> list[tuple[str | None, str]]:
    """The MEM IRI (None where the row keeps none) and wording of each of the import's rows whose anchor
    stands ``notFound`` - those past the search's time among them, which the anchors do not tell apart."""
    values = {
        "document": document_id,
        "imported": CV + "orig_import",
        "rejected": CV + "rev_rejected",
        "not_found": CV + "match_notFound",
    }
    cursor = await connection.execute(_NOT_FOUND, values)
    return [(iri, wording) for iri, wording in await cursor.fetchall()]
