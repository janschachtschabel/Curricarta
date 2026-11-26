"""A document frozen (plan M1 9.6; Paket 9b H5, H6): it gets its IRIs and changes no more - the database's
triggers keep its rows as they are (migration freeze).

Under the tree's lock, in this order, each refused with its own reason and nothing changed: frozen already
(DocumentFrozen), beside its open job (JobOpen), its tree not all there (NotExtracted: X4 has not read every
package, and it is no draft copy), short of its work, the work's country or short title, its issuer or
edition, or one with nothing to name the IRI by (``incomplete``), no base to name it under (``no_iri_base``),
X5 not done on it (a draft copy runs none until its check job), owing it a check or an anchor X5 has not
checked (``check_owed``), violations among its findings the editors have not accepted (``has_violations``).
Then the work gets its IRI where it has none, the document its own - the work's country, issuer, the work's
short title, edition (app/domain/iris.py) - where it has none, its specifications, variants, nodes and
statements theirs, its rules theirs - numbered on past every number its revisions gave (``document.serials``,
and what they hold) - (app/domain/naming.py), its assessments by the document's counter
(app/db/assessment_rows.py); an IRI another work or document holds, committed before or while
this one waited, refuses (``iri_taken``). The document is frozen last: after that, the triggers refuse every
change. A freeze shares the lock python -m app.db.name_frozen holds alone (``NAMING_LOCK``): what one
revision names by key, the other reads.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg import errors

from app.db.anchors import unchecked_anchors
from app.db.assessment_rows import name_assessments
from app.db.documents import DocumentError
from app.db.editing import CV, DocumentFrozen, JobOpen, NotExtracted, extracted, frozen
from app.db.nodes import lock_tree
from app.db.runs import done_stages, x5_owed
from app.domain.iris import document_iri, slug, work_iri
from app.domain.naming import (
    GivenByKey,
    Named,
    NodeRow,
    RuleRow,
    SpecificationRow,
    StatementRow,
    VariantRow,
    name_rows,
)
from app.jobs.queue import open_job
from app.pipeline.extraction import unique_key
from app.pipeline.x4_unit import UNIT_WITHOUT_NODE

_DOCUMENT = """
SELECT d.iri, d.revision, d.issuer, d.edition, d.work_id, w.iri, w.region, w.short_title
FROM document d LEFT JOIN work w ON w.id = d.work_id WHERE d.id = %s
"""
_NODES = """
SELECT id, parent_id, position, code, code_assigned, iri, statement_serial FROM node WHERE document_id = %s
"""
_STATEMENTS = """
SELECT id, node_id, position, iri, review_status_iri = %s FROM statement WHERE document_id = %s
"""
# a node IRI a revision gave may come back under a node made anew: its statements count on past it
_SERVED = """
SELECT n.iri, max(n.statement_serial) FROM node n JOIN document d ON d.id = n.document_id
WHERE d.iri = %s AND n.iri IS NOT NULL GROUP BY n.iri
"""
_SPECIFICATIONS = "SELECT id, key, iri FROM specification WHERE document_id = %s"
_VARIANTS = """
SELECT v.id, v.specification_id, v.key, v.iri FROM variant v JOIN specification s ON s.id = v.specification_id
WHERE s.document_id = %s
"""
# what a key named in the revisions of the document, the latest revision's where two differ
_GIVEN_SPECIFICATIONS = """
SELECT DISTINCT ON (s.key) s.key, s.iri FROM specification s JOIN document d ON d.id = s.document_id
WHERE d.iri = %s AND s.iri IS NOT NULL ORDER BY s.key, d.revision DESC
"""
_GIVEN_VARIANTS = """
SELECT DISTINCT ON (s.key, v.key) s.key, v.key, v.iri FROM variant v
JOIN specification s ON s.id = v.specification_id JOIN document d ON d.id = s.document_id
WHERE d.iri = %s AND v.iri IS NOT NULL ORDER BY s.key, v.key, d.revision DESC
"""
# a document's rules in their order (plan M3a I), each with the IRI of the rule it corresponds to in the
# revision it copies or in a copy of it - the same place and time it was made, as a copy keeps them, whatever
# an editor changed of its values there: a rule made anew in the copy corresponds to none -; and the highest
# rule number given: by the document's counter and by the IRIs its revisions hold - a revision frozen before
# migration 0038 named its rules later
_RULES = """
SELECT f.id, f.iri, f.review_status_iri = %(rejected)s,
    (SELECT c.iri FROM frame_part c JOIN document cd ON cd.id = c.document_id
     WHERE (cd.id = d.copy_of OR cd.copy_of = d.id) AND c.part_kind = 'rules' AND c.iri IS NOT NULL
         AND c.position = f.position AND c.created_at = f.created_at
     ORDER BY cd.revision LIMIT 1)
FROM frame_part f JOIN document d ON d.id = f.document_id
WHERE f.document_id = %(document)s AND f.part_kind = 'rules'
ORDER BY f.position
"""
_RULE_SERIAL = """
SELECT greatest(
    (SELECT (serials ->> 'rule')::integer FROM document WHERE id = %(document)s),
    (SELECT max(substring(f.iri FROM '/rule-([0-9]+)$')::integer) FROM frame_part f
     JOIN document d ON d.id = f.document_id WHERE d.iri = %(iri)s),
    0)
"""
_VIOLATIONS = "SELECT count(*) FROM validation_finding WHERE document_id = %s AND severity = 'violation'"


NAMING_LOCK = 0x6B6B_612D_6E61_6D65  # "curricarta-name": shared by each freeze, held alone by name_frozen

FreezeCode = Literal["incomplete", "no_iri_base", "check_owed", "has_violations", "iri_taken"]


class FreezeRefused(Exception):
    """The document is not frozen: ``code`` says why, ``details`` what of it."""

    def __init__(self, code: FreezeCode, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code: FreezeCode = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class Frozen:
    iri: str  # the document's
    revision: int
    nodes: int  # named now
    statements: int
    specifications: int
    variants: int
    violations: int  # the editors accepted


async def freeze(
    connection: psycopg.AsyncConnection, document_id: UUID, base: str | None, *, accept_violations: bool
) -> Frozen:
    """Freeze the document under ``base`` (IRI_BASE) as above; DocumentError for none."""
    async with connection.transaction():
        await lock_tree(connection, document_id)
        await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (NAMING_LOCK,))
        if await frozen(connection, document_id):
            raise DocumentFrozen(f"the document {document_id} is frozen")
        if (job := await open_job(connection, unique_key(document_id))) is not None:
            raise JobOpen(job)
        if not await extracted(connection, document_id):
            raise NotExtracted(f"X4 has not read every package of the document {document_id}")
        cursor = await connection.execute(_DOCUMENT, (document_id,))
        row = await cursor.fetchone()
        if row is None:
            raise DocumentError(f"no document {document_id}")
        iri, revision, issuer, edition, work_id, work, region, short_title = row
        missing = [name for name, lacking in (
            ("work", work_id is None), ("region", work_id is not None and region is None),
            ("short_title", work_id is not None and short_title is None),
            ("issuer", not _names(issuer)), ("edition", not _names(edition)),
        ) if lacking]  # fmt: skip
        if missing:
            raise FreezeRefused("incomplete", f"the document lacks {missing}", {"missing": missing})
        if base is None:
            raise FreezeRefused("no_iri_base", "the service names no IRI base (IRI_BASE)")
        unchecked = len(await unchecked_anchors(connection, document_id, rule_titles=(UNIT_WITHOUT_NODE,)))
        never = "X5" not in await done_stages(connection, document_id)
        if unchecked or never or await x5_owed(connection, document_id):
            raise FreezeRefused("check_owed", "X5 owes the document a check", {"unchecked": unchecked})
        cursor = await connection.execute(_VIOLATIONS, (document_id,))
        violations = int((await cursor.fetchone() or (0,))[0])
        if violations and not accept_violations:
            raise FreezeRefused("has_violations", "violations not accepted", {"violations": violations})
        if work is None:
            work = work_iri(base, region, short_title)
            await _give(connection, "UPDATE work SET iri = %s WHERE id = %s", work, work_id)
        if iri is None:
            iri = document_iri(base, region, issuer, short_title, edition)
        named = await name_document(connection, document_id, iri)
        await write_names(connection, named)
        for name, serial in named.document_serials.items():
            await connection.execute(
                "UPDATE document SET serials = jsonb_set(serials, %s, to_jsonb(%s::integer)) WHERE id = %s",
                ([name], serial, document_id),
            )
        await name_assessments(connection, document_id, iri)  # <document>/assessment-<n> (plan M3a J)
        frozen_now = "UPDATE document SET iri = %s, frozen_at = now(), updated_at = now() WHERE id = %s"
        await _give(connection, frozen_now, iri, document_id)
        counts = (len(named.nodes), len(named.statements), len(named.specifications), len(named.variants))
        return Frozen(iri, revision, *counts, violations)


def _names(text: str | None) -> bool:
    """Whether ``text`` names a part of the document's IRI: a Greek letter or a bullet names none."""
    if text is None:
        return False
    try:
        slug(text)
    except ValueError:
        return False
    return True


async def _give(connection: psycopg.AsyncConnection, query: str, iri: str, row: UUID) -> None:
    """Give the row ``iri`` by ``query``; an IRI another work or document holds - committed before, or
    while this one waited for the unique key - refuses, and the refusal takes back all the freeze wrote."""
    try:
        await connection.execute(query, (iri, row))
    except errors.UniqueViolation as taken:
        raise FreezeRefused("iri_taken", f"the IRI {iri} is another's", {"iri": iri}) from taken


async def name_document(connection: psycopg.AsyncConnection, document_id: UUID, iri: str) -> Named:
    """The IRIs the document's rows lack under its IRI ``iri``, past what its revisions gave; none written."""
    cursor = await connection.execute(_NODES, (document_id,))
    nodes = [NodeRow(*found) for found in await cursor.fetchall()]
    cursor = await connection.execute(_STATEMENTS, (CV + "rev_rejected", document_id))
    statements = [StatementRow(*found) for found in await cursor.fetchall()]
    cursor = await connection.execute(_SPECIFICATIONS, (document_id,))
    specifications = [SpecificationRow(*found) for found in await cursor.fetchall()]
    cursor = await connection.execute(_VARIANTS, (document_id,))
    variants = [VariantRow(*found) for found in await cursor.fetchall()]
    cursor = await connection.execute(_SERVED, (iri,))
    served: dict[str, int] = dict(await cursor.fetchall())
    cursor = await connection.execute(_GIVEN_SPECIFICATIONS, (iri,))
    given_specifications: dict[str, str] = dict(await cursor.fetchall())
    cursor = await connection.execute(_GIVEN_VARIANTS, (iri,))
    given_variants = {(specification, key): given for specification, key, given in await cursor.fetchall()}
    cursor = await connection.execute(_RULES, {"rejected": CV + "rev_rejected", "document": document_id})
    rules = [RuleRow(*found) for found in await cursor.fetchall()]
    cursor = await connection.execute(_RULE_SERIAL, {"document": document_id, "iri": iri})
    rule_serial = int((await cursor.fetchone() or (0,))[0])
    return name_rows(
        iri, nodes, statements, served, specifications=specifications, variants=variants,
        given=GivenByKey(given_specifications, given_variants), rules=rules, rule_serial=rule_serial,
    )  # fmt: skip


async def write_names(connection: psycopg.AsyncConnection, named: Named) -> None:
    """Give the rows the IRIs ``named`` holds, and the nodes the statement numbers they grew to."""
    async with connection.cursor() as writing:
        for query, given in (
            ("UPDATE specification SET iri = %s WHERE id = %s", named.specifications),
            ("UPDATE variant SET iri = %s WHERE id = %s", named.variants),
            ("UPDATE node SET iri = %s WHERE id = %s", named.nodes),
            ("UPDATE node SET statement_serial = %s WHERE id = %s", named.serials),
            ("UPDATE statement SET iri = %s WHERE id = %s", named.statements),
            ("UPDATE frame_part SET iri = %s WHERE id = %s", named.rules),
        ):
            await writing.executemany(query, [(value, row) for row, value in given.items()])
