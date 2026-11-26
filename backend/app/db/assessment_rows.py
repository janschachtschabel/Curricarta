"""A document's assessments read (plan M3a J; migration assessment, app/domain/assessments.py), as the Kern
graph states them and the editors see them: each with what it assesses and the levels at it, every part
after the assessment it is a part of, the parts of one parent in their order; and named when the document
is frozen (``name_assessments``) - the IRIs a frozen graph states. Written in app/db/assessments.py; what an
assessment may be a part of, assess or be of in app/db/assessment_choices.py.
"""

from collections import defaultdict
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.db.counted_names import name_by_counter
from app.db.value_rows import values_of
from app.domain.assessments import AssessmentRow, ParentKind, Target
from app.domain.l2 import Holder, Stated, Values

LABEL_SIGNS: Final = 160  # of a statement's wording, what a list shows of what an assessment assesses
_ASSESSMENTS = """
SELECT id, parent_assessment_id, specification_id, node_id, position, assessment_kind_iri, label,
    duration_minutes, weight_percent, graded, iri, origin_iri, review_status_iri, rule_id, revision
FROM assessment WHERE document_id = %(document)s ORDER BY position, id
"""
_TARGETS = """
SELECT t.assessment_id, CASE WHEN t.node_id IS NULL THEN 'statement' ELSE 'node' END AS kind,
    coalesce(t.node_id, t.statement_id) AS id,
    CASE WHEN t.node_id IS NULL THEN left(s.verbatim, %(signs)s)
        ELSE nullif(concat_ws(' ', n.code, n.original_title), '') END AS label
FROM assessment_target t LEFT JOIN node n ON n.id = t.node_id LEFT JOIN statement s ON s.id = t.statement_id
WHERE t.document_id = %(document)s ORDER BY t.assessment_id, t.position
"""


async def assessments_of(
    connection: psycopg.AsyncConnection, document_id: UUID, *, values: Values | None = None
) -> list[AssessmentRow]:
    """The document's assessments, each part after the assessment it is a part of and the parts of one
    parent in their order, in one snapshot - of a read-only transaction of its own, or of the caller's; the
    levels at them from ``values``, the document's values where the caller read them already in that snapshot
    (app/exports/kern_rows.py), so they are read once."""
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        return await _read(connection, document_id, values)
    async with connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return await _read(connection, document_id, values)


async def name_assessments(connection: psycopg.AsyncConnection, document_id: UUID, iri: str) -> int:
    """Give each assessment of the document without an IRI its own under the document's IRI ``iri`` -
    ``<iri>/assessment-<n>``, in the order they were made -, counting on from the document's counter
    (document.serials), which a draft copy takes along: no number is given twice. How many were named.
    Within the freeze, under the tree's lock, before the document is frozen (app/db/freezing.py)."""
    return await name_by_counter(connection, "assessment", document_id, iri)


async def _read(
    connection: psycopg.AsyncConnection, document_id: UUID, values: Values | None
) -> list[AssessmentRow]:
    params = {"document": document_id, "signs": LABEL_SIGNS}
    async with connection.cursor(row_factory=dict_row) as rows:
        await rows.execute(_ASSESSMENTS, params)
        found = await rows.fetchall()
        await rows.execute(_TARGETS, params)
        targets: defaultdict[UUID, list[Target]] = defaultdict(list)
        for row in await rows.fetchall():
            targets[row["assessment_id"]].append(Target(row["kind"], row["id"], row["label"]))
    if values is None:
        values = await values_of(connection, document_id)
    parts: defaultdict[UUID | None, list[dict[str, Any]]] = defaultdict(list)
    for row in found:
        parts[row["parent_assessment_id"]].append(row)
    ordered: list[AssessmentRow] = []
    pending = list(reversed(parts[None]))  # the tops, then each one's parts after it
    while pending:
        row = pending.pop()
        held = values.get(Holder("assessment", row["id"]))
        ordered.append(_row(row, tuple(targets[row["id"]]), () if held is None else held.levels))
        pending.extend(reversed(parts[row["id"]]))
    return ordered


def _row(row: dict[str, Any], targets: tuple[Target, ...], levels: tuple[Any, ...]) -> AssessmentRow:
    kind: ParentKind = (
        "assessment" if row["parent_assessment_id"] is not None
        else "specification" if row["specification_id"] is not None else "node"
    )  # fmt: skip
    return AssessmentRow(
        id=row["id"], parent_kind=kind,
        parent_id=row["parent_assessment_id"] or row["specification_id"] or row["node_id"],
        position=row["position"], assessment_kind=row["assessment_kind_iri"], label=row["label"],
        duration_minutes=row["duration_minutes"], weight_percent=row["weight_percent"], graded=row["graded"],
        iri=row["iri"],
        stated=Stated(row["origin_iri"], row["review_status_iri"], row["rule_id"], row["revision"]),
        targets=targets, levels=levels,
    )  # fmt: skip
