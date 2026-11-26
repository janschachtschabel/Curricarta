"""The editors' review of a document's assessments and placements (plan M3a L; app/db/review.py), rows as
a node is: each on the revision it was read at, its origin kept, its revision one up. A level at an assessment
is its value, reviewed as a node's are, which counts the assessment's revision one up - the token of a set of
its levels; a placement is the node's, which a set of the node's placements names by the node's revision: its
review counts the node's one up too. Under the tree's lock, as every write."""

import asyncio
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.db.assessments import edit_assessment
from app.db.editing import StaleRevision
from app.db.placements import replace_placements
from app.db.review import ReviewItem, StaleItems, set_review
from app.db.values import replace_values, values_of
from app.domain.l2 import Holder, ValueDrafts
from app.domain.placements import PlacementDraft
from tests.db.test_assessments import GRADE, an_exam
from tests.db.test_editing import document, edited_at, one
from tests.db.test_nodes import CV, connection, owner, url, waiting_for_a_lock
from tests.db.test_placement_reads import a_placement
from tests.db.test_placements import BINDING
from tests.db.test_values import holders

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

HUMAN, CONFIRMED, REJECTED = CV + "orig_human", CV + "rev_confirmed", CV + "rev_rejected"


async def test_an_assessment_reviewed_counts_its_revision_and_keeps_its_origin(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    specification = (await holders(connection, document))["specification"].id
    exam = await an_exam(connection, document, specification)
    await connection.execute("UPDATE document SET edited_at = NULL")

    revisions = await set_review(connection, document.id, CONFIRMED, [ReviewItem("assessment", exam, 1)])

    assert revisions == {exam: 2}
    assert await one(
        connection, "SELECT origin_iri, review_status_iri, revision FROM assessment WHERE id = %s", exam
    ) == (HUMAN, CONFIRMED, 2)
    assert await edited_at(connection, document) is None  # a review changes not what the document says
    with pytest.raises(StaleItems) as stale:  # read before the review
        await set_review(connection, document.id, REJECTED, [ReviewItem("assessment", exam, 1)])
    assert [(each.kind, each.current) for each in stale.value.stale] == [("assessment", 2)]


async def test_an_assessment_rejected_leaves_the_curriculum_and_edits_the_document(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    specification = (await holders(connection, document))["specification"].id
    exam = await an_exam(connection, document, specification)
    await connection.execute("UPDATE document SET edited_at = NULL")

    await set_review(connection, document.id, REJECTED, [ReviewItem("assessment", exam, 1)])

    assert await edited_at(connection, document) is not None


async def test_a_level_at_an_assessment_reviewed_counts_the_assessment_s_revision(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the assessment's revision is the token of a set of its levels: a set read before the review is stale
    specification = (await holders(connection, document))["specification"].id
    exam = await an_exam(connection, document, specification)
    await replace_values(
        connection, owner(document), Holder("assessment", exam), 1, ValueDrafts(levels=(GRADE,))
    )
    [level] = (await values_of(connection, document.id))[Holder("assessment", exam)].levels
    assert level.value.id is not None

    revisions = await set_review(
        connection, document.id, CONFIRMED, [ReviewItem("level_assignment", level.value.id, 1)]
    )

    assert revisions == {level.value.id: 2}
    assert await one(connection, "SELECT review_status_iri, revision FROM level_assignment") == (CONFIRMED, 2)
    assert await one(connection, "SELECT revision FROM assessment WHERE id = %s", exam) == (3,)
    with pytest.raises(StaleRevision) as stale:
        await replace_values(connection, owner(document), Holder("assessment", exam), 2, ValueDrafts())
    assert stale.value.current is not None
    # reviewed with its level, the assessment counts once
    both = [ReviewItem("assessment", exam, 3), ReviewItem("level_assignment", level.value.id, 2)]
    assert await set_review(connection, document.id, REJECTED, both) == {exam: 4, level.value.id: 3}


async def test_a_placement_reviewed_counts_its_revision_and_its_node_s(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the node's revision is the token of a set of its placements: one read before the review is stale
    _, placement = await a_placement(connection, document)
    node_before = (await one(connection, "SELECT revision FROM node WHERE id = %s", placement.node_id))[0]
    span = placement.values.time_spans[0].value.id
    assert span is not None

    revisions = await set_review(
        connection, document.id, CONFIRMED, [ReviewItem("placement", placement.id, placement.stated.revision)]
    )

    assert revisions == {placement.id: placement.stated.revision + 1}
    assert await one(
        connection, "SELECT origin_iri, review_status_iri FROM placement WHERE id = %s", placement.id
    ) == (HUMAN, CONFIRMED)
    assert await one(connection, "SELECT revision FROM node WHERE id = %s", placement.node_id) == (
        node_before + 1,
    )
    # reviewed with a value of it, the placement and its node count once each
    both = [
        ReviewItem("placement", placement.id, placement.stated.revision + 1),
        ReviewItem("time_span", span, 1),
    ]
    assert await set_review(connection, document.id, REJECTED, both) == {
        placement.id: placement.stated.revision + 2,
        span: 2,
    }
    assert await one(connection, "SELECT revision FROM node WHERE id = %s", placement.node_id) == (
        node_before + 2,
    )


async def test_a_set_of_the_node_s_placements_waiting_for_a_review_of_one_is_stale(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the set waits for the tree's lock; then the node's revision it was read at is one the review left behind
    made, placement = await a_placement(connection, document)
    node_before = (await one(connection, "SELECT revision FROM node WHERE id = %s", placement.node_id))[0]
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[int | None] | None = None
        try:
            async with other.transaction():
                reviewed = ReviewItem("placement", placement.id, placement.stated.revision)
                await set_review(other, document.id, REJECTED, [reviewed])
                kept = PlacementDraft(BINDING, specification_id=made["specification"], id=placement.id)
                waiting = asyncio.create_task(
                    replace_placements(connection, owner(document), made["module"], node_before, [kept])
                )
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            with pytest.raises(StaleRevision) as lost:
                if waiting is not None:
                    await waiting

    assert lost.value.current == node_before + 1
    assert await one(connection, "SELECT review_status_iri FROM placement") == (REJECTED,)


async def test_an_edit_of_an_assessment_waiting_for_its_review_is_stale(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    specification = (await holders(connection, document))["specification"].id
    exam = await an_exam(connection, document, specification)
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[int | None] | None = None
        try:
            async with other.transaction():
                await set_review(other, document.id, CONFIRMED, [ReviewItem("assessment", exam, 1)])
                waiting = asyncio.create_task(
                    edit_assessment(connection, owner(document), exam, 1, {"label": "Später"})
                )
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            with pytest.raises(StaleRevision) as lost:
                if waiting is not None:
                    await waiting

    assert lost.value.current == 2
    assert await one(connection, "SELECT label, review_status_iri FROM assessment") == (None, CONFIRMED)


async def test_a_row_named_as_an_assessment_or_a_placement_it_is_not_is_none(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    _, placement = await a_placement(connection, document)
    gone: UUID = placement.node_id  # a node, not a placement nor an assessment

    with pytest.raises(StaleItems) as stale:
        await set_review(
            connection,
            document.id,
            CONFIRMED,
            [ReviewItem("assessment", gone, 1), ReviewItem("placement", gone, 1)],
        )

    assert [(each.kind, each.current) for each in stale.value.stale] == [
        ("assessment", None), ("placement", None),
    ]  # fmt: skip
