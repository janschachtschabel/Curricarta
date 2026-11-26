"""The levels a holder may hold, as the form checks them (app/vocab/value_checks.py) and as the core's shapes
do (LevelAssignmentShape, its SPARQL constraints): a level the set takes passes the shape, one it refuses
the shape rejects - a qualification level at a statement, a grading or conduct level at a node or at a
statement other than a standard, a range's end of another level system than its start; a grading level at
a specification but an assessment specification, or in an applicability context (plan M3a H1); a grade at an
assessment (plan M3a J), where a node's is refused. The shapes
check each case's level as the Kern graph states it at its holder (app/exports/kern_values.py,
kern_scope.py)."""

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

import psycopg
import pytest
from rdflib import Namespace

from app.db.migrate import migrate
from app.domain.assessments import AssessmentRow
from app.domain.l2 import (
    Context,
    ContextDraft,
    HeldValues,
    Holder,
    Level,
    LevelDraft,
    Stated,
    ValueDrafts,
)
from app.exports.kern_rdf import kern_graph
from app.pipeline.shacl_child import validate_graph
from app.vocab.form_values import FieldError
from app.vocab.store import load_vocabulary
from app.vocab.value_checks import check_values, kind_of_check, refused_field
from app.vocab.value_forms import SPECIFICATION_TYPES, RuleHolder, ValueForm, value_form_of
from tests.pipeline.test_shacl import a_document
from tests.support import ontology_vocabulary

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
CV = Namespace("https://w3id.org/wlo/curriculum/vocab#")
LVL = Namespace("https://w3id.org/wlo/curriculum/level/")
LEARNING, STANDARD = str(CV.kind_learningOutcome), str(CV.kind_standard)
CURRICULUM, ASSESSMENT = (SPECIFICATION_TYPES[kind] for kind in ("curriculum", "assessmentSpecification"))
CONTEXT = "context"  # the type of the holder of a level in a curriculum's applicability context
EXAM = str(CUR.Assessment)  # an assessment's type, by its class (app/api/values.py)
STATED = Stated(str(CV.orig_human), str(CV.rev_proposed), None, 1)


class Case(NamedTuple):
    name: str
    holder: RuleHolder
    kind: str | None  # the statement's kind, the specification's class
    level: str
    level_to: str | None = None
    dimension: str | None = None
    refused_at: str | None = None  # the field the form refuses, none where it takes the level


CASES = [
    # a qualification level at a statement: by its system's dimension, or by the assignment's own
    Case("qualification_at_statement", "statement", LEARNING, str(LVL["EQF-4"]), refused_at="level"),
    Case("qualification_named_at_statement", "statement", LEARNING, str(LVL["cefr-B1"]),
         dimension=str(CV.dim_qualification), refused_at="dimension"),
    Case("qualification_at_node", "node", None, str(LVL["EQF-4"])),
    Case("proficiency_at_statement", "statement", LEARNING, str(LVL["cefr-B1"])),
    # a grading or conduct level: at a standard alone
    Case("grade_at_node", "node", None, str(LVL["grade-2"]), refused_at="level"),
    Case("grade_at_outcome", "statement", LEARNING, str(LVL["grade-2"]), refused_at="level"),
    Case("grade_at_standard", "statement", STANDARD, str(LVL["grade-2"])),
    Case("conduct_named_at_node", "node", None, str(LVL["cefr-B1"]), dimension=str(CV.dim_conduct),
         refused_at="dimension"),
    # a range's end of the start's system
    Case("range_across_systems", "node", None, str(LVL["DQR-4"]), str(LVL["EQF-5"]), refused_at="level_to"),
    Case("range_in_one_system", "node", None, str(LVL["DQR-3"]), str(LVL["DQR-5"])),
    # a qualification level at a specification and in its context; a grade at an assessment's alone
    Case("qualification_at_specification", "specification", CURRICULUM, str(LVL["EQF-4"])),
    Case("qualification_in_context", "applicability_context", CONTEXT, str(LVL["EQF-4"])),
    Case("grade_at_curriculum", "specification", CURRICULUM, str(LVL["grade-2"]), refused_at="level"),
    Case("grade_at_assessment", "specification", ASSESSMENT, str(LVL["grade-2"])),
    Case("grade_in_context", "applicability_context", CONTEXT, str(LVL["grade-2"]), refused_at="level"),
    # a grade or conduct level at an assessment: where it belongs (plan M3a J)
    Case("grade_at_exam", "assessment", EXAM, str(LVL["grade-2"])),
    Case("conduct_named_at_exam", "assessment", EXAM, str(LVL["cefr-B1"]), dimension=str(CV.dim_conduct)),
]  # fmt: skip


@pytest.fixture
async def form(database_url: str, preloaded_vocabulary: None) -> AsyncIterator[ValueForm]:
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as connection:
        yield await value_form_of(connection)


def refused(form: ValueForm, case: Case) -> str | None:
    """The field the form refuses of the case's level, none where it takes it."""
    draft = LevelDraft(level=case.level, level_to=case.level_to, dimension=case.dimension)
    drafts, prefix = ValueDrafts(levels=(draft,)), "level_assignments[0]."
    if case.holder == "applicability_context":  # a context's, set with its specification's values
        drafts, prefix = ValueDrafts(contexts=(ContextDraft(levels=(draft,)),)), "contexts[0]." + prefix
    holder = "specification" if case.holder == "applicability_context" else case.holder
    try:
        check_values(form, holder, drafts, None, holder_type=case.kind)
    except FieldError as error:
        assert error.problem == "not_offered", case.name
        return error.key.removeprefix(prefix)
    return None


def shape_rejected() -> set[str]:
    """The cases whose assignment LevelAssignmentShape rejects, all checked in one graph: a document's
    node, a learning outcome and a standard of it, its curriculum with an applicability context and an
    assessment specification, an assessment of the curriculum, each case's level at its holder."""
    rows = a_document([str(CV.addr_learner)])
    outcome = rows.statements[0] | {"statement_kind_iri": LEARNING}
    standard = outcome | {"id": uuid4(), "position": 2, "statement_kind_iri": STANDARD}
    curriculum = rows.specifications[0]
    assessment = curriculum | {"id": uuid4(), "spec_kind": "assessmentSpecification", "title": "Prüfung"}
    holders = {
        None: Holder("node", rows.nodes[0]["id"]),
        LEARNING: Holder("statement", outcome["id"]),
        STANDARD: Holder("statement", standard["id"]),
        CURRICULUM: Holder("specification", curriculum["id"]),
        ASSESSMENT: Holder("specification", assessment["id"]),
        EXAM: Holder("assessment", uuid4()),
    }
    held: dict[Holder, list[Level]] = {holder: [] for holder in holders.values()}
    in_context: list[Level] = []  # a context is no holder of a set: its levels go with the curriculum's
    named: dict[str, str] = {}
    for case in CASES:
        draft = LevelDraft(level=case.level, level_to=case.level_to, dimension=case.dimension, id=uuid4())
        (in_context if case.kind == CONTEXT else held[holders[case.kind]]).append(Level(draft, STATED))
        named[f"urn:uuid:{draft.id}"] = case.name
    context = Context(ContextDraft(id=uuid4()), STATED, tuple(in_context))
    values = {holder: HeldValues(levels=tuple(levels)) for holder, levels in held.items()}
    values[holders[CURRICULUM]] = replace(values[holders[CURRICULUM]], contexts=(context,))
    exam = AssessmentRow(
        holders[EXAM].id, "specification", curriculum["id"], 1, str(CV.ak_exam), None, None, None, None, None,
        STATED,
    )  # fmt: skip
    valued = replace(
        rows, statements=[outcome, standard], specifications=[curriculum, assessment], values=values,
        assessments=[exam],
    )  # fmt: skip
    results = validate_graph(ONTOLOGY, kern_graph(valued))
    return {
        named[found.focus]
        for found in results
        if found.severity == "violation" and found.shape == "LevelAssignmentShape"
    }


@pytest.mark.pg
@pytest.mark.anyio
async def test_a_level_the_form_takes_passes_the_shapes_and_one_it_refuses_they_reject(
    form: ValueForm,
) -> None:
    rejected = shape_rejected()

    assert {
        case.name for case in CASES if case.refused_at is not None
    } == rejected  # each constraint, both ways
    for case in CASES:
        assert refused(form, case) == case.refused_at, case.name


@pytest.mark.pg
@pytest.mark.anyio
async def test_each_level_names_its_system_s_dimension(form: ValueForm) -> None:
    assert form.dimension_of[str(LVL["EQF-4"])] == str(CV.dim_qualification)
    assert form.dimension_of[str(LVL["grade-2"])] == str(CV.dim_grading)
    assert form.dimension_of[str(LVL["cefr-B1"])] == str(CV.dim_proficiency)


@pytest.mark.parametrize(
    ("check", "kind"),
    [
        ("workload_amount_order", "workloads"),
        ("time_span_span_order", "time_spans"),
        ("level_assignment_level_fits", "level_assignments"),  # the trigger's, named by its column
        ("applicability_context_institution_text_check", "contexts"),
        ("not_held", "values"),
        (None, "values"),  # a number beyond its column's type: the store names no check
    ],
)
def test_a_store_s_refusal_names_the_kind_of_its_check(check: str | None, kind: str) -> None:
    assert kind_of_check(check) == kind
    assert refused_field(check, None) == kind


@pytest.mark.parametrize(
    ("check", "context", "field"),
    [
        ("level_assignment_level_fits", 1, "contexts[1].level_assignments"),
        ("time_span_span_order", 0, "contexts[0].time_spans"),
        ("applicability_context_institution_text_check", 2, "contexts[2]"),
        (None, 0, "contexts[0]"),
    ],
)
def test_a_store_s_refusal_in_a_context_names_that_context(
    check: str | None, context: int, field: str
) -> None:
    assert refused_field(check, context) == field
