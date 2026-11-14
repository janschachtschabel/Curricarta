"""How a MEM part is typed (app/sources/mem/classes.py, rules mem-rules/2, plan M2 E2/E8): a node or a
statement, its type, kind and addressee - by its state class's cue, else by its base class from the chain
and the base-type table, else as an area of an unknown class. Rules from the repository's ontology; parts
from the synthetic plans (tests/sources/fixtures/mem)."""

import dataclasses
import json
from functools import cache
from pathlib import Path

import pytest
from rdflib import Graph

from app.sources.mem.classes import (
    RULES,
    MemModel,
    MemRules,
    base_to_add,
    generic_class,
    model_from,
    rules_from,
    typed,
)
from app.sources.mem.rules_db import mem_files
from app.sources.mem.tree import VERWEIS, MemPart, build_tree
from tests.support import ONTOLOGY, ontology_vocabulary

CV = "https://w3id.org/wlo/curriculum/vocab#"
SCHUL = "https://w3id.org/wlo/curriculum/profile/school#"
LP = "https://w3id.org/lehrplan/ontology/"
EXACT = "http://www.w3.org/2004/02/skos/core#exactMatch"
DEFAULT = "https://w3id.org/wlo/curriculum/core#defaultAddressee"
FIXTURES = Path(__file__).parent / "fixtures" / "mem"


@cache
def rules() -> MemRules:
    vocabulary = ontology_vocabulary()
    cues = [
        (match["iri"], cue.maps_to[0])
        for cue in vocabulary.cues.values()
        for match in cue.properties.get(EXACT, [])
        if match.get("iri", "").startswith(LP) and cue.maps_to
    ]
    concepts = [
        (concept.iri, concept.broader[0] if concept.broader else None,
         next((value["iri"] for value in concept.properties.get(DEFAULT, []) if "iri" in value), None))
        for concept in vocabulary.concepts.values()
    ]  # fmt: skip
    chain = Graph().parse(ONTOLOGY / "mem" / "lp-klassen.ttl", format="turtle")
    bases = json.loads((ONTOLOGY / "mem" / "grundtypen.json").read_text(encoding="utf-8"))["grundtypen"]
    return rules_from(cues, concepts, chain, bases)


def part(*classes: str, children: int = 0, reference: bool = False) -> MemPart:
    made = MemPart("https://w3id.org/p/x", "Teil", tuple(LP + name for name in classes), reference=reference)
    made.children.extend(MemPart(f"https://w3id.org/p/c{at}", "Kind", ()) for at in range(children))
    return made


def test_the_rules_say_their_version() -> None:
    assert RULES == "mem-rules/2"


def test_a_leaf_of_a_competence_specification_is_a_learning_outcome_for_the_learner() -> None:
    found = typed(part("LP_0000263"), rules())

    assert (found.node, found.kind, found.addressee) == (
        False,
        CV + "kind_learningOutcome",
        CV + "addr_learner",
    )


def test_a_note_and_a_reference_are_for_the_educator() -> None:
    note, reference = typed(part("LP_0000852"), rules()), typed(part(reference=True), rules())

    assert (note.kind, note.addressee) == (CV + "kind_guidance", CV + "addr_educator")
    assert (reference.node, reference.kind, reference.addressee) == (
        False,
        CV + "kind_reference",
        CV + "addr_educator",
    )


def test_two_base_types_give_the_first_of_the_order() -> None:
    # Saxony's "Lernziel/Lerninhalt": a competence specification before a content
    assert typed(part("LP_0000263", "LP_0000332"), rules()).kind == CV + "kind_learningOutcome"


def test_a_statement_s_class_with_parts_below_is_a_subunit_node() -> None:
    found = typed(part("LP_0000263", children=2), rules())

    assert (found.node, found.function, found.kind) == (True, CV + "fn_subunit", None)


@pytest.mark.parametrize(
    ("classes", "function", "node_type"),
    [
        (("LP_0000349",), "fn_area", SCHUL + "Kompetenzbereich"),
        (("LP_0030325",), "fn_crossCutting", SCHUL + "Querschnittsbereich"),
        (("LP_0001015",), "fn_area", None),  # a fragment: never a frame part
    ],
    ids=["area", "cross-cutting", "fragment"],
)
def test_an_area_a_perspective_and_a_fragment_are_nodes(
    classes: tuple[str, ...], function: str, node_type: str | None
) -> None:
    found = typed(part(*classes), rules())

    assert (found.node, found.function, found.node_type) == (True, CV + function, node_type)


def test_a_state_class_typed_by_its_cue_takes_the_profile_s_type() -> None:
    # Teilthema (RP), LP_0000345: the lexicon maps it to an Inhaltsbereich
    found = typed(part("LP_0000345"), rules())

    assert (found.node, found.node_type, found.rule) == (True, SCHUL + "Inhaltsbereich", "cue")


def test_a_state_class_without_a_cue_is_typed_by_its_base_type() -> None:
    # Anforderung (HB), no cue: its base type follows from its function, the table gives it - lp.ttl does not
    found = typed(part("LP_0002128"), rules())

    assert (found.rule, found.node, found.kind) == ("base", False, CV + "kind_learningOutcome")


def test_a_class_whose_base_the_chain_alone_names_is_typed_by_it() -> None:
    # Fachbezogene Kompetenzspezifikation: subClassOf* reaches LP_0000263, the table does not name it
    found = typed(part("LP_0000336"), rules())

    assert (found.rule, found.node, found.kind) == ("base", False, CV + "kind_learningOutcome")


def test_a_state_class_the_lexicon_leaves_unclassified_is_a_statement_of_that_kind() -> None:
    # Lernmaterial (BB): the cue names the kind itself; the document decides, the review list holds it
    found = typed(part("LP_0000446"), rules())

    assert (found.rule, found.node, found.kind, found.subkind, found.addressee) == (
        "cue",
        False,
        CV + "kind_unclassified",
        None,
        CV + "addr_other",
    )


def test_a_part_of_no_known_class_is_an_area_marked_unknown() -> None:
    found = typed(part("LP_9999999"), rules())

    assert (found.node, found.function, found.rule) == (True, CV + "fn_area", "unknown")


@pytest.mark.parametrize("land", ["rp", "sn", "by", "be"])
def test_every_part_of_a_land_s_plan_is_typed_by_a_cue_or_its_base(land: str) -> None:
    answers = json.loads((FIXTURES / f"{land}.json").read_text(encoding="utf-8"))
    tree = build_tree(answers["closure"], answers["references"])

    found = {typed(each, rules()).rule for each in tree.parts.values()}

    assert "unknown" not in found


def test_a_cue_class_with_parts_below_is_a_subunit_node() -> None:
    # Kompetenzerwartung (LP_0000350): its cue names a subkind, but a statement has no children
    found = typed(part("LP_0000350", children=1), rules())

    assert (found.rule, found.node, found.function, found.kind) == ("cue", True, CV + "fn_subunit", None)


def test_a_content_leaf_is_for_the_learner() -> None:
    found = typed(part("LP_0000332"), rules())

    assert (found.kind, found.addressee) == (CV + "kind_content", CV + "addr_learner")


def test_a_subkind_s_own_addressee_comes_before_its_kind_s() -> None:
    made = rules_from(
        [(LP + "LP_1", CV + "sub_forTeachers")],
        [(CV + "sub_forTeachers", CV + "kind_learningOutcome", CV + "addr_educator")],
        Graph(),
        {},
    )

    found = typed(part("LP_1"), made)

    assert (found.kind, found.subkind, found.addressee) == (
        CV + "kind_learningOutcome",
        CV + "sub_forTeachers",
        CV + "addr_educator",
    )


def test_a_class_two_cues_name_takes_the_first_target_by_iri() -> None:
    # none does today; two imports must agree when one comes
    made = rules_from(
        [(LP + "LP_1", CV + "sub_b"), (LP + "LP_1", CV + "sub_a")],
        [(CV + "sub_a", CV + "kind_content", None), (CV + "sub_b", CV + "kind_guidance", None)],
        Graph(),
        {},
    )

    assert typed(part("LP_1"), made).subkind == CV + "sub_a"


def test_a_reference_with_parts_below_is_a_subunit_node_its_parts_kept() -> None:
    # a statement has no children: a Verweis the closure holds as a part, with parts of its own, is a node
    found = typed(part("LP_0030065", children=2), rules())

    assert (found.node, found.function, found.kind, found.rule) == (
        True,
        CV + "fn_subunit",
        None,
        "reference",
    )


# The classes the export adds and writes (plan M2-6, E8/E9)


@cache
def model() -> MemModel:
    return model_from(*mem_files(ONTOLOGY))


def test_a_class_the_chain_carries_to_its_base_needs_none_added() -> None:
    # Sachsen's "Allgemeines fachliches Ziel" is a Bereich by the chain the shapes read
    assert base_to_add((LP + "LP_0030050",), model()) is None


def test_a_class_the_chain_does_not_carry_gets_the_base_class_of_the_table() -> None:
    assert base_to_add((LP + "LP_0030011",), model()) == VERWEIS


def test_a_row_holding_its_base_class_or_no_known_class_gets_none() -> None:
    assert base_to_add((LP + "LP_0030011", VERWEIS), model()) is None
    assert base_to_add((LP + "LP_9999999",), model()) is None
    assert base_to_add((), model()) is None


def test_a_class_of_two_base_types_gets_the_first_in_their_order() -> None:
    two = model_from(Graph(), {LP + "LP_2": [LP + "LP_0000332", LP + "LP_0000263"]})

    assert base_to_add((LP + "LP_2",), two) == LP + "LP_0000263"


@pytest.mark.parametrize(
    ("function", "node_type", "kind", "expected"),
    [(None, None, CV + "kind_learningOutcome", "LP_0000263"), (None, None, CV + "kind_content", "LP_0000332"),
     (None, None, CV + "kind_guidance", "LP_0000852"), (None, None, CV + "kind_reference", "LP_0030065"),
     (None, None, CV + "kind_unclassified", "LP_0001015"), (None, None, CV + "kind_standard", "LP_0000263"),
     (CV + "fn_area", SCHUL + "Kompetenzbereich", None, "LP_0000349"),
     (CV + "fn_area", None, None, "LP_0001015"),
     (CV + "fn_area", SCHUL + "Inhaltsbereich", None, "LP_0001015"),
     (CV + "fn_crossCutting", None, None, "LP_0030325"), (CV + "fn_subunit", None, None, "LP_0001015")],
)  # fmt: skip
def test_the_generic_class_of_a_core_typing_is_the_rules_backwards(
    function: str | None, node_type: str | None, kind: str | None, expected: str
) -> None:
    # a Bereich is an area of the type the rules make one of; another area, a Fragment
    assert generic_class(function=function, node_type=node_type, kind=kind) == LP + expected


CLOSE = "http://www.w3.org/2004/02/skos/core#closeMatch"


@pytest.mark.parametrize(
    ("concept", "klass"),
    [(SCHUL + "dt-Bildungsstandards", "LP_0000571"), (SCHUL + "Regelstandard", "LP_0030266"),
     (SCHUL + "dt-Lehrplan", "LP_0000438")],
)  # fmt: skip
def test_the_school_profile_matches_the_kmk_s_classes_the_rules_type_by(concept: str, klass: str) -> None:
    matches = ontology_vocabulary().concepts[concept].properties.get(CLOSE, [])

    assert {"iri": LP + klass} in matches


# the KMK's educational standards (plan M2-7, E13): their own table, before the lexicon's cues
STANDARD, COMPETENCE_AREA, ELEMENT = "LP_0030266", "LP_0030263", "LP_0000536"


def kmk_rules() -> MemRules:
    return dataclasses.replace(rules(), kmk=True)


def test_the_rules_of_the_kmk_s_graph_say_so() -> None:
    made = rules_from([], [], Graph(), {}, kmk=True)

    assert (made.kmk, rules().kmk) == (True, False)


def test_a_kmk_standard_is_a_standard_of_the_regelstandard_for_the_learner() -> None:
    found = typed(part("LP_0000261", ELEMENT, STANDARD), kmk_rules())

    assert (found.node, found.kind, found.subkind, found.addressee, found.rule) == (
        False,
        CV + "kind_standard",
        SCHUL + "Regelstandard",
        CV + "addr_learner",
        "kmk",
    )


def test_a_kmk_standard_with_parts_below_is_a_subunit_node() -> None:
    found = typed(part(ELEMENT, STANDARD, children=2), kmk_rules())

    assert (found.node, found.function, found.rule) == (True, CV + "fn_subunit", "kmk")


def test_a_kmk_competence_area_is_an_area_of_the_competence_area_type() -> None:
    found = typed(part("LP_0000349", ELEMENT, COMPETENCE_AREA, children=1), kmk_rules())

    assert (found.node, found.function, found.node_type, found.rule) == (
        True,
        CV + "fn_area",
        SCHUL + "Kompetenzbereich",
        "kmk",
    )


def test_a_kmk_element_of_no_other_known_class_is_an_area_without_a_type_counted_apart() -> None:
    # the catch-all: every Bista part is an Element, so a class new to the rules shows in its own count
    found = typed(part("LP_0000261", ELEMENT), kmk_rules())

    assert (found.node, found.function, found.node_type, found.rule) == (
        True,
        CV + "fn_area",
        None,
        "kmk_element",
    )


def test_a_kmk_part_both_a_competence_area_and_a_standard_is_the_area() -> None:
    found = typed(part(ELEMENT, COMPETENCE_AREA, STANDARD), kmk_rules())

    assert (found.node, found.function, found.node_type, found.rule) == (
        True,
        CV + "fn_area",
        SCHUL + "Kompetenzbereich",
        "kmk",
    )


def test_a_kmk_standard_takes_its_subkind_s_own_addressee_first() -> None:
    own = dataclasses.replace(kmk_rules(), addressees={SCHUL + "Regelstandard": CV + "addr_educator"})

    assert typed(part(ELEMENT, STANDARD), own).addressee == CV + "addr_educator"


@pytest.mark.parametrize(
    ("klass", "node_type"),
    [("LP_0030335", SCHUL + "Querschnittsbereich"), ("LP_0030268", SCHUL + "Inhaltsbereich")],
)
def test_a_kmk_element_a_cue_types_keeps_the_cue_s_type(klass: str, node_type: str) -> None:
    # every Bista part is an Element (inferred): as a catch-all it comes after the cues
    found = typed(part(ELEMENT, klass), kmk_rules())

    assert (found.node_type, found.rule) == (node_type, "cue")


def test_a_kmk_reference_stays_a_reference() -> None:
    found = typed(part(ELEMENT, STANDARD, reference=True), kmk_rules())

    assert (found.kind, found.rule) == (CV + "kind_reference", "reference")


def test_outside_the_kmk_s_graph_its_classes_are_typed_as_before() -> None:
    standard = typed(part(ELEMENT, STANDARD), rules())
    element = typed(part("LP_0000261", ELEMENT), rules())

    assert (standard.subkind, standard.rule) == (SCHUL + "Kompetenzerwartung", "cue")
    assert element.rule == "unknown"


def test_every_part_of_the_kmk_s_plan_is_typed_by_its_table() -> None:
    answers = json.loads((FIXTURES / "kmk.json").read_text(encoding="utf-8"))
    tree = build_tree(answers["closure"], answers["references"])

    found = [typed(each, kmk_rules()) for each in tree.parts.values()]

    assert len(found) == 10
    assert {(each.rule, each.subkind) for each in found} == {("kmk", SCHUL + "Regelstandard")}
