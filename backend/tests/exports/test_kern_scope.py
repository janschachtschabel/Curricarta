"""A specification's applicability in the Kern graph (plan M3a H1; app/exports/kern_scope.py): each context
the editors set (cur:applicability, cur:ApplicabilityContext) with its sector, formality, time spans and
levels - named as a value is, its urn:uuid in a draft, a blank node once frozen -; a specification without
contexts states what X1 read (specification.applicability) as one, with the time and level as written. The
shapes take a context, and a qualification level at a specification, not at a statement."""

from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from rdflib import RDF, BNode, Literal, URIRef
from rdflib.namespace import PROV

from app.db.freezing import freeze
from app.db.values import replace_values
from app.domain.l2 import (
    Context,
    ContextDraft,
    HeldValues,
    Holder,
    LevelDraft,
    TimeSpanDraft,
    ValueDrafts,
)
from app.exports.kern_naming import draft_naming, frozen_naming
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import KernRows, read_document
from tests.db.test_editing import document
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_freeze_naming import specified
from tests.db.test_nodes import connection, owner, url
from tests.exports.test_kern_naming import assert_isomorphic, under_frozen_names
from tests.exports.test_kern_values import CV, LVL, STATED, held, level, results, span, uri, with_values
from tests.pipeline.test_shacl import a_document

__all__ = ["connection", "document", "url"]  # the fixtures, shared with tests/db
SCHOOL, FORMAL = URIRef(CV + "sec_school"), URIRef(CV + "form_formal")


def a_context(*values: Any, **stated: Any) -> Context:
    levels = tuple(each for each in values if hasattr(each.value, "level"))
    spans = tuple(each for each in values if hasattr(each.value, "time_kind"))
    return Context(ContextDraft(id=uuid4(), **stated), STATED, levels, spans)


def with_applicability(rows: KernRows, applicability: dict[str, Any]) -> KernRows:
    return replace(rows, specifications=[rows.specifications[0] | {"applicability": applicability}])


def violations(rows: KernRows, shape: str) -> set[str]:
    return {found.focus for found in results(kern_graph(rows)) if found.shape == shape}


def test_a_context_holds_sector_formality_time_and_level() -> None:
    rows = a_document([CV + "addr_learner"])
    specification = held(rows)["specification"]
    when, which = span("time_gradeLevel", 5, 6), level("EQF-4")
    context = a_context(when, which, sector=str(SCHOOL), formality=str(FORMAL), institution_text="Gymnasium")
    valued = with_values(rows, {specification: HeldValues(contexts=(context,))})

    graph = kern_graph(valued)

    named = uri(context.value.id)
    assert (uri(specification.id), CUR.applicability, named) in graph
    assert set(graph.predicate_objects(named)) == {
        (RDF.type, CUR.ApplicabilityContext), (CUR.educationSector, SCHOOL), (CUR.formality, FORMAL),
        (CUR.timeSpan, uri(when.value.id)), (CUR.levelAssignment, uri(which.value.id)),
    }  # fmt: skip
    assert (uri(when.value.id), RDF.type, CUR.TimeSpan) in graph
    assert (uri(which.value.id), CUR.level, URIRef(LVL + "EQF-4")) in graph
    # the shapes take it: the contexts add no result to those of the document without them
    assert results(graph) == results(kern_graph(rows))


def test_a_document_without_context_rows_states_what_x1_read() -> None:
    plain = a_document([CV + "addr_learner"])
    rows = with_applicability(plain, {
        "sector": str(SCHOOL), "formality": str(FORMAL), "timeKind": CV + "time_gradeLevel",
        "timeText": "Ende Jahrgangsstufe 6", "levelText": "Niveaustufe D", "institutionText": "Gymnasium",
        "targetGroupText": None,
    })  # fmt: skip
    specification = uri(rows.specifications[0]["id"])

    graph = kern_graph(rows)

    [context] = graph.objects(specification, CUR.applicability)
    assert isinstance(context, BNode)  # no row of its own: X5 finds nothing at it
    assert set(graph.predicate_objects(context)) == {
        (RDF.type, CUR.ApplicabilityContext), (CUR.educationSector, SCHOOL), (CUR.formality, FORMAL),
        (CUR.timeText, Literal("Ende Jahrgangsstufe 6")), (CUR.levelText, Literal("Niveaustufe D")),
    }  # fmt: skip
    assert results(graph) == results(kern_graph(plain))


def test_what_x1_read_gives_way_to_the_editors_contexts_and_nothing_read_states_none() -> None:
    read = {"sector": str(SCHOOL), "formality": None, "timeText": "Klasse 5", "levelText": None}
    rows = with_applicability(a_document([CV + "addr_learner"]), read)
    specification = held(rows)["specification"]
    context = a_context(formality=str(FORMAL))
    nothing = with_applicability(rows, {"sector": None, "formality": None, "timeText": None})

    set_by_editors = kern_graph(with_values(rows, {specification: HeldValues(contexts=(context,))}))

    assert list(set_by_editors.objects(uri(specification.id), CUR.applicability)) == [uri(context.value.id)]
    assert (None, CUR.timeText, Literal("Klasse 5")) not in set_by_editors
    assert list(kern_graph(nothing).objects(uri(specification.id), CUR.applicability)) == []


def test_a_qualification_level_stands_at_the_specification_not_at_a_statement() -> None:
    rows = a_document([CV + "addr_learner"])
    at = held(rows)
    at_specification, in_context, at_statement = level("EQF-4"), level("EQF-4"), level("EQF-4")
    context = a_context(in_context)
    valued = with_values(rows, {
        at["specification"]: HeldValues(levels=(at_specification,), contexts=(context,)),
        at["statement"]: HeldValues(levels=(at_statement,)),
    })  # fmt: skip

    assert violations(valued, "LevelAssignmentShape") == {str(uri(at_statement.value.id))}


def test_a_curriculum_s_field_set_lifts_the_warning_of_a_curriculum_without_one() -> None:
    rows = a_document([CV + "addr_learner"])
    without = replace(rows, specifications=[rows.specifications[0] | {"field_text": None}])

    assert violations(without, "SpecificationFieldShape") == {str(uri(rows.specifications[0]["id"]))}
    assert violations(rows, "SpecificationFieldShape") == set()


@pytest.mark.pg
@pytest.mark.anyio
async def test_the_frozen_graph_with_contexts_is_the_draft_graph_under_other_names(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # a context and its values each a blank node of its own; what X1 read of a specification without
    # contexts a blank node in either naming
    await ready(connection, document)
    specification = await specified(connection, document.id, "lp")
    read = await specified(connection, document.id, "lp-g8")
    await connection.execute(
        "UPDATE specification SET applicability = %s WHERE id = %s",
        (Jsonb({"sector": str(SCHOOL), "timeText": "Klasse 5"}), read),
    )
    context = ContextDraft(
        sector=str(SCHOOL), levels=(LevelDraft(level=LVL + "EQF-4"),),
        time_spans=(TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=Decimal(5)),),
    )  # fmt: skip
    holder = Holder("specification", specification)
    await replace_values(connection, owner(document), holder, 1, ValueDrafts(contexts=(context,)))
    await checked(connection, document)
    await freeze(connection, document.id, BASE, accept_violations=False)
    rows = await read_document(connection, document.id)

    frozen = kern_graph(rows, frozen_naming())

    terms = {term for triple in frozen for term in (triple[0], triple[2])}
    assert not [term for term in terms if str(term).startswith("urn:uuid:")]
    assert len(list(frozen.subjects(RDF.type, CUR.ApplicabilityContext))) == 2
    frozen.remove((URIRef(DOC), PROV.generatedAtTime, None))
    assert_isomorphic(frozen, under_frozen_names(kern_graph(rows, draft_naming()), rows))
