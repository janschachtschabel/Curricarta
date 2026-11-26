"""A document of the first layer read for its Kern RDF (plan M1 8.3; app/exports/kern_rdf.py): the document -
with the count of violations among its findings, those the editors accepted once it is frozen (plan M3a C1),
the version of the graph its last check ran under (``checked_graph``) and where it came from -, the work it
is a version of and the file it was read off (plan M3a A1), its specifications - with what X1 read of
their applicability (plan M3a H1) - and their variants, its nodes and statements, the anchors of nodes and
statements with their blocks - rows as the tables hold them, each with the IRI it is named by once frozen
(app/exports/kern_naming.py) - and the values of its
holders (app/db/value_rows.py, plan M3a F1), the specifications' applicability contexts and the
document's assessments (app/db/assessment_rows.py, plan M3a J) and the nodes' placements
(app/db/placement_rows.py, plan M3a K), read in one snapshot; its rules with their
anchors as the graph states them (plan M3a I, app/db/rule_rows.py). A rejected statement is not read, nor
are its anchors and values; a rejected value is left out - a workload with its periods, a context with its
values -, and a rejected node's values follow their own status.

No visibility check: the export serves the pipeline (X5's SHACL check) of a document it already holds;
a route that exports for a reader checks what that reader sees first.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.db.assessment_rows import assessments_of
from app.db.documents import DocumentError
from app.db.placement_rows import placements_of
from app.db.rule_rows import Rule, rules_of
from app.db.value_rows import values_of
from app.domain.assessments import AssessmentRow
from app.domain.l2 import Context, HeldValues, Level, TimeSpan, Values, Workload
from app.domain.placements import PlacementRow
from app.vocab.lookup import REGIONS

Row = dict[str, Any]
_SNAPSHOTS = ("repeatable read", "serializable")  # the isolation levels whose queries share one snapshot
_REJECTED = "https://w3id.org/wlo/curriculum/vocab#rev_rejected"

_DOCUMENT = """
SELECT d.id, d.iri, d.revision, d.frozen_at, d.rights_status, d.title, d.issuer, d.edition,
    d.document_type_iri, d.sector_iri, d.legal_form_iri, d.binding_iri, d.lifecycle_iri, d.valid_from,
    d.valid_until, d.issued,
    (SELECT s.iri FROM document s WHERE s.id = d.supersedes_id) AS supersedes_iri,  -- frozen: it has one
    -- where it came from: its register entry's address, an import's MEM plan, attribution and licence
    (SELECT s.url FROM source s WHERE s.id = d.source_id) AS source_url, d.mem_iri, d.mem_attribution,
    d.mem_licence,
    -- the violations among its findings: those the editors accepted, once it is frozen (app/db/freezing.py)
    (SELECT count(*) FROM validation_finding f WHERE f.document_id = d.id AND f.severity = 'violation')
        AS violations,
    -- the version of the graph its last check (X5) ran under (migration 0036): none where it recorded none
    (SELECT r.graph_version FROM extraction_run r
     WHERE r.document_id = d.id AND r.stage_iri = 'https://w3id.org/wlo/curriculum/vocab#stage_X5'
         AND r.outcome = 'done'
     ORDER BY r.started_at DESC LIMIT 1) AS checked_graph,
    ARRAY(SELECT iri FROM (
              SELECT DISTINCT ON (region) c.iri FROM unnest(d.regions) AS region JOIN vocab_concept c
                  ON c.scheme_iri = %(regions)s AND c.notation = region
              ORDER BY region, c.retired_in DESC NULLS FIRST  -- the active concept, else the last retired
          ) AS found ORDER BY iri) AS region_iris
FROM document d WHERE d.id = %(document)s
"""
_WORK = """
SELECT w.id, w.iri, w.title FROM work w JOIN document d ON d.work_id = w.id WHERE d.id = %(document)s
"""
# the file the document's conversion read, by its checksum
_FILE = """
SELECT f.id, encode(f.sha256, 'hex') AS sha256 FROM document d JOIN conversion c ON c.id = d.conversion_id
JOIN source_file f ON f.id = c.source_file_id WHERE d.id = %(document)s
"""
_SPECIFICATIONS = """
SELECT s.id, s.iri, s.spec_kind, s.title, s.field_text, s.applicability,
    -- whether the editors set contexts at all, rejected ones too: X1's reading stands no more (kern_scope)
    EXISTS (SELECT FROM applicability_context c WHERE c.specification_id = s.id) AS has_contexts
FROM specification s WHERE s.document_id = %(document)s ORDER BY s.key
"""
_VARIANTS = """
SELECT v.id, v.iri, v.specification_id, v.label, v.variant_kind_iri FROM variant v
JOIN specification s ON s.id = v.specification_id WHERE s.document_id = %(document)s ORDER BY v.key
"""
# A node lacks what every unit of it checked absent: one part of a node vouches for no other part
_NODES = """
SELECT n.id, n.iri, n.parent_id, n.position, n.function_iri, n.node_type_iri, n.code, n.code_assigned,
    n.original_title, n.title_language, n.obligation_iri, n.scope_share_iri, n.extraction_depth_iri,
    n.applies_to, n.origin_iri, n.review_status_iri,
    ARRAY(SELECT point FROM extraction_unit u CROSS JOIN LATERAL unnest(u.checked_absent) AS point
          WHERE u.node_id = n.id GROUP BY point
          HAVING count(DISTINCT u.unit_key) = (SELECT count(*) FROM extraction_unit w WHERE w.node_id = n.id)
          ORDER BY point) AS checked_absent
FROM node n WHERE n.document_id = %(document)s ORDER BY n.parent_id NULLS FIRST, n.position
"""
_STATEMENTS = """
SELECT s.id, s.iri, s.node_id, s.position, s.verbatim, s.language, s.lead_in, s.statement_kind_iri,
    s.subkind_iri, s.obligation_iri, s.origin_iri, s.review_status_iri, s.text_hash, s.details,
    s.layout_markers,
    ARRAY(SELECT a.addressee_iri FROM statement_addressee a WHERE a.statement_id = s.id
          ORDER BY a.addressee_iri) AS addressees
FROM statement s WHERE s.document_id = %(document)s AND s.review_status_iri <> 'https://w3id.org/wlo/curriculum/vocab#rev_rejected'
ORDER BY s.node_id, s.position
"""
_ANCHORS = """
SELECT a.id, a.node_id, a.statement_id, a.page_start, a.page_end, a.printed_page, a.quote, a.match_kind_iri,
    a.match_score, a.frame_part_id, a.char_start, a.char_end, a.table_cell, a.section_path,
    ARRAY(SELECT ab.block_id FROM anchor_block ab WHERE ab.anchor_id = a.id) AS blocks
FROM anchor a
WHERE a.document_id = %(document)s AND (a.node_id IS NOT NULL OR a.statement_id IS NOT NULL
        OR EXISTS (SELECT FROM frame_part f WHERE f.id = a.frame_part_id AND f.part_kind = 'rules'
                   AND f.review_status_iri <> 'https://w3id.org/wlo/curriculum/vocab#rev_rejected'))
    AND NOT EXISTS (SELECT FROM statement s WHERE s.id = a.statement_id AND s.review_status_iri = 'https://w3id.org/wlo/curriculum/vocab#rev_rejected')
ORDER BY a.id
"""


@dataclass(frozen=True)
class KernRows:
    document: Row
    specifications: list[Row]
    variants: list[Row]
    nodes: list[Row]
    statements: list[Row]
    anchors: list[Row]  # of nodes, statements and rules
    work: Row | None  # the work it is a version of, where the editors set one
    file: Row  # the file it was read off
    values: Values = field(default_factory=dict)  # of its holders read, rejected ones left out
    rules: list[Rule] = field(default_factory=list)  # rejected ones left out (plan M3a I)
    assessments: list[AssessmentRow] = field(default_factory=list)  # each part after its parent (plan M3a J)
    placements: list[PlacementRow] = field(default_factory=list)  # by node, in its order (plan M3a K)


async def read_document(connection: psycopg.AsyncConnection, document_id: UUID) -> KernRows:
    """The document's rows for its Kern RDF, in one snapshot (``in_one_snapshot``). DocumentError where
    there is none."""
    return await in_one_snapshot(connection, lambda reading: _read(reading, document_id))


async def in_one_snapshot[T](
    connection: psycopg.AsyncConnection, read: Callable[[psycopg.AsyncConnection], Awaitable[T]]
) -> T:
    """``read`` in one snapshot: in a read-only transaction of its own, or within the caller's where that
    one keeps a snapshot (repeatable read, serializable) - RuntimeError where it does not, as a pool's
    connection after its first query."""
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        cursor = await connection.execute("SELECT current_setting('transaction_isolation')")
        isolation = await cursor.fetchone()
        if isolation is None or isolation[0] not in _SNAPSHOTS:
            raise RuntimeError("the rows are read in one snapshot: in repeatable read, or idle")
        return await read(connection)
    async with connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return await read(connection)


async def _read(connection: psycopg.AsyncConnection, document_id: UUID) -> KernRows:
    params = {"document": document_id, "regions": REGIONS}
    async with connection.cursor(row_factory=dict_row) as rows:
        await rows.execute(_DOCUMENT, params)
        document = await rows.fetchone()
        if document is None:
            raise DocumentError(f"no document {document_id}")
        read = []
        for query in (_SPECIFICATIONS, _VARIANTS, _NODES, _STATEMENTS, _ANCHORS):
            await rows.execute(query, params)
            read.append(await rows.fetchall())
        await rows.execute(_WORK, params)
        work = await rows.fetchone()
        await rows.execute(_FILE, params)
        file = await rows.fetchone()
    values = await values_of(connection, document_id)  # within this snapshot
    rules = await rules_of(connection, document_id, stated=True)
    assessments = await assessments_of(connection, document_id, values=values)  # the values read once
    placements = await placements_of(connection, document_id, values=values)
    if file is None:  # a document is of a conversion, a conversion of a file: both columns NOT NULL
        raise DocumentError(f"no file of document {document_id}")
    specifications, variants, nodes, statements, anchors = read
    kept = _kept(values, {row["id"] for row in statements})
    return KernRows(
        document,
        specifications,
        variants,
        nodes,
        statements,
        anchors,
        work,
        file,
        kept,
        rules,
        assessments,
        placements,
    )


def _kept(values: Values, statements: set[UUID]) -> Values:
    """The values the graph states: those of the holders read - a rejected statement's go with it -, each
    but a rejected one, a workload's periods and a context's values but the rejected ones."""

    def kept[T: (Level, TimeSpan, Workload, Context)](items: tuple[T, ...]) -> tuple[T, ...]:
        return tuple(item for item in items if item.stated.review_status != _REJECTED)

    return {
        holder: HeldValues(
            kept(held.levels),
            kept(held.time_spans),
            tuple(replace(workload, periods=kept(workload.periods)) for workload in kept(held.workloads)),
            tuple(
                replace(context, levels=kept(context.levels), time_spans=kept(context.time_spans))
                for context in kept(held.contexts)
            ),
        )
        for holder, held in values.items()
        if holder.kind != "statement" or holder.id in statements
    }
