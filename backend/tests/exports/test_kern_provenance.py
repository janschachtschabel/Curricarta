"""Where a document's Kern graph says it came from (app/exports/kern_rdf.py; plan M3a E13, owner decision 5):
the register entry's address as its source, where the entry has one - an uploaded entry of none states its
file's checksum alone -; an import from MEM-Schule the MEM plan as its source and origin, MEM's attribution
and the licence recorded for MEM's data at the plan (plan M2 E14), as the MEM export says them. The same
under either naming: X5 checks what the export writes. Synthetic rows (app/exports/measure_kern.py)."""

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV

from app.exports.kern_naming import draft_naming, frozen_naming
from app.exports.kern_rdf import kern_graph
from app.exports.kern_rows import KernRows
from app.exports.measure_kern import synthetic_rows

URL = "https://example.org/plaene/synthese.pdf"
PLAN = "https://example.org/mem/plan-1"
LICENCE = "https://creativecommons.org/licenses/by/4.0/"


def document_of(graph: Graph, rows: KernRows, frozen: bool) -> URIRef:
    return URIRef(rows.document["iri"] if frozen else f"urn:uuid:{rows.document['id']}")


@pytest.mark.parametrize("frozen", [False, True], ids=["draft", "frozen"])
def test_the_document_names_the_address_of_its_register_entry_as_its_source(frozen: bool) -> None:
    rows = synthetic_rows(nodes=1, statements=1, source_url=URL)

    graph = kern_graph(rows, frozen_naming() if frozen else draft_naming())

    assert list(graph.objects(document_of(graph, rows, frozen), DCTERMS.source)) == [URIRef(URL)]


def test_an_uploaded_entry_of_no_address_states_no_source_but_its_file() -> None:
    rows = synthetic_rows(nodes=1, statements=1)

    graph = kern_graph(rows, frozen_naming())

    assert list(graph.objects(None, DCTERMS.source)) == []


def test_an_address_no_iri_can_hold_is_stated_as_written() -> None:
    rows = synthetic_rows(nodes=1, statements=1, source_url="https://example.org/a plan.pdf")

    graph = kern_graph(rows, frozen_naming())

    assert list(graph.objects(None, DCTERMS.source)) == [Literal("https://example.org/a plan.pdf")]


@pytest.mark.parametrize("frozen", [False, True], ids=["draft", "frozen"])
def test_an_import_names_the_mem_plan_its_attribution_and_the_licence_of_mem_s_data(frozen: bool) -> None:
    rows = synthetic_rows(
        nodes=1, statements=1, source_url=URL, mem_iri=PLAN, mem_attribution="MEM-Schule", mem_licence=LICENCE
    )

    graph = kern_graph(rows, frozen_naming() if frozen else draft_naming())

    document, plan = document_of(graph, rows, frozen), URIRef(PLAN)
    assert set(graph.objects(document, DCTERMS.source)) == {URIRef(URL), plan}
    assert list(graph.objects(document, PROV.wasDerivedFrom)) == [plan]
    assert list(graph.objects(document, DCTERMS.bibliographicCitation)) == [Literal("MEM-Schule")]
    assert list(graph.objects(plan, DCTERMS.license)) == [URIRef(LICENCE)]  # the data's, not the wordings'
    assert list(graph.objects(document, DCTERMS.license)) == []


def test_an_import_of_no_licence_recorded_states_none() -> None:
    rows = synthetic_rows(nodes=1, statements=1, mem_iri=PLAN, mem_attribution=None)

    graph = kern_graph(rows, frozen_naming())

    assert list(graph.objects(None, DCTERMS.license)) == []
    assert list(graph.objects(None, DCTERMS.bibliographicCitation)) == []
    assert list(graph.objects(None, PROV.wasDerivedFrom)) == [URIRef(PLAN)]
