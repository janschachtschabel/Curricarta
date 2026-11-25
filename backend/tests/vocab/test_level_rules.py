"""The levels a holder may hold, as the form checks them (app/vocab/value_checks.py) and as the core's shapes
do (LevelAssignmentShape, its SPARQL constraints): a level the set takes passes the shape, one it refuses
the shape rejects - a qualification level at a statement, a grading or conduct level at a node or at a
statement other than a standard, a range's end of another level system than its start. The shapes check
each case's level as the Kern graph states it at its holder (app/exports/kern_values.py)."""

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

import psycopg
import pytest
from rdflib import Namespace

from app.db.migrate import migrate
from app.domain.l2 import HeldValues, Holder, HolderKind, Level, LevelDraft, Stated, ValueDrafts
from app.exports.kern_rdf import kern_graph
from app.pipeline.shacl_child import validate_graph
from app.vocab.form_values import FieldError
from app.vocab.store import load_vocabulary
from app.vocab.value_checks import check_values, kind_of_check
from app.vocab.value_forms import ValueForm, value_form_of
from tests.pipeline.test_shacl import a_document
from tests.support import ontology_vocabulary

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
CV = Namespace("https://w3id.org/wlo/curriculum/vocab#")
LVL = Namespace("https://w3id.org/wlo/curriculum/level/")
LEARNING, STANDARD = str(CV.kind_learningOutcome), str(CV.kind_standard)
STATED = Stated(str(CV.orig_human), str(CV.rev_proposed), None, 1)


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
    """The cases whose assignment LevelAssignmentShape rejects, all checked in one graph: a document's
    node, a learning outcome and a standard of it, each case's level at its holder."""
    rows = a_document([str(CV.addr_learner)])
    outcome = rows.statements[0] | {"statement_kind_iri": LEARNING}
    standard = outcome | {"id": uuid4(), "position": 2, "statement_kind_iri": STANDARD}
    holders = {
        None: Holder("node", rows.nodes[0]["id"]),
        LEARNING: Holder("statement", outcome["id"]),
        STANDARD: Holder("statement", standard["id"]),
    }
    held: dict[Holder, list[Level]] = {holder: [] for holder in holders.values()}
    named: dict[str, str] = {}
    for case in CASES:
        draft = LevelDraft(level=case.level, level_to=case.level_to, dimension=case.dimension, id=uuid4())
        held[holders[case.kind]].append(Level(draft, STATED))
        named[f"urn:uuid:{draft.id}"] = case.name
    values = {holder: HeldValues(levels=tuple(levels)) for holder, levels in held.items()}
    results = validate_graph(
        ONTOLOGY, kern_graph(replace(rows, statements=[outcome, standard], values=values))
    )
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
        ("not_held", "values"),
        (None, "values"),  # a number beyond its column's type: the store names no check
    ],
)
def test_a_store_s_refusal_names_the_kind_of_its_check(check: str | None, kind: str) -> None:
    assert kind_of_check(check) == kind
