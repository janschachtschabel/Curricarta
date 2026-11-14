"""Importing the Länderrecherche into the lexicon (ontology/werkzeuge/importiere_recherche.py, plan M1 10a
R2, R3, R8, R11): one generated file per sector and land under profile/laender/, its cues attached to the
sector's profile, keyed by stable IRIs, the same rows giving the same bytes - and the files in the repository
are what the importer gives today."""

from decimal import Decimal
from pathlib import Path

import pytest
import rdflib
from importiere_recherche import import_reports, model_of, write_files
from rdflib import RDF, Literal, URIRef
from rdflib.namespace import DCTERMS, SKOS
from recherche_entscheidungen import decisions_of

from tests.lexicon.reports import ontology, row

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
CUR = rdflib.Namespace("https://w3id.org/wlo/curriculum/core#")
SCHOOL = rdflib.Namespace("https://w3id.org/wlo/curriculum/profile/school#")
LAND = rdflib.Namespace("https://w3id.org/wlo/curriculum/region/")


def graph(content: bytes) -> rdflib.Graph:
    return rdflib.Graph().parse(data=content.decode("utf-8"), format="turtle")


def test_one_file_per_sector_and_land_the_whole_country_and_several_lands_in_one(tmp_path: Path) -> None:
    root = ontology(
        tmp_path,
        {
            "01-schule-DE-NW.md": [row()],
            "01-schule-DE-HE.md": [row(land="DE-HE")],
            "01-schule-mehrere.md": [row(land="DE-BE | DE-BY")],
            "07A-y.md": [row(land="alle")],
        },
    )

    files, _ = import_reports(root)

    assert sorted(files) == [
        "profile/laender/schule-DE-HE.ttl",
        "profile/laender/schule-DE-NW.ttl",
        "profile/laender/schule-DE.ttl",
    ]
    nationwide = graph(files["profile/laender/schule-DE.ttl"])
    assert set(nationwide.objects(None, CUR.scopeRegion)) == {LAND["DE"], LAND["DE-BE"], LAND["DE-BY"]}
    assert len(set(nationwide.subjects(CUR.scopeRegion, None))) == 2


def test_a_cue_hangs_at_its_sector_s_profile_unverified_with_where_it_was_found(tmp_path: Path) -> None:
    files, _ = import_reports(ontology(tmp_path, {"01-schule-DE-NW.md": [row()]}))

    content = files["profile/laender/schule-DE-NW.ttl"]
    assert content.startswith(b"# GENERIERT")
    g = graph(content)
    (cue,) = g.objects(SCHOOL.Terminology, CUR.hasCue)
    assert isinstance(cue, URIRef) and str(cue).startswith(str(SCHOOL) + "re-DE-NW-")
    assert g.value(cue, CUR.surfaceForm) == Literal("Inhaltsfeld")
    assert g.value(cue, CUR.mapsTo) == SCHOOL.Inhaltsbereich
    strength = g.value(cue, CUR.strength)
    assert isinstance(strength, Literal) and strength.toPython() == Decimal("0.7")
    assert g.value(cue, CUR.verified) == Literal(False)
    assert g.value(cue, DCTERMS.source) == Literal("recherche-ergebnisse/01-schule-DE-NW.md")
    assert g.value(cue, SKOS.editorialNote) == Literal("Länderrecherche, Beleg E: KLP S. 14", lang="de")


def test_the_same_cue_twice_is_one_its_findings_together_its_strength_the_highest(tmp_path: Path) -> None:
    files, _ = import_reports(
        ontology(
            tmp_path,
            {"01-schule-DE-NW.md": [row(fundstelle="KLP S. 14", beleg="S"), row(fundstelle="KLP S. 20")]},
        )
    )

    g = graph(files["profile/laender/schule-DE-NW.ttl"])
    (cue,) = g.objects(SCHOOL.Terminology, CUR.hasCue)
    assert set(g.objects(cue, SKOS.editorialNote)) == {
        Literal("Länderrecherche, Beleg S: KLP S. 14", lang="de"),
        Literal("Länderrecherche, Beleg E: KLP S. 20", lang="de"),
        Literal("Plangeneration laut Länderrecherche: 2019", lang="de"),
    }
    strength = g.value(cue, CUR.strength)
    assert isinstance(strength, Literal) and strength.toPython() == Decimal("0.7")


def test_one_term_with_two_targets_or_two_roles_stays_two_cues(tmp_path: Path) -> None:
    other_target = row().replace("schul:Inhaltsbereich", "schul:Kompetenzbereich")
    other_role = row().replace(";cue;", ";alt;")
    files, _ = import_reports(ontology(tmp_path, {"01-schule-DE-NW.md": [row(), other_target, other_role]}))

    g = graph(files["profile/laender/schule-DE-NW.ttl"])
    assert len(set(g.objects(SCHOOL.Terminology, CUR.hasCue))) == 3


def test_a_cue_keeps_its_iri_and_the_files_their_bytes_from_one_run_to_the_next(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row(), row("Kompetenzbereich")]})

    first, _ = import_reports(root)
    second, _ = import_reports(root)

    assert first == second


def test_each_report_s_cues_and_what_gave_none_are_reported(tmp_path: Path) -> None:
    unknown = row().replace("schul:Inhaltsbereich", "schul:Unbekannt")
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row(), unknown], "01-schule-DE-HE.md": [unknown]})

    _, reported = import_reports(root)

    assert reported == {
        "01-schule-DE-HE.md": {"T3 ohne bekanntes Ziel": 1},
        "01-schule-DE-NW.md": {"Cues": 1, "T3 ohne bekanntes Ziel": 1},
    }


def test_writing_replaces_the_generated_files_and_drops_those_no_longer_given(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    folder = root / "profile" / "laender"
    folder.mkdir()
    (folder / "schule-DE-SL.ttl").write_bytes(b"# GENERIERT von werkzeuge/importiere_recherche.py alt\n")
    (folder / "schule-DE-SL-redaktion.ttl").write_bytes(b"# von Hand\n")
    files, _ = import_reports(root)

    write_files(root, files)

    assert sorted(path.name for path in folder.iterdir()) == [
        "schule-DE-NW.ttl",
        "schule-DE-SL-redaktion.ttl",
    ]
    assert (folder / "schule-DE-NW.ttl").read_bytes() == files["profile/laender/schule-DE-NW.ttl"]


def test_a_word_of_the_sector_s_own_lexicon_gives_no_research_cue(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row(), row("Kompetenzbereich")]})
    own = 'schul:Terminology cur:hasCue schul:cue-feld .\nschul:cue-feld cur:surfaceForm "INHALTSFELD" .\n'
    with (root / "profile" / "schule.ttl").open("a", encoding="utf-8") as model:
        model.write(own)

    files, reported = import_reports(root)

    g = graph(files["profile/laender/schule-DE-NW.ttl"])
    assert set(g.objects(None, CUR.surfaceForm)) == {Literal("Kompetenzbereich")}
    assert reported["01-schule-DE-NW.md"] == {"Cues": 1, "Wort schon im eigenen Lexikon": 1}


def test_a_word_an_own_pattern_finds_as_a_heading_gives_no_research_cue(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    own = (
        'schul:Terminology cur:hasCue schul:cue-if .\nschul:cue-if cur:pattern "^Inhaltsfeld\\\\s+\\\\d+" ;\n'
        "    cur:mapsTo schul:Inhaltsbereich .\n"
    )
    with (root / "profile" / "schule.ttl").open("a", encoding="utf-8") as model:
        model.write(own)

    files, reported = import_reports(root)

    assert files == {}
    assert reported["01-schule-DE-NW.md"] == {"Wort schon im eigenen Lexikon": 1}


def test_the_model_s_targets_are_no_schemes_profiles_or_cues_and_carry_their_labels(tmp_path: Path) -> None:
    root = ontology(tmp_path, {})
    extra = (
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "schul:Faecher a skos:ConceptScheme .\n"
        "schul:cue-x a cur:LexicalCue .\n"
        'schul:Inhaltsbereich skos:prefLabel "Inhaltsbereich"@de ; skos:altLabel "Inhaltsfeld"@de ,'
        ' "Feld (NW)"@de .\n'
    )
    with (root / "profile" / "schule.ttl").open("a", encoding="utf-8") as model:
        model.write(extra)

    model_, _ = model_of(root)

    assert "schul:Inhaltsbereich" in model_.targets
    assert {"schul:Faecher", "schul:cue-x", "schul:Terminology"}.isdisjoint(model_.targets)
    assert model_.schemes == {"schul:Faecher"}
    # a label with its bracketed part and without
    assert model_.labels["schul:Inhaltsbereich"] == {"inhaltsbereich", "inhaltsfeld", "feld (nw)", "feld"}


def test_the_same_cue_from_rows_that_say_more_keeps_all_they_say(tmp_path: Path) -> None:
    other = row().replace(";Nummer;", ";Doppelpunkt;")
    files, _ = import_reports(ontology(tmp_path, {"01-schule-DE-NW.md": [row(), other]}))

    g = graph(files["profile/laender/schule-DE-NW.ttl"])
    assert set(g.objects(None, CUR.recognitionHint)) == {
        Literal("Nummer", lang="de"),
        Literal("Doppelpunkt", lang="de"),
    }


def test_the_same_cue_from_two_reports_names_both(tmp_path: Path) -> None:
    files, _ = import_reports(ontology(tmp_path, {"01-schule-DE-NW.md": [row()], "06B-x.md": [row()]}))

    g = graph(files["profile/laender/schule-DE-NW.ttl"])
    assert set(g.objects(None, DCTERMS.source)) == {
        Literal("recherche-ergebnisse/01-schule-DE-NW.md"),
        Literal("recherche-ergebnisse/06B-x.md"),
    }


def test_a_file_written_by_hand_under_a_generated_name_is_not_overwritten(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    folder = root / "profile" / "laender"
    folder.mkdir()
    (folder / "schule-DE-NW.ttl").write_bytes(b"# von Hand\n")
    files, _ = import_reports(root)

    with pytest.raises(ValueError, match=r"schule-DE-NW\.ttl"):
        write_files(root, files)

    assert (folder / "schule-DE-NW.ttl").read_bytes() == b"# von Hand\n"


@pytest.mark.parametrize("land", ["x/../../../evil", "NW.ttl/../../../evil"])
def test_a_land_that_is_no_code_names_no_file_and_nothing_is_written(tmp_path: Path, land: str) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row(), row("Lernbereich", land=land)]})
    files, _ = import_reports(root)

    with pytest.raises(ValueError, match="evil"):
        write_files(root, files)

    assert not (root / "profile" / "laender").exists() or not any((root / "profile" / "laender").iterdir())
    assert not list(tmp_path.rglob("evil*"))


def test_the_repository_holds_what_the_importer_gives_today() -> None:
    files, _ = import_reports(ONTOLOGY)

    folder = ONTOLOGY / "profile" / "laender"
    held = {f"profile/laender/{path.name}": path.read_bytes() for path in folder.glob("*.ttl")}
    assert held.keys() == files.keys()
    # the working copy may end its lines with CRLF (autocrlf); the importer writes LF
    assert {name: content.replace(b"\r\n", b"\n") for name, content in held.items()} == files


def test_no_research_cue_is_verified_or_stronger_than_point_seven_unless_the_editors_confirmed_it() -> None:
    files, _ = import_reports(ONTOLOGY)
    confirmed = {cue for cue, made in decisions_of(ONTOLOGY).items() if made.decision == "confirmed"}

    for content in files.values():
        g = graph(content)
        for cue in g.subjects(RDF.type, CUR.LexicalCue):  # a cue without cur:verified fails here too
            verified, strength = g.value(cue, CUR.verified), g.value(cue, CUR.strength)
            assert isinstance(verified, Literal) and isinstance(strength, Literal)
            if str(cue) in confirmed:
                assert (verified.toPython(), strength.toPython() <= Decimal("0.9")) == (True, True), cue
            else:
                assert (verified.toPython(), strength.toPython() <= Decimal("0.7")) == (False, True), cue
