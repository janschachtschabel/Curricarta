"""The class chain of MEM-Schule and the base types the import types by (plan M2 E8/E9): the chain a faithful
extract of the published ontology, the base types from the state classes' table kept apart - a
classification aid the ontology does not entail, never written as FWU's axioms."""

import csv
import json
from pathlib import Path

from erzeuge_lp_klassen import HEADER, base_types, build
from rdflib import RDFS, Graph, URIRef

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
LP = "https://w3id.org/lehrplan/ontology/"
BASES = {LP + name for name in (
    "LP_0001015", "LP_0000349", "LP_0000263", "LP_0000332", "LP_0000852", "LP_0030065", "LP_0030325",
)}  # fmt: skip


def source() -> Graph:
    return Graph().parse(ONTOLOGY / "werkzeuge" / "quellen" / "lp.ttl", format="turtle")


def rows() -> list[dict[str, str]]:
    with (ONTOLOGY / "werkzeuge" / "quellen" / "fwu-landesklassen.csv").open(encoding="utf-8") as table:
        return list(csv.DictReader(table, delimiter=";"))


def above(graph: Graph, klass: str) -> set[str]:
    seen: set[str] = set()
    todo = [URIRef(klass)]
    while todo:
        for parent in graph.objects(todo.pop(), RDFS.subClassOf):
            if str(parent) not in seen:
                seen.add(str(parent))
                todo.append(URIRef(str(parent)))
    return seen


def test_the_chain_is_as_its_generator_makes_it_byte_for_byte() -> None:
    # a checkout under core.autocrlf holds the same blob with CRLF: compared as LF
    written = (ONTOLOGY / "mem" / "lp-klassen.ttl").read_bytes().replace(b"\r\n", b"\n")

    assert written == (HEADER + build(source()).serialize(format="turtle")).encode("utf-8")


def test_the_chain_says_nothing_the_ontology_does_not() -> None:
    published = source()

    added = [triple for triple in build(published) if triple not in published]

    assert added == []


def test_a_state_class_reaches_its_base_class_by_the_ontology_s_own_superclasses() -> None:
    # Allgemeines fachliches Ziel (SN): a Bereich, as lp.ttl says
    assert LP + "LP_0000349" in above(build(source()), LP + "LP_0030050")


def test_the_base_types_are_the_table_s_byte_for_byte_and_say_what_they_are() -> None:
    written = (ONTOLOGY / "mem" / "grundtypen.json").read_bytes().replace(b"\r\n", b"\n")

    assert written == (json.dumps(base_types(rows()), ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    assert "nicht" in json.loads(written)["hinweis"]  # a classification aid, not entailed by the ontology


def test_every_curricular_state_class_has_a_base_type() -> None:
    types = base_types(rows())["grundtypen"]
    curricular = [row for row in rows() if row["basistyp"].startswith("CE-")]

    assert len(types) == len(curricular) == 428
    assert [row["iri"] for row in curricular if not set(types[row["iri"]]) & BASES] == []


def test_a_base_type_the_table_derives_from_the_chain_the_chain_holds_but_three_standards() -> None:
    # the table and lp.ttl agree, but for three Bista classes the table derives by a chain lp.ttl does not
    # give them (the KMK's are typed by a table of their own, plan M2 E13)
    chain = build(source())

    disagreeing = {
        row["iri"].removeprefix(LP) for row in rows()
        if row["basistyp"].startswith("CE-") and row["herleitung"] == "Oberklassenkette"
        and not set(row["basistyp_iri"].split(" + ")) <= above(chain, row["iri"]) | {row["iri"]}
    }  # fmt: skip

    assert disagreeing == {"LP_0030264", "LP_0000268", "LP_0030265"}
