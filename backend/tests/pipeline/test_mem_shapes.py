"""The MEM shapes (ontology/mem/shapes, plan M2 E9/E10) over a MEM graph, as the SHACL child checks it:
without a reasoner, a state class reaching its shape through the class chain."""

import shutil
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal, URIRef

from app.pipeline.shacl_child import ShaclResult, validate_graph

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
LP = "https://w3id.org/lehrplan/ontology/"
OBO = "http://purl.obolibrary.org/obo/"
PLAN = URIRef("https://lp-sachsen.org/resource/lehrplan-1")
AREA = URIRef("https://lp-sachsen.org/resource/lehrplan-1/bereich-1")
REFERENCE = URIRef("https://lp-sachsen.org/resource/lehrplan-1/verweis-1")


def checked(graph: Graph) -> list[ShaclResult]:
    return validate_graph(ONTOLOGY, graph, shapes="mem")


def a_plan() -> Graph:
    graph = Graph()
    graph.add((PLAN, RDF.type, URIRef(LP + "LP_0000438")))  # Lehrplan
    graph.add((PLAN, URIRef(LP + "LP_0000029"), URIRef(LP + "LP_3000014")))  # Bundesland
    # Allgemeines fachliches Ziel (SN), a Bereich only by the class chain
    graph.add((AREA, RDF.type, URIRef(LP + "LP_0030050")))
    graph.add((AREA, URIRef(OBO + "BFO_0000050"), PLAN))
    graph.add((AREA, URIRef(LP + "LP_0030071"), REFERENCE))
    graph.add((REFERENCE, RDF.type, URIRef(LP + "LP_0030065")))  # Verweis
    graph.add((REFERENCE, URIRef(LP + "LP_0030072"), Literal("Lehrplan Deutsch")))
    return graph


def shapes(results: list[ShaclResult]) -> set[str]:
    return {result.shape for result in results if result.severity == "violation"}


def test_a_whole_plan_meets_the_mem_shapes() -> None:
    assert shapes(checked(a_plan())) == set()


def test_a_state_class_s_area_part_of_nothing_breaks_the_area_shape() -> None:
    graph = a_plan()
    graph.remove((AREA, URIRef(OBO + "BFO_0000050"), PLAN))

    assert shapes(checked(graph)) == {"BereichShape"}


def test_a_plan_of_no_land_and_a_reference_to_nothing_break_their_shapes() -> None:
    graph = a_plan()
    graph.remove((PLAN, URIRef(LP + "LP_0000029"), None))
    graph.remove((REFERENCE, URIRef(LP + "LP_0030072"), None))

    assert shapes(checked(graph)) == {"LPBundeslandShape", "VerweisShape"}


def test_a_missing_mem_shape_stops_the_check_rather_than_passing_all(tmp_path: Path) -> None:
    # an image or ONTOLOGY_DIR without the shapes must not let every export through: the chain is there
    (tmp_path / "mem" / "shapes").mkdir(parents=True)
    shutil.copyfile(ONTOLOGY / "mem" / "lp-klassen.ttl", tmp_path / "mem" / "lp-klassen.ttl")

    with pytest.raises(FileNotFoundError, match="bereich"):
        validate_graph(tmp_path, a_plan(), shapes="mem")


def test_a_shape_set_of_no_name_is_refused() -> None:
    with pytest.raises(ValueError, match="no shape set"):
        validate_graph(ONTOLOGY, a_plan(), shapes="core")  # type: ignore[arg-type]
