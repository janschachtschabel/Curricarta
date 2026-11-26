"""A node's placements as others read them (plan M3a K): in the tree, at their node with their time spans and
workloads and the findings on all of it counted there; in the findings, named by the node they place; and
their values reviewed as a node's are, which counts the placement's revision one up - the token a set of its
values is made on - and its node's, the token of a set of the node's placements."""

from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.db.findings import findings_of
from app.db.placement_rows import placements_of
from app.db.placements import replace_placements
from app.db.review import ReviewItem, set_review
from app.db.tree import read_tree, walk
from app.db.values import replace_values, values_of
from app.domain.l2 import Holder, ValueDrafts, WorkloadDraft
from app.domain.placements import PlacementDraft
from tests.db.test_editing import a_finding, document, one
from tests.db.test_nodes import CV, connection, owner, url
from tests.db.test_placements import BINDING, SEMESTER, placed

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

CREDITS = WorkloadDraft(Decimal(5), CV + "unit_ectsCredit", periods=(SEMESTER,))


async def a_placement(connection: psycopg.AsyncConnection, document: Any) -> tuple[dict[str, Any], Any]:
    """The module placed in the specification, with a semester and its credits there."""
    made = await placed(connection, document)
    await replace_placements(
        connection,
        owner(document),
        made["module"],
        1,
        [PlacementDraft(BINDING, specification_id=made["specification"])],
    )
    [placement] = await placements_of(connection, document.id)
    await replace_values(connection, owner(document), Holder("placement", placement.id), 1,
                         ValueDrafts(time_spans=(SEMESTER,), workloads=(CREDITS,)))  # fmt: skip
    [placement] = await placements_of(connection, document.id)
    return made, placement


async def test_the_tree_reads_each_node_s_placements_with_their_values_and_counts_their_findings_there(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made, placement = await a_placement(connection, document)
    [workload] = placement.values.workloads
    for focus in (
        placement.id,
        placement.values.time_spans[0].value.id,
        workload.value.id,
        workload.periods[0].value.id,
    ):
        await a_finding(connection, document, focus)

    tree = await read_tree(connection, owner(document), document.id)

    assert tree is not None
    nodes = {node.id: node for node in walk(tree)}
    assert nodes[made["module"]].placements == (placement,)
    assert nodes[made["area"]].placements == ()
    assert nodes[made["module"]].findings["warning"] == 4


async def test_a_finding_on_a_placement_or_a_value_at_it_names_the_node_it_places(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    _, placement = await a_placement(connection, document)
    await connection.execute(
        "UPDATE node SET original_title = 'Analysis I' WHERE id = %s", (placement.node_id,)
    )
    await a_finding(connection, document, placement.id)
    await a_finding(connection, document, placement.values.workloads[0].periods[0].value.id)

    rows = (await findings_of(connection, document.id)).rows

    assert {(row.focus_kind, row.holder_kind, row.holder_id, row.focus_label) for row in rows} == {
        ("placement", None, None, "Analysis I"),
        ("time_span", "placement", placement.id, "Analysis I"),
    }


async def test_a_value_at_a_placement_reviewed_counts_the_placement_s_revision_one_up(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    _, placement = await a_placement(connection, document)
    span = placement.values.time_spans[0].value.id
    period = placement.values.workloads[0].periods[0].value.id
    assert span is not None and period is not None

    node_before = (await one(connection, "SELECT revision FROM node WHERE id = %s", placement.node_id))[0]
    revisions = await set_review(
        connection, document.id, CV + "rev_confirmed",
        [ReviewItem("time_span", span, 1), ReviewItem("time_span", period, 1)],
    )  # fmt: skip

    assert revisions == {span: 2, period: 2}
    assert await one(connection, "SELECT revision FROM placement WHERE id = %s", placement.id) == (3,)
    # the node holds the placement: its revision counts once more, the token of a set of its placements
    assert await one(connection, "SELECT revision FROM node WHERE id = %s", placement.node_id) == (
        node_before + 1,
    )
    held = (await values_of(connection, document.id))[Holder("placement", placement.id)]
    assert held.time_spans[0].stated.review_status == CV + "rev_confirmed"
