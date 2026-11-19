"""The levels a holder may hold, as the form checks them (app/vocab/value_checks.py) and as the core's shapes
do (LevelAssignmentShape, its SPARQL constraints): a level the set takes passes the shape, one it refuses
the shape rejects - a qualification level at a statement, a grading or conduct level at a node or at a
statement other than a standard, a range's end of another level system than its start."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import NamedTuple

import psycopg
import pytest
from rdflib import RDF, Graph, Namespace, URIRef

from app.db.migrate import migrate
from app.domain.l2 import HolderKind, LevelDraft, ValueDrafts
from app.pipeline.shacl_child import validate_graph
from app.vocab.form_values import FieldError
from app.vocab.store import load_vocabulary
from app.vocab.value_checks import check_values, kind_of_check
from app.vocab.value_forms import ValueForm, value_form_of
from tests.support import ontology_vocabulary

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
CV = Namespace("https://w3id.org/wlo/curriculum/vocab#")
LVL = Namespace("https://w3id.org/wlo/curriculum/level/")
EX = Namespace("https://example.org/level-rules/")
LEARNING, STANDARD = str(CV.kind_learningOutcome), str(CV.kind_standard)


class Case(NamedTuple):
    name: str
    holder: HolderKind
    kind: str | None  # the statement's kind
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
    try:
        check_values(form, case.holder, ValueDrafts(levels=(draft,)), None, holder_type=case.kind)
    except FieldError as error:
        assert error.problem == "not_offered", case.name
        return error.key.removeprefix("level_assignments[0].")
    return None


def shape_rejected() -> set[str]:
    """The cases whose assignment LevelAssignmentShape rejects, all checked in one graph."""
    data = Graph()
    for case in CASES:
        holder, assignment = EX[f"{case.name}/holder"], EX[case.name]
        if case.holder == "node":
            data.add((holder, RDF.type, CUR.CurriculumNode))
        else:
            data.add((holder, RDF.type, CUR.Statement))
            data.add((holder, CUR.statementKind, URIRef(str(case.kind))))
        data.add((holder, CUR.levelAssignment, assignment))
        data.add((assignment, RDF.type, CUR.LevelAssignment))
        data.add((assignment, CUR.level, URIRef(case.level)))
        data.add((assignment, CUR.origin, CV.orig_human))
        if case.level_to is not None:
            data.add((assignment, CUR.levelTo, URIRef(case.level_to)))
        if case.dimension is not None:
            data.add((assignment, CUR.levelDimension, URIRef(case.dimension)))
    results = validate_graph(ONTOLOGY, data)
    return {
        found.focus.removeprefix(str(EX))
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
        ("not_held", "values"),
        (None, "values"),  # a number beyond its column's type: the store names no check
    ],
)
def test_a_store_s_refusal_names_the_kind_of_its_check(check: str | None, kind: str) -> None:
    assert kind_of_check(check) == kind
