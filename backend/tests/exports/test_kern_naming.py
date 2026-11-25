"""The Kern graph under its two namings (plan M3a A1): a draft names every row by its urn:uuid, as X5 checks
it; a frozen document names its work, document, nodes and statements by the IRIs freezing stored, its
anchors, its file and its values by blank nodes - one graph under other names, plus the time the document
was frozen.
Either way the document says the work it is a version of, its revision and the file it is in."""

from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest
from rdflib import OWL, RDF, BNode, Graph, Literal, Node, URIRef
from rdflib.compare import graph_diff, isomorphic, to_isomorphic
from rdflib.namespace import DCTERMS, PROV

from app.db.draft_copy import copy_document
from app.db.freezing import freeze
from app.db.values import replace_values
from app.domain.l2 import Holder, LevelDraft, TimeSpanDraft, ValueDrafts, WorkloadDraft
from app.exports.kern_naming import draft_naming, frozen_naming
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import KernRows, read_document
from app.pipeline.shacl_child import validate_graph
from tests.db.test_editing import document
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_freeze_naming import specified
from tests.db.test_nodes import CV, connection, owner, url
from tests.db.test_supersedes import an_edition
from tests.exports.test_kern_rdf import a_document
from tests.pipeline.test_shacl import ONTOLOGY

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with tests/db
WORK = BASE + "work/de-nw/lp-physik"


async def frozen_rows(connection: psycopg.AsyncConnection, document: Any) -> KernRows:
    """The rows of a document frozen under BASE: its work, a node with a child, two statements, anchors."""
    await ready(connection, document)
    await freeze(connection, document.id, BASE, accept_violations=False)
    return await read_document(connection, document.id)


def value_ids(rows: KernRows) -> list[UUID | None]:
    """The ids of the rows' values, a workload's periods among them."""
    found: list[UUID | None] = []
    for held in rows.values.values():
        found += [level.value.id for level in held.levels] + [span.value.id for span in held.time_spans]
        found += [workload.value.id for workload in held.workloads]
        found += [period.value.id for workload in held.workloads for period in workload.periods]
        for context in held.contexts:  # an applicability context and the values it holds (plan M3a H1)
            found += [context.value.id, *(each.value.id for each in context.levels)]
            found += [each.value.id for each in context.time_spans]
    return found


def under_frozen_names(draft: Graph, rows: KernRows) -> Graph:
    """The draft graph, each row's urn:uuid replaced by its stored IRI - an anchor's, the file's and a
    value's by a blank node of its own."""
    named = [rows.document, *rows.specifications, *rows.variants, *rows.nodes, *rows.statements]
    names: dict[Node, Node] = {
        URIRef(f"urn:uuid:{row['id']}"): URIRef(row["iri"]) for row in [*named, *filter(None, [rows.work])]
    }
    names |= {URIRef(f"urn:uuid:{row['id']}"): BNode() for row in [*rows.anchors, rows.file]}
    names |= {URIRef(f"urn:uuid:{value}"): BNode() for value in value_ids(rows)}
    renamed = Graph()
    for subject, predicate, value in draft:
        renamed.add((names.get(subject, subject), predicate, names.get(value, value)))
    return renamed


def assert_isomorphic(made: Graph, expected: Graph) -> None:
    if not isomorphic(made, expected):
        _, only_made, only_expected = graph_diff(to_isomorphic(made), to_isomorphic(expected))
        pytest.fail(
            f"made only:\n{only_made.serialize(format='nt')}\n"
            f"expected only:\n{only_expected.serialize(format='nt')}"
        )


async def test_the_frozen_graph_is_the_draft_graph_under_other_names(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    rows = await frozen_rows(connection, document)

    frozen = kern_graph(rows, frozen_naming())
    draft = kern_graph(rows, draft_naming())

    # the one triple only the export states: when the document was frozen - a draft has not been
    stamped = list(frozen.triples((URIRef(DOC), PROV.generatedAtTime, None)))
    assert stamped == [(URIRef(DOC), PROV.generatedAtTime, Literal(rows.document["frozen_at"]))]
    frozen.remove(stamped[0])
    assert_isomorphic(frozen, under_frozen_names(draft, rows))


async def test_the_frozen_graph_with_values_is_the_draft_graph_under_other_names(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # each value a blank node of its own, a workload's period too
    top = await ready(connection, document)
    period = TimeSpanDraft(time_kind=CV + "time_trainingYear", span_from=Decimal(1))
    drafts = ValueDrafts(
        levels=(LevelDraft(level="https://w3id.org/wlo/curriculum/level/EQF-4"),),
        time_spans=(TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=Decimal(5)),),
        workloads=(WorkloadDraft(amount=Decimal(40), unit=CV + "unit_lesson", periods=(period,)),),
    )
    await replace_values(connection, owner(document), Holder("node", top), 1, drafts)
    await checked(connection, document)
    await freeze(connection, document.id, BASE, accept_violations=False)
    rows = await read_document(connection, document.id)

    frozen = kern_graph(rows, frozen_naming())

    assert len(value_ids(rows)) == 4
    terms = {term for triple in frozen for term in (triple[0], triple[2])}
    assert not [term for term in terms if str(term).startswith("urn:uuid:")]
    frozen.remove((URIRef(DOC), PROV.generatedAtTime, None))
    assert_isomorphic(frozen, under_frozen_names(kern_graph(rows, draft_naming()), rows))


async def test_a_frozen_graph_names_no_row_by_its_id(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    rows = await frozen_rows(connection, document)

    frozen = kern_graph(rows, frozen_naming())

    terms = {term for triple in frozen for term in (triple[0], triple[2])}
    assert not [term for term in terms if str(term).startswith("urn:uuid:")]
    # an anchor each of the two statements kept: each its own blank node
    assert len(set(frozen.subjects(RDF.type, CUR.SourceAnchor))) == len(rows.anchors) == 2
    assert all(isinstance(anchor, BNode) for anchor in frozen.subjects(RDF.type, CUR.SourceAnchor))


async def test_a_row_without_its_iri_refuses_the_frozen_naming(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    rows = await frozen_rows(connection, document)
    rows.nodes[-1]["iri"] = None

    with pytest.raises(ValueError, match=f"node {rows.nodes[-1]['id']} has no IRI"):
        kern_graph(rows, frozen_naming())


async def test_a_frozen_graph_names_specifications_and_variants_by_the_iris_freezing_gave(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    await ready(connection, document)
    await specified(connection, document.id, "lp", "g8")
    await freeze(connection, document.id, BASE, accept_violations=False)
    rows = await read_document(connection, document.id)

    frozen = kern_graph(rows, frozen_naming())

    specification, variant = URIRef(DOC + "/spec/lp"), URIRef(DOC + "/spec/lp/variant/g8")
    assert (URIRef(DOC), CUR.represents, specification) in frozen
    assert (variant, CUR.variantOf, specification) in frozen
    frozen.remove((URIRef(DOC), PROV.generatedAtTime, None))
    assert_isomorphic(frozen, under_frozen_names(kern_graph(rows, draft_naming()), rows))


async def test_the_graph_states_what_the_document_supersedes(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # by the IRI of the edition it supersedes - frozen, so it has one - whatever the naming
    older = await frozen_rows(connection, document)
    newer = await an_edition(connection, document, "2030", freezing=True, superseding=True)
    rows = await read_document(connection, newer.id)
    newer_iri = URIRef(DOC.removesuffix("2024") + "2030")

    for graph, subject in (
        (kern_graph(rows), URIRef(f"urn:uuid:{newer.id}")),
        (kern_graph(rows, frozen_naming()), newer_iri),
    ):
        assert list(graph.objects(subject, CUR.supersedes)) == [URIRef(DOC)]
    assert not list(kern_graph(older).objects(None, CUR.supersedes))


async def test_the_frozen_naming_refuses_the_rows_of_a_document_not_frozen(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # a draft copy's rows carry the IRIs of the revision it copies: its graph is no frozen document's
    await frozen_rows(connection, document)
    copy = await copy_document(connection, document.id)
    rows = await read_document(connection, copy)

    with pytest.raises(ValueError, match=f"document {copy} is not frozen"):
        kern_graph(rows, frozen_naming())


async def test_the_document_is_a_version_of_its_work_and_says_its_revision(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    rows = await frozen_rows(connection, document)
    assert rows.work is not None

    for graph, work, made in (
        (kern_graph(rows), URIRef(f"urn:uuid:{rows.work['id']}"), URIRef(f"urn:uuid:{document.id}")),
        (kern_graph(rows, frozen_naming()), URIRef(WORK), URIRef(DOC)),
    ):  # fmt: skip
        assert (made, CUR.versionOf, work) in graph
        assert (work, RDF.type, CUR.Work) in graph
        assert (work, DCTERMS.title, Literal("Lehrplan Physik")) in graph
        assert list(graph.objects(made, OWL.versionInfo)) == [Literal("1")]
    # the work is typed: the shape's sh:class cur:Work at cur:versionOf holds (cur-shapes.ttl)
    assert not [
        found for found in validate_graph(ONTOLOGY, kern_graph(rows)) if found.path == "cur:versionOf"
    ]


async def test_a_document_without_a_work_states_none(connection: psycopg.AsyncConnection) -> None:
    ids = await a_document(connection)

    draft = kern_graph(await read_document(connection, ids["doc"]))

    assert not list(draft.objects(None, CUR.versionOf))
    assert not list(draft.subjects(RDF.type, CUR.Work))
    assert list(draft.objects(URIRef(f"urn:uuid:{ids['doc']}"), OWL.versionInfo)) == [Literal("1")]
    assert not list(draft.objects(None, PROV.generatedAtTime))


async def test_the_file_states_its_checksum(connection: psycopg.AsyncConnection, document: Any) -> None:
    rows = await frozen_rows(connection, document)
    cursor = await connection.execute(
        "SELECT f.id, encode(f.sha256, 'hex') FROM document d JOIN conversion c ON c.id = d.conversion_id"
        " JOIN source_file f ON f.id = c.source_file_id WHERE d.id = %s",
        (document.id,),
    )
    [(file_id, checksum)] = await cursor.fetchall()

    draft = kern_graph(rows)

    file = URIRef(f"urn:uuid:{file_id}")
    assert set(draft.predicate_objects(file)) == {
        (RDF.type, CUR.SourceFile), (CUR.checksum, Literal(checksum)),
        (CUR.containsDocument, URIRef(f"urn:uuid:{document.id}")),
    }  # fmt: skip
    assert not [found for found in validate_graph(ONTOLOGY, draft) if found.shape == "SourceFileShape"]
    [blank] = kern_graph(rows, frozen_naming()).subjects(CUR.checksum, Literal(checksum))
    assert isinstance(blank, BNode)


async def test_x5_checks_the_graph_it_checked_before(connection: psycopg.AsyncConnection) -> None:
    # a document without a work, as X5 builds it (no naming): the graph of before, plus its revision and
    # its file - and the shapes find on it no more than on the graph of before
    ids = await a_document(connection)
    rows = await read_document(connection, ids["doc"])

    made = kern_graph(rows)

    assert_isomorphic(made, kern_graph(rows, draft_naming()))
    file = URIRef(f"urn:uuid:{rows.file['id']}")
    added = {
        (URIRef(f"urn:uuid:{ids['doc']}"), OWL.versionInfo, Literal("1")),
        *made.triples((file, None, None)),
    }
    assert {(predicate, value) for _, predicate, value in added} == {
        (OWL.versionInfo, Literal("1")), (RDF.type, CUR.SourceFile),
        (CUR.checksum, Literal(rows.file["sha256"])),
        (CUR.containsDocument, URIRef(f"urn:uuid:{ids['doc']}")),
    }  # fmt: skip
    before = Graph()
    for triple in made:
        if triple not in added:
            before.add(triple)
    assert validate_graph(ONTOLOGY, made) == validate_graph(ONTOLOGY, before)
