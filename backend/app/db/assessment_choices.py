"""What an assessment of a document may be (plan M3a J; app/db/assessments.py checks it): a part of one of the
document's specifications, by key, or of its nodes, from the top, each after its parent - beside its
assessments -, assessing those nodes; of a kind the list offers, the active concepts of cv:AssessmentKinds
by their labels.
"""

from typing import Final
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.domain.assessments import Choice
from app.vocab.lookup import ConceptDetails, concept_details

KINDS: Final = "https://w3id.org/wlo/curriculum/vocab#AssessmentKinds"
_KINDS = """
SELECT c.iri FROM vocab_concept c JOIN vocab_scheme s ON s.iri = c.scheme_iri
WHERE c.scheme_iri = %s AND c.retired_in IS NULL AND s.retired_in IS NULL
"""
_SPECIFICATIONS = "SELECT id, title AS label FROM specification WHERE document_id = %(document)s ORDER BY key"
# the nodes from the top, each after its parent, siblings in their order
_NODES = """
WITH RECURSIVE down (id, label, place) AS (
    SELECT id, nullif(concat_ws(' ', code, original_title), ''), ARRAY[position]
    FROM node WHERE document_id = %(document)s AND parent_id IS NULL
    UNION ALL SELECT n.id, nullif(concat_ws(' ', n.code, n.original_title), ''), d.place || n.position
    FROM node n JOIN down d ON n.document_id = %(document)s AND n.parent_id = d.id
)
SELECT id, label FROM down ORDER BY place
"""


async def choices_of(connection: psycopg.AsyncConnection, document_id: UUID) -> list[Choice]:
    """What an assessment of the document may be a part of or assess beside its assessments: its
    specifications by key, then its nodes from the top, each after its parent."""
    params = {"document": document_id}
    async with connection.cursor(row_factory=dict_row) as rows:
        await rows.execute(_SPECIFICATIONS, params)
        specifications = await rows.fetchall()
        await rows.execute(_NODES, params)
        nodes = await rows.fetchall()
    return [Choice("specification", row["id"], row["label"]) for row in specifications] + [
        Choice("node", row["id"], row["label"]) for row in nodes
    ]


async def kinds_of(connection: psycopg.AsyncConnection) -> list[ConceptDetails]:
    """The kinds an assessment may be of: the active concepts of cv:AssessmentKinds, by their labels."""
    cursor = await connection.execute(_KINDS, (KINDS,))
    details = await concept_details(connection, [iri for (iri,) in await cursor.fetchall()])
    return sorted(details.values(), key=lambda kind: kind.label.casefold())
