"""Findings on the second layer's values (plan M3a F2): a value keeps its own focus, as X5 finds it at the
value's row, and the list names the value's holder - a node, a statement, a specification; a workload's
period by the workload's holder -, with that holder's wording or title; a value no longer there names none.
A node counts the findings on its values and on its statements' values. A node or statement taken away
takes the findings on its values along, as it takes those on itself and its anchors."""

from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.db.findings import findings_of
from app.db.node_drop import drop_node
from app.db.nodes import drop_statements, write_subtree
from app.db.statement_editing import HandAnchor, add_statement, drop_or_reject_statement
from app.db.tree import read_tree
from app.db.values import replace_values, values_of
from app.domain.l2 import HeldValues, Holder, LevelDraft, TimeSpanDraft, ValueDrafts, WorkloadDraft
from tests.db.test_editing import a_finding, document, one
from tests.db.test_nodes import CV, connection, node, owner, statement, url

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

LEVEL = LevelDraft(level="https://w3id.org/wlo/curriculum/level/EQF-4")
GRADE = TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=Decimal(5))
LESSONS = WorkloadDraft(amount=Decimal(40), unit=CV + "unit_lesson", periods=(GRADE,))
NODE_VALUES = ValueDrafts(levels=(LEVEL,), time_spans=(GRADE,), workloads=(LESSONS,))
NEW = {
    "verbatim": "Sie prüfen.",
    "statement_kind": CV + "kind_learningOutcome",
    "addressees": [CV + "addr_learner"],
}


async def valued(
    connection: psycopg.AsyncConnection, document: Any, holder: Holder, drafts: ValueDrafts
) -> HeldValues:
    """The holder's values set to ``drafts``, as stored."""
    revision = await one(connection, f"SELECT revision FROM {holder.kind} WHERE id = %s", holder.id)  # noqa: S608
    await replace_values(connection, owner(document), holder, revision[0], drafts)
    return (await values_of(connection, document.id))[holder]


def ids(held: HeldValues) -> list[UUID | None]:
    """Every value's id, a workload's periods among them."""
    found = [level.value.id for level in held.levels] + [span.value.id for span in held.time_spans]
    for workload in held.workloads:
        found += [workload.value.id, *(period.value.id for period in workload.periods)]
    return found


async def a_tree(connection: psycopg.AsyncConnection, document: Any) -> dict[str, Any]:
    """A node "Optik" with a statement and a child, the node's and the statement's values set."""
    top = await write_subtree(connection, document.id, node(
        original_title="Optik", statements=(statement("Sie messen."),), children=(node("fn_unit"),),
    ))  # fmt: skip
    said = await one(connection, "SELECT id FROM statement WHERE node_id = %s", top)
    return {
        "top": top,
        "said": said[0],
        "node_values": await valued(connection, document, Holder("node", top), NODE_VALUES),
        "said_values": await valued(
            connection, document, Holder("statement", said[0]), ValueDrafts(levels=(LEVEL,))
        ),
    }


async def findings_left(connection: psycopg.AsyncConnection) -> set[Any]:
    cursor = await connection.execute("SELECT focus_id FROM validation_finding")
    return {found for (found,) in await cursor.fetchall()}


async def test_a_finding_on_a_value_names_its_holder(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_tree(connection, document)
    level, span, *_ = ids(made["node_values"])
    [said_level] = ids(made["said_values"])
    for focus in (level, said_level):
        await a_finding(connection, document, focus)
    kept = ValueDrafts(levels=(made["node_values"].levels[0].value,))
    await valued(connection, document, Holder("node", made["top"]), kept)  # its time span goes
    await a_finding(connection, document, span)  # as X5 left it, of rows read before

    rows = (await findings_of(connection, document.id)).rows

    found = {(row.focus_kind, row.focus_id, row.focus_label, row.holder_kind, row.holder_id) for row in rows}
    assert found == {
        ("level_assignment", level, "Optik", "node", made["top"]),
        ("level_assignment", said_level, "Sie messen.", "statement", made["said"]),
        ("time_span", span, None, None, None),  # no longer there: no holder to name
    }


async def test_a_period_s_and_a_workload_s_findings_name_the_workload_s_holder(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_tree(connection, document)
    _, span, workload, period = ids(made["node_values"])
    for focus in (span, workload, period):
        await a_finding(connection, document, focus)

    rows = (await findings_of(connection, document.id)).rows

    assert {(row.focus_kind, row.focus_id, row.holder_kind, row.holder_id) for row in rows} == {
        ("time_span", span, "node", made["top"]), ("workload", workload, "node", made["top"]),
        ("time_span", period, "node", made["top"]),
    }  # fmt: skip
    assert {row.focus_label for row in rows} == {"Optik"}


async def test_a_node_counts_the_findings_of_its_values(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_tree(connection, document)
    level, span, workload, period = ids(made["node_values"])
    for focus in (level, span, workload, period, *ids(made["said_values"])):
        await a_finding(connection, document, focus)

    tree = await read_tree(connection, owner(document), document.id)

    assert tree is not None
    [top] = tree
    assert top.findings == {"violation": 0, "warning": 5, "info": 0}  # its own and its statement's values
    assert top.children[0].findings == {"violation": 0, "warning": 0, "info": 0}


async def test_dropping_a_node_drops_the_findings_on_its_values_and_its_statements_values(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_tree(connection, document)
    other = await write_subtree(connection, document.id, node(original_title="Akustik"))
    elsewhere = ids(await valued(connection, document, Holder("node", other), ValueDrafts(levels=(LEVEL,))))
    for focus in (*ids(made["node_values"]), *ids(made["said_values"]), *elsewhere):
        await a_finding(connection, document, focus)
    revision = await one(connection, "SELECT revision FROM node WHERE id = %s", made["top"])

    await drop_node(connection, owner(document), made["top"], revision[0])

    assert await findings_left(connection) == set(elsewhere)


async def test_deleting_a_statement_drops_the_findings_on_its_levels(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_tree(connection, document)
    by_hand = await add_statement(connection, owner(document), made["top"], NEW, [HandAnchor(page=1)])
    assert by_hand is not None
    gone = ids(await valued(connection, document, Holder("statement", by_hand), ValueDrafts(levels=(LEVEL,))))
    kept = ids(made["said_values"])
    for focus in (*gone, *kept):
        await a_finding(connection, document, focus)
    revision = await one(connection, "SELECT revision FROM statement WHERE id = %s", by_hand)

    await drop_or_reject_statement(connection, owner(document), by_hand, revision[0])

    assert await findings_left(connection) == set(kept)


async def test_statements_dropped_by_a_repair_take_the_findings_on_their_levels(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_tree(connection, document)
    for focus in (*ids(made["said_values"]), *ids(made["node_values"])):
        await a_finding(connection, document, focus)

    await drop_statements(connection, document.id, [made["said"]])

    assert await findings_left(connection) == set(ids(made["node_values"]))
