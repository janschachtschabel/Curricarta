"""A document's assessments, as the editors write them (plan M3a J; migration assessment,
app/domain/assessments.py): one added after the parts of its parent, one's fields and what it assesses set on
its revision, one taken away with its parts. The levels at an assessment are its values, set as a whole on its
revision as a node's are (app/db/values.py); its anchors none writes here. Read by document, and named when
the document is frozen, in app/db/assessment_rows.py.

An edit holds the tree's lock and refuses what every edit of the tree refuses (app/db/editing.py ``guard``);
StaleRevision where the assessment stands at another revision. Its kind is one of cv:AssessmentKinds the
vocabulary holds active - a kept one retired since stays until it is changed -, its parent an assessment, a
specification or a node of its document, and never one of its own parts; what it assesses nodes and
statements of its document, each once (FieldError, by the field and why). An editor's assessment is a
proposal (origin human, proposed); a change makes it one again, counts its revision one up and notes the
document edited, which owes X5 a check; one that changes nothing leaves it as it was. An assessment taken
away takes its parts, what they assess and the levels at them, and the findings on all of it.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final, LiteralString
from uuid import UUID

import psycopg
from psycopg import sql

from app.db.anchors import new_entity
from app.db.assessment_choices import KINDS
from app.db.documents import DOCUMENT_VISIBLE
from app.db.editing import (
    CV,
    DOCUMENT,
    HUMAN,
    PROPOSED,
    SECTOR,
    StaleRevision,
    drop_findings,
    guard,
    mark_edited,
    target_of,
)
from app.db.source_queries import Reader
from app.domain.assessments import FIELDS, MOST_LABEL, AssessmentDraft
from app.domain.text import UNSTORABLE
from app.vocab.form_values import FieldError

DOCUMENT_OF_ASSESSMENT = f"""
SELECT d.id, sector.notation FROM assessment a JOIN document d ON d.id = a.document_id {SECTOR}
WHERE a.id = %(id)s AND {DOCUMENT_VISIBLE}
"""  # noqa: S608 - fixed parts
# the parent's column by the table the parent is of
_PARENT_COLUMNS: Final[dict[str, LiteralString]] = {
    "assessment": "parent_assessment_id", "specification": "specification_id", "node": "node_id",
}  # fmt: skip
_PARENT = """
SELECT 'assessment' FROM assessment WHERE id = %(id)s AND document_id = %(document)s
UNION ALL SELECT 'specification' FROM specification WHERE id = %(id)s AND document_id = %(document)s
UNION ALL SELECT 'node' FROM node WHERE id = %(id)s AND document_id = %(document)s
"""
_TARGETS = """
SELECT id, 'node' FROM node WHERE id = ANY(%(ids)s) AND document_id = %(document)s
UNION ALL SELECT id, 'statement' FROM statement WHERE id = ANY(%(ids)s) AND document_id = %(document)s
"""
_ACTIVE_KIND = """
SELECT FROM vocab_concept c JOIN vocab_scheme s ON s.iri = c.scheme_iri
WHERE c.scheme_iri = %s AND c.iri = %s AND c.retired_in IS NULL AND s.retired_in IS NULL
"""
_CURRENT = """
SELECT revision, coalesce(parent_assessment_id, specification_id, node_id) AS parent_id,
    assessment_kind_iri AS assessment_kind, label, duration_minutes, weight_percent, graded,
    array(SELECT coalesce(t.node_id, t.statement_id) FROM assessment_target t
          WHERE t.assessment_id = a.id ORDER BY t.position) AS targets
FROM assessment a WHERE id = %s FOR UPDATE
"""
_NEXT = "SELECT coalesce(max(position), 0) + 1 FROM assessment WHERE {} = %s"
# the assessment, its parts, the levels and anchors at them: what goes with it, by id
_SUBTREE = """
WITH RECURSIVE under (id) AS (
    SELECT id FROM assessment WHERE id = %(id)s
    UNION ALL SELECT a.id FROM assessment a JOIN under u ON a.document_id = %(document)s
        AND a.parent_assessment_id = u.id
)
SELECT array(SELECT id FROM under),
    array(SELECT l.id FROM level_assignment l JOIN under u ON l.document_id = %(document)s
          AND l.assessment_id = u.id
          UNION ALL SELECT a.id FROM anchor a JOIN under u ON a.document_id = %(document)s
          AND a.assessment_id = u.id)
"""
_CYCLE: Final = frozenset({"assessment_without_cycle", "assessment_not_its_own_part"})


async def add_assessment(
    connection: psycopg.AsyncConnection, reader: Reader, document_id: UUID, draft: AssessmentDraft
) -> UUID | None:
    """A new assessment ``draft`` of the document, after the parts of its parent, an editor's proposal; its
    id. None where ``reader`` sees no such document. FieldError or a refusal of ``guard``, and then nothing
    is written."""
    async with connection.transaction():
        if await target_of(connection, DOCUMENT, reader, document_id) is None:
            return None
        await guard(connection, document_id)
        await _check_kind(connection, draft.assessment_kind, None)
        parent = await _parent(connection, document_id, draft.parent_id)
        targets = await _targets(connection, document_id, draft.targets)
        made = await new_entity(connection, "assessment")
        values = {
            "id": made, "document_id": document_id, parent: draft.parent_id,
            "position": await _next(connection, parent, draft.parent_id),
            "assessment_kind_scheme": KINDS, "assessment_kind_iri": draft.assessment_kind,
            "label": _label(draft.label), "duration_minutes": draft.duration_minutes,
            "weight_percent": draft.weight_percent, "graded": draft.graded,
            "origin_scheme": CV + "Origins", "origin_iri": HUMAN,
            "review_status_scheme": CV + "ReviewStatuses", "review_status_iri": PROPOSED,
        }  # fmt: skip
        await connection.execute(
            sql.SQL("INSERT INTO assessment ({}) VALUES ({})").format(
                sql.SQL(", ").join(map(sql.Identifier, values)),
                sql.SQL(", ").join(sql.Placeholder() * len(values)),
            ),
            tuple(values.values()),
        )
        await _write_targets(connection, document_id, made, targets)
        await mark_edited(connection, document_id)
        return made


async def edit_assessment(
    connection: psycopg.AsyncConnection,
    reader: Reader,
    assessment_id: UUID,
    revision: int,
    given: Mapping[str, Any],
) -> int | None:
    """Set the assessment's ``given`` fields (FIELDS' keys; a blank label none, ``targets`` the whole list),
    on its revision ``revision``; its revision after, None where ``reader`` sees no such assessment. A new
    parent takes it after the parts there. FieldError, StaleRevision or a refusal of ``guard``, and then
    nothing is changed."""
    if unknown := next((key for key in given if key not in FIELDS), None):
        raise FieldError(unknown, "unknown")
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT_OF_ASSESSMENT, reader, assessment_id)
        if target is None:
            return None
        document_id = target.document_id
        await guard(connection, document_id)
        current = await _current(connection, assessment_id)
        if current is None:  # taken away meanwhile
            return None
        stood = current.pop("revision")
        if stood != revision:
            raise StaleRevision(stood)
        wanted = current | {key: _label(value) if key == "label" else value for key, value in given.items()}
        if "targets" in given:
            wanted["targets"] = list(given["targets"])
        if wanted == current:
            return revision
        await _check_kind(connection, wanted["assessment_kind"], current["assessment_kind"])
        columns: dict[str, Any] = {
            key: wanted[key] for key in ("label", "duration_minutes", "weight_percent", "graded")
        }
        columns["assessment_kind_iri"] = wanted["assessment_kind"]
        if wanted["parent_id"] != current["parent_id"]:
            parent = await _parent(connection, document_id, wanted["parent_id"])
            columns |= dict.fromkeys(_PARENT_COLUMNS.values()) | {parent: wanted["parent_id"]}
            columns["position"] = await _next(connection, parent, wanted["parent_id"])
        targets = await _targets(connection, document_id, wanted["targets"])
        try:
            cursor = await connection.execute(
                sql.SQL(
                    "UPDATE assessment SET {}, origin_iri = %s, rule_id = NULL, review_status_iri = %s,"
                    " revision = revision + 1, updated_at = now() WHERE id = %s RETURNING revision"
                ).format(
                    sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(key)) for key in columns)
                ),
                (*columns.values(), HUMAN, PROPOSED, assessment_id),
            )
        except psycopg.errors.CheckViolation as refused:
            if refused.diag.constraint_name in _CYCLE:
                raise FieldError("parent_id", "cycle") from refused
            raise
        raised = await cursor.fetchone()
        assert raised is not None  # noqa: S101 - the row locked above
        if wanted["targets"] != current["targets"]:
            await connection.execute(
                "DELETE FROM assessment_target WHERE assessment_id = %s", (assessment_id,)
            )
            await _write_targets(connection, document_id, assessment_id, targets)
        await mark_edited(connection, document_id)
        return int(raised[0])


async def drop_assessment(
    connection: psycopg.AsyncConnection, reader: Reader, assessment_id: UUID, revision: int
) -> int | None:
    """Take the assessment away with its parts - what they assess, the levels and anchors at them - and the
    findings on all of it; how many assessments went. None where ``reader`` sees no such assessment.
    StaleRevision or a refusal of ``guard``, and then nothing goes."""
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT_OF_ASSESSMENT, reader, assessment_id)
        if target is None:
            return None
        await guard(connection, target.document_id)
        cursor = await connection.execute(
            "SELECT revision FROM assessment WHERE id = %s FOR UPDATE", (assessment_id,)
        )
        found = await cursor.fetchone()
        if found is None:
            return None
        if found[0] != revision:
            raise StaleRevision(found[0])
        cursor = await connection.execute(_SUBTREE, {"id": assessment_id, "document": target.document_id})
        subtree = await cursor.fetchone()
        assert subtree is not None  # noqa: S101 - arrays of an assessment that stands
        assessments, held = subtree
        await drop_findings(connection, target.document_id, [*assessments, *held])
        await connection.execute("DELETE FROM assessment WHERE id = %s", (assessment_id,))
        await mark_edited(connection, target.document_id)
        return len(assessments)


async def _current(connection: psycopg.AsyncConnection, assessment_id: UUID) -> dict[str, Any] | None:
    cursor = await connection.execute(_CURRENT, (assessment_id,))
    found = await cursor.fetchone()
    if found is None:
        return None
    assert cursor.description is not None  # noqa: S101 - a SELECT's
    return dict(zip((column.name for column in cursor.description), found, strict=True))


async def _check_kind(connection: psycopg.AsyncConnection, kind: str, kept: str | None) -> None:
    """``kind`` one of cv:AssessmentKinds the vocabulary holds active, or the one the assessment holds."""
    if kind == kept:
        return
    cursor = await connection.execute(_ACTIVE_KIND, (KINDS, kind))
    if await cursor.fetchone() is None:
        raise FieldError("assessment_kind", "not_offered")


async def _parent(connection: psycopg.AsyncConnection, document_id: UUID, parent_id: UUID) -> LiteralString:
    """The column of the parent ``parent_id``, an assessment, a specification or a node of the document."""
    cursor = await connection.execute(_PARENT, {"id": parent_id, "document": document_id})
    found = await cursor.fetchone()
    if found is None:
        raise FieldError("parent_id", "not_offered")
    return _PARENT_COLUMNS[found[0]]


async def _next(connection: psycopg.AsyncConnection, column: LiteralString, parent_id: UUID) -> int:
    cursor = await connection.execute(sql.SQL(_NEXT).format(sql.Identifier(column)), (parent_id,))
    found = await cursor.fetchone()
    assert found is not None  # noqa: S101 - an aggregate's row
    return int(found[0])


async def _targets(
    connection: psycopg.AsyncConnection, document_id: UUID, targets: Sequence[UUID]
) -> list[tuple[UUID, str]]:
    """Each target with its table, in order; FieldError at the first that is no node or statement of the
    document, or is named twice."""
    cursor = await connection.execute(_TARGETS, {"ids": list(targets), "document": document_id})
    tables: dict[UUID, str] = dict(await cursor.fetchall())
    seen: set[UUID] = set()
    for place, target in enumerate(targets):
        if target not in tables or target in seen:
            raise FieldError(f"targets[{place}]", "not_offered")
        seen.add(target)
    return [(target, tables[target]) for target in targets]


async def _write_targets(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    assessment_id: UUID,
    targets: Sequence[tuple[UUID, str]],
) -> None:
    async with connection.cursor() as writing:
        await writing.executemany(
            "INSERT INTO assessment_target (document_id, assessment_id, node_id, statement_id, position)"
            " VALUES (%s, %s, %s, %s, %s)",
            [
                (document_id, assessment_id, *((target, None) if table == "node" else (None, target)), place)
                for place, (target, table) in enumerate(targets, start=1)
            ],
        )


def _label(value: str | None) -> str | None:
    """A label as the store keeps it: a blank one none; FieldError where it may not be stored."""
    if value is None or not value.strip():
        return None
    if UNSTORABLE.search(value):
        raise FieldError("label", "not_storable")
    if len(value) > MOST_LABEL:
        raise FieldError("label", "too_long")
    return value
