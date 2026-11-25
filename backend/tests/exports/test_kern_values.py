"""The second layer's values in the Kern graph (plan M3a F1; app/exports/kern_values.py): each holder - a
specification, a node, a statement - states its workloads (cur:workload, cur:totalWorkload), time spans and
level assignments, each value typed with what its row holds, a workload's periods (cur:inPeriod) under it.
A value the shapes take passes them, one they reject X5 finds at the value; a rejected value and every value
of a rejected statement stay out of the graph X5 checks and of the export. How the graph names a value -
its urn:uuid in a draft, a blank node once frozen -: test_kern_naming.py."""

import asyncio
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from rdflib import RDF, XSD, Graph, Literal, URIRef

from app.db.freezing import freeze
from app.db.values import replace_values, values_of
from app.domain.l2 import (
    HeldValues,
    Holder,
    HolderKind,
    Level,
    LevelDraft,
    Stated,
    TimeSpan,
    TimeSpanDraft,
    ValueDrafts,
    Values,
    Workload,
    WorkloadDraft,
)
from app.exports.kern_child import turtle
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import KernRows, read_document
from app.exports.measure_kern import synthetic_rows
from app.pipeline.shacl import as_findings
from app.pipeline.shacl_child import ShaclResult, validate_graph
from tests.db.test_editing import document
from tests.db.test_freeze import checked, ready
from tests.db.test_nodes import connection, owner, url
from tests.db.test_values import holders
from tests.exports.test_kern_export import an_exporter
from tests.pipeline.test_shacl import ONTOLOGY, a_document

__all__ = ["connection", "document", "url"]  # the fixtures, shared with tests/db

CV = "https://w3id.org/wlo/curriculum/vocab#"
LVL = "https://w3id.org/wlo/curriculum/level/"
VOCATIONAL = "https://w3id.org/wlo/curriculum/profile/vocational#"
STANDARD = CV + "kind_standard"
PROPOSED, CONFIRMED, REJECTED = CV + "rev_proposed", CV + "rev_confirmed", CV + "rev_rejected"
STATED = Stated(CV + "orig_human", PROPOSED, None, 1)
BASE = "https://example.org/kk/"


def uri(value_id: UUID | None) -> URIRef:
    return URIRef(f"urn:uuid:{value_id}")


def level(name: str, **more: Any) -> Level:
    return Level(LevelDraft(level=LVL + name, id=uuid4(), **more), STATED)


def span(kind: str, start: int | None = None, end: int | None = None, **more: Any) -> TimeSpan:
    least, most = (None if at is None else Decimal(at) for at in (start, end))
    return TimeSpan(
        TimeSpanDraft(time_kind=CV + kind, span_from=least, span_to=most, id=uuid4(), **more), STATED
    )


def workload(amount: int, *periods: TimeSpan, **more: Any) -> Workload:
    more.setdefault("unit", CV + "unit_lesson")
    return Workload(WorkloadDraft(amount=Decimal(amount), id=uuid4(), **more), STATED, periods)


def held(rows: KernRows) -> dict[str, Holder]:
    """The holders of a document of one specification, one node and one statement (a_document)."""
    return {
        "specification": Holder("specification", rows.specifications[0]["id"]),
        "node": Holder("node", rows.nodes[0]["id"]),
        "statement": Holder("statement", rows.statements[0]["id"]),
    }


def with_values(rows: KernRows, values: Values) -> KernRows:
    return replace(rows, values=values)


def results(graph: Graph) -> set[ShaclResult]:
    return set(validate_graph(ONTOLOGY, graph))


def test_each_value_states_what_its_row_holds_at_its_holder() -> None:
    rows = a_document([CV + "addr_learner"])
    at = held(rows)
    year = span("time_trainingYear", 1, 1)
    part = workload(40, year, amount_to=Decimal(50), workload_kind=CV + "wl_guidanceValue",
                    is_recommendation=True, minutes_per_unit=45)  # fmt: skip
    whole = workload(280, total=True)
    when = span("time_gradeLevel", 5, 6, time_relation=CV + "trel_during")
    told = level("DQR-3", level_to=LVL + "DQR-5", relation=CV + "lrel_range", dimension=CV + "dim_attainment",
                 competence_dimension=None)  # fmt: skip
    rows = with_values(rows, {
        at["node"]: HeldValues(time_spans=(when,), workloads=(part,)),
        at["specification"]: HeldValues(workloads=(whole,)),
        at["statement"]: HeldValues(levels=(told,)),
    })  # fmt: skip

    graph = kern_graph(rows)

    node, spec, said = (uri(holder.id) for holder in (at["node"], at["specification"], at["statement"]))
    number = XSD.decimal
    assert (node, CUR.workload, uri(part.value.id)) in graph
    assert (spec, CUR.totalWorkload, uri(whole.value.id)) in graph
    assert (node, CUR.timeSpan, uri(when.value.id)) in graph
    assert (said, CUR.levelAssignment, uri(told.value.id)) in graph
    assert set(graph.predicate_objects(uri(part.value.id))) == {
        (RDF.type, CUR.Workload), (CUR.amount, Literal(Decimal(40), datatype=number)),
        (CUR.amountTo, Literal(Decimal(50), datatype=number)), (CUR.unit, URIRef(CV + "unit_lesson")),
        (CUR.workloadKind, URIRef(CV + "wl_guidanceValue")), (CUR.isRecommendation, Literal(True)),
        (CUR.minutesPerUnit, Literal(45)), (CUR.inPeriod, uri(year.value.id)),
    }  # fmt: skip
    assert set(graph.predicate_objects(uri(year.value.id))) == {
        (RDF.type, CUR.TimeSpan), (CUR.timeKind, URIRef(CV + "time_trainingYear")),
        (CUR["from"], Literal(Decimal(1), datatype=number)),
        (CUR.to, Literal(Decimal(1), datatype=number)),
    }  # fmt: skip
    assert (uri(whole.value.id), CUR.isRecommendation, Literal(False)) in graph
    assert (uri(when.value.id), CUR.timeRelation, URIRef(CV + "trel_during")) in graph
    assert set(graph.predicate_objects(uri(told.value.id))) == {
        (RDF.type, CUR.LevelAssignment), (CUR.level, URIRef(LVL + "DQR-3")),
        (CUR.levelTo, URIRef(LVL + "DQR-5")), (CUR.levelRelation, URIRef(CV + "lrel_range")),
        (CUR.levelDimension, URIRef(CV + "dim_attainment")), (CUR.origin, URIRef(CV + "orig_human")),
    }  # fmt: skip
    # a period is the workload's alone, not its holder's time span
    assert (node, CUR.timeSpan, uri(year.value.id)) not in graph


def test_each_kind_of_value_passes_its_shape() -> None:
    rows = a_document([CV + "addr_learner"])
    at = held(rows)
    valued = with_values(rows, {
        at["node"]: HeldValues(
            levels=(level("EQF-4"),), time_spans=(span("time_gradeLevel", 5, 6),),
            workloads=(workload(40, span("time_trainingYear", 1, 2), amount_to=Decimal(50)),),
        ),
        at["specification"]: HeldValues(levels=(level("DQR-4"),), workloads=(workload(280, total=True),)),
        at["statement"]: HeldValues(levels=(level("cefr-B1", relation=CV + "lrel_target"),)),
    })  # fmt: skip

    # the values add no result to those of the document without them
    assert results(kern_graph(valued)) == results(kern_graph(rows))


def test_x5_finds_each_value_its_shape_rejects_at_the_value() -> None:
    rows = a_document([CV + "addr_learner"])
    at = held(rows)
    unitless = workload(40, unit=cast(Any, None))
    backwards = span("time_gradeLevel", 6, 5)
    qualification = level("DQR-4")  # at a statement
    grade = level("grade-2")  # at a node
    across = level("DQR-4", level_to=LVL + "EQF-5")
    rows = with_values(rows, {
        at["node"]: HeldValues(levels=(grade, across), time_spans=(backwards,), workloads=(unitless,)),
        at["statement"]: HeldValues(levels=(qualification,)),
    })  # fmt: skip

    found = {
        (finding.focus_id, finding.rule)
        for finding in as_findings(validate_graph(ONTOLOGY, kern_graph(rows)), rows.document["id"])
        if finding.severity == "violation"
    }

    assert {
        (unitless.value.id, "shacl.WorkloadShape"), (backwards.value.id, "shacl.TimeSpanShape"),
        (qualification.value.id, "shacl.LevelAssignmentShape"),
        (grade.value.id, "shacl.LevelAssignmentShape"), (across.value.id, "shacl.LevelAssignmentShape"),
    } <= found  # fmt: skip


def test_a_lernfeld_with_a_workload_no_longer_lacks_its_guidance_value() -> None:
    rows = a_document([CV + "addr_learner"])
    lernfeld = rows.nodes[0] | {"function_iri": CV + "fn_unit", "node_type_iri": VOCATIONAL + "Lernfeld"}
    rows = replace(rows, nodes=[lernfeld])
    guidance = workload(80, workload_kind=CV + "wl_guidanceValue")
    guided = with_values(rows, {Holder("node", lernfeld["id"]): HeldValues(workloads=(guidance,))})

    def lacks(graph: Graph) -> set[str]:
        return {
            found.message for found in validate_graph(ONTOLOGY, graph) if found.shape == "BerufLernfeldShape"
        }

    assert lacks(kern_graph(rows)) == {"Lernfeld ohne Zeitrichtwert.", "Lernfeld ohne Ausbildungsjahr."}
    assert lacks(kern_graph(guided)) == {"Lernfeld ohne Ausbildungsjahr."}


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


@pytest.mark.pg
@pytest.mark.anyio
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


@pytest.mark.pg
@pytest.mark.anyio
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


@pytest.mark.pg
@pytest.mark.anyio
async def test_the_draft_graph_changes_by_the_value_triples_alone(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    await a_document_with_values(connection, document)
    rows = await read_document(connection, document.id)

    valued, plain = kern_graph(rows), kern_graph(replace(rows, values={}))

    assert not plain - valued
    values = stated_values(valued)
    assert values and all(subject in values or value in values for subject, _, value in valued - plain)


@pytest.mark.pg
@pytest.mark.anyio
async def test_a_frozen_document_s_values_are_exported_and_change_no_more(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the kept export's key needs not name them (app/exports/kern_export.py, fingerprint): the store refuses
    # every change of a frozen document's values (keep_frozen_rows), so its rows say them once for all
    top = await ready(connection, document)
    drafts = ValueDrafts(workloads=(WorkloadDraft(amount=Decimal(40), unit=CV + "unit_lesson"),))
    await replace_values(connection, owner(document), Holder("node", top), 1, drafts)
    await checked(connection, document)
    await freeze(connection, document.id, BASE, accept_violations=False)
    rows = await read_document(connection, document.id)

    assert b"cur:workload" in turtle(rows)
    for change in (
        "UPDATE workload SET amount = 41 WHERE document_id = %s",
        "DELETE FROM workload WHERE document_id = %s",
    ):
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            await connection.execute(change, (document.id,))


@pytest.mark.anyio
async def test_two_builds_of_a_document_with_values_give_the_same_bytes(tmp_path: Path) -> None:
    # two processes, each its own hash seed: each value's blank node is labelled in the order of its row
    rows = synthetic_rows(nodes=4, statements=8)
    rows = with_values(
        rows,
        {
            Holder("node", node["id"]): HeldValues(
                levels=(level("EQF-4"), level("EQF-5")),
                time_spans=(span("time_gradeLevel", 5),),
                workloads=(workload(40, span("time_trainingYear", 1), span("time_trainingYear", 2)),),
            )
            for node in rows.nodes
        }
        | {
            Holder("statement", said["id"]): HeldValues(levels=(level("cefr-B1"),))
            for said in rows.statements
        },
    )

    one, other = await asyncio.gather(
        an_exporter(tmp_path / "one").export(rows), an_exporter(tmp_path / "other").export(rows)
    )

    made = (tmp_path / "one" / one.key).read_bytes()
    assert made == (tmp_path / "other" / other.key).read_bytes()
    assert made.count(b"cur:LevelAssignment") == 4 * 2 + 8 and b"cur:inPeriod" in made
