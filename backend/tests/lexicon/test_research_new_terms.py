"""The new cues the editors took from the documents' terms, in the research's files (plan M1 10.4, 10d D8,
D9): each a cue of its profile's land file, unverified at 0.7, with the editors' note, its source the
decisions' file; one the own lexicon holds, too short or of an unknown target or land is counted and left
out; the same cue the research gives is one; a decision on its IRI applies to it - and the file is checked
whole first."""

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import rdflib
from importiere_recherche import import_reports
from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, SKOS

from tests.lexicon.reports import ontology, row

CUR = rdflib.Namespace("https://w3id.org/wlo/curriculum/core#")
CV = rdflib.Namespace("https://w3id.org/wlo/curriculum/vocab#")
SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"
FILE = "entscheidungen.json"
NW = "profile/laender/schule-DE-NW.ttl"
TAKEN = Literal("Neuer Begriff eines Dokuments (X1), von der Redaktion als Hinweis übernommen", lang="de")


def graph(content: bytes) -> rdflib.Graph:
    return rdflib.Graph().parse(data=content.decode("utf-8"), format="turtle")


def new_cue(**changes: Any) -> dict[str, Any]:
    entry = {
        "profile": SCHOOL + "Terminology",
        "regions": ["DE-NW"],
        "surface_form": "Lernbereich",
        "maps_to": SCHOOL + "Kompetenzbereich",
        "role": "alt",
        "note": None,
    }
    return entry | changes


def decided(root: Path, *terms: Any, decisions: tuple[Any, ...] = ()) -> None:
    held = {"format": 2, "decisions": list(decisions), "new_terms": list(terms)}
    (root / "recherche-ergebnisse" / FILE).write_text(json.dumps(held, ensure_ascii=False), encoding="utf-8")


def cue_of(content: bytes, word: str) -> URIRef:
    found = graph(content).value(predicate=CUR.surfaceForm, object=Literal(word))
    assert isinstance(found, URIRef), word
    return found


def test_a_new_cue_comes_in_unverified_at_point_seven_with_the_editors_note(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    before, _ = import_reports(root)
    decided(root, new_cue(note="wie in HE"))

    after, reported = import_reports(root)

    g = graph(after[NW])
    cue = cue_of(after[NW], "Lernbereich")
    assert (URIRef(SCHOOL + "Terminology"), CUR.hasCue, cue) in g
    assert str(cue).startswith(SCHOOL + "re-DE-NW-")
    assert g.value(cue, CUR.cueRole) == CV.role_alt
    assert g.value(cue, CUR.cueKind) == CV.ck_term
    assert set(g.objects(cue, CUR.mapsTo)) == {URIRef(SCHOOL + "Kompetenzbereich")}
    assert set(g.objects(cue, CUR.scopeRegion)) == {URIRef("https://w3id.org/wlo/curriculum/region/DE-NW")}
    assert g.value(cue, CUR.verified) == Literal(False)
    strength = g.value(cue, CUR.strength)
    assert isinstance(strength, Literal) and strength.toPython() == Decimal("0.7")
    assert set(g.objects(cue, DCTERMS.source)) == {Literal("recherche-ergebnisse/entscheidungen.json")}
    assert set(g.objects(cue, SKOS.editorialNote)) == {
        TAKEN,
        Literal("Anmerkung der Redaktion zum neuen Begriff: wie in HE", lang="de"),
    }
    assert {t for t in g if cue not in t} == set(graph(before[NW]))  # every other cue as it was
    assert reported[FILE] == Counter({"neuer Hinweis": 1})


def test_a_new_cue_of_a_land_the_research_has_no_file_for_gets_one(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    before, _ = import_reports(root)
    decided(root, new_cue(regions=["DE-BY"]), new_cue(regions=["DE-HE", "DE-SN"], note=None))

    after, _ = import_reports(root)

    assert sorted(set(after) - set(before)) == [
        "profile/laender/schule-DE-BY.ttl",
        "profile/laender/schule-DE.ttl",
    ]
    assert after[NW] == before[NW]
    several = cue_of(after["profile/laender/schule-DE.ttl"], "Lernbereich")
    assert set(graph(after["profile/laender/schule-DE.ttl"]).objects(several, SKOS.editorialNote)) == {TAKEN}


def test_a_new_cue_s_regions_are_one_set_and_its_word_has_no_spaces_at_its_ends(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    decided(root, new_cue(regions=["DE-SN", "DE-HE"]), new_cue(regions=["DE-HE", "DE-SN", "DE-HE"]))
    once, _ = import_reports(root)
    decided(root, new_cue(regions=["DE-HE", "DE-SN"], surface_form="  Lernbereich "))

    again, reported = import_reports(root)

    assert again == once
    assert reported[FILE] == Counter({"neuer Hinweis": 1})


def test_a_new_cue_of_the_whole_country_stands_in_its_sector_s_file_of_it(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    decided(root, new_cue(regions=["DE"]))

    after, _ = import_reports(root)

    cue = cue_of(after["profile/laender/schule-DE.ttl"], "Lernbereich")
    assert str(cue).startswith(SCHOOL + "re-DE-")
    assert set(graph(after["profile/laender/schule-DE.ttl"]).objects(cue, CUR.scopeRegion)) == {
        URIRef("https://w3id.org/wlo/curriculum/region/DE")
    }


def test_a_new_cue_the_research_gives_too_is_one(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row(beleg="S")]})
    before, _ = import_reports(root)
    research = cue_of(before[NW], "Inhaltsfeld")
    decided(root, new_cue(surface_form="Inhaltsfeld", maps_to=SCHOOL + "Inhaltsbereich", role="cue"))

    after, _ = import_reports(root)

    g = graph(after[NW])
    assert cue_of(after[NW], "Inhaltsfeld") == research
    assert set(g.objects(research, DCTERMS.source)) == {
        Literal("recherche-ergebnisse/01-schule-DE-NW.md"),
        Literal("recherche-ergebnisse/entscheidungen.json"),
    }
    assert set(g.objects(research, SKOS.editorialNote)) == set(
        graph(before[NW]).objects(research, SKOS.editorialNote)
    ) | {TAKEN}
    strength = g.value(research, CUR.strength)
    assert isinstance(strength, Literal) and strength.toPython() == Decimal(
        "0.7"
    )  # the higher, not the S's 0.6
    assert g.value(research, CUR.verified) == Literal(False)


def test_a_rejection_on_a_new_cue_s_iri_leaves_it_out(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    decided(root, new_cue(regions=["DE-BY"]))
    taken = cue_of(import_reports(root)[0]["profile/laender/schule-DE-BY.ttl"], "Lernbereich")
    rejected = {"cue": str(taken), "decision": "rejected", "strength": None, "evidence": None}
    decided(root, new_cue(regions=["DE-BY"]), decisions=(rejected | {"note": None, "content": {}},))

    after, reported = import_reports(root)

    assert sorted(after) == [NW]  # the land's file held that cue alone
    assert reported[FILE] == Counter({"neuer Hinweis": 1, "verworfen": 1})


def test_a_decision_on_a_new_cue_s_iri_applies_to_it(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    decided(root, new_cue())
    taken = cue_of(import_reports(root)[0][NW], "Lernbereich")
    confirmed = {"cue": str(taken), "decision": "confirmed", "strength": "0.80", "evidence": "KLP S. 3"}
    decided(root, new_cue(), decisions=(confirmed | {"note": None, "content": {}},))

    after, reported = import_reports(root)

    assert graph(after[NW]).value(taken, CUR.verified) == Literal(True)
    assert reported[FILE] == Counter({"neuer Hinweis": 1, "bestätigt": 1})


def test_a_new_cue_the_files_cannot_take_is_counted_and_left_out(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    own = (
        "schul:Terminology cur:hasCue schul:cue-lb, schul:cue-lf .\n"
        'schul:cue-lb cur:surfaceForm "LERNBEREICH" .\n'
        'schul:cue-lf cur:pattern "^Leitfeld\\\\s+\\\\d+" ; cur:mapsTo schul:Kompetenzbereich .\n'
    )
    with (root / "profile" / "schule.ttl").open("a", encoding="utf-8") as model:
        model.write(own)
    before, _ = import_reports(root)
    decided(
        root,
        new_cue(),  # the own lexicon's word
        new_cue(surface_form="Leitfeld"),  # a heading an own pattern finds for the same target
        new_cue(surface_form="LF"),
        new_cue(surface_form="Leitidee", maps_to=SCHOOL + "Leitidee"),  # no node type of the model
        new_cue(surface_form="Leitidee", regions=["DE-NW", "DE-XX"]),  # a land not of the model
    )

    after, reported = import_reports(root)

    assert after == before
    assert reported[FILE] == Counter(
        {
            "neuer Hinweis: Wort des eigenen Lexikons": 2,
            "neuer Hinweis: zu kurz": 1,
            "neuer Hinweis: Ziel unbekannt": 1,
            "neuer Hinweis: Land unbekannt": 1,
        }
    )


@pytest.mark.parametrize(
    "terms",
    [
        [new_cue(profile="https://example.org/profile#Terminology")],
        [new_cue(regions=[])],
        [new_cue(regions={"DE-NW": True})],
        [new_cue(regions=["nw"])],
        [new_cue(regions=["DE-NW\n"])],
        [new_cue(surface_form="")],
        [new_cue(surface_form="   ")],
        [new_cue(surface_form=None)],
        [new_cue(maps_to="https://example.org/Inhaltsbereich")],
        [new_cue(maps_to=None)],
        [new_cue(role="negative")],
        [new_cue(note=7)],
        ["Lernbereich"],
    ],
    ids=[
        "unknown-profile",
        "no-regions",
        "regions-no-list",
        "region-unwritten",
        "region-with-a-line-end",
        "empty-word",
        "blank-word",
        "no-word",
        "target-of-no-namespace",
        "no-target",
        "role-negative",
        "note-no-text",
        "no-object",
    ],
)
def test_a_new_cue_outside_the_form_is_refused_before_anything_is_written(
    tmp_path: Path, terms: list[Any]
) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    decided(root, *terms)

    with pytest.raises(ValueError, match=FILE):
        import_reports(root)
