"""A node's placements in the Kern graph (plan M3a K; app/exports/kern_placements.py): each a cur:Placement of
its node in a specification or a variant, at a node where the editors said one, with its obligation, its grade
weight, where it came from and how far it is reviewed, and its time spans and workloads - named by its
urn:uuid in a draft and by its stored IRI once frozen. The core's shapes take a sound one; the
higher-education profile's shape finds the credits of the binding placements of one semester over 40."""

from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from rdflib import RDF, XSD, Literal, URIRef
from rdflib.namespace import PROV

from app.db.freezing import freeze
from app.db.placements import replace_placements
from app.db.values import replace_values
from app.domain.l2 import HeldValues, Holder, ValueDrafts, WorkloadDraft
from app.domain.placements import PlacementDraft, PlacementRow
from app.exports.kern_naming import draft_naming, frozen_naming
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import KernRows, read_document
from tests.db.test_editing import document
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_nodes import connection, owner, url
from tests.db.test_placements import SEMESTER, placed
from tests.exports.test_kern_naming import assert_isomorphic, under_frozen_names
from tests.exports.test_kern_values import CV, STATED, held, results, span, uri, workload
from tests.pipeline.test_shacl import a_document

__all__ = ["connection", "document", "url"]  # the fixtures, shared with tests/db
BINDING, ELECTIVE = CV + "obl_binding", CV + "obl_elective"


def a_placement(node: UUID, specification: UUID | None, **fields: Any) -> PlacementRow:
    values: dict[str, Any] = {
        "variant_id": None,
        "in_node_id": None,
        "obligation": BINDING,
        "grade_weight": None,
    }
    return PlacementRow(
        id=uuid4(), node_id=node, position=1, specification_id=specification, iri=None, stated=STATED,
        **(values | fields),
    )  # fmt: skip


def in_semester(placement: PlacementRow, semester: int, credits: int | None = None) -> PlacementRow:
    """The placement in the semester ``semester``, with ``credits`` there where given."""
    workloads = () if credits is None else (workload(credits, unit=CV + "unit_ectsCredit"),)
    return replace(
        placement, values=HeldValues(time_spans=(span("time_semester", semester),), workloads=workloads)
    )


def with_placements(rows: KernRows, *placements: PlacementRow) -> KernRows:
    """The rows with ``placements``, their values among the rows' as the store reads them."""
    found = {Holder("placement", each.id): each.values for each in placements}
    return replace(rows, placements=list(placements), values={**rows.values, **found})


def a_variant(rows: KernRows) -> tuple[KernRows, UUID]:
    variant = uuid4()
    row = {"id": variant, "iri": None, "specification_id": rows.specifications[0]["id"],
           "label": "Schwerpunkt", "variant_kind_iri": CV + "var_track"}  # fmt: skip
    return replace(rows, variants=[row]), variant


def a_second_node(rows: KernRows) -> tuple[KernRows, UUID]:
    area = {**rows.nodes[0], "id": uuid4(), "position": 2, "code": "2", "original_title": "Wahlbereich"}
    return replace(rows, nodes=[*rows.nodes, area]), area["id"]


def found_at(rows: KernRows, shape: str) -> set[tuple[str, str]]:
    return {(each.focus, each.severity) for each in results(kern_graph(rows)) if each.shape == shape}


def test_a_placement_states_its_node_place_obligation_weight_and_values() -> None:
    rows, variant = a_variant(a_document([CV + "addr_learner"]))
    rows, area = a_second_node(rows)
    at = held(rows)
    placement = in_semester(
        a_placement(at["node"].id, at["specification"].id, variant_id=variant, in_node_id=area,
                    grade_weight=Decimal("1.5")),
        3, credits=5,
    )  # fmt: skip

    graph = kern_graph(with_placements(rows, placement))

    subject = uri(placement.id)
    assert set(graph.predicate_objects(subject)) >= {
        (RDF.type, CUR.Placement), (CUR.placedUnit, uri(at["node"].id)),
        (CUR.inSpecification, uri(at["specification"].id)), (CUR.forVariant, uri(variant)),
        (CUR.inNode, uri(area)), (CUR.obligation, URIRef(BINDING)),
        (CUR.gradeWeight, Literal(Decimal("1.5"), datatype=XSD.decimal)),
        (CUR.origin, URIRef(CV + "orig_human")), (CUR.reviewStatus, URIRef(CV + "rev_proposed")),
    }  # fmt: skip
    [semester] = graph.objects(subject, CUR.timeSpan)
    assert (semester, CUR.timeKind, URIRef(CV + "time_semester")) in graph
    assert (semester, CUR["from"], Literal(Decimal(3), datatype=XSD.decimal)) in graph
    [credits] = graph.objects(subject, CUR.workload)
    assert (credits, CUR.unit, URIRef(CV + "unit_ectsCredit")) in graph


def test_a_placement_in_a_variant_alone_and_one_in_its_specification_pass_the_shapes() -> None:
    rows, variant = a_variant(a_document([CV + "addr_learner"]))
    at = held(rows)
    in_variant = a_placement(at["node"].id, None, variant_id=variant, obligation=ELECTIVE)
    in_specification = in_semester(a_placement(at["node"].id, at["specification"].id), 1, credits=5)

    found = results(kern_graph(with_placements(rows, in_variant, in_specification)))

    assert {(each.shape, each.severity) for each in found if each.severity == "violation"} == set()
    assert not {
        each for each in found if each.focus in {str(uri(in_variant.id)), str(uri(in_specification.id))}
    }


def test_the_credits_of_one_semester_s_binding_placements_over_40_are_a_warning_at_the_specification() -> (
    None
):
    rows, area = a_second_node(a_document([CV + "addr_learner"]))
    at = held(rows)
    specification = at["specification"].id
    over = [
        in_semester(a_placement(at["node"].id, specification), 1, credits=25),
        in_semester(a_placement(area, specification), 1, credits=20),
    ]
    elective = [  # an elective one counts not, nor one of another semester
        in_semester(a_placement(at["node"].id, specification), 1, credits=25),
        in_semester(a_placement(area, specification, obligation=ELECTIVE), 1, credits=20),
    ]
    other_semester = [
        in_semester(a_placement(at["node"].id, specification), 1, credits=25),
        in_semester(a_placement(area, specification), 2, credits=20),
    ]

    assert found_at(with_placements(rows, *over), "HsSemesterLoadShape") == {
        (str(uri(specification)), "warning")
    }
    assert found_at(with_placements(rows, *elective), "HsSemesterLoadShape") == set()
    assert found_at(with_placements(rows, *other_semester), "HsSemesterLoadShape") == set()


def test_a_placement_without_credits_of_its_own_counts_those_of_the_node_it_places() -> None:
    rows, area = a_second_node(a_document([CV + "addr_learner"]))
    at = held(rows)
    specification = at["specification"].id
    module_credits = {
        Holder("node", at["node"].id): HeldValues(workloads=(workload(30, unit=CV + "unit_ectsCredit"),))
    }
    rows = replace(rows, values={**rows.values, **module_credits})
    placements = [
        in_semester(a_placement(at["node"].id, specification), 4),
        in_semester(a_placement(area, specification), 4, credits=15),
    ]

    assert found_at(with_placements(rows, *placements), "HsSemesterLoadShape") == {
        (str(uri(specification)), "warning")
    }


def test_a_rejected_placement_is_not_stated() -> None:
    rows = a_document([CV + "addr_learner"])
    at = held(rows)
    rejected = replace(
        a_placement(at["node"].id, at["specification"].id),
        stated=replace(STATED, review_status=CV + "rev_rejected"),
    )

    graph = kern_graph(with_placements(rows, rejected))

    assert list(graph.subjects(RDF.type, CUR.Placement)) == []


@pytest.mark.pg
@pytest.mark.anyio
async def test_a_frozen_document_names_its_placements_by_their_iris(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    await ready(connection, document)
    await replace_placements(
        connection, owner(document), made["module"], 1,
        [PlacementDraft(BINDING, specification_id=made["specification"], in_node_id=made["area"])],
    )  # fmt: skip
    [placement] = (await read_document(connection, document.id)).placements
    credits = WorkloadDraft(Decimal(5), CV + "unit_ectsCredit", periods=(SEMESTER,))
    await replace_values(connection, owner(document), Holder("placement", placement.id), 1,
                         ValueDrafts(time_spans=(SEMESTER,), workloads=(credits,)))  # fmt: skip
    await checked(connection, document)
    await freeze(connection, document.id, BASE, accept_violations=False)
    rows = await read_document(connection, document.id)

    frozen = kern_graph(rows, frozen_naming())
    draft = kern_graph(rows, draft_naming())

    named = URIRef(f"{DOC}/placement-1")
    assert (named, RDF.type, CUR.Placement) in frozen
    assert not any("urn:uuid:" in str(term) for triple in frozen for term in triple)
    frozen.remove((URIRef(DOC), PROV.generatedAtTime, None))
    assert_isomorphic(frozen, under_frozen_names(draft, rows))
    with pytest.raises(ValueError, match="has no IRI"):
        kern_graph(replace(rows, placements=[replace(rows.placements[0], iri=None)]), frozen_naming())
