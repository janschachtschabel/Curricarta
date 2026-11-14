"""The report on the research results before and beside their import (ontology/werkzeuge/pruefe_recherche.py,
plan M1 10.2, 10b B1-B7): per report and table its rows, shifted rows by line, values outside the briefs'
lists, unknown targets and the share of evidence E; what the import makes of the report; corrections the
research offers to words of the own lexicon. A shifted row fails it."""

from pathlib import Path

from importiere_recherche import import_reports
from pruefe_recherche import report

from tests.lexicon.reports import T3, T4, block, ontology, row

OWN = """
schul:Terminology cur:hasCue schul:cue-ib .
schul:cue-ib cur:surfaceForm "Inhaltsfeld" ; cur:mapsTo schul:Inhaltsbereich .
"""


def lines_of(root: Path) -> tuple[list[str], int]:
    return report(root)


def test_a_clean_report_passes_and_says_its_rows_and_evidence(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row("Lernbereich"), row("Fach", beleg="S")]})

    lines, code = lines_of(root)

    assert code == 0
    assert "== 01-schule-DE-NW.md" in lines
    assert any("2 Zeilen, verschoben 0, Beleg E 50 %" in line for line in lines)


def test_a_shifted_row_fails_the_report_by_its_line(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row("Lernbereich"), row("Fach") + ";zu viel"]})

    lines, code = lines_of(root)

    assert code == 1
    assert any("verschoben 1 (Zeile 5)" in line for line in lines)
    assert lines[-1] == "verschobene Zeilen: 1 - der Bericht scheitert"


def test_values_outside_the_briefs_lists_are_named_with_their_count(tmp_path: Path) -> None:
    rows = [
        row("Lernbereich", rolle="oft"),
        row("Fach", fundort="Feld | ueberschrift", beleg="X"),
        row("Gebiet", fundort="Feld"),
    ]
    root = ontology(tmp_path, {"01-schule-DE-NW.md": rows})

    lines, _ = lines_of(root)

    (outside,) = [line for line in lines if "außerhalb der Listen" in line]
    assert "fundort=Feld x2" in outside
    assert "rolle=oft x1" in outside
    assert "beleg=X x1" in outside


def test_targets_the_model_does_not_know_are_named(tmp_path: Path) -> None:
    root = ontology(
        tmp_path, {"01-schule-DE-NW.md": [row("Fach", ziel="schul:Unbekannt | schul:Inhaltsbereich")]}
    )

    lines, _ = lines_of(root)

    assert any(line.strip() == "unbekannte Ziele: schul:Unbekannt x1" for line in lines)


def test_objectives_outside_the_list_of_a_frames_table_are_named(tmp_path: Path) -> None:
    text = block(T4, "DE-NW;Rahmen;-;x;y;BNE, Persönlichkeitsentwicklung (Kapitel 2);S. 1;E")
    root = ontology(tmp_path, {"01-schule-DE-NW.md": text})

    lines, _ = lines_of(root)

    (outside,) = [line for line in lines if "außerhalb der Listen" in line]
    assert outside == "    außerhalb der Listen: entspricht=Persönlichkeitsentwicklung x1"


def test_what_the_import_makes_of_a_report_is_said_as_the_importer_counts_it(tmp_path: Path) -> None:
    unknown = row("Fach", ziel="schul:Unbekannt")
    root = ontology(
        tmp_path, {"01-schule-DE-NW.md": [row("Lernbereich"), unknown, row("Gebiet", abgleich="bestaetigt")]}
    )
    _, reported = import_reports(root)

    lines, _ = lines_of(root)

    counts = reported["01-schule-DE-NW.md"]
    assert counts == {"Cues": 1, "T3 ohne bekanntes Ziel": 1, "T3 bestaetigt": 1}
    assert "  Import: 1 Cues; ohne Cue: T3 ohne bekanntes Ziel x1, T3 bestaetigt x1" in lines


def test_corrections_to_words_of_the_own_lexicon_are_listed_for_the_editors(tmp_path: Path) -> None:
    corrected = row(ziel="schul:Kompetenzbereich", abgleich="korrigiert", hinweis="schul:cue-ib")
    elsewhere = row("Lernfeld", abgleich="korrigiert", hinweis="schul:cue-lf")  # no word of the own lexicon
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row("Lernbereich"), corrected, elsewhere]})
    with (root / "profile" / "schule.ttl").open("a", encoding="utf-8") as model:
        model.write(OWN)

    lines, _ = lines_of(root)

    at = lines.index("  Korrekturvorschläge zu Wörtern des eigenen Lexikons:")
    assert lines[at + 1 :] == [
        "    Zeile 5: „Inhaltsfeld“ → schul:Kompetenzbereich (zu schul:cue-ib)",
        lines[-1],
    ]


def test_only_the_files_named_are_reported(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()], "01-schule-DE-HE.md": [row(land="DE-HE")]})

    lines, _ = report(root, [root / "recherche-ergebnisse" / "01-schule-DE-HE.md"])

    assert [line for line in lines if line.startswith("== ")] == ["== 01-schule-DE-HE.md"]


# --- after the reviews of 10b (plan M1, Nachtrag 10b) ---


def test_a_clean_report_raises_no_alarm(tmp_path: Path) -> None:
    rows = [
        row("Lernbereich"),
        row("Fach", fundort="titlePage | ueberschrift"),
        row("Gebiet", fundort="randspalte"),
        row("Feld", abgleich="bestaetigt"),
        row("Thema", abgleich="nicht_gefunden"),
    ]
    frame = "DE-NW;Rahmen;-;x;y;BNE | (Kapitel 2);S. 1;E"  # a part that is only a bracket names no objective
    root = ontology(tmp_path, {"01-schule-DE-NW.md": block(T3, *rows) + block(T4, frame)})

    lines, _ = lines_of(root)

    assert [line for line in lines if "außerhalb" in line or "unbekannte" in line] == []


def test_functions_and_comparisons_outside_their_lists_are_named(tmp_path: Path) -> None:
    rows = [row("Fach", funktion="gliederung:area | thema"), row("Gebiet", abgleich="bestaetigt (Stufe)")]
    root = ontology(tmp_path, {"01-schule-DE-NW.md": rows})

    lines, _ = lines_of(root)

    (outside,) = [line for line in lines if "außerhalb der Listen" in line]
    assert outside == "    außerhalb der Listen: funktion=thema x1, abgleich_vorliste=bestaetigt (Stufe) x1"


def test_places_are_checked_only_where_the_brief_lists_them(tmp_path: Path) -> None:
    rows = [row("Modulbeschreibung", fundort="Modulhandbuch")]
    root = ontology(tmp_path, {"03B-beruf-laender.md": rows, "04A-hochschule-laender.md": rows})

    lines, _ = lines_of(root)

    assert [line for line in lines if "außerhalb" in line] == [
        "    außerhalb der Listen: fundort=Modulhandbuch x1"
    ]
    assert lines.index("== 03B-beruf-laender.md") < lines.index("== 04A-hochschule-laender.md")


def test_a_scheme_is_no_target_of_a_term_but_names_a_level_system(tmp_path: Path) -> None:
    levels = block(
        "land;system;stufen_in_reihenfolge_woertlich;bezug;schularten_stufen;darstellung_in_lehrplaenen;"
        "rechtsgrundlage;fundstelle;beleg",
        "DE-BY;Abschlüsse [schul:Faecher | lvl:Fremd];Fächer | Fremd;-;-;-;-;S. 1;E",
    )
    reports: dict[str, list[str] | str] = {
        "01-schule-DE-NW.md": [row("Fach", ziel="schul:Faecher")],
        "06B-schule-laender.md": levels,
    }
    root = ontology(tmp_path, reports)

    lines, _ = lines_of(root)

    assert [line for line in lines if "unbekannte" in line] == [
        "    unbekannte Ziele: schul:Faecher x1",
        "    unbekannte Ziele: lvl:Fremd x1",
    ]


def test_a_correction_to_a_word_an_own_pattern_finds_is_listed_and_one_without_target_says_so(
    tmp_path: Path,
) -> None:
    own = (
        '\nschul:Terminology cur:hasCue schul:cue-lf .\nschul:cue-lf cur:pattern "^Lernfeld\\\\s+\\\\d+" ;\n'
        "    cur:mapsTo schul:Inhaltsbereich .\n"
    )
    rows = [
        row("Lernfeld", abgleich="korrigiert", hinweis="schul:cue-lf"),
        row("Lernfeld", ziel="schul:Kompetenzbereich", abgleich="korrigiert"),
        row("Inhaltsfeld", ziel="", abgleich="korrigiert"),
    ]
    root = ontology(tmp_path, {"01-schule-DE-NW.md": rows})
    with (root / "profile" / "schule.ttl").open("a", encoding="utf-8") as model:
        model.write(own + OWN)

    lines, _ = lines_of(root)

    at = lines.index("  Korrekturvorschläge zu Wörtern des eigenen Lexikons:")
    assert lines[at + 1 :] == [
        "    Zeile 4: „Lernfeld“ → schul:Inhaltsbereich (zu schul:cue-lf)",
        "    Zeile 6: „Inhaltsfeld“ → (ohne Ziel)",
        "verschobene Zeilen: 0",
    ]


def test_a_listed_word_is_judged_by_the_one_target_it_names_as_the_importer_pairs_it(tmp_path: Path) -> None:
    own = (
        '\nschul:Terminology cur:hasCue schul:cue-lf .\nschul:cue-lf cur:pattern "^Lernfeld\\\\s+\\\\d+" ;\n'
        "    cur:mapsTo schul:Kompetenzbereich .\n"
        'schul:Inhaltsbereich skos:prefLabel "Lernfeld"@de .\n'
        'schul:Kompetenzbereich skos:prefLabel "Fach"@de .\n'
        "schul:Lernbereich a cur:NodeType .\n"
    )
    rows = [
        # "Lernfeld" names schul:Inhaltsbereich, where no own word stands: the importer makes it a cue
        row("Lernfeld | Fach", ziel="schul:Inhaltsbereich | schul:Kompetenzbereich", abgleich="korrigiert"),
        # here it names none of the row's targets: the importer leaves it; the own pattern holds it for one
        row("Lernfeld | Fach", ziel="schul:Kompetenzbereich | schul:Lernbereich", abgleich="korrigiert"),
    ]
    root = ontology(tmp_path, {"01-schule-DE-NW.md": rows})
    with (root / "profile" / "schule.ttl").open("a", encoding="utf-8") as model:
        model.write(own)

    lines, _ = lines_of(root)

    (imported,) = [line for line in lines if line.startswith("  Import: ")]
    assert imported.endswith(" Cues; ohne Cue: T3 Liste mit mehreren Zielen x1")  # none as an own word
    at = lines.index("  Korrekturvorschläge zu Wörtern des eigenen Lexikons:")
    assert lines[at + 1 :] == [
        "    Zeile 5: „Lernfeld“ → schul:Kompetenzbereich | schul:Lernbereich",
        "verschobene Zeilen: 0",
    ]


def test_no_report_read_is_a_failure_of_its_own(tmp_path: Path) -> None:
    lines, code = report(tmp_path / "nicht-da")

    assert code == 2
    assert lines == ["keine Berichte gelesen"]
