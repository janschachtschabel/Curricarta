"""A frozen document's draft copy (plan M1 9.6; Paket 9b H7): the next revision of the same edition, under
its IRI, to change what the frozen one may not.

It is a document of its own - the same source, conversion, owner, work, metadata, the edition it supersedes
and the counters of its names, the revision one up,
its own draft IRI, ``copy_of`` the revision it copies - with every row the frozen one holds under ids of
its own: specifications and their variants, frame parts, nodes (``applies_to`` and their parents
followed), statements, addressees, anchors (their owner followed) and their blocks, the profile, the values
- workloads, time spans, levels, applicability contexts - at their holders (followed as an anchor's owner),
the links of rules (their rule and target followed),
the assessments with what they assess (plan M3a J). IRIs,
origins, review statuses, revisions, positions and found anchors are taken along as they are; no run is
(``run_id`` none: the runs and their findings are the frozen revision's), so X5 owes the copy a check.
Of the latest revision of an IRI alone (``not_latest``), not of a draft (``not_frozen``), and one draft at
most is open under an IRI (``draft_open``, also the database's index). The copy's rows are written now, so
the database checks them against today's vocabularies: a row a later load no longer takes - a node type
taken from under its function - refuses the copy (``vocabulary_changed``, ``details.check`` the check).
"""

import re
from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

import psycopg

from app.core.ids import new_id
from app.db.anchors import new_entity
from app.db.documents import DocumentError
from app.db.draft_copy_rows import ENTITIES, ROWS

CopyCode = Literal["not_frozen", "not_latest", "draft_open", "vocabulary_changed"]
# where a check is a trigger's (migrations l1_documents, l1_nodes), the error names its function alone
_TRIGGER = re.compile(r"PL/pgSQL function (\w+)\(")
_DOCUMENT = """
INSERT INTO document (id, source_id, conversion_id, owner_id, work_id, draft_iri, iri, edition, issuer,
    revision, title, document_type_iri, sector_scheme, sector_iri, regions, legal_form_scheme,
    legal_form_iri, binding_scheme, binding_iri, lifecycle_scheme, lifecycle_iri, valid_from, valid_until,
    issued, rights_status, edited_at, copy_of, mem_iri, mem_subjects, mem_school_types, mem_licence,
    mem_attribution, mem_land_iri, mem_class_iri, supersedes_id, serials)
SELECT %(new)s, source_id, conversion_id, owner_id, work_id, %(draft)s, iri, edition, issuer,
    revision + 1, title, document_type_iri, sector_scheme, sector_iri, regions, legal_form_scheme,
    legal_form_iri, binding_scheme, binding_iri, lifecycle_scheme, lifecycle_iri, valid_from, valid_until,
    issued, rights_status, now(), id, mem_iri, mem_subjects, mem_school_types, mem_licence,
    mem_attribution, mem_land_iri, mem_class_iri, supersedes_id, serials
FROM document WHERE id = %(old)s
"""


class CopyRefused(Exception):
    """No draft copy is made: ``code`` says why, ``details`` what of it."""

    def __init__(self, code: CopyCode, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code: CopyCode = code
        self.details = dict(details or {})


async def copy_document(connection: psycopg.AsyncConnection, document_id: UUID) -> UUID:
    """The draft copy of the frozen document ``document_id``, made as above; its id. CopyRefused, or
    DocumentError for no such document, and then nothing is made."""
    async with connection.transaction():
        cursor = await connection.execute(
            "SELECT iri, revision, frozen_at IS NOT NULL FROM document WHERE id = %s", (document_id,)
        )
        found = await cursor.fetchone()
        if found is None:
            raise DocumentError(f"no document {document_id}")
        iri, revision, frozen = found
        if not frozen:
            raise CopyRefused("not_frozen", f"the document {document_id} is a draft: change it as it is")
        cursor = await connection.execute(
            "SELECT id, frozen_at IS NULL FROM document WHERE iri = %s AND revision > %s"
            " ORDER BY revision DESC",
            (iri, revision),
        )
        later = await cursor.fetchall()
        drafts = [str(row[0]) for row in later if row[1]]
        if drafts:
            raise CopyRefused("draft_open", "a draft of the IRI is open", {"document_id": drafts[0]})
        if later:
            raise CopyRefused("not_latest", f"a later revision of {iri} is frozen: copy that one")
        copy = await new_entity(connection, "document")
        try:
            await _write(connection, copy, document_id, iri)
        except psycopg.errors.CheckViolation as changed:
            check = changed.diag.constraint_name
            if check is None and (trigger := _TRIGGER.search(changed.diag.context or "")) is not None:
                check = trigger.group(1)
            raise CopyRefused(
                "vocabulary_changed",
                "a row of the document no longer fits the vocabularies",
                {"check": check},
            ) from changed
        return copy


async def _write(connection: psycopg.AsyncConnection, copy: UUID, document_id: UUID, iri: str) -> None:
    """The copy's document row, then every other row under its new id."""
    try:
        async with connection.transaction():
            await connection.execute(_DOCUMENT, {"new": copy, "draft": copy.urn, "old": document_id})
    except psycopg.errors.UniqueViolation as raced:  # another copy, made meanwhile (document_one_draft)
        cursor = await connection.execute(
            "SELECT id FROM document WHERE iri = %s AND frozen_at IS NULL", (iri,)
        )
        other = await cursor.fetchone()
        details = {} if other is None else {"document_id": str(other[0])}
        raise CopyRefused("draft_open", "a draft of the IRI is open", details) from raced
    await _map(connection, document_id)
    for query in ROWS:
        await connection.execute(query, {"new": copy, "old": document_id})


async def _map(connection: psycopg.AsyncConnection, document_id: UUID) -> None:
    """The ids of the copied document's entities, each with a new one, in ``copied`` for the transaction."""
    await connection.execute(
        "CREATE TEMPORARY TABLE copied (old uuid PRIMARY KEY, new uuid NOT NULL) ON COMMIT DROP"
    )
    async with connection.cursor() as cursor:
        for kind, query in ENTITIES.items():
            await cursor.execute(query, {"old": document_id})
            rows = [(old, new_id(), kind) for (old,) in await cursor.fetchall()]
            await cursor.executemany(
                "INSERT INTO entity (id, kind) VALUES (%s, %s)", [(new, made) for _, new, made in rows]
            )
            await cursor.executemany(
                "INSERT INTO copied (old, new) VALUES (%s, %s)", [(old, new) for old, new, _ in rows]
            )
