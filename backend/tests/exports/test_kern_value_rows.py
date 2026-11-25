"""The values of a document's holders as app/exports/kern_rows.py reads them for the Kern graph (plan M3a
F1): all its holders' values, each a value of the graph; a rejected value - a workload with its periods -
and every value of a rejected statement left out of the graph X5 checks and of the export, a rejected node's
values following their own status. Values change the draft graph by their own triples alone, and a frozen
document's values change no more: the kept export's key needs not name them. The triples:
test_kern_values.py."""

from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest
from rdflib import RDF, Graph, URIRef

from app.db.anchors import new_entity
from app.db.freezing import freeze
from app.db.values import replace_values, values_of
from app.domain.l2 import Holder, HolderKind, LevelDraft, TimeSpanDraft, ValueDrafts, WorkloadDraft
from app.exports.kern_child import turtle
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import read_document
from tests.db.test_editing import document
from tests.db.test_freeze import checked, ready
from tests.db.test_nodes import connection, owner, url
from tests.db.test_values import holders

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with tests/db

CV = "https://w3id.org/wlo/curriculum/vocab#"
LVL = "https://w3id.org/wlo/curriculum/level/"
CONFIRMED, REJECTED = CV + "rev_confirmed", CV + "rev_rejected"
BASE = "https://example.org/kk/"
# a value added - a copy of one of its table's rows under an entity of its own, at a free position -,
# changed and taken away
FROZEN_CHANGES = (
    "INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table}, to_jsonb(t)"
    " || jsonb_build_object('id', %(added)s::uuid, 'position', 9))).*"
    " FROM {table} t WHERE document_id = %(document)s LIMIT 1",
    "UPDATE {table} SET updated_at = now() WHERE document_id = %(document)s",
    "DELETE FROM {table} WHERE document_id = %(document)s",
)


def uri(value_id: UUID | None) -> URIRef:
    return URIRef(f"urn:uuid:{value_id}")


async def a_document_with_values(connection: psycopg.AsyncConnection, document: Any) -> dict[Any, Any]:
    """A node, its statement and a specification of the document, each with values set."""
    at = await holders(connection, document)
    year = TimeSpanDraft(time_kind=CV + "time_trainingYear", span_from=Decimal(1))
    lessons = WorkloadDraft(amount=Decimal(40), unit=CV + "unit_lesson", periods=(year, year))
    sets: dict[HolderKind, ValueDrafts] = {
        "node": ValueDrafts(
            levels=(LevelDraft(level=LVL + "EQF-4"), LevelDraft(level=LVL + "EQF-5")),
            time_spans=(TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=Decimal(5)),) * 2,
            workloads=(lessons, lessons),
        ),
        "statement": ValueDrafts(levels=(LevelDraft(level=LVL + "cefr-B1"),)),
        "specification": ValueDrafts(workloads=(replace(lessons, periods=(), total=True),)),
    }
    for kind, drafts in sets.items():
        await replace_values(connection, owner(document), at[kind], 1, drafts)
    return {**at, "values": await values_of(connection, document.id)}


async def status(connection: psycopg.AsyncConnection, table: str, row: UUID | None, review: str) -> None:
    await connection.execute(f"UPDATE {table} SET review_status_iri = %s WHERE id = %s", (review, row))  # noqa: S608


def stated_values(graph: Graph) -> set[Any]:
    kinds = (CUR.Workload, CUR.TimeSpan, CUR.LevelAssignment)
    return {value for kind in kinds for value in graph.subjects(RDF.type, kind)}


async def test_the_rows_carry_the_document_s_values_and_a_value_of_a_kept_holder_is_in(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_document_with_values(connection, document)
    every = [made["values"][made[kind]] for kind in ("node", "statement", "specification")]
    node = every[0]
    await status(connection, "level_assignment", node.levels[1].value.id, CONFIRMED)

    graph = kern_graph(await read_document(connection, document.id))

    ids = {each.value.id for held in every for kind in (held.levels, held.time_spans) for each in kind}
    ids |= {each.value.id for held in every for each in held.workloads}
    ids |= {period.value.id for held in every for each in held.workloads for period in each.periods}
    assert stated_values(graph) == {uri(value_id) for value_id in ids} and len(ids) == 12
    assert (uri(made["node"].id), CUR.workload, uri(node.workloads[0].value.id)) in graph
    assert (uri(made["statement"].id), CUR.levelAssignment, uri(every[1].levels[0].value.id)) in graph


async def test_a_rejected_value_and_every_value_of_a_rejected_statement_stay_out(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_document_with_values(connection, document)
    node, said = made["values"][made["node"]], made["values"][made["statement"]]
    gone_workload, kept_workload = node.workloads
    for table, row in (
        ("level_assignment", node.levels[0].value.id), ("time_span", node.time_spans[0].value.id),
        ("workload", gone_workload.value.id), ("time_span", kept_workload.periods[0].value.id),
    ):  # fmt: skip
        await status(connection, table, row, REJECTED)
    await status(connection, "statement", made["statement"].id, REJECTED)
    # a rejected node stays: its values follow their own status
    await status(connection, "node", made["node"].id, REJECTED)

    graph = kern_graph(await read_document(connection, document.id))

    stated = stated_values(graph)
    out = [
        node.levels[0],
        node.time_spans[0],
        gone_workload,
        *gone_workload.periods,
        kept_workload.periods[0],
    ]
    out += [said.levels[0]]  # the rejected statement's, with it
    assert not stated & {uri(value.value.id) for value in out}
    kept = [node.levels[1], node.time_spans[1], kept_workload, kept_workload.periods[1]]
    assert {uri(value.value.id) for value in kept} <= stated
    assert set(graph.objects(uri(kept_workload.value.id), CUR.inPeriod)) == {
        uri(kept_workload.periods[1].value.id)
    }


async def test_the_draft_graph_changes_by_the_value_triples_alone(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    await a_document_with_values(connection, document)
    rows = await read_document(connection, document.id)

    valued, plain = kern_graph(rows), kern_graph(replace(rows, values={}))

    assert not plain - valued
    values = stated_values(valued)
    assert values and all(subject in values or value in values for subject, _, value in valued - plain)


async def test_a_frozen_document_s_values_are_exported_and_change_no_more(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the kept export's key needs not name them (app/exports/kern_export.py, fingerprint): the store refuses
    # every change of a frozen document's values (keep_frozen_rows), so its rows say them once for all
    top = await ready(connection, document)
    period = TimeSpanDraft(time_kind=CV + "time_trainingYear", span_from=Decimal(1))
    drafts = ValueDrafts(
        levels=(LevelDraft(level=LVL + "EQF-4"),),
        time_spans=(TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=Decimal(5)),),
        workloads=(WorkloadDraft(amount=Decimal(40), unit=CV + "unit_lesson", periods=(period,)),),
    )
    await replace_values(connection, owner(document), Holder("node", top), 1, drafts)
    await checked(connection, document)
    await freeze(connection, document.id, BASE, accept_violations=False)
    rows = await read_document(connection, document.id)

    made = turtle(rows)
    assert b"cur:workload" in made and b"cur:timeSpan" in made and b"cur:levelAssignment" in made
    for table in ("workload", "time_span", "level_assignment"):
        added = await new_entity(connection, table)
        for change in FROZEN_CHANGES:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                await connection.execute(
                    change.format(table=table), {"document": document.id, "added": added}
                )
