"""A MEM import read for its export (plan M2-6; app/exports/mem_ttl.py): the document with the plan it
names - its IRI, Land, class, subjects, school types, licence and attribution as the import recorded them -,
its nodes and statements with their own IRIs, origins and what MEM said of them, a rejected statement left
out; rows as the tables hold them, read in one snapshot.

No visibility check: the route that exports for a reader checks what that reader sees first.
"""

from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.db.documents import DocumentError
from app.exports.kern_rows import Row, in_one_snapshot

_DOCUMENT = """
SELECT id, iri, title, rights_status, frozen_at, mem_iri, mem_land_iri, mem_class_iri, mem_subjects,
    mem_school_types, mem_licence, mem_attribution
FROM document WHERE id = %(document)s
"""
_NODES = """
SELECT id, parent_id, position, iri, origin_iri, review_status_iri, function_iri, node_type_iri,
    original_title, title_language, code, mem_iri, mem_classes, mem_properties
FROM node WHERE document_id = %(document)s ORDER BY parent_id NULLS FIRST, position
"""
_STATEMENTS = """
SELECT id, node_id, position, iri, origin_iri, verbatim, language, statement_kind_iri, subkind_iri, mem_iri,
    mem_classes, mem_properties
FROM statement
WHERE document_id = %(document)s AND review_status_iri <> 'https://w3id.org/wlo/curriculum/vocab#rev_rejected'
ORDER BY node_id, position
"""


@dataclass(frozen=True)
class MemRows:
    document: Row
    nodes: list[Row]
    statements: list[Row]


async def read_mem_document(connection: psycopg.AsyncConnection, document_id: UUID) -> MemRows:
    """The document's rows for its MEM export, in one snapshot (kern_rows.in_one_snapshot). DocumentError
    where there is none."""
    return await in_one_snapshot(connection, lambda reading: _read(reading, document_id))


async def _read(connection: psycopg.AsyncConnection, document_id: UUID) -> MemRows:
    params = {"document": document_id}
    async with connection.cursor(row_factory=dict_row) as rows:
        await rows.execute(_DOCUMENT, params)
        document = await rows.fetchone()
        if document is None:
            raise DocumentError(f"no document {document_id}")
        await rows.execute(_NODES, params)
        nodes = await rows.fetchall()
        await rows.execute(_STATEMENTS, params)
        statements = await rows.fetchall()
    return MemRows(document, nodes, statements)
