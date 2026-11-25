"""The second layer's values in the Kern graph (plan M3a F1; app/exports/kern_values.py): each holder - a
specification, a node, a statement - states its workloads (cur:workload, cur:totalWorkload), time spans and
level assignments, each value typed with what its row holds, a workload's periods (cur:inPeriod) under it.
A value the shapes take passes them, one they reject X5 finds at the value; a rejected value and every value
of a rejected statement stay out of the graph X5 checks and of the export (test_kern_value_rows.py). How
the graph names a value - its urn:uuid in a draft, a blank node once frozen -: test_kern_naming.py."""

import asyncio
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from rdflib import RDF, XSD, Graph, Literal, URIRef

from app.domain.l2 import (
    HeldValues,
    Holder,
    Level,
    LevelDraft,
    Stated,
    TimeSpan,
    TimeSpanDraft,
    Values,
    Workload,
    WorkloadDraft,
)
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import KernRows
from app.exports.measure_kern import synthetic_rows
from app.pipeline.shacl import as_findings
from app.pipeline.shacl_child import ShaclResult, validate_graph
from tests.exports.test_kern_export import an_exporter
from tests.pipeline.test_shacl import ONTOLOGY, a_document

CV = "https://w3id.org/wlo/curriculum/vocab#"
LVL = "https://w3id.org/wlo/curriculum/level/"
VOCATIONAL = "https://w3id.org/wlo/curriculum/profile/vocational#"
STATED = Stated(CV + "orig_human", CV + "rev_proposed", None, 1)


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
