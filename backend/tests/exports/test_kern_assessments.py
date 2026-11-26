"""A document's assessments in the Kern graph (plan M3a J; app/exports/kern_assessments.py): each a
cur:Assessment of its kind, a part of its assessment, specification or node, with its name, duration, weight
and grading, what it assesses and the levels at it - named by its urn:uuid in a draft and by its stored IRI
once frozen. The core's shapes take a sound one and a grade at it, find the weights of one assessment's parts
over 100 %, and refuse a grade at a node (tests/vocab/test_level_rules.py holds the form to the same)."""

from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from rdflib import RDF, SKOS, XSD, Literal, URIRef
from rdflib.namespace import PROV

from app.db.assessments import add_assessment
from app.db.freezing import freeze
from app.db.values import replace_values
from app.domain.assessments import AssessmentDraft, AssessmentRow, ParentKind, Target
from app.domain.l2 import HeldValues, Holder, Level, LevelDraft, ValueDrafts
from app.exports.kern_naming import draft_naming, frozen_naming
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import KernRows, read_document
from tests.db.test_editing import document
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_nodes import connection, owner, url
from tests.exports.test_kern_naming import assert_isomorphic, under_frozen_names
from tests.exports.test_kern_values import CV, LVL, STATED, held, results, uri
from tests.pipeline.test_shacl import a_document

__all__ = ["connection", "document", "url"]  # the fixtures, shared with tests/db
EXAM, PART = CV + "ak_exam", CV + "ak_examPart"
GRADE = LVL + "grade-2"


def an_assessment(
    parent: tuple[ParentKind, UUID], kind: str = EXAM, *targets: Target, **fields: Any
) -> AssessmentRow:
    values: dict[str, Any] = {"label": None, "duration_minutes": None, "weight_percent": None, "graded": None}
    return AssessmentRow(
        id=uuid4(), parent_kind=parent[0], parent_id=parent[1], position=1, assessment_kind=kind,
        iri=None, stated=STATED, targets=targets, **(values | fields),
    )  # fmt: skip


def graded(level: str = GRADE) -> HeldValues:
    return HeldValues(levels=(Level(LevelDraft(level=level, id=uuid4()), STATED),))


def with_assessments(rows: KernRows, *assessments: AssessmentRow, graded_at: UUID | None = None) -> KernRows:
    """The rows with ``assessments``, and a grade at the one ``graded_at``."""
    held_values = {} if graded_at is None else {Holder("assessment", graded_at): graded()}
    return replace(rows, assessments=list(assessments), values={**rows.values, **held_values})


def shaped(rows: KernRows, shape: str) -> set[str]:
    return {
        found.focus
        for found in results(kern_graph(rows))
        if found.shape == shape and found.severity == "violation"
    }


def test_an_assessment_states_its_kind_parent_fields_targets_and_levels() -> None:
    rows = a_document([CV + "addr_learner"])
    at = held(rows)
    exam = an_assessment(("specification", at["specification"].id), label="Abschlussprüfung",
                         duration_minutes=240, graded=True)  # fmt: skip
    part = an_assessment(("assessment", exam.id), PART, Target("node", at["node"].id, None),
                         Target("statement", at["statement"].id, None),
                         weight_percent=Decimal("37.5"))  # fmt: skip
    rows = with_assessments(rows, exam, part, graded_at=exam.id)

    graph = kern_graph(rows)

    subject, piece = uri(exam.id), uri(part.id)
    assert set(graph.predicate_objects(subject)) >= {
        (RDF.type, CUR.Assessment), (CUR.assessmentKind, URIRef(EXAM)),
        (CUR.partOf, uri(at["specification"].id)), (SKOS.prefLabel, Literal("Abschlussprüfung")),
        (CUR.durationMinutes, Literal(240, datatype=XSD.integer)),
        (CUR.graded, Literal(True)), (CUR.origin, URIRef(CV + "orig_human")),
        (CUR.reviewStatus, URIRef(CV + "rev_proposed")),
    }  # fmt: skip
    assert set(graph.predicate_objects(piece)) >= {
        (CUR.partOf, subject), (CUR.weightPercent, Literal(Decimal("37.5"), datatype=XSD.decimal)),
        (CUR.assesses, uri(at["node"].id)), (CUR.assesses, uri(at["statement"].id)),
    }  # fmt: skip
    [level] = graph.objects(subject, CUR.levelAssignment)
    assert (level, CUR.level, URIRef(GRADE)) in graph


def test_a_sound_assessment_and_a_grade_at_it_pass_the_shapes() -> None:
    rows = a_document([CV + "addr_learner"])
    at = held(rows)
    exam = an_assessment(("specification", at["specification"].id), label="Prüfung", graded=True)
    parts = [
        an_assessment(("assessment", exam.id), PART, weight_percent=Decimal(weight)) for weight in (60, 40)
    ]
    module = an_assessment(("node", at["node"].id), CV + "ak_moduleExam", duration_minutes=90)
    rows = with_assessments(rows, exam, *parts, module, graded_at=exam.id)

    found = {(each.shape, each.severity) for each in results(kern_graph(rows))}

    assert not {shape for shape, severity in found if severity == "violation"} & {
        "AssessmentShape", "LevelAssignmentShape",
    }  # fmt: skip


def test_the_weights_of_an_assessment_s_parts_over_100_are_a_finding_at_the_assessment() -> None:
    rows = a_document([CV + "addr_learner"])
    exam = an_assessment(("specification", held(rows)["specification"].id))
    parts = [
        an_assessment(("assessment", exam.id), PART, weight_percent=Decimal(weight)) for weight in (60, 50)
    ]
    fine = an_assessment(("specification", held(rows)["specification"].id))
    even = [
        an_assessment(("assessment", fine.id), PART, weight_percent=Decimal(weight)) for weight in (60, 40)
    ]

    assert shaped(with_assessments(rows, exam, *parts, fine, *even), "AssessmentShape") == {str(uri(exam.id))}


def test_a_grade_at_an_assessment_passes_where_one_at_a_node_is_refused() -> None:
    rows = a_document([CV + "addr_learner"])
    exam = an_assessment(("node", held(rows)["node"].id), label="Prüfung")
    rows = with_assessments(rows, exam, graded_at=exam.id)
    at_node = replace(rows, values={**rows.values, held(rows)["node"]: graded()})
    [node_grade] = at_node.values[held(rows)["node"]].levels

    assert shaped(rows, "LevelAssignmentShape") == set()
    assert shaped(at_node, "LevelAssignmentShape") == {str(uri(node_grade.value.id))}


def test_what_an_assessment_assesses_is_stated_where_the_graph_states_it() -> None:
    # a rejected statement is not read (app/exports/kern_rows.py): an assessment does not name it
    rows = a_document([CV + "addr_learner"])
    gone = Target("statement", uuid4(), "Verworfen.")
    exam = an_assessment(("specification", held(rows)["specification"].id), EXAM, gone)

    graph = kern_graph(with_assessments(rows, exam))

    assert list(graph.objects(uri(exam.id), CUR.assesses)) == []


@pytest.mark.pg
@pytest.mark.anyio
async def test_a_frozen_document_names_its_assessments_by_their_iris(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    top = await ready(connection, document)
    made = await add_assessment(
        connection, owner(document), document.id, AssessmentDraft(top, EXAM, label="Prüfung", targets=(top,))
    )
    assert made is not None
    await replace_values(
        connection, owner(document), Holder("assessment", made), 1, ValueDrafts(levels=(LevelDraft(GRADE),))
    )
    await checked(connection, document)
    await freeze(connection, document.id, BASE, accept_violations=False)
    rows = await read_document(connection, document.id)

    frozen = kern_graph(rows, frozen_naming())
    draft = kern_graph(rows, draft_naming())

    named = URIRef(f"{DOC}/assessment-1")
    assert (named, RDF.type, CUR.Assessment) in frozen
    assert not any("urn:uuid:" in str(term) for triple in frozen for term in triple)
    frozen.remove((URIRef(DOC), PROV.generatedAtTime, None))
    assert_isomorphic(frozen, under_frozen_names(draft, rows))
    with pytest.raises(ValueError, match="has no IRI"):
        kern_graph(replace(rows, assessments=[replace(rows.assessments[0], iri=None)]), frozen_naming())
