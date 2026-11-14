"""The catalogue of MEM's plans (app/sources/mem/catalog.py, plan M2 E11): per allowed graph, every plan -
a Land's Lehrplan or the KMK's Bildungsstandard - with its title, class, Land, subjects and school types,
read in pages; the queries run in rdflib over a few invented triples."""

import re
from typing import Any

import pytest
from pydantic import ValidationError
from rdflib import Graph
from rdflib.query import ResultRow

from app.db.mem_plans import MemPlan
from app.sources.mem.catalog import catalog_count, catalog_page, mismatched, plans_from
from app.sources.mem.queries import PREFIXES
from app.sources.mem.sparql import MemEndpoint, MemRefused, MemSparql
from tests.support import make_settings

LP = "https://w3id.org/lehrplan/ontology/"
RP = "https://w3id.org/lehrplan/rp"
SPARQL = MemSparql(MemEndpoint("https://sparql.example.invalid/sparql"))
ATTRIBUTION = "MEM-Schule"


def answered(query: str, turtle: str) -> list[dict[str, str]]:
    """The query's rows over ``turtle`` in rdflib, its FROM lines gone (rdflib would fetch them)."""
    graph = Graph().parse(
        data=PREFIXES.replace("PREFIX ", "@prefix ").replace(">\n", "> .\n") + turtle, format="turtle"
    )
    local = "\n".join(line for line in query.splitlines() if not line.startswith("FROM "))
    rows = [row for row in graph.query(local) if isinstance(row, ResultRow)]
    return [{str(name): str(value) for name, value in row.asdict().items()} for row in rows]


TURTLE = """
<https://w3id.org/p/rp-1> a lp:LP_0000438 , lp:LP_0000433 , obo:BFO_0000001 ;
    rdfs:label "Deutsch 5-6"@de , "untagged" , "German"@en ; lp:LP_0000029 lp:LP_3000046 ;
    lp:LP_0000537 <https://w3id.org/schulfach/RP_1> , <https://w3id.org/schulfach/RP_2> ;
    lp:LP_0000812 <https://w3id.org/schulart/RP_9> .
<https://w3id.org/p/kmk-1> a lp:LP_0000571 ; rdfs:label "Bildungsstandards Mathematik" ;
    lp:LP_0000537 <http://w3id.org/kim/schulfaecher/s1017> ; lp:LP_0000812 <https://w3id.org/schulart/X> ;
    lp:LP_0000029 lp:LP_0 .
<https://w3id.org/p/be-1> a lp:LP_0000438 ; skos:prefLabel "Informatik"@de ; lp:LP_0000029 lp:LP_0 ;
    lp:LP_0000537 <https://w3id.org/schulfach/BE_1> ; lp:LP_0000812 <https://w3id.org/schulart/X> .
<https://w3id.org/p/part> a lp:LP_0000263 ; rdfs:label "kein Plan" ; lp:LP_0000029 lp:LP_0 ;
    lp:LP_0000537 <https://w3id.org/schulfach/RP_1> ; lp:LP_0000812 <https://w3id.org/schulart/X> .
"""  # every plan with a Land, a subject and a school type: rdflib cannot aggregate DISTINCT over none


def test_the_catalogue_counts_and_reads_lehrplaene_and_bildungsstandards_alone() -> None:
    count = answered(catalog_count(SPARQL, RP), TURTLE)
    rows = answered(catalog_page(SPARQL, RP, 500, 0), TURTLE)

    assert count == [{"count": "3"}]
    assert sorted(row["p"] for row in rows) == [
        "https://w3id.org/p/be-1", "https://w3id.org/p/kmk-1", "https://w3id.org/p/rp-1"
    ]  # fmt: skip


def test_a_plan_s_row_names_its_german_title_classes_land_subjects_and_school_types() -> None:
    rows = {row["p"]: row for row in answered(catalog_page(SPARQL, RP, 500, 0), TURTLE)}

    # a German label before an untagged one before a preferred one; Berlin has the preferred one alone
    assert [rows[f"https://w3id.org/p/{name}"]["label"] for name in ("rp-1", "kmk-1", "be-1")] == [
        "Deutsch 5-6", "Bildungsstandards Mathematik", "Informatik"
    ]  # fmt: skip
    plan = rows["https://w3id.org/p/rp-1"]
    assert sorted(plan["classes"].split("|")) == [LP + "LP_0000433", LP + "LP_0000438"]
    assert plan["land"] == LP + "LP_3000046"
    assert sorted(plan["subjects"].split("|")) == [
        "https://w3id.org/schulfach/RP_1",
        "https://w3id.org/schulfach/RP_2",
    ]
    assert plan["schoolTypes"] == "https://w3id.org/schulart/RP_9"


def test_a_page_is_ordered_and_bounded_and_reads_the_land_s_graph() -> None:
    query = catalog_page(SPARQL, RP, 500, 1000)

    assert "ORDER BY ?p LIMIT 500 OFFSET 1000" in query
    assert f"FROM <{RP}>" in query
    with pytest.raises(MemRefused):
        catalog_page(SPARQL, "http://sn-2026-02-26/", 500, 0)


def row(**values: str) -> dict[str, str]:
    return {"p": "https://w3id.org/p/1", "label": "Deutsch", "classes": LP + "LP_0000438", **values}


def test_a_plan_s_class_is_its_land_s_class_before_the_base_class() -> None:
    plans, skipped = plans_from(
        [row(classes=f"{LP}LP_0000438|{LP}LP_0000819"), row(p="https://w3id.org/p/2")], RP, ATTRIBUTION
    )

    # Bavaria's LP_0000819 sorts after the base class: the Land's class is taken, not the first
    assert [plan.class_iri for plan in plans] == [LP + "LP_0000819", LP + "LP_0000438"]
    assert skipped == 0


def test_a_standard_of_the_kmk_keeps_its_class() -> None:
    plans, _ = plans_from(
        [row(classes=LP + "LP_0000571")], "https://w3id.org/lehrplan/graph/bista", ATTRIBUTION
    )

    assert plans[0].class_iri == LP + "LP_0000571"


def test_a_plan_keeps_its_land_subjects_school_types_graph_and_attribution_and_states_no_licence() -> None:
    plans, _ = plans_from(
        [
            row(
                land=LP + "LP_3000046",
                subjects="https://w3id.org/s/2|https://w3id.org/s/1",
                schoolTypes="https://w3id.org/a/1",
            )
        ],
        RP,
        ATTRIBUTION,
    )

    plan = plans[0]
    assert (plan.iri, plan.graph, plan.land_iri, plan.title) == (
        "https://w3id.org/p/1",
        RP,
        LP + "LP_3000046",
        "Deutsch",
    )
    assert (plan.subjects, plan.school_types) == (
        ("https://w3id.org/s/1", "https://w3id.org/s/2"),
        ("https://w3id.org/a/1",),
    )
    assert (plan.licence, plan.attribution) == (
        None,
        ATTRIBUTION,
    )  # the endpoint states none (probe 2026-11-09)


@pytest.mark.parametrize(
    ("values", "title"),
    [
        ({"label": ""}, "lehrplan-134-1"),
        ({"label": "  Deutsch\n  5-6 "}, "Deutsch 5-6"),
        ({"label": "x" * 2100}, "x" * 2000),
    ],
    ids=["no-label", "spaces", "too-long"],
)
def test_a_title_is_on_one_line_and_bounded_and_the_iri_s_end_without_a_label(
    values: dict[str, str], title: str
) -> None:
    plans, _ = plans_from(
        [row(p="https://w3id.org/lehrplan/instances/rp/resource/lehrplan-134-1", **values)], RP, ATTRIBUTION
    )

    assert plans[0].title == title


@pytest.mark.parametrize(
    "values",
    [
        {"p": "https://w3id.org/p/a b"},
        {"p": "urn:x:1"},
        {"p": "https://w3id.org/" + "a" * 1984},
    ],
    ids=["space", "urn", "too-long"],
)
def test_a_plan_whose_iri_the_table_cannot_take_is_skipped_and_counted(values: dict[str, Any]) -> None:
    plans, skipped = plans_from([row(**values), row(p="https://w3id.org/p/ok")], RP, ATTRIBUTION)

    assert [plan.iri for plan in plans] == ["https://w3id.org/p/ok"]
    assert skipped == 1


def test_no_projected_name_is_a_variable_of_the_pattern() -> None:
    # SPARQL 1.1, 18.2.1: (expr AS ?v) must not name a variable in scope - strict stores refuse it
    query = catalog_page(SPARQL, RP, 500, 0)
    head, body = query.split("\nWHERE {", 1)

    projected = set(re.findall(r"AS (\?\w+)\)", head))

    assert projected
    assert not {name for name in projected if re.search(re.escape(name) + r"\b", body)}


@pytest.mark.parametrize(
    "url",
    ["http://sparql.example/sparql", "https://user:secret@sparql.example/sparql",
     "https://sparql.example/sparql?key=secret", "https://sparql.example/sparql#x",
     "https://sparql.example/ a"],
    ids=["http", "userinfo", "query", "fragment", "space"],
)  # fmt: skip
def test_an_endpoint_address_with_more_than_a_host_and_path_is_refused(url: str) -> None:
    # the address is written into every plan's attribution: no credentials, no keys
    with pytest.raises(ValidationError):
        make_settings(mem_sparql_url=url)


@pytest.mark.parametrize(
    "iri",
    ["https://w3id.org/p/a\x80b", "https://w3id.org/p/a\x9fb", "https://w3id.org/p/a\ud800b"],
    ids=["c1-first", "c1-last", "surrogate"],
)
def test_a_plan_whose_iri_holds_a_sign_the_database_refuses_is_skipped(iri: str) -> None:
    plans, skipped = plans_from([row(p=iri)], RP, ATTRIBUTION)

    assert (plans, skipped) == ([], 1)


def test_a_nul_the_database_cannot_hold_is_dropped_from_a_plan() -> None:
    plans, _ = plans_from(
        [
            row(
                label="Deu\x00tsch",
                land="https://w3id.org/l\x00",
                subjects="https://w3id.org/s/\x00|https://w3id.org/s/1",
            )
        ],
        RP,
        ATTRIBUTION,
    )

    assert (plans[0].title, plans[0].land_iri, plans[0].subjects) == (
        "Deutsch",
        None,
        ("https://w3id.org/s/1",),
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://sparql.example:8890/sparql",
        "https://host.example/~u/sp%61rql",
        "https://my-host.example/a_b.c",
    ],
    ids=["port", "tilde-escape", "signs"],
)
def test_an_endpoint_address_of_host_port_and_path_is_taken(url: str) -> None:
    assert make_settings(mem_sparql_url=url).mem_sparql_url == url


def test_a_lone_surrogate_the_database_cannot_hold_is_dropped_from_a_plan() -> None:
    # JSON may spell one ("\ud800"); it is no UTF-8, and the database refuses it as it refuses a NUL
    plans, _ = plans_from(
        [row(label="Deu\ud800tsch", land="https://w3id.org/l\ud800", subjects="https://w3id.org/s/\udfff")],
        RP,
        ATTRIBUTION,
    )

    assert (plans[0].title, plans[0].land_iri, plans[0].subjects) == ("Deutsch", None, ())


def test_a_licence_the_operators_checked_goes_with_every_plan() -> None:
    licence = "https://creativecommons.org/licenses/by-sa/4.0/"

    plans, _ = plans_from([row()], RP, ATTRIBUTION, licence)
    unchecked, _ = plans_from([row()], RP, ATTRIBUTION)

    assert (plans[0].licence, unchecked[0].licence) == (licence, None)


KMK = "https://w3id.org/lehrplan/graph/bista"


@pytest.mark.parametrize(
    ("graph", "klass", "count"),
    [(KMK, "LP_0000571", 0), (RP, "LP_0000438", 0), (RP, "LP_0000819", 0), (KMK, "LP_0000438", 1),
     (RP, "LP_0000571", 1)],
)  # fmt: skip
def test_a_plan_whose_graph_and_class_disagree_on_the_kmk_is_counted(
    graph: str, klass: str, count: int
) -> None:
    # the import knows the KMK by the graph, the export by the class (plan M2-7)
    plans, _ = plans_from([row(classes=LP + klass)], graph, ATTRIBUTION)

    assert mismatched(plans) == count


def test_no_plan_no_mismatch() -> None:
    assert mismatched(list[MemPlan]()) == 0
