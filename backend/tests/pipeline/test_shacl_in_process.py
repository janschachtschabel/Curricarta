"""The fixture in_process_shacl (tests/shacl_in_process.py) answers as the child does: on each graph here,
the results of the real check in its child and of the stand-in at the names X5 and the MEM export call
are equal, field by field and in the order the product sorts them in.

The graphs: a sound document; the faulty example, which breaks every kind of shape it names; a document
whose statement breaks a count, a SPARQL constraint (its message's language) and whose anchor holds
values of the wrong type; the MEM plan the gate's tests build, sound and refused; and the largest graph a
switched test checks, Saxony's plan as its import hands it to X5 (about 1,350 triples). Not covered: a
deadline or a crash (the stand-in raises ShaclTimeout as the check does; test_shacl.py tests both in the
child), and graphs larger than the tests' own."""

from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import XSD

from app.core.child import ChildLog
from app.exports import mem_export
from app.exports.kern_rdf import kern_graph
from app.exports.mem_ttl import mem_graph
from app.pipeline import x5_stage
from app.pipeline.shacl import shacl_check
from app.pipeline.shacl_child import ShaclResult, ShapeSet
from tests.exports.test_mem_gate import imported, model
from tests.exports.test_mem_roundtrip import SAXONY
from tests.exports.test_mem_roundtrip import imported as imported_by_the_job
from tests.jobs.test_mem_import import setup
from tests.pipeline.test_shacl import CV, ONTOLOGY, a_document, example

CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
TOLD = ChildLog(level="WARNING", format="text", request_id="-")
pytestmark = pytest.mark.anyio
__all__ = ["setup"]  # the fixture, shared with test_mem_import


def a_sound_document() -> Graph:
    return kern_graph(a_document([CV + "addr_learner"]))


def a_broken_document() -> Graph:
    rows = a_document(addressees=[])  # StatementShape: no addressee
    rows.statements[0]["statement_kind_iri"] = CV + "kind_learningOutcome"  # a SPARQL constraint's message
    graph = kern_graph(rows)
    [anchor] = graph.subjects(CUR.pageStart, None)
    graph.set((anchor, CUR.pageStart, Literal("eins", datatype=XSD.integer)))  # ill-typed
    graph.add((anchor, CUR.quote, Literal("Licht", lang="de")))  # not an xsd:string
    return graph


def a_sound_plan() -> Graph:
    return mem_graph(imported(), model()).graph


def a_refused_plan() -> Graph:
    return mem_graph(imported(mem_land_iri=None), model()).graph


Check = Callable[..., Awaitable[list[ShaclResult]]]


def called_by(shapes: ShapeSet) -> Check:
    """The check at the name its caller looks it up by: X5's for the Kern shapes, the export's for MEM."""
    return cast(Check, vars(x5_stage if shapes == "kern" else mem_export)["shacl_check"])


GRAPHS: list[tuple[str, Callable[[], Graph], ShapeSet]] = [
    ("sound document", a_sound_document, "kern"),
    ("faulty example", lambda: example("fehlerhaft.ttl"), "kern"),
    ("broken document", a_broken_document, "kern"),
    ("sound MEM plan", a_sound_plan, "mem"),
    ("refused MEM plan", a_refused_plan, "mem"),
]


@pytest.mark.parametrize(("graph", "shapes"), [(make, shapes) for _, make, shapes in GRAPHS],
                         ids=[name for name, _, _ in GRAPHS])  # fmt: skip
async def test_the_stand_in_answers_as_the_child_does(
    in_process_shacl: None, graph: Callable[[], Graph], shapes: ShapeSet
) -> None:
    data = graph()
    asked: dict[str, Any] = {"ontology_dir": ONTOLOGY, "timeout_s": 300, "told": TOLD, "shapes": shapes}

    child = await shacl_check(data, **asked)
    stand_in = called_by(shapes)
    in_process = await stand_in(data, **asked)

    assert stand_in is not shacl_check
    assert in_process == child
    assert all(isinstance(result, ShaclResult) for result in in_process)


async def test_the_graphs_here_meet_what_they_are_here_for(in_process_shacl: None) -> None:
    async def results(data: Graph, shapes: ShapeSet) -> list[ShaclResult]:
        return await called_by(shapes)(data, ontology_dir=ONTOLOGY, timeout_s=300, told=TOLD, shapes=shapes)

    sound = await results(a_sound_document(), "kern")
    broken = await results(a_broken_document(), "kern")
    plan = await results(a_sound_plan(), "mem")
    refused = await results(a_refused_plan(), "mem")

    assert [found for found in sound if found.severity == "violation"] == []
    components = {found.component for found in broken}
    assert {"MinCountConstraintComponent", "SPARQLConstraintComponent", "DatatypeConstraintComponent"} <= (
        components
    )
    assert any(found.lang == "de" for found in broken)
    assert [found for found in plan if found.severity == "violation"] == []
    assert "LPBundeslandShape" in {found.shape for found in refused}


@pytest.mark.pg
async def test_the_stand_in_answers_as_the_child_does_on_the_largest_graph_the_tests_check(
    in_process_shacl: None, setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, connection = setup
    checked: list[tuple[Graph, dict[str, Any], list[ShaclResult]]] = []
    stand_in = called_by("kern")

    async def kept(graph: Graph, **asked: Any) -> list[ShaclResult]:
        results = await stand_in(graph, **asked)
        checked.append((graph, asked, results))
        return results

    monkeypatch.setattr(x5_stage, "shacl_check", kept)
    await imported_by_the_job(context, connection, SAXONY)

    [(graph, asked, in_process)] = checked
    assert len(graph) > 1_000
    assert await shacl_check(graph, **asked) == in_process
