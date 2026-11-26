"""A document's assessments as the editors write them (plan M3a J; app/db/assessments.py,
app/db/assessment_rows.py): added after the parts of their parent, an editor's proposal; their fields and what
they assess set on their revision; taken away with their parts and the findings on them; the levels at them
set as their values; named when the document is frozen, by a counter a draft copy takes along. Under the
tree's lock, as every edit."""

import asyncio
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from app.db.assessment_choices import choices_of
from app.db.assessment_rows import assessments_of
from app.db.assessments import add_assessment, drop_assessment, edit_assessment
from app.db.draft_copy import copy_document
from app.db.editing import DocumentFrozen, StaleRevision, drop_node
from app.db.findings import findings_of
from app.db.freezing import freeze
from app.db.runs import x5_owed
from app.db.source_queries import Reader
from app.db.values import replace_values, values_of
from app.domain.assessments import AssessmentDraft
from app.domain.l2 import HeldValues, Holder, Level, LevelDraft, Stated, ValueDrafts
from app.vocab.form_values import FieldError
from tests.db.test_editing import a_finding, document, edited_at, one
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_nodes import CV, connection, owner, url, waiting_for_a_lock
from tests.db.test_values import holders

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

EXAM, PART, MODULE = CV + "ak_exam", CV + "ak_examPart", CV + "ak_moduleExam"
HUMAN, PROPOSED = CV + "orig_human", CV + "rev_proposed"
GRADE = LevelDraft(level="https://w3id.org/wlo/curriculum/level/grade-2")


async def an_exam(connection: psycopg.AsyncConnection, document: Any, parent: UUID, **fields: Any) -> UUID:
    made = await add_assessment(
        connection, owner(document), document.id, AssessmentDraft(parent, fields.pop("kind", EXAM), **fields)
    )
    assert made is not None
    return made


async def read(connection: psycopg.AsyncConnection, document: Any) -> dict[UUID, Any]:
    return {row.id: row for row in await assessments_of(connection, document.id)}


async def test_an_assessment_is_added_after_the_parts_of_its_parent_an_editor_s_proposal(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    held = await holders(connection, document)
    specification, node, statement = (held[kind].id for kind in ("specification", "node", "statement"))

    exam = await an_exam(connection, document, specification, label="Abschlussprüfung", graded=True,
                         duration_minutes=240)  # fmt: skip
    first = await an_exam(connection, document, exam, kind=PART, weight_percent=Decimal(60),
                          targets=(node, statement))  # fmt: skip
    second = await an_exam(connection, document, exam, kind=PART, label=" ", weight_percent=Decimal(40))

    rows = await assessments_of(connection, document.id)
    assert [row.id for row in rows] == [exam, first, second]  # each part after its parent, in its order
    by_id = {row.id: row for row in rows}
    assert (by_id[exam].parent_kind, by_id[exam].parent_id, by_id[exam].label, by_id[exam].graded) == (
        "specification", specification, "Abschlussprüfung", True,
    )  # fmt: skip
    parts = (by_id[first], by_id[second])
    assert [(row.parent_kind, row.parent_id, row.position, row.label) for row in parts] == [
        ("assessment", exam, 1, None), ("assessment", exam, 2, None),
    ]  # fmt: skip
    assert [(target.kind, target.id, target.label) for target in by_id[first].targets] == [
        ("node", node, None), ("statement", statement, "Sie messen."),
    ]  # fmt: skip
    assert {(row.stated.origin, row.stated.review_status, row.stated.revision) for row in rows} == {
        (HUMAN, PROPOSED, 1)
    }
    assert await edited_at(connection, document) is not None
    assert await x5_owed(connection, document.id)


async def test_an_assessment_the_store_does_not_take_is_refused_and_nothing_is_written(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    held = await holders(connection, document)
    specification, node = held["specification"].id, held["node"].id
    refused = [
        (AssessmentDraft(specification, CV + "form_formal"), "assessment_kind"),  # another list's
        (AssessmentDraft(uuid4(), EXAM), "parent_id"),
        (AssessmentDraft(specification, EXAM, targets=(uuid4(),)), "targets[0]"),
        (AssessmentDraft(specification, EXAM, targets=(node, node)), "targets[1]"),
        (AssessmentDraft(specification, EXAM, label="x" * 1001), "label"),
    ]

    problems = []
    for draft, _ in refused:
        with pytest.raises(FieldError) as error:
            await add_assessment(connection, owner(document), document.id, draft)
        problems.append((error.value.key, error.value.problem))

    assert problems == [(field, "too_long" if field == "label" else "not_offered") for _, field in refused]
    assert await one(connection, "SELECT count(*) FROM assessment") == (0,)
    assert (
        await add_assessment(
            connection, Reader(uuid4(), sees_all=False), document.id, AssessmentDraft(specification, EXAM)
        )
        is None
    )


async def test_an_assessment_s_fields_and_targets_are_set_on_its_revision(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    held = await holders(connection, document)
    specification, node, statement = (held[kind].id for kind in ("specification", "node", "statement"))
    exam = await an_exam(connection, document, specification)
    module = await an_exam(connection, document, node, kind=MODULE)
    part = await an_exam(connection, document, exam, kind=PART, targets=(node,))
    me = owner(document)

    assert await edit_assessment(connection, me, part, 1, {"weight_percent": Decimal("50.0"),
                                                           "targets": [statement, node]}) == 2  # fmt: skip
    assert await edit_assessment(connection, me, part, 2, {"weight_percent": Decimal(50)}) == 2  # no change
    with pytest.raises(StaleRevision) as stale:
        await edit_assessment(connection, me, part, 1, {"label": "Teil 1"})
    # moved: after the parts of its new parent
    assert await edit_assessment(connection, me, part, 2, {"parent_id": module, "label": "Teil 1"}) == 3

    assert stale.value.current == 2
    row = (await read(connection, document))[part]
    assert (row.parent_kind, row.parent_id, row.position, row.label, row.weight_percent) == (
        "assessment", module, 1, "Teil 1", Decimal(50),
    )  # fmt: skip
    assert [target.id for target in row.targets] == [statement, node]
    assert (row.stated.origin, row.stated.review_status, row.stated.revision) == (HUMAN, PROPOSED, 3)


async def test_an_assessment_is_never_moved_under_its_own_part(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    specification = (await holders(connection, document))["specification"].id
    exam = await an_exam(connection, document, specification)
    part = await an_exam(connection, document, exam, kind=PART)
    me = owner(document)

    refused = []
    for parent in (exam, part):
        with pytest.raises(FieldError) as error:
            await edit_assessment(connection, me, exam, 1, {"parent_id": parent})
        refused.append((error.value.key, error.value.problem))
    with pytest.raises(FieldError) as unknown:
        await edit_assessment(connection, me, exam, 1, {"position": 3})

    assert refused == [("parent_id", "cycle")] * 2
    assert (unknown.value.key, unknown.value.problem) == ("position", "unknown")
    assert (await read(connection, document))[exam].parent_id == specification


async def test_an_assessment_taken_away_takes_its_parts_their_levels_and_the_findings_on_them(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    held = await holders(connection, document)
    exam = await an_exam(connection, document, held["specification"].id)
    part = await an_exam(connection, document, exam, kind=PART, targets=(held["node"].id,))
    other = await an_exam(connection, document, held["specification"].id)
    assert (
        await replace_values(
            connection, owner(document), Holder("assessment", part), 1, ValueDrafts(levels=(GRADE,))
        )
        == 2
    )
    [level] = (await values_of(connection, document.id))[Holder("assessment", part)].levels
    kept = await a_finding(connection, document, other)
    for focus in (exam, part, level.value.id):
        await a_finding(connection, document, focus)

    with pytest.raises(StaleRevision):
        await drop_assessment(connection, owner(document), exam, 2)
    assert await drop_assessment(connection, owner(document), exam, 1) == 2

    assert list(await read(connection, document)) == [other]
    assert await one(connection, "SELECT count(*) FROM level_assignment") == (0,)
    assert await one(connection, "SELECT count(*) FROM assessment_target") == (0,)
    assert await one(connection, "SELECT array_agg(id) FROM validation_finding") == ([kept],)


async def test_a_node_taken_away_takes_its_assessments_and_the_findings_on_them(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    node = (await holders(connection, document))["node"].id
    module = await an_exam(connection, document, node, kind=MODULE)
    part = await an_exam(connection, document, module, kind=PART)
    await replace_values(
        connection, owner(document), Holder("assessment", part), 1, ValueDrafts(levels=(GRADE,))
    )
    [level] = (await values_of(connection, document.id))[Holder("assessment", part)].levels
    for focus in (module, part, level.value.id):
        await a_finding(connection, document, focus)

    revision = (await one(connection, "SELECT revision FROM node WHERE id = %s", node))[0]
    await drop_node(connection, owner(document), node, revision)

    assert await one(connection, "SELECT count(*) FROM assessment") == (0,)
    assert await one(connection, "SELECT count(*) FROM validation_finding") == (0,)


async def test_a_finding_on_an_assessment_or_a_level_at_it_names_the_assessment(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    specification = (await holders(connection, document))["specification"].id
    exam = await an_exam(connection, document, specification, label="Abschlussprüfung")
    await replace_values(
        connection, owner(document), Holder("assessment", exam), 1, ValueDrafts(levels=(GRADE,))
    )
    [level] = (await values_of(connection, document.id))[Holder("assessment", exam)].levels
    await a_finding(connection, document, exam)
    await a_finding(connection, document, level.value.id)

    rows = (await findings_of(connection, document.id)).rows

    assert {(row.focus_kind, row.holder_kind, row.holder_id, row.focus_label) for row in rows} == {
        ("assessment", None, None, "Abschlussprüfung"),
        ("level_assignment", "assessment", exam, "Abschlussprüfung"),
    }


async def test_what_an_assessment_may_be_a_part_of_or_assess_is_read_in_the_tree_s_order(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    held = await holders(connection, document)

    choices = await choices_of(connection, document.id)

    assert [(choice.kind, choice.id) for choice in choices] == [
        ("specification", held["specification"].id), ("node", held["node"].id),
    ]  # fmt: skip


async def test_a_frozen_document_s_assessments_are_named_and_its_draft_copy_counts_on(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    top = await ready(connection, document)
    exam = await an_exam(connection, document, top)
    await an_exam(connection, document, exam, kind=PART)
    await checked(connection, document)

    await freeze(connection, document.id, BASE, accept_violations=False)
    with pytest.raises(DocumentFrozen):
        await an_exam(connection, document, top)
    copy_id = await copy_document(connection, document.id)
    copy = await one(connection, "SELECT id, owner_id FROM document WHERE id = %s", copy_id)
    copied = type("Copy", (), {"id": copy[0], "owner_id": copy[1]})
    copied_top = (
        await one(connection, "SELECT id FROM node WHERE document_id = %s AND parent_id IS NULL", copy_id)
    )[0]
    await an_exam(connection, copied, copied_top, kind=MODULE)
    await checked(connection, copied)
    await freeze(connection, copy_id, BASE, accept_violations=False)

    named = "SELECT array_agg(iri ORDER BY iri) FROM assessment WHERE document_id = %s"
    assert await one(connection, named, document.id) == ([f"{DOC}/assessment-1", f"{DOC}/assessment-2"],)
    assert await one(connection, named, copy_id) == (
        [f"{DOC}/assessment-1", f"{DOC}/assessment-2", f"{DOC}/assessment-3"],
    )
    assert await one(connection, "SELECT serials FROM document WHERE id = %s", copy_id) == (
        {"assessment": 3},
    )


@pytest.mark.parametrize("second", ["edit", "values", "drop"])
async def test_two_editors_of_an_assessment_at_once_one_wins(
    url: str, connection: psycopg.AsyncConnection, document: Any, second: str
) -> None:
    # both on revision 1: the second waits for the tree's lock, then finds the revision the first wrote -
    # an edit against an edit, a set of its levels or a taking away
    specification = (await holders(connection, document))["specification"].id
    exam = await an_exam(connection, document, specification)
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[int | None] | None = None
        try:
            async with other.transaction():
                assert await edit_assessment(other, owner(document), exam, 1, {"label": "Erste"}) == 2
                waiting = asyncio.create_task(
                    edit_assessment(connection, owner(document), exam, 1, {"label": "Zweite"})
                    if second == "edit"
                    else drop_assessment(connection, owner(document), exam, 1)
                    if second == "drop"
                    else replace_values(
                        connection,
                        owner(document),
                        Holder("assessment", exam),
                        1,
                        ValueDrafts(levels=(GRADE,)),
                    )
                )
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            with pytest.raises(StaleRevision) as lost:
                if waiting is not None:
                    await waiting

    assert lost.value.current == 2
    assert await one(connection, "SELECT label, revision FROM assessment WHERE id = %s", exam) == ("Erste", 2)
    assert await one(connection, "SELECT count(*) FROM level_assignment") == (0,)


async def test_two_assessments_added_under_one_parent_at_once_take_positions_one_and_two(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the second waits for the tree's lock, then counts past the first: its position is counted under the lock
    specification = (await holders(connection, document))["specification"].id
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[UUID | None] | None = None
        try:
            async with other.transaction():
                first = await an_exam(other, document, specification)
                waiting = asyncio.create_task(an_exam(connection, document, specification))
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            second = await waiting if waiting is not None else None

    assert await one(connection, "SELECT position FROM assessment WHERE id = %s", first) == (1,)
    assert await one(connection, "SELECT position FROM assessment WHERE id = %s", second) == (2,)


async def test_the_assessments_take_the_values_a_reader_read_already(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # a graph build reads the document's values once (app/exports/kern_rows.py) and hands them in
    specification = (await holders(connection, document))["specification"].id
    exam = await an_exam(connection, document, specification)
    handed = Level(replace(GRADE, id=uuid4()), Stated(HUMAN, PROPOSED, None, 1))

    [row] = await assessments_of(
        connection, document.id, values={Holder("assessment", exam): HeldValues((handed,))}
    )

    assert row.levels == (handed,)
