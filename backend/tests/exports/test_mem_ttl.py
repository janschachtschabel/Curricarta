"""A frozen MEM import as MEM's own RDF (app/exports/mem_ttl.py, plan M2-6, E7-E9, E14): an unchanged row
under its MEM IRI with MEM's classes - the base class beside them where the chain leaves it out -, a changed
or new row under its own IRI, every row part of its parent, what MEM said beside going back out; the document
under its own IRI as a plan of its Land, from the MEM plan, with attribution and rights and no licence of the
wordings. Rows built by hand, as the reader gives them."""

from datetime import UTC, datetime
from functools import cache
from typing import Any
from uuid import UUID, uuid4

import pytest
from rdflib import RDF, RDFS, BNode, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV

from app.exports.mem_rows import MemRows
from app.exports.mem_ttl import MEM_EXPORT, mem_graph
from app.sources.mem.classes import MemModel, model_from
from app.sources.mem.rules_db import mem_files
from tests.support import ONTOLOGY

CV = "https://w3id.org/wlo/curriculum/vocab#"
LP = "https://w3id.org/lehrplan/ontology/"
OBO = "http://purl.obolibrary.org/obo/"
PART_OF, HAS_PART = URIRef(OBO + "BFO_0000050"), URIRef(OBO + "BFO_0000051")
PLAN = "https://lp-sachsen.org/resource/lehrplan-141-1"
DOC = "https://example.org/kk/doc/de-sn/lp/1"
IMPORTED, HUMAN, SOURCE = CV + "orig_import", CV + "orig_human", CV + "orig_source"
SCHUL = "https://w3id.org/wlo/curriculum/profile/school#"


@cache
def model() -> MemModel:
    return model_from(*mem_files(ONTOLOGY))


def a_document(**columns: Any) -> dict[str, Any]:
    return {
        "id": uuid4(), "iri": DOC, "title": "Lehrplan Deutsch", "rights_status": "unklar",
        "frozen_at": datetime(2026, 11, 1, tzinfo=UTC), "mem_iri": PLAN, "mem_land_iri": LP + "LP_3000046",
        "mem_class_iri": LP + "LP_0000433", "mem_subjects": [LP + "LP_0000590"],
        "mem_school_types": ["https://w3id.org/schulart/SN_1"], "mem_licence": None,
        "mem_attribution": "FWU Lehrplan-Ontologie (MEM-Schule)",
    } | columns  # fmt: skip


def a_node(name: str, *, parent: UUID | None = None, **columns: Any) -> dict[str, Any]:
    return {
        "id": uuid4(), "parent_id": parent, "position": 1, "iri": f"{DOC}/{name}", "origin_iri": IMPORTED,
        "review_status_iri": CV + "rev_proposed", "function_iri": CV + "fn_area", "node_type_iri": None,
        "original_title": f"Bereich {name}", "title_language": "de", "code": name,
        "mem_iri": f"{PLAN}/{name}", "mem_classes": [LP + "LP_0030050"], "mem_properties": {},
    } | columns  # fmt: skip


def a_statement(name: str, node: UUID, **columns: Any) -> dict[str, Any]:
    return {
        "id": uuid4(), "node_id": node, "position": 1, "iri": f"{DOC}/{name}", "origin_iri": IMPORTED,
        "verbatim": f"Die Lernenden {name}.", "language": "de",
        "statement_kind_iri": CV + "kind_learningOutcome", "subkind_iri": None, "mem_iri": f"{PLAN}/{name}",
        "mem_classes": [LP + "LP_0000263"],
        "mem_properties": {},
    } | columns  # fmt: skip


def exported(nodes: list[dict[str, Any]], statements: list[dict[str, Any]], **document: Any) -> Any:
    return mem_graph(MemRows(a_document(**document), nodes, statements), model())


def types(export: Any, subject: str) -> set[str]:
    return {str(found) for found in export.graph.objects(URIRef(subject), RDF.type)}


def test_the_exporter_says_its_version() -> None:
    assert MEM_EXPORT == "mem-ttl/1"


def test_an_unchanged_imported_row_keeps_its_mem_iri_reviewed_or_not() -> None:
    area = a_node("a")
    reviewed = a_statement("s", area["id"], review_status_iri=CV + "rev_confirmed")

    export = exported([area], [reviewed])

    assert (URIRef(PLAN + "/a"), RDFS.label, Literal("Bereich a", lang="de")) in export.graph
    assert (URIRef(PLAN + "/s"), RDFS.label, Literal("Die Lernenden s.", lang="de")) in export.graph
    assert not list(export.graph.triples((URIRef(DOC + "/a"), None, None)))
    assert export.subjects[PLAN + "/s"] == ("statement", reviewed["id"])


def test_an_edited_row_goes_out_under_its_own_iri_derived_from_mem_s() -> None:
    area = a_node("a")
    edited = a_statement("s", area["id"], origin_iri=HUMAN, statement_kind_iri=CV + "kind_content")

    export = exported([area], [edited])

    assert (URIRef(DOC + "/s"), PROV.wasDerivedFrom, URIRef(PLAN + "/s")) in export.graph
    # its kind changed: the generic class of the new one, MEM's classes of another base left out
    assert types(export, DOC + "/s") == {LP + "LP_0000332"}


def test_an_edited_row_keeps_mem_s_classes_of_the_base_it_still_has() -> None:
    area = a_node("a")
    edited = a_statement("s", area["id"], origin_iri=HUMAN, mem_classes=[LP + "LP_0030011"],
                         statement_kind_iri=CV + "kind_reference",
                         mem_properties={"targets": [PLAN + "/z"]})  # fmt: skip

    export = exported([area], [edited])

    assert types(export, DOC + "/s") == {LP + "LP_0030065", LP + "LP_0030011"}


def test_a_row_the_editors_made_has_its_own_iri_and_the_generic_class() -> None:
    area = a_node("a", origin_iri=SOURCE, mem_iri=None, mem_classes=[], function_iri=CV + "fn_crossCutting")

    export = exported([area], [])

    assert types(export, DOC + "/a") == {LP + "LP_0030325"}
    assert not list(export.graph.triples((URIRef(DOC + "/a"), PROV.wasDerivedFrom, None)))


def test_mem_s_classes_go_out_as_they_stand_and_the_base_class_beside_where_the_chain_ends_short() -> None:
    area = a_node("a")
    reference = a_statement("v", area["id"], mem_classes=[LP + "LP_0030011"],
                            statement_kind_iri=CV + "kind_reference")  # fmt: skip

    export = exported([area], [reference])

    assert types(export, PLAN + "/a") == {LP + "LP_0030050"}  # a Bereich by the chain alone
    assert types(export, PLAN + "/v") == {LP + "LP_0030011", LP + "LP_0030065"}


def test_every_row_is_part_of_its_parent_and_the_parent_has_it() -> None:
    top = a_node("a")
    below = a_node("b", parent=top["id"], origin_iri=HUMAN)
    statement = a_statement("s", below["id"])

    export = exported([top, below], [statement])

    for part, whole in ((PLAN + "/a", DOC), (DOC + "/b", PLAN + "/a"), (PLAN + "/s", DOC + "/b")):
        assert (URIRef(part), PART_OF, URIRef(whole)) in export.graph
        assert (URIRef(whole), HAS_PART, URIRef(part)) in export.graph


def test_a_reference_is_held_by_its_node_and_its_holders_and_points_at_its_targets() -> None:
    area, other = a_node("a"), a_node("b")
    # held alone: the node it hangs at is the first of its holders (app/sources/mem/tree.py)
    properties = {"holders": [PLAN + "/a", PLAN + "/b", PLAN + "/fremd"],
                  "targets": [PLAN + "/z", "Kapitel 3"], "held_only": True}  # fmt: skip
    reference = a_statement("v", area["id"], statement_kind_iri=CV + "kind_reference",
                            mem_classes=[LP + "LP_0030065"], mem_properties=properties)  # fmt: skip

    export = exported([area, other], [reference])

    held = URIRef(LP + "LP_0030071")
    assert {str(holder) for holder in export.graph.subjects(held, URIRef(PLAN + "/v"))} == {
        PLAN + "/a", PLAN + "/b", PLAN + "/fremd",
    }  # fmt: skip
    assert set(export.graph.objects(URIRef(PLAN + "/v"), URIRef(LP + "LP_0030072"))) == {
        URIRef(PLAN + "/z"), Literal("Kapitel 3"),
    }  # fmt: skip
    # a reference MEM reaches by "hat Verweis" alone is no part in MEM: it is held, not had
    assert not list(export.graph.triples((URIRef(PLAN + "/v"), PART_OF, None)))
    assert not list(export.graph.triples((None, HAS_PART, URIRef(PLAN + "/v"))))


def test_a_reference_the_closure_holds_as_a_part_stays_a_part_of_it() -> None:
    area = a_node("a")
    reference = a_statement(
        "v", area["id"], statement_kind_iri=CV + "kind_reference", mem_classes=[LP + "LP_0030065"],
        mem_properties={"targets": [PLAN + "/z"], "holders": [PLAN + "/a"]},
    )  # fmt: skip

    export = exported([area], [reference])

    assert (URIRef(PLAN + "/v"), PART_OF, URIRef(PLAN + "/a")) in export.graph
    assert (URIRef(PLAN + "/a"), URIRef(LP + "LP_0030071"), URIRef(PLAN + "/v")) in export.graph


def test_an_unchanged_reference_is_held_by_whom_mem_names_alone() -> None:
    # a Verweis of the closure MEM names no holder of: none is made up in MEM's name - the shape says so
    area = a_node("a")
    reference = a_statement(
        "v", area["id"], statement_kind_iri=CV + "kind_reference", mem_classes=[LP + "LP_0030065"],
        mem_properties={"targets": [PLAN + "/z"]},
    )  # fmt: skip

    export = exported([area], [reference])

    assert not list(export.graph.triples((None, URIRef(LP + "LP_0030071"), None)))


def test_a_reference_an_editor_changed_is_held_by_its_node() -> None:
    area = a_node("a")
    changed = a_statement(
        "v", area["id"], origin_iri=HUMAN, statement_kind_iri=CV + "kind_reference",
        mem_classes=[LP + "LP_0030065"], mem_properties={"targets": [PLAN + "/z"]},
    )  # fmt: skip

    export = exported([area], [changed])

    assert (URIRef(PLAN + "/a"), URIRef(LP + "LP_0030071"), URIRef(DOC + "/v")) in export.graph


def test_a_reference_of_no_target_the_editors_made_goes_out_as_a_hinweis() -> None:
    # nothing in the core names a reference's target: MEM's reference shape could never be met
    area = a_node("a")
    made = a_statement("v", area["id"], origin_iri=HUMAN, statement_kind_iri=CV + "kind_reference",
                       mem_iri=None, mem_classes=[], mem_properties={})  # fmt: skip

    export = exported([area], [made])

    assert types(export, DOC + "/v") == {LP + "LP_0000852"}
    assert not list(export.graph.triples((None, URIRef(LP + "LP_0030071"), None)))


def test_a_reference_an_editor_made_something_else_holds_and_points_at_nothing() -> None:
    area = a_node("a")
    properties = {"holders": [PLAN + "/a"], "targets": [PLAN + "/z"]}
    changed = a_statement("v", area["id"], origin_iri=HUMAN, statement_kind_iri=CV + "kind_content",
                          mem_classes=[LP + "LP_0030065"], mem_properties=properties)  # fmt: skip

    export = exported([area], [changed])

    assert not list(export.graph.triples((None, URIRef(LP + "LP_0030071"), None)))
    assert not list(export.graph.triples((None, URIRef(LP + "LP_0030072"), None)))


def test_what_mem_said_beside_goes_back_out() -> None:
    properties = {"number": "1.2", "position": 3, "grades": ["5", "6"], "page": "https://lp-sachsen.org/p/1",
                  "description": "Beschreibung", "hours": "12", "other_parents": [PLAN + "/x"]}  # fmt: skip
    area = a_node("a", mem_properties=properties)

    export = exported([area], [])

    graph, subject = export.graph, URIRef(PLAN + "/a")
    assert (subject, URIRef(LP + "LP_0030057"), Literal("1.2")) in graph
    assert (subject, URIRef(LP + "LP_0000460"), Literal(3)) in graph
    assert set(graph.objects(subject, URIRef(LP + "LP_0000026"))) == {Literal("5"), Literal("6")}
    assert (subject, URIRef(LP + "LP_0000463"), URIRef("https://lp-sachsen.org/p/1")) in graph
    [description] = graph.objects(subject, URIRef(LP + "LP_0030051"))
    assert (
        isinstance(description, BNode)
        and (description, DCTERMS.description, Literal("Beschreibung")) in graph
    )
    [hours] = graph.objects(subject, URIRef(LP + "LP_0000024"))
    assert (hours, RDF.type, URIRef(LP + "LP_0000508")) in graph
    assert (hours, URIRef(LP + "LP_0000344"), Literal("12")) in graph
    assert (subject, PART_OF, URIRef(PLAN + "/x")) in graph
    assert (URIRef(PLAN + "/x"), HAS_PART, subject) in graph


def test_a_changed_row_or_a_document_without_an_iri_of_its_own_is_no_export() -> None:
    exported([a_node("a", iri=None)], [])  # an unchanged row needs none: it goes out under its MEM IRI
    with pytest.raises(ValueError, match="frozen"):
        exported([a_node("a", iri=None, origin_iri=HUMAN)], [])
    with pytest.raises(ValueError, match="frozen"):
        exported([], [], iri=None)
    with pytest.raises(ValueError, match="frozen"):
        exported([], [], frozen_at=None)  # a draft copy carries its revision's IRIs: no frozen state
    with pytest.raises(ValueError, match="MEM"):
        exported([], [], mem_iri=None)


# The document (task 5)


def test_the_document_is_a_lehrplan_of_its_land_from_its_mem_plan() -> None:
    export = exported([a_node("a")], [])

    graph, document = export.graph, URIRef(DOC)
    assert types(export, DOC) == {LP + "LP_0000438", LP + "LP_0000433"}
    assert (document, URIRef(LP + "LP_0000029"), URIRef(LP + "LP_3000046")) in graph
    assert (document, URIRef(LP + "LP_0000537"), URIRef(LP + "LP_0000590")) in graph
    assert (document, URIRef(LP + "LP_0000812"), URIRef("https://w3id.org/schulart/SN_1")) in graph
    assert (document, RDFS.label, Literal("Lehrplan Deutsch", lang="de")) in graph
    assert (document, DCTERMS.source, URIRef(PLAN)) in graph
    assert (document, PROV.wasDerivedFrom, URIRef(PLAN)) in graph
    assert export.subjects[DOC][0] == "document"


def test_a_standard_of_the_kmk_is_a_bildungsstandard_of_no_land() -> None:
    export = exported([], [], mem_class_iri=LP + "LP_0000571", mem_land_iri=None)

    assert types(export, DOC) == {LP + "LP_0000571"}
    assert not list(export.graph.triples((URIRef(DOC), URIRef(LP + "LP_0000029"), None)))


def test_the_attribution_and_the_rights_status_are_written() -> None:
    export = exported([], [])

    assert (URIRef(DOC), DCTERMS.bibliographicCitation, Literal("FWU Lehrplan-Ontologie (MEM-Schule)")) in (
        export.graph
    )
    [rights] = export.graph.objects(URIRef(DOC), DCTERMS.rights)
    assert "unklar" in str(rights)


def test_no_licence_is_written_while_none_is_recorded() -> None:
    export = exported([a_node("a")], [])

    assert not list(export.graph.triples((None, DCTERMS.license, None)))


def test_a_recorded_licence_is_the_mem_plan_s_never_the_wordings() -> None:
    licence = "https://creativecommons.org/licenses/by-sa/4.0/"
    export = exported([a_node("a")], [], mem_licence=licence)
    as_text = exported([], [], mem_licence="CC BY-SA 4.0")

    assert list(export.graph.triples((None, DCTERMS.license, None))) == [
        (URIRef(PLAN), DCTERMS.license, URIRef(licence))
    ]
    assert (URIRef(PLAN), DCTERMS.license, Literal("CC BY-SA 4.0")) in as_text.graph


def test_a_plan_of_no_class_known_is_typed_by_none() -> None:
    export = exported([], [], mem_class_iri=None)

    assert types(export, DOC) == set()


def test_a_subject_or_school_type_that_is_no_iri_goes_out_as_text() -> None:
    export = exported([], [], mem_subjects=["Deutsch"], mem_school_types=["https://w3id.org/a b"])

    assert (URIRef(DOC), URIRef(LP + "LP_0000537"), Literal("Deutsch")) in export.graph
    assert (URIRef(DOC), URIRef(LP + "LP_0000812"), Literal("https://w3id.org/a b")) in export.graph


@pytest.mark.parametrize("node_type", [SCHUL + "Kompetenzbereich", SCHUL + "Inhaltsbereich"])
def test_an_edited_area_mem_makes_a_bereich_stays_one(node_type: str) -> None:
    # an edit of its title makes the row the editors' (orig_human): MEM's class still makes it a Bereich
    area = a_node("a", origin_iri=HUMAN, node_type_iri=node_type)

    export = exported([area], [])

    assert types(export, DOC + "/a") == {LP + "LP_0000349", LP + "LP_0030050"}


def test_an_edited_area_of_no_bereich_class_is_a_fragment() -> None:
    area = a_node("a", origin_iri=HUMAN, mem_classes=[LP + "LP_0000434"])  # Element (BY)

    export = exported([area], [])

    assert types(export, DOC + "/a") == {LP + "LP_0001015"}


def test_an_edited_node_mem_made_of_a_statement_s_class_keeps_it() -> None:
    # a Kompetenzspezifikation with parts became a subunit: a title fix keeps its class
    area = a_node("a")
    told = a_node("k", parent=area["id"], origin_iri=HUMAN, function_iri=CV + "fn_subunit",
                  mem_classes=[LP + "LP_0000263"])  # fmt: skip

    export = exported([area, told], [])

    assert types(export, DOC + "/k") == {LP + "LP_0000263"}


def test_an_edited_reference_with_parts_keeps_its_class_holders_and_targets() -> None:
    area = a_node("a")
    held = a_node("v", parent=area["id"], origin_iri=HUMAN, function_iri=CV + "fn_subunit",
                  mem_classes=[LP + "LP_0030011"],
                  mem_properties={"holders": [PLAN + "/a"], "targets": [PLAN + "/z"]})  # fmt: skip

    export = exported([area, held], [])

    assert types(export, DOC + "/v") == {LP + "LP_0030065", LP + "LP_0030011"}
    assert (URIRef(PLAN + "/a"), URIRef(LP + "LP_0030071"), URIRef(DOC + "/v")) in export.graph
    assert (URIRef(DOC + "/v"), URIRef(LP + "LP_0030072"), URIRef(PLAN + "/z")) in export.graph


def test_an_unchanged_row_keeps_the_holders_and_targets_mem_named_whatever_its_class() -> None:
    area = a_node("a")
    part = a_node("b", parent=area["id"], mem_properties={"holders": [PLAN + "/a"], "targets": [PLAN + "/z"]})

    export = exported([area, part], [])

    assert (URIRef(PLAN + "/a"), URIRef(LP + "LP_0030071"), URIRef(PLAN + "/b")) in export.graph
    assert (URIRef(PLAN + "/b"), URIRef(LP + "LP_0030072"), URIRef(PLAN + "/z")) in export.graph


def test_an_edited_reference_mem_holds_alone_stays_a_reference_and_no_part() -> None:
    # MEM's own reference of no target fails its shape as MEM gave it: an edit does not make it a Hinweis
    area = a_node("a")
    held = a_statement("v", area["id"], origin_iri=HUMAN, statement_kind_iri=CV + "kind_reference",
                       mem_classes=[LP + "LP_0030065"],
                       mem_properties={"held_only": True, "holders": [PLAN + "/a"]})  # fmt: skip

    export = exported([area], [held])

    assert LP + "LP_0030065" in types(export, DOC + "/v")
    assert not list(export.graph.triples((URIRef(DOC + "/v"), PART_OF, None)))
    assert (URIRef(PLAN + "/a"), URIRef(LP + "LP_0030071"), URIRef(DOC + "/v")) in export.graph


def test_an_edited_subunit_mem_names_a_verweis_stays_one_as_the_import_typed_it() -> None:
    area = a_node("a")
    held = a_node("v", parent=area["id"], origin_iri=HUMAN, function_iri=CV + "fn_subunit",
                  mem_classes=[LP + "LP_0030065", LP + "LP_0000263"],
                  mem_properties={"holders": [PLAN + "/a"], "targets": [PLAN + "/z"]})  # fmt: skip

    export = exported([area, held], [])

    assert LP + "LP_0030065" in types(export, DOC + "/v")
    assert (URIRef(DOC + "/v"), URIRef(LP + "LP_0030072"), URIRef(PLAN + "/z")) in export.graph


def test_an_edited_area_mem_makes_a_leitperspektive_stays_one() -> None:
    cross = next(klass for klass, bases in model().table_bases.items() if bases == {LP + "LP_0030325"})
    area = a_node("a", origin_iri=HUMAN, mem_classes=[cross])

    export = exported([area], [])

    assert types(export, DOC + "/a") == {LP + "LP_0030325", cross}


KMK_STANDARD = [LP + "LP_0000261", LP + "LP_0000536", LP + "LP_0030266"]  # a Bista part's classes


def a_standard(name: str, node: UUID, **columns: Any) -> dict[str, Any]:
    standard = {"statement_kind_iri": CV + "kind_standard", "subkind_iri": SCHUL + "Regelstandard",
                "mem_classes": KMK_STANDARD}  # fmt: skip
    return a_statement(name, node, **(standard | columns))


def test_an_unchanged_kmk_standard_keeps_its_classes_and_the_competence_specification_beside() -> None:
    area = a_node("a")

    export = exported([area], [a_standard("s", area["id"])])

    assert types(export, PLAN + "/s") == {*KMK_STANDARD, LP + "LP_0000263"}


def test_an_edited_kmk_standard_is_a_competence_specification_keeping_the_standard() -> None:
    area = a_node("a")

    export = exported([area], [a_standard("s", area["id"], origin_iri=HUMAN)])

    assert types(export, DOC + "/s") == {LP + "LP_0000263", LP + "LP_0030266"}
    assert (URIRef(DOC + "/s"), PROV.wasDerivedFrom, URIRef(PLAN + "/s")) in export.graph


def test_a_standard_the_editors_made_is_a_competence_specification() -> None:
    area = a_node("a")
    made = a_standard("s", area["id"], origin_iri=SOURCE, mem_iri=None, mem_classes=[])

    export = exported([area], [made])

    assert types(export, DOC + "/s") == {LP + "LP_0000263"}
