"""The fixture in_process_shacl (tests/shacl_in_process.py) answers as the child does: on each graph here,
the results of the real check in its child and of the stand-in at the names X5 and the MEM export call
are equal, field by field and in the order the product sorts them in.

The graphs: a sound document; the faulty example, which breaks every kind of shape it names; a document
whose statement breaks a count, a SPARQL constraint (its message's language) and whose anchor holds
values of the wrong type; the MEM plan the gate's tests build, sound, refused, and with a reference held
by none and pointing at nothing (VerweisShape, an inverse path among its results); the largest graph a
switched test checks, Saxony's plan as its import hands it to X5 (about 1,350 triples); and the KMK's plan
typed a Lehrplan as its import hands it to X5 (the profile's warnings of its Regelstandards). Not covered: a
deadline or a crash (the stand-in raises ShaclTimeout as the check does; test_shacl.py tests both in the
child), and graphs larger than the tests' own."""

import ast
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from app.core.child import ChildLog
from app.exports import mem_export
from app.exports.kern_rdf import kern_graph
from app.exports.mem_ttl import mem_graph
from app.pipeline import x5_stage
from app.pipeline.shacl import ShaclCrashed, shacl_check
from app.pipeline.shacl_child import ShaclResult, ShapeSet
from tests.exports.test_mem_gate import imported, model
from tests.exports.test_mem_roundtrip import KMK, SAXONY, Kind
from tests.exports.test_mem_roundtrip import imported as imported_by_the_job
from tests.jobs.test_mem_import import setup
from tests.pipeline.test_shacl import CV, ONTOLOGY, a_document, example

CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
LP = "https://w3id.org/lehrplan/ontology/"
HAS_REFERENCE = URIRef(LP + "LP_0030071")  # hat verweis
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


def a_plan_with_a_reference_of_nothing() -> Graph:
    rows = imported()
    reference = next(row for row in rows.statements if row["statement_kind_iri"] == CV + "kind_reference")
    reference["mem_properties"] = {key: value for key, value in reference["mem_properties"].items()
                                   if key != "targets"}  # fmt: skip
    graph = mem_graph(rows, model()).graph
    graph.remove((None, HAS_REFERENCE, URIRef(reference["mem_iri"])))  # held by none
    return graph


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
    ("MEM plan with a reference of nothing", a_plan_with_a_reference_of_nothing, "mem"),
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
    nothing = await results(a_plan_with_a_reference_of_nothing(), "mem")

    assert [found for found in sound if found.severity == "violation"] == []
    assert any(found.severity == "warning" for found in sound)
    components = {found.component for found in broken}
    assert {"MinCountConstraintComponent", "SPARQLConstraintComponent", "DatatypeConstraintComponent"} <= (
        components
    )
    assert any(found.lang == "de" for found in broken)
    assert [found for found in plan if found.severity == "violation"] == []
    assert "LPBundeslandShape" in {found.shape for found in refused}
    referred = [found for found in nothing if found.shape == "VerweisShape"]
    assert len(referred) == 2 and any((found.path or "").startswith("^") for found in referred)


KMK_AS_LEHRPLAN = Kind("kmk", None, LP + "LP_0000571", "DE", "dt-Lehrplan", "curriculum", "KMK", KMK.work)


@pytest.mark.pg
@pytest.mark.parametrize("kind", [SAXONY, KMK_AS_LEHRPLAN], ids=["Saxony", "KMK typed a Lehrplan"])
async def test_the_stand_in_answers_as_the_child_does_on_a_plan_as_its_import_hands_it_to_x5(
    in_process_shacl: None, setup: Any, monkeypatch: pytest.MonkeyPatch, kind: Kind
) -> None:
    context, connection = setup
    checked: list[tuple[Graph, dict[str, Any], list[ShaclResult]]] = []
    stand_in = called_by("kern")

    async def kept(graph: Graph, **asked: Any) -> list[ShaclResult]:
        results = await stand_in(graph, **asked)
        checked.append((graph, asked, results))
        return results

    monkeypatch.setattr(x5_stage, "shacl_check", kept)
    await imported_by_the_job(context, connection, kind)

    [(graph, asked, in_process)] = checked
    assert await shacl_check(graph, **asked) == in_process
    if kind is SAXONY:
        assert len(graph) > 1_000  # the largest graph a switched test checks
    else:  # the profile warns of a Regelstandard outside the KMK's standards
        regelstandards = [found for found in in_process if found.shape == "SchulRegelstandardShape"]
        assert regelstandards and {found.severity for found in regelstandards} == {"warning"}


async def test_a_validation_that_breaks_comes_back_as_the_child_s_does(
    in_process_shacl: None, tmp_path: Path
) -> None:
    # the shapes are missing: both ways refuse the path, by the error's kind and in the same words
    asked: dict[str, Any] = {"ontology_dir": tmp_path, "timeout_s": 120, "told": TOLD}
    data = a_sound_document()

    with pytest.raises(ShaclCrashed) as child:
        await shacl_check(data, **asked)
    with pytest.raises(ShaclCrashed) as in_process:
        await called_by("kern")(data, **asked)

    assert (
        str(in_process.value)
        == str(child.value)
        == "the SHACL validation raised FileNotFoundError in its process"
    )


TESTS = Path(__file__).resolve().parents[1]
# each caller of the check keeps a test on the real child (the tests of the check itself: test_shacl.py)
ON_THE_CHILD = {
    "pipeline/test_x5_stage.py": [
        "test_x5_checks_the_document_after_x4_and_writes_its_findings_on_their_rows",
        "test_x5_after_a_crashed_check_writes_its_findings_once_and_counts_the_anchors_as_they_stand",
    ],
    "pipeline/test_x5_check.py": ["test_an_import_whose_tree_is_written_is_checked_with_no_x5_before"],
    "pipeline/test_x6_repair.py": [
        "test_a_repair_asks_again_only_the_packages_with_defects_and_checks_the_document_again"
    ],
    "jobs/test_mem_import.py": ["test_an_import_writes_the_plan_s_tree_as_imported_rows_then_checks_it"],
    "exports/test_mem_export.py": [
        "test_a_state_the_shapes_refuse_is_no_export_and_leaves_its_violations_alone"
    ],
    "api/test_exports.py": ["test_a_state_the_shapes_refuse_answers_with_its_violations"],
    "exports/test_mem_roundtrip.py": ["test_saxony_s_plan_imported_frozen_and_exported_meets_the_mem_shapes"],
}


def _functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.mark.parametrize("file", sorted(ON_THE_CHILD))
def test_the_tests_kept_on_the_child_do_not_ask_for_the_stand_in(file: str) -> None:
    functions = _functions(TESTS / file)

    for name in ON_THE_CHILD[file]:
        arguments = functions[name].args
        assert "in_process_shacl" not in [each.arg for each in arguments.args + arguments.kwonlyargs], name


def test_the_stand_in_is_asked_for_by_name_alone() -> None:
    fixture = _functions(TESTS / "conftest.py")["in_process_shacl"]

    [decorator] = fixture.decorator_list
    assert ast.unparse(decorator) == "pytest.fixture"  # no autouse, no usefixtures in a module of the callers
    for file in ON_THE_CHILD:
        assert 'usefixtures("in_process_shacl")' not in (TESTS / file).read_text(encoding="utf-8"), file
