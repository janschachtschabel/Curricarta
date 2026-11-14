"""The queries of a plan's parts and references (app/sources/mem/queries.py, plan M2 E8/E11): each reads its
Land's graph and the shared ones alone, names the plan only as a checked IRI, and reads in pages ordered so
that a page's rows are the next ones."""

import re

import pytest
from rdflib import Graph
from rdflib.query import ResultRow

from app.sources.mem.queries import (
    PREFIXES,
    SEPARATOR,
    closure_count,
    closure_page,
    label_shape_count,
    plan_count,
    reference_count,
    reference_page,
)
from app.sources.mem.sparql import MemEndpoint, MemRefused, MemSparql

RP = "https://w3id.org/lehrplan/rp"
PLAN = "https://w3id.org/lehrplan/instances/rp/resource/lehrplan-134-1"
SPARQL = MemSparql(MemEndpoint("https://sparql.example.invalid/sparql"))


@pytest.mark.parametrize("query", [
    closure_count(SPARQL, RP, PLAN), closure_page(SPARQL, RP, PLAN, 500, 1000),
    reference_count(SPARQL, RP, PLAN), reference_page(SPARQL, RP, PLAN, 500, 0),
])  # fmt: skip
def test_a_query_reads_the_land_s_graph_and_names_the_plan_in_brackets(query: str) -> None:
    assert f"FROM <{RP}>" in query and "FROM <https://w3id.org/lehrplan/ontology/1.0.0rc3>" in query
    assert f"<{PLAN}> obo:BFO_0000051+" in query
    assert "FROM <https://w3id.org/lehrplan/rp/data>" not in query


def test_a_page_of_the_parts_is_ordered_and_bounded() -> None:
    query = closure_page(SPARQL, RP, PLAN, 500, 1000)

    assert "ORDER BY ?n LIMIT 500 OFFSET 1000" in query
    assert "GROUP BY ?n" in query


def test_a_page_of_the_references_is_ordered_by_holder_and_reference() -> None:
    assert "ORDER BY ?x ?v LIMIT 200 OFFSET 0" in reference_page(SPARQL, RP, PLAN, 200, 0)


@pytest.mark.parametrize("plan", ["https://w3id.org/x> } DROP ALL { <y", "javascript:alert(1)"])
def test_a_plan_that_is_no_iri_builds_no_query(plan: str) -> None:
    with pytest.raises(MemRefused):
        closure_page(SPARQL, RP, plan, 500, 0)


def test_a_graph_the_client_does_not_read_builds_no_query() -> None:
    with pytest.raises(MemRefused):
        closure_count(SPARQL, "http://sn-2026-02-26/", PLAN)


def answered(query: str, turtle: str) -> list[dict[str, str]]:
    """The query's rows over ``turtle`` in rdflib, its FROM lines gone (rdflib would fetch them)."""
    graph = Graph().parse(
        data=PREFIXES.replace("PREFIX ", "@prefix ").replace(">\n", "> .\n") + turtle, format="turtle"
    )
    local = "\n".join(line for line in query.splitlines() if not line.startswith("FROM "))
    rows = [row for row in graph.query(local) if isinstance(row, ResultRow)]
    return [{str(name): str(value) for name, value in row.asdict().items()} for row in rows]


def test_a_part_s_label_prefers_german_to_untagged_to_preferred_and_its_hours_are_its_time() -> None:
    turtle = f"""
    <{PLAN}> obo:BFO_0000051 <https://w3id.org/p/a> , <https://w3id.org/p/b> , <https://w3id.org/p/c> .
    <https://w3id.org/p/a> rdfs:label "plain" , "Zweit"@de , "Deutsch"@de , "English"@en ;
        skos:prefLabel "preferred" .
    <https://w3id.org/p/b> rdfs:label "plain" , "English"@en ; skos:prefLabel "preferred"@de .
    <https://w3id.org/p/c> rdfs:label "English"@en ; skos:prefLabel "preferred"@de .
    <https://w3id.org/p/a> a lp:LP_0000263 ; lp:LP_0000026 "5" .  # rdflib: the DISTINCT aggregates bound
    <https://w3id.org/p/b> a lp:LP_0000263 ; lp:LP_0000026 "5" .
    <https://w3id.org/p/c> a lp:LP_0000263 ; lp:LP_0000026 "5" .
    <https://w3id.org/p/a> lp:LP_0000024 [ a lp:LP_0000508 ; lp:LP_0000344 "12" ] .
    <https://w3id.org/p/b> lp:LP_0000024 [ a lp:LP_0000509 ; lp:LP_0000344 "3" ] .  # no time specification
    """

    rows = answered(closure_page(SPARQL, RP, PLAN, 500, 0), turtle)

    assert {row["n"].rsplit("/", 1)[1]: row.get("label") for row in rows} == {
        "a": "Deutsch",
        "b": "plain",
        "c": "preferred",
    }
    assert {row["n"].rsplit("/", 1)[1]: row.get("hours") for row in rows} == {"a": "12", "b": None, "c": None}


def test_a_reference_names_every_target_it_points_at() -> None:
    turtle = f"""
    <{PLAN}> obo:BFO_0000051 <https://w3id.org/p/a> .
    <https://w3id.org/p/a> lp:LP_0030071 <https://w3id.org/p/v> , <https://w3id.org/p/w> .
    <https://w3id.org/p/w> skos:prefLabel "W"@de ; a lp:LP_0000554 ; lp:LP_0030072 <https://w3id.org/z/3> .
    <https://w3id.org/p/v> rdfs:label "plain" , "Z"@de , "V"@de ; skos:prefLabel "preferred"@de ;
        lp:LP_0030072 <https://w3id.org/z/1> , <https://w3id.org/z/2> ;
        a lp:LP_0000554 .
    """

    rows = answered(reference_page(SPARQL, RP, PLAN, 500, 0), turtle)

    found = {row["v"].rsplit("/", 1)[1]: row for row in rows}
    assert sorted(found["v"]["target"].split(SEPARATOR)) == ["https://w3id.org/z/1", "https://w3id.org/z/2"]
    assert (found["v"]["label"], found["w"]["label"]) == ("V", "W")


@pytest.mark.parametrize(
    "query",
    [closure_page(SPARQL, RP, PLAN, 500, 0), reference_page(SPARQL, RP, PLAN, 500, 0)],
    ids=["closure", "references"],
)
def test_no_projected_name_is_a_variable_of_the_pattern(query: str) -> None:
    # SPARQL 1.1, 18.2.1: (expr AS ?v) must not name a variable in scope - strict stores refuse it
    head, body = query.split("\nWHERE {", 1)

    projected = set(re.findall(r"AS (\?\w+)\)", head))

    assert projected
    assert not {name for name in projected if re.search(re.escape(name) + r"\b", body)}


def test_the_count_query_projects_no_variable_of_its_pattern() -> None:
    head, body = label_shape_count(SPARQL, RP, PLAN).split("\nWHERE {", 1)

    projected = set(re.findall(r"AS (\?\w+)\)", head))

    assert projected == {"?count"}
    assert not {name for name in projected if re.search(re.escape(name) + r"\b", body)}


def test_the_count_query_names_only_checked_iris() -> None:
    query = label_shape_count(SPARQL, RP, PLAN)
    assert f"FROM <{RP}>" in query and f"<{PLAN}> obo:BFO_0000051+" in query

    with pytest.raises(MemRefused):
        label_shape_count(SPARQL, RP, "https://w3id.org/x> } DROP ALL { <y")
    with pytest.raises(MemRefused):
        label_shape_count(SPARQL, "http://sn-2026-02-26/", PLAN)


def test_the_count_query_counts_the_parts_by_the_shape_of_their_labels_and_typed_literals() -> None:
    turtle = f"""
    <{PLAN}> obo:BFO_0000051 <https://w3id.org/p/a> , <https://w3id.org/p/b> , <https://w3id.org/p/c> ,
        <https://w3id.org/p/d> .
    <https://w3id.org/p/a> rdfs:label "Deutsch"@de , "Zweit"@de , "English"@en ;
        lp:LP_0030057 "3"^^<http://www.w3.org/2001/XMLSchema#integer> ;
        lp:LP_0000026 "5"^^<http://www.w3.org/2001/XMLSchema#integer> .
    <https://w3id.org/p/b> rdfs:label "plain" ; lp:LP_0030057 "4" ;
        lp:LP_0000024 [ a lp:LP_0000508 ; lp:LP_0000344 "12"^^<http://www.w3.org/2001/XMLSchema#decimal> ] .
    <https://w3id.org/p/c> skos:prefLabel "preferred"@de .
    <https://w3id.org/p/d> rdfs:label "English"@en ; skos:prefLabel "preferred"@de ;
        lp:LP_0000024 [ a lp:LP_0000509 ; lp:LP_0000344 "3"^^<http://www.w3.org/2001/XMLSchema#integer> ] .
    """

    rows = answered(label_shape_count(SPARQL, RP, PLAN), turtle)

    assert {row["measure"]: int(row["count"]) for row in rows} == {
        "label_de": 1,
        "label_untagged": 1,
        "label_other_language": 2,
        "pref_label_only": 1,
        "typed_number": 1,
        "typed_hours": 1,
        "typed_grade": 1,
    }


def test_a_plan_s_count_is_one_while_the_graph_holds_it_and_none_after() -> None:
    held = f"<{PLAN}> a lp:LP_0000438 .\n<https://w3id.org/p/kmk> a lp:LP_0000571 .\n"

    assert answered(plan_count(SPARQL, RP, PLAN), held) == [{"count": "1"}]
    assert answered(plan_count(SPARQL, RP, "https://w3id.org/p/kmk"), held) == [{"count": "1"}]
    assert answered(plan_count(SPARQL, RP, "https://w3id.org/p/gone"), held) == [{"count": "0"}]
    assert answered(plan_count(SPARQL, RP, PLAN), f"<{PLAN}> a lp:LP_0000263 .\n") == [{"count": "0"}]
