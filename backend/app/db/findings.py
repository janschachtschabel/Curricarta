"""What a stage finds on a document (plan M1 6.2, 8; table validation_finding): a value outside the
profile, a block id nobody showed, a work the document may be an edition of. A finding is kept, never a
failure of its run: the run goes on without the value, and the editors see why. Written with the
stage's result, in its transaction, so that findings go with their run; read for the document's page,
gravest first, each with the row it is about. A stage that runs again (X5 after a repair, plan M1 8b)
drops the findings of its earlier runs: they describe a document that is no more."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.core.ids import new_id
from app.db.runs import STAGE_PREFIX, Stage, stage_iri
from app.domain.l1 import Severity

MOST_MESSAGE_SIGNS = 4000  # as the table holds them
MOST_FINDINGS = 500  # what a page lists of a document's findings
LABEL_SIGNS = 160  # of the row a finding is about, what a list shows
SEVERITIES: tuple[Severity, ...] = ("violation", "warning", "info")  # gravest first
_ADD = """
    INSERT INTO validation_finding (id, document_id, run_id, rule, severity, focus_id, path, message, details)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
# The row a finding is about by its entity's kind, named by its wording or title - cut, and said to be
# -; a value's holder (plan M3a F2), a period's its workload's, an applicability context's and its values'
# the context's specification (plan M3a H1), by which the value is named; the stage of its run; the counts
# of all the document's findings beside each, so that one statement reads both in one snapshot
_ROWS = """
SELECT f.rule, f.severity, replace(r.stage_iri, %(stages)s, ''), e.kind, f.focus_id,
    CASE WHEN length(l.label) > %(label)s THEN left(l.label, %(label)s - 1) || '…' ELSE l.label END,
    f.path, f.message, f.details ->> 'lang', f.details ->> 'unit', h.kind, h.id,
    (SELECT json_object_agg(c.severity, c.n) FROM (
        SELECT severity, count(*) AS n FROM validation_finding
        WHERE document_id = %(document)s GROUP BY severity
    ) AS c)
FROM validation_finding f
JOIN entity e ON e.id = f.focus_id
LEFT JOIN extraction_run r ON r.id = f.run_id
LEFT JOIN level_assignment la ON la.id = f.focus_id
LEFT JOIN time_span ts ON ts.id = f.focus_id
LEFT JOIN workload w ON w.id = coalesce(ts.workload_id, f.focus_id)  -- the value, or a period's workload
-- the context, or the context a value stands in
LEFT JOIN applicability_context ac
    ON ac.id = coalesce(la.applicability_context_id, ts.applicability_context_id, f.focus_id)
CROSS JOIN LATERAL (SELECT
    CASE WHEN coalesce(la.node_id, ts.node_id, w.node_id) IS NOT NULL THEN 'node'
        WHEN la.statement_id IS NOT NULL THEN 'statement'
        WHEN coalesce(la.specification_id, ts.specification_id, w.specification_id, ac.specification_id)
            IS NOT NULL THEN 'specification'
        WHEN la.frame_part_id IS NOT NULL THEN 'frame_part' END AS kind,
    coalesce(la.node_id, ts.node_id, w.node_id, la.statement_id, la.specification_id, ts.specification_id,
        w.specification_id, ac.specification_id, la.frame_part_id) AS id
) AS h
LEFT JOIN statement s ON s.id = coalesce(h.id, f.focus_id)
LEFT JOIN node n ON n.id = coalesce(h.id, f.focus_id)
LEFT JOIN specification sp ON sp.id = coalesce(h.id, f.focus_id)
LEFT JOIN document d ON d.id = f.focus_id
LEFT JOIN frame_part fp ON fp.id = coalesce(h.id, f.focus_id) AND fp.part_kind = 'rules'  -- a rule's wording
CROSS JOIN LATERAL (SELECT coalesce(s.verbatim, n.original_title, n.code, sp.title, d.title,
    fp.content ->> 'verbatim') AS label) AS l
WHERE f.document_id = %(document)s
ORDER BY array_position(%(severities)s::text[], f.severity), r.stage_iri, f.rule, f.created_at, f.id
LIMIT %(most)s
"""
_DROP_RULE = "DELETE FROM validation_finding WHERE document_id = %s AND rule = %s"
# the findings on the values of nodes and statements about to go: a workload's periods' too
_DROP_VALUES = """
DELETE FROM validation_finding WHERE document_id = %(document)s AND focus_id IN (
    SELECT id FROM level_assignment WHERE document_id = %(document)s
        AND (node_id = ANY(%(nodes)s) OR statement_id = ANY(%(statements)s))
    UNION ALL SELECT id FROM workload WHERE document_id = %(document)s AND node_id = ANY(%(nodes)s)
    UNION ALL SELECT t.id FROM time_span t LEFT JOIN workload w ON w.id = t.workload_id
        WHERE t.document_id = %(document)s AND (t.node_id = ANY(%(nodes)s) OR w.node_id = ANY(%(nodes)s))
)
"""
# a finding of ``rule`` that names the package: among its details.units (X4's), or as details.unit
_DROP_NAMING = """
DELETE FROM validation_finding WHERE document_id = %(document)s AND rule = %(rule)s
    AND (details -> 'units' ? %(unit)s OR details ->> 'unit' = %(unit)s)
"""
_RULE_DETAILS = (
    "SELECT details FROM validation_finding WHERE document_id = %s AND rule = %s ORDER BY created_at, id"
)
# the findings of reading the model's answer for a package (details.unit) by the stages that read one
_DROP_UNIT = """
DELETE FROM validation_finding f USING extraction_run r
WHERE f.document_id = %s AND r.id = f.run_id AND r.stage_iri = ANY(%s) AND f.details ->> 'unit' = %s
"""
_DROP = """
DELETE FROM validation_finding f USING extraction_run r
WHERE f.document_id = %s AND r.id = f.run_id AND r.stage_iri = %s AND f.run_id <> %s
"""


@dataclass(frozen=True)
class Finding:
    """``rule`` names what was found ("x1.not_in_profile"); ``focus_id`` the row it is about - the
    document itself where it is about the whole; ``path`` the property, where it is one."""

    rule: str
    severity: Severity
    focus_id: UUID
    message: str
    path: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FindingRow:
    """A finding as the document's page lists it: ``stage`` its run's ("X5"), ``focus_kind`` the kind of
    the row it is about ("statement", "node", "document" …) and ``focus_label`` that row's wording or
    title, where it has one; ``message_lang`` the message's language where the stage knew it (SHACL's
    German, "de"), else none - English; ``unit`` the work package it names; ``holder_kind`` and ``holder_id``
    the row a value it is about is held by - a node, a statement, a specification, a rule's frame part -,
    none for a finding about another row and for a value no longer there."""

    rule: str
    severity: Severity
    stage: str | None
    focus_kind: str
    focus_id: UUID
    focus_label: str | None
    path: str | None
    message: str
    message_lang: str | None
    unit: str | None
    holder_kind: str | None = None
    holder_id: UUID | None = None


@dataclass(frozen=True)
class FindingsPage:
    counts: dict[Severity, int]  # of all the document's findings
    rows: list[FindingRow]  # at most the most asked for
    truncated: bool


async def findings_of(
    connection: psycopg.AsyncConnection, document_id: UUID, *, most: int = MOST_FINDINGS
) -> FindingsPage:
    """The document's findings, gravest first, then by stage and rule - at most ``most`` of them."""
    cursor = await connection.execute(
        _ROWS,
        {
            "document": document_id,
            "stages": STAGE_PREFIX,
            "label": LABEL_SIGNS,
            "severities": list(SEVERITIES),
            "most": most + 1,
        },
    )
    found = await cursor.fetchall()
    rows = [FindingRow(*row[:-1]) for row in found]
    counted: dict[str, int] = found[0][-1] if found else {}  # none found: none to count
    return FindingsPage(
        {severity: counted.get(severity, 0) for severity in SEVERITIES}, rows[:most], len(rows) > most
    )


async def drop_value_findings(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    *,
    nodes: Sequence[UUID] = (),
    statements: Sequence[UUID] = (),
) -> None:
    """Drop the findings on the values of the document's ``nodes`` and ``statements``, which go with them:
    a value is an entity of its own, and validation_finding.focus_id has no cascade."""
    await connection.execute(
        _DROP_VALUES, {"document": document_id, "nodes": list(nodes), "statements": list(statements)}
    )


async def drop_stage_findings(
    connection: psycopg.AsyncConnection, document_id: UUID, stage: Stage, *, keep_run: UUID
) -> int:
    """Drop the findings of the stage's runs on the document but ``keep_run``; how many went."""
    cursor = await connection.execute(_DROP, (document_id, stage_iri(stage), keep_run))
    return cursor.rowcount


async def drop_unit_findings(
    connection: psycopg.AsyncConnection, document_id: UUID, unit_key: str, stages: Sequence[Stage]
) -> int:
    """Drop the findings the ``stages``' runs made of the package ``unit_key`` - a repair's reading of a
    new answer makes way for its own; how many went."""
    cursor = await connection.execute(
        _DROP_UNIT, (document_id, [stage_iri(stage) for stage in stages], unit_key)
    )
    return cursor.rowcount


async def rules_of_runs(connection: psycopg.AsyncConnection, run_ids: Sequence[UUID]) -> dict[str, int]:
    """How many findings the runs wrote that are kept still, by rule."""
    cursor = await connection.execute(
        "SELECT rule, count(*)::int FROM validation_finding WHERE run_id = ANY (%s)"
        " GROUP BY rule ORDER BY rule",
        (list(run_ids),),
    )
    return {rule: count for rule, count in await cursor.fetchall()}


async def drop_rule_findings(connection: psycopg.AsyncConnection, document_id: UUID, rule: str) -> int:
    """Drop the document's findings of ``rule``, whichever run found them; how many went."""
    cursor = await connection.execute(_DROP_RULE, (document_id, rule))
    return cursor.rowcount


async def drop_findings_naming(
    connection: psycopg.AsyncConnection, document_id: UUID, rule: str, unit_key: str
) -> int:
    """Drop the document's findings of ``rule`` that name the package ``unit_key``; how many went."""
    cursor = await connection.execute(_DROP_NAMING, {"document": document_id, "rule": rule, "unit": unit_key})
    return cursor.rowcount


async def rule_details(
    connection: psycopg.AsyncConnection, document_id: UUID, rule: str
) -> list[dict[str, Any]]:
    """The details of the document's findings of ``rule``, whichever run found them, oldest first."""
    cursor = await connection.execute(_RULE_DETAILS, (document_id, rule))
    return [details for (details,) in await cursor.fetchall()]


async def add_findings(
    connection: psycopg.AsyncConnection, document_id: UUID, run_id: UUID | None, findings: Sequence[Finding]
) -> None:
    """Keep the findings of the run, a message past MOST_MESSAGE_SIGNS cut to them."""
    if not findings:
        return
    async with connection.cursor() as cursor:
        await cursor.executemany(
            _ADD,
            [
                (
                    new_id(),
                    document_id,
                    run_id,
                    finding.rule,
                    finding.severity,
                    finding.focus_id,
                    finding.path,
                    finding.message[:MOST_MESSAGE_SIGNS],
                    Jsonb(dict(finding.details)),
                )
                for finding in findings
            ],
        )
