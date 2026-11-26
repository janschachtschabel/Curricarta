"""X5 reports what a shape nests (audit 2026-11-14): a value's membership in its vocabulary (``sh:node
shs:In…``) is a shape evaluated on the value, not on a row of the document, and a blank node of the graph
(what X1 read of a specification's applicability; a value once frozen) is a focus of its own shapes. A
result at a blank node is the row that holds it: the graph followed back to the nearest named subject.
Through the real builder and the real shapes, no database."""

from uuid import uuid4

import pytest
from rdflib import RDF, BNode, Graph, URIRef

from app.domain.l2 import HeldValues
from app.exports.kern_rdf import CUR, kern_graph
from app.pipeline.shacl import as_findings
from app.pipeline.shacl_child import ShaclResult, validate_graph
from tests.exports.test_kern_scope import a_context, with_applicability
from tests.exports.test_kern_values import CV, held, level, span, uri, with_values
from tests.pipeline.test_shacl import ONTOLOGY, a_document

SCHOOL, FORMAL = CV + "sec_school", CV + "form_formal"


def violations(graph: Graph) -> set[tuple[str, str, str | None, str | None]]:
    return {
        (found.focus, found.shape, found.path, found.value)
        for found in validate_graph(ONTOLOGY, graph)
        if found.severity == "violation"
    }


def at_path(graph: Graph, path: str) -> list[ShaclResult]:
    return [found for found in validate_graph(ONTOLOGY, graph) if found.path == path]


def test_a_node_s_obligation_outside_the_obligations_is_a_violation_of_the_node() -> None:
    rows = a_document([CV + "addr_learner"])
    rows.nodes[0]["obligation_iri"] = SCHOOL

    found = [
        result._replace(message="") for result in validate_graph(ONTOLOGY, kern_graph(rows))
        if result.path == "cur:obligation"
    ]  # fmt: skip

    assert found == [
        ShaclResult(
            str(uri(rows.nodes[0]["id"])), "CurriculumNodeShape", "violation", "cur:obligation", "", SCHOOL,
            "NodeConstraintComponent",
        )
    ]  # fmt: skip


def test_a_row_as_a_vocabulary_value_breaks_its_holder_alone_not_the_row() -> None:
    # the nested shape's own result (sh:detail of the node's) is at the statement, a row of the document:
    # it is part of the node's finding, no finding of the statement's
    rows = a_document([CV + "addr_learner"])
    statement = str(uri(rows.statements[0]["id"]))
    rows.nodes[0]["obligation_iri"] = statement

    results = validate_graph(ONTOLOGY, kern_graph(rows))

    found = [(result.focus, result.shape, result.path) for result in results]

    assert [result for result in found if result[0] == statement] == []
    assert [result for result in found if result[2] in ("cur:obligation", "skos:inScheme")] == [
        (str(uri(rows.nodes[0]["id"])), "CurriculumNodeShape", "cur:obligation")
    ]


def test_a_context_with_sector_and_formality_swapped_breaks_both_at_the_context() -> None:
    rows = a_document([CV + "addr_learner"])
    context = a_context(sector=FORMAL, formality=SCHOOL)
    valued = with_values(rows, {held(rows)["specification"]: HeldValues(contexts=(context,))})

    named = str(uri(context.value.id))
    assert violations(kern_graph(valued)) == {
        (named, "ApplicabilityContextShape", "cur:educationSector", FORMAL),
        (named, "ApplicabilityContextShape", "cur:formality", SCHOOL),
    }


def test_a_value_s_concept_outside_its_scheme_breaks_the_value() -> None:
    rows = a_document([CV + "addr_learner"])
    at = held(rows)
    when, which = span("time_gradeLevel", 5, 6, time_relation=SCHOOL), level("EQF-4", relation=FORMAL)
    valued = with_values(rows, {at["node"]: HeldValues(levels=(which,), time_spans=(when,))})

    assert violations(kern_graph(valued)) == {
        (str(uri(when.value.id)), "TimeSpanShape", "cur:timeRelation", SCHOOL),
        (str(uri(which.value.id)), "LevelAssignmentShape", "cur:levelRelation", FORMAL),
    }


def test_what_x1_read_with_sector_and_formality_swapped_breaks_at_its_specification() -> None:
    # X1's reading is a blank node: its shape runs on it, and its results are the specification's
    rows = with_applicability(a_document([CV + "addr_learner"]), {"sector": FORMAL, "formality": SCHOOL})
    specification = rows.specifications[0]["id"]

    results = validate_graph(ONTOLOGY, kern_graph(rows))

    assert {(found.focus, found.shape, found.path) for found in results if found.severity == "violation"} == {
        (str(uri(specification)), "ApplicabilityContextShape", "cur:educationSector"),
        (str(uri(specification)), "ApplicabilityContextShape", "cur:formality"),
    }
    findings = as_findings(results, rows.document["id"])
    assert {found.focus_id for found in findings if found.rule == "shacl.ApplicabilityContextShape"} == {
        specification
    }


def test_a_result_deep_in_blank_nodes_is_the_nearest_named_subject_s() -> None:
    # as a frozen document writes its values: a time span in a context, both blank, at a specification
    specification, context, when = URIRef("urn:uuid:00000000-0000-0000-0000-00000000000a"), BNode(), BNode()
    graph = kern_graph(a_document([CV + "addr_learner"]))
    graph.add((specification, CUR.applicability, context))
    graph.add((context, RDF.type, CUR.ApplicabilityContext))
    graph.add((context, CUR.timeSpan, when))
    graph.add((when, RDF.type, CUR.TimeSpan))
    graph.add((when, CUR.timeKind, URIRef(SCHOOL)))

    assert (str(specification), "TimeSpanShape", "cur:timeKind", SCHOOL) in violations(graph)


def test_a_finding_moved_to_its_holder_names_the_property_it_holds_it_by() -> None:
    # the specification has no cur:educationSector: the finding says it is that of its applicability
    rows = with_applicability(a_document([CV + "addr_learner"]), {"sector": FORMAL})
    [result] = at_path(kern_graph(rows), "cur:educationSector")

    [finding] = as_findings([result], rows.document["id"])

    assert finding.focus_id == rows.specifications[0]["id"]
    assert finding.details.get("held_by") == "cur:applicability"


def test_a_finding_deep_in_blank_nodes_names_the_properties_from_its_holder_down() -> None:
    specification, context, when = URIRef("urn:uuid:00000000-0000-0000-0000-00000000000a"), BNode(), BNode()
    graph = Graph()
    graph.add((specification, CUR.applicability, context))
    graph.add((context, CUR.timeSpan, when))
    graph.add((when, RDF.type, CUR.TimeSpan))
    graph.add((when, CUR.timeKind, URIRef(SCHOOL)))

    [result] = at_path(graph, "cur:timeKind")

    assert (result.focus, result.held_by) == (str(specification), "cur:applicability/cur:timeSpan")


def test_a_finding_at_a_row_itself_names_no_holder() -> None:
    rows = a_document([CV + "addr_learner"])
    rows.nodes[0]["obligation_iri"] = SCHOOL
    [result] = at_path(kern_graph(rows), "cur:obligation")

    [finding] = as_findings([result], rows.document["id"])

    assert "held_by" not in finding.details


@pytest.mark.parametrize("held", [False, True])
def test_a_value_outside_its_vocabulary_says_what_the_nested_shape_found(held: bool) -> None:
    rows = a_document([CV + "addr_learner"])
    if held:
        rows = with_applicability(rows, {"sector": FORMAL})
    else:
        rows.nodes[0]["obligation_iri"] = FORMAL
    scheme = "EducationSectors" if held else "Obligations"
    [result] = at_path(kern_graph(rows), "cur:educationSector" if held else "cur:obligation")

    # pyshacl's "See details for more information." points at a result no finding keeps: it says it
    assert "See details" not in result.message
    assert result.message.startswith(f"Value does not conform to Shape shs:In{scheme}. ")
    assert f"skos:inScheme does not contain a value in the set: ['cv:{scheme}']" in result.message


def test_a_result_at_a_blank_node_nothing_holds_is_the_document_s() -> None:
    document, loose = uuid4(), BNode()
    graph = Graph()
    graph.add((loose, RDF.type, CUR.ApplicabilityContext))
    graph.add((loose, CUR.formality, URIRef(SCHOOL)))

    [result] = [found for found in validate_graph(ONTOLOGY, graph) if found.path == "cur:formality"]
    [finding] = as_findings([result], document)

    assert result.focus == f"_:{loose}"
    assert (finding.focus_id, finding.details["focus"]) == (document, f"_:{loose}")


def test_a_sound_document_with_what_x1_read_contexts_and_values_stays_sound() -> None:
    rows = with_applicability(a_document([CV + "addr_learner"]), {"sector": SCHOOL, "formality": FORMAL})
    rows.nodes[0]["obligation_iri"] = CV + "obl_binding"
    at = held(rows)
    context = a_context(span("time_gradeLevel", 5, 6), level("EQF-4"), sector=SCHOOL, formality=FORMAL)
    valued = with_values(rows, {
        at["specification"]: HeldValues(contexts=(context,)),
        at["node"]: HeldValues(
            levels=(level("EQF-4", relation=CV + "lrel_minimum"),),
            time_spans=(span("time_gradeLevel", 5, 6, time_relation=CV + "trel_during"),),
        ),
    })  # fmt: skip

    assert violations(kern_graph(rows)) == set()  # what X1 read, a blank node: no editors' context
    assert violations(kern_graph(valued)) == set()
