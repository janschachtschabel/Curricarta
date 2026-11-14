"""What a research report's rows become as cues (ontology/werkzeuge/recherche_cues.py, plan M1 10a
R4-R7): terms (T3), cross-cutting frames (T4) and levels (T5, scales) with a known target, heading patterns
(T2) only where a structural term and its examples carry them; unverified, strength by evidence; everything
else counted by reason, never guessed."""

import re

from recherche_cues import NONE_OWN, Cue, Model, Own, cues_of, paired
from recherche_tabellen import read_tables

FENCE = "`" * 3
T3 = (
    "land;begriff_woertlich;fundort;funktion;ziel_id;rolle;erkennungsmerkmal;beispiel_woertlich;fundstelle;"
    "gilt_fuer;plangeneration_oder_gueltig_ab;abgrenzung_verwechslung;abgleich_vorliste;hinweis_id;beleg"
)
MODEL = Model(
    targets=frozenset(
        {
            "schul:Inhaltsbereich",
            "schul:Kompetenzbereich",
            "schul:dt-Lehrplan",
            "qz:BNE",
            "qz:DigitalWorld",
            "qz:Values",
            "lvl:grade-1",
            "lvl:grade-2",
            "lvl:school-ESA",
            "lvl:school-MSA",
            "lvl:school-AHR",
            "lvl:school-FHR",
            "lvl:afb-I",
            "lvl:afb-II",
            "lvl:afb-III",
        }
    ),
    schemes=frozenset({"lvl:Grades", "qz:Hub"}),
    labels={
        "schul:Inhaltsbereich": frozenset({"inhaltsbereich", "inhaltsfeld"}),
        "schul:Kompetenzbereich": frozenset({"kompetenzbereich"}),
        "lvl:school-AHR": frozenset({"allgemeine hochschulreife", "abitur"}),
        "lvl:school-FHR": frozenset({"fachhochschulreife"}),
        # as model_of keeps a label: as written, and without its bracketed part
        "lvl:afb-I": frozenset({"anforderungsbereich i (reproduktion)", "anforderungsbereich i"}),
        "lvl:afb-II": frozenset({"anforderungsbereich ii (reorganisation)", "anforderungsbereich ii"}),
        "lvl:afb-III": frozenset({"anforderungsbereich iii (reflexion)", "anforderungsbereich iii"}),
    },
)


def report(header: str, *rows: str) -> str:
    return "\n".join(["<!-- Recherche -->", f"{FENCE}csv", header, *rows, FENCE, ""])


def t3(
    begriff: str = "Inhaltsfeld",
    ziel: str = "schul:Inhaltsbereich",
    rolle: str = "cue",
    abgleich: str = "neu",
    beleg: str = "E",
    land: str = "DE-NW",
    fundort: str = "ueberschrift",
    merkmal: str = "Nummer und Doppelpunkt",
    hinweis: str = "",
    funktion: str = "gliederung:area",
) -> str:
    example = "„Inhaltsfeld 1: Wärme“ (S. 14)"
    place = "KLP-Gym-SI-Phy-2019 S. 14"
    fields = [
        land,
        begriff,
        fundort,
        funktion,
        ziel,
        rolle,
        merkmal,
        example,
        place,
        "Physik",
        "2019",
    ]
    fields += ["nicht Lernbereich", abgleich, hinweis, beleg]
    return ";".join(fields)


def cues(
    text: str, name: str = "01-schule-DE-NW.md", own: Own = NONE_OWN
) -> tuple[list[Cue], dict[str, int]]:
    found, skipped = cues_of(name, read_tables(text), MODEL, own)
    return found, dict(skipped)


def test_a_term_becomes_an_unverified_cue_with_its_target_scope_and_evidence() -> None:
    (cue,), skipped = cues(report(T3, t3()))

    assert skipped == {}
    assert cue == Cue(
        surface="Inhaltsfeld",
        role="cue",
        kind="term",
        maps_to=("schul:Inhaltsbereich",),
        regions=("DE-NW",),
        strength="0.7",
        sources=("01-schule-DE-NW.md",),
        notes=(
            "Länderrecherche, Beleg E: KLP-Gym-SI-Phy-2019 S. 14",
            "Plangeneration laut Länderrecherche: 2019",
        ),
        occurs_in=("heading",),
        recognition=("Nummer und Doppelpunkt",),
        negative=("nicht Lernbereich",),
        examples=("Inhaltsfeld 1: Wärme",),
    )


def test_the_strength_follows_the_evidence_never_above_point_seven() -> None:
    found, _ = cues(report(T3, t3(beleg="E"), t3(begriff="Beta", beleg="S"), t3(begriff="Gamma", beleg="A")))

    assert [cue.strength for cue in found] == ["0.7", "0.6", "0.5"]


def test_a_correction_of_a_listed_cue_comes_as_a_proposal_beside_it() -> None:
    (cue,), _ = cues(report(T3, t3(abgleich="korrigiert", hinweis="schul:cue-ib-inhaltsfeld")))

    assert "Korrekturvorschlag der Länderrecherche zu schul:cue-ib-inhaltsfeld" in cue.notes


def test_a_row_without_evidence_counts_as_an_assumption() -> None:
    (cue,), _ = cues(report(T3, t3(beleg="")))

    assert cue.strength == "0.5"
    assert "Länderrecherche, Beleg A: KLP-Gym-SI-Phy-2019 S. 14" in cue.notes


def test_rows_without_a_cue_of_their_own_are_counted_by_reason() -> None:
    rows = [
        t3(abgleich="bestaetigt"),
        t3(abgleich="nicht_gefunden"),
        t3(ziel="neu"),
        t3(ziel=""),
        t3(ziel="-"),
        t3(ziel="schul:Unbekannt"),
        t3(ziel="schul:Inhaltsbereich, cv:obl_elective"),
        t3(ziel="schul:Inhaltsbereich | schul:Unbekannt"),
        t3(rolle=""),
        t3(rolle="oft"),
        t3(rolle="homonym", merkmal=""),
    ]

    found, skipped = cues(report(T3, *rows))

    assert found == []
    assert skipped == {
        "T3 bestaetigt": 1,
        "T3 nicht_gefunden": 1,
        "T3 ohne bekanntes Ziel": 6,
        "T3 ohne Rolle": 2,
        "T3 Homonym ohne Erkennungsmerkmal": 1,
    }


def test_shifted_rows_are_counted_never_read() -> None:
    found, skipped = cues(report(T3, t3(), t3() + ";zu viel"))

    assert len(found) == 1
    assert skipped == {"verschoben": 1}


def test_several_targets_are_all_mapped_where_each_is_known() -> None:
    (cue,), _ = cues(report(T3, t3(ziel="schul:Inhaltsbereich | schul:Kompetenzbereich")))

    assert cue.maps_to == ("schul:Inhaltsbereich", "schul:Kompetenzbereich")


def test_a_land_is_written_as_its_region_however_the_report_wrote_it() -> None:
    found, _ = cues(
        report(T3, t3(land="BW"), t3(begriff="Beta", land="alle"), t3(begriff="Gamma", land="DE-BE | DE-BY"))
    )

    assert [cue.regions for cue in found] == [("DE-BW",), ("DE",), ("DE-BE", "DE-BY")]


def test_where_a_term_was_found_maps_to_the_occurrence_off_list_to_none() -> None:
    places = [
        "titel",
        "inhaltsverzeichnis",
        "tabellenkopf",
        "fliesstext",
        "kasten",
        "kopfzeile",
        "randspalte",
        "Feld",
    ]
    found, _ = cues(report(T3, *(t3(begriff=place, fundort=place) for place in places)))

    assert [cue.occurs_in for cue in found] == [
        ("titlePage",),
        ("toc",),
        ("tableHeader",),
        ("body",),
        ("box",),
        ("headerFooter",),
        (),
        (),
    ]


T4 = "land;rahmen_titel;kuerzel_oder_symbol;bedeutung_woertlich;markierung_wo;entspricht;fundstelle;beleg"


def test_a_cross_cutting_frame_maps_to_its_objectives_others_are_counted() -> None:
    found, skipped = cues(
        report(
            T4,
            "DE-NW;Medienkompetenzrahmen NRW;MKR 1.1;Medien;am Satzende;"
            "Medienbildung/Digitale Welt | BNE;MKR S. 1;E",
            "DE-NW;Eigener Rahmen;X;y;z;sonstiges;S. 2;S",
        )
    )

    (cue,) = found
    assert (cue.surface, cue.maps_to, cue.role, cue.kind) == (
        "Medienkompetenzrahmen NRW",
        ("qz:BNE", "qz:DigitalWorld"),
        "cue",
        "term",
    )
    assert cue.recognition == ("Kürzel oder Symbol: MKR 1.1; markiert: am Satzende",)
    assert skipped == {"T4 ohne bekanntes Querschnittsziel": 1}


def test_a_frame_listed_once_per_objective_is_one_cue_with_all_its_objectives() -> None:
    found, _ = cues(
        report(
            T4,
            "DE-NW;Querschnittsaufgaben;-;Medien;Kapitel 1;Medienbildung/Digitale Welt;KLP S. 3;E",
            "DE-NW;Querschnittsaufgaben;-;Nachhaltigkeit;Kapitel 1;BNE;KLP S. 4;S",
            "DE-HE;Querschnittsaufgaben;-;Nachhaltigkeit;Kapitel 1;BNE;KLP S. 4;E",
        )
    )

    assert [(cue.regions, cue.maps_to, cue.notes, cue.strength) for cue in found] == [
        (
            ("DE-NW",),
            ("qz:BNE", "qz:DigitalWorld"),
            ("Länderrecherche, Beleg E: KLP S. 3", "Länderrecherche, Beleg S: KLP S. 4"),
            "0.7",
        ),
        (("DE-HE",), ("qz:BNE",), ("Länderrecherche, Beleg E: KLP S. 4",), "0.7"),
    ]


def test_early_childhood_principles_are_counted_not_mapped_to_objectives() -> None:
    found, skipped = cues(
        report(
            "land;prinzip_oder_thema_woertlich;entspricht;fundstelle;beleg",
            "DE-BB;Partizipation;Kinderrechte;S. 3;E",
        ),
        name="02-elementar-DE-BB.md",
    )

    assert found == []
    assert skipped == {"T4 Elementar (Prinzipien)": 1}


def test_school_leaving_levels_pair_each_name_with_its_level_where_the_counts_agree() -> None:
    header = (
        "land;system;stufen_in_reihenfolge_woertlich;bezug;schularten_stufen;darstellung_in_lehrplaenen;"
        "rechtsgrundlage;fundstelle;beleg"
    )
    found, skipped = cues(
        report(
            header,
            "BW;Abschlüsse [lvl:school-ESA | lvl:school-MSA];Hauptschulabschluss | Realschulabschluss;"
            "abschluss;x;y;z;S. 1;E",
            "BY;Abschlüsse [lvl:school-ESA | lvl:school-MSA];A | B | C;abschluss;x;y;z;S. 1;E",
        ),
        name="06B-abschluesse-niveaus-schularten.md",
    )

    assert [(cue.surface, cue.maps_to, cue.regions) for cue in found] == [
        ("Hauptschulabschluss", ("lvl:school-ESA",), ("DE-BW",)),
        ("Realschulabschluss", ("lvl:school-MSA",), ("DE-BW",)),
    ]
    assert skipped == {"Niveaus: Stufen und Ziele ungleich viele": 1}


def test_a_scale_pairs_its_steps_with_the_levels_after_its_scheme() -> None:
    header = (
        "land;skala_art;bereich_woertlich;stufen_in_reihenfolge_woertlich;form;jahrgaenge_schularten;"
        "auf_abschlusszeugnis;ziel_id;rechtsgrundlage_paragraf;fundstelle;beleg"
    )
    found, _ = cues(
        report(
            header,
            "BW;notenstufen;Leistungsnoten;sehr gut (1) | gut (2);note;alle;ja;"
            "lvl:Grades | lvl:grade-1 | lvl:grade-2;§ 5;S. 1;E",
        ),
        name="07A-bewertungsskalen.md",
    )

    assert [(cue.surface, cue.maps_to) for cue in found] == [
        ("sehr gut (1)", ("lvl:grade-1",)),
        ("gut (2)", ("lvl:grade-2",)),
    ]


def test_a_level_the_model_does_not_know_pairs_nothing() -> None:
    header = (
        "land;skala_art;bereich_woertlich;stufen_in_reihenfolge_woertlich;form;jahrgaenge_schularten;"
        "auf_abschlusszeugnis;ziel_id;rechtsgrundlage_paragraf;fundstelle;beleg"
    )
    found, skipped = cues(
        report(
            header,
            "BW;notenstufen;Noten;sehr gut | befriedigend;note;alle;ja;lvl:grade-1 | lvl:grade-9;§ 5;S. 1;E",
        ),
        name="07A-bewertungsskalen.md",
    )

    assert found == []
    assert skipped == {"Niveaus ohne bekanntes Ziel": 1}


def test_free_text_level_systems_are_counted_not_guessed() -> None:
    header = "land;system;stufen_in_reihenfolge;bezug;verwendet_in;darstellung;fundstelle;beleg"
    found, skipped = cues(report(header, "DE-NW;Niveaustufen;A | B;frei;x;y;S. 1;E"))

    assert found == []
    assert skipped == {"Niveaus ohne lvl-Ziele": 1}


T2 = "land;dokumentart;beispieldokument;ebene_1;ebene_2;ebene_3;nummerierung_beispiele;fundstelle;beleg"


def test_a_structural_term_with_numbered_examples_becomes_a_heading_pattern() -> None:
    text = report(T3, t3()) + report(
        T2,
        "DE-NW;KLP;KLP-Phy;Kapitel;Inhaltsfeld n: Name;Schwerpunkt;"
        "„Inhaltsfeld 1: Wärme“ / „Inhaltsfeld 12: Licht“ / „2.1“;S. 4;E",
    )

    found, _ = cues(text)

    (pattern,) = [cue for cue in found if cue.kind == "headingPattern"]
    assert (pattern.surface, pattern.maps_to, pattern.examples) == (
        "Inhaltsfeld",
        ("schul:Inhaltsbereich",),
        ("Inhaltsfeld 1: Wärme", "Inhaltsfeld 12: Licht"),
    )
    assert pattern.pattern is not None


def test_no_heading_pattern_from_a_term_that_is_no_structure_nor_from_another_land() -> None:
    outline = "Kapitel;Inhaltsfeld n: Name;x;„Inhaltsfeld 1: Wärme“;S. 4;E"
    statement = report(T3, t3(funktion="aussage:content")) + report(T2, "DE-NW;KLP;K;" + outline)
    elsewhere = report(T3, t3()) + report(T2, "DE-HE;KLP;K;" + outline)

    assert [cue.kind for cue in cues(statement)[0]] == ["term"]
    assert [cue.kind for cue in cues(elsewhere)[0]] == ["term"]


def test_no_heading_pattern_without_examples_or_without_a_structural_term() -> None:
    text = report(T3, t3(begriff="Kompetenzbereich", ziel="schul:Kompetenzbereich")) + report(
        T2,
        "DE-NW;KLP;K;Kapitel;Inhaltsfeld n: Name;x;„Inhaltsfeld 1: Wärme“;S. 4;E",
        "DE-NW;KLP;K;Kompetenzbereich;x;y;„2.1“;S. 4;E",
    )

    found, _ = cues(text)

    assert [cue.kind for cue in found] == ["term"]


# --- after review 10a (report-10a.md F1-F6, F9, F12, F13) ---


def test_a_word_the_sector_s_own_lexicon_holds_gives_no_research_cue() -> None:
    # an own cue holds in every land; a research cue of one land would outrank it there (F1)
    found, skipped = cues(report(T3, t3(), t3(begriff="Kompetenzbereich", ziel="schul:Kompetenzbereich")),
                          own=Own(words=frozenset({"inhaltsfeld"})))  # fmt: skip

    assert [cue.surface for cue in found] == ["Kompetenzbereich"]
    assert skipped == {"Wort schon im eigenen Lexikon": 1}


def test_a_word_listed_with_others_gives_one_cue_each_paired_with_its_target() -> None:
    found, _ = cues(
        report(
            T3,
            t3(
                begriff="Inhaltsfeld | Kompetenzbereich", ziel="schul:Inhaltsbereich | schul:Kompetenzbereich"
            ),
            t3(begriff="Feld | Bereich", ziel="schul:Inhaltsbereich"),
        )
    )

    assert [(cue.surface, cue.maps_to) for cue in found] == [
        ("Inhaltsfeld", ("schul:Inhaltsbereich",)),
        ("Kompetenzbereich", ("schul:Kompetenzbereich",)),
        ("Feld", ("schul:Inhaltsbereich",)),
        ("Bereich", ("schul:Inhaltsbereich",)),
    ]


def test_a_template_or_a_pattern_written_as_a_word_gives_no_cue() -> None:
    found, skipped = cues(
        report(T3, t3(begriff="Inhaltsfeld …"), t3(begriff="^Inhaltsfeld"), t3(begriff="X ..."))
    )

    assert found == []
    assert skipped == {"T3 Begriff ist Muster oder Auslassung": 3}


def test_only_new_and_corrected_rows_are_imported_any_other_match_is_counted() -> None:
    found, skipped = cues(report(T3, t3(abgleich="bestaetigt (Stufenabschnitt)"), t3(abgleich="")))

    assert found == []
    assert skipped == {"T3 Abgleich unklar": 2}


def test_a_correction_without_the_listed_cue_named_says_so_plainly() -> None:
    (cue,), _ = cues(report(T3, t3(abgleich="korrigiert")))

    assert "Korrekturvorschlag der Länderrecherche" in cue.notes


def test_several_places_and_the_vocabulary_s_own_names_map_to_occurrences() -> None:
    found, _ = cues(
        report(T3, t3(fundort="inhaltsverzeichnis | ueberschrift"), t3(begriff="Beta", fundort="heading"))
    )

    assert [cue.occurs_in for cue in found] == [("heading", "toc"), ("heading",)]


def test_examples_are_the_quoted_parts_only_where_the_field_begins_with_one() -> None:
    def example_of(field: str) -> tuple[str, ...]:
        row = t3().replace("„Inhaltsfeld 1: Wärme“ (S. 14)", field)
        (cue,), _ = cues(report(T3, row))
        return cue.examples

    assert example_of("„Inhaltsfeld 1“ und „Inhaltsfeld 2“") == ("Inhaltsfeld 1", "Inhaltsfeld 2")
    assert example_of("Sprechen und „Zuhören“") == ("Sprechen und „Zuhören“",)


def test_a_plan_generation_is_a_note_not_a_filter() -> None:
    (cue,), _ = cues(report(T3, t3()))

    assert "Plangeneration laut Länderrecherche: 2019" in cue.notes


def test_a_scheme_is_no_target_of_a_term() -> None:
    found, skipped = cues(report(T3, t3(ziel="lvl:Grades")))

    assert found == []
    assert skipped == {"T3 ohne bekanntes Ziel": 1}


def test_objectives_listed_with_commas_and_explained_in_brackets_are_mapped() -> None:
    (cue,), _ = cues(
        report(
            T4,
            "DE-SN;Rahmen;-;x;y;Medienbildung/Digitale Welt (Medien- und informatische Bildung), BNE, "
            "sonstiges;S. 1;E",
        )
    )

    assert cue.maps_to == ("qz:BNE", "qz:DigitalWorld")


def test_a_scale_s_scheme_is_dropped_before_pairing_prose_with_a_scheme_alone_pairs_nothing() -> None:
    header = (
        "land;skala_art;bereich_woertlich;stufen_in_reihenfolge_woertlich;form;jahrgaenge_schularten;"
        "auf_abschlusszeugnis;ziel_id;rechtsgrundlage_paragraf;fundstelle;beleg"
    )
    found, skipped = cues(
        report(
            header,
            "BW;noten;Noten;sehr gut | befriedigend;note;alle;ja;"
            "lvl:grade-1 | lvl:Grades | lvl:grade-2;§ 5;S. 1;E",
            "BW;noten;Tendenz;Noten dürfen mit Tendenzen versehen werden;note;alle;ja;lvl:Grades;§ 5;S. 1;E",
        ),
        name="07A-bewertungsskalen.md",
    )

    assert [(cue.surface, cue.maps_to) for cue in found] == [
        ("sehr gut", ("lvl:grade-1",)),
        ("befriedigend", ("lvl:grade-2",)),
    ]
    assert skipped == {"Niveaus: Stufen und Ziele ungleich viele": 1}


def test_steps_that_name_another_level_than_their_place_gives_pair_nothing() -> None:
    header = (
        "land;system;stufen_in_reihenfolge_woertlich;bezug;schularten_stufen;darstellung_in_lehrplaenen;"
        "rechtsgrundlage;fundstelle;beleg"
    )
    found, skipped = cues(
        report(
            header,
            "alle;Hochschulreife [lvl:school-AHR | lvl:school-FHR];Fachhochschulreife | Allgemeine "
            "Hochschulreife (Abitur);abschluss;x;y;z;S. 1;E",
        ),
        name="06B-abschluesse-niveaus-schularten.md",
    )

    assert found == []
    assert skipped == {"Niveaus: Reihenfolge widerspricht Label": 1}


def test_a_heading_pattern_finds_its_headings_and_no_other_words() -> None:
    text = report(T3, t3()) + report(
        T2, "DE-NW;KLP;K;Kapitel;Inhaltsfeld n: Name;x;„Inhaltsfeld 1: Wärme“;S. 4;E"
    )

    (pattern,) = [cue.pattern for cue in cues(text)[0] if cue.pattern]

    assert re.match(pattern, "Inhaltsfeld 12: Licht")
    assert re.match(pattern, "Inhaltsfeld IV")
    assert not re.match(pattern, "Inhaltsfelder 1")
    assert not re.match(pattern, "Das Inhaltsfeld 1")
    assert not re.match(pattern, "Inhaltsfeld Wärme")


# --- after the recheck of 10a (report-10a-recheck.md F1-F6, F11) ---


def test_words_listed_with_several_targets_are_paired_by_the_targets_labels_never_by_order() -> None:
    found, skipped = cues(
        report(
            T3,
            t3(
                begriff="Kompetenzbereich | Inhaltsfeld", ziel="schul:Inhaltsbereich | schul:Kompetenzbereich"
            ),
            t3(begriff="Bereich | Feld", ziel="schul:Inhaltsbereich | schul:Kompetenzbereich"),
        )
    )

    assert [(cue.surface, cue.maps_to) for cue in found] == [
        ("Kompetenzbereich", ("schul:Kompetenzbereich",)),
        ("Inhaltsfeld", ("schul:Inhaltsbereich",)),
    ]
    assert skipped == {"T3 Liste mit mehreren Zielen": 2}


def test_a_listed_word_that_names_several_of_its_targets_stands_for_none() -> None:
    labels = {**MODEL.labels, "schul:Kompetenzbereich": frozenset({"kompetenzbereich", "inhaltsfeld"})}
    model = Model(MODEL.targets, MODEL.schemes, labels)
    members, targets = ["Inhaltsfeld", "Kompetenzbereich"], ["schul:Inhaltsbereich", "schul:Kompetenzbereich"]

    assert paired("Inhaltsfeld", members, targets, model) is None
    assert paired("Kompetenzbereich", members, targets, model) == ["schul:Kompetenzbereich"]


def test_a_pattern_with_alternatives_is_no_list_of_words() -> None:
    found, skipped = cues(report(T3, t3(begriff="^([A-Z][a-z]+(,| und| oder)? )+Kinder$")))

    assert found == []
    assert skipped == {"T3 Begriff ist Muster oder Auslassung": 1}


def test_a_word_of_fewer_than_four_signs_gives_no_cue() -> None:
    found, skipped = cues(report(T3, t3(begriff="E | Inhaltsfeld"), t3(begriff="Ki")))

    assert [cue.surface for cue in found] == ["Inhaltsfeld"]
    assert skipped == {"Wort zu kurz": 2}


def test_an_own_word_with_a_colon_or_an_own_pattern_s_word_gives_no_cue() -> None:
    found, skipped = cues(
        report(T3, t3(begriff="Inhaltsfeld:"), t3(begriff="Lernfeld")),
        own=Own(
            words=frozenset({"inhaltsfeld"}),
            patterns=((r"^Lernfeld\s+\d+", frozenset({"schul:Inhaltsbereich"})),),
        ),
    )

    assert found == []
    assert skipped == {"Wort schon im eigenen Lexikon": 2}


def test_an_own_word_gives_no_frame_and_no_level_either() -> None:
    header = (
        "land;skala_art;bereich_woertlich;stufen_in_reihenfolge_woertlich;form;jahrgaenge_schularten;"
        "auf_abschlusszeugnis;ziel_id;rechtsgrundlage_paragraf;fundstelle;beleg"
    )
    frames, _ = cues(report(T4, "DE-NW;Rahmen;-;x;y;BNE;S. 1;E"), own=Own(words=frozenset({"rahmen"})))
    levels, _ = cues(
        report(
            header, "BW;noten;Noten;sehr gut | befriedigend;note;alle;ja;lvl:grade-1 | lvl:grade-2;§ 5;S. 1;E"
        ),
        name="07A-bewertungsskalen.md",
        own=Own(words=frozenset({"sehr gut"})),
    )

    assert frames == []
    assert [cue.surface for cue in levels] == ["befriedigend"]


def test_a_scheme_named_at_its_place_leaves_with_its_name() -> None:
    header = (
        "land;skala_art;bereich_woertlich;stufen_in_reihenfolge_woertlich;form;jahrgaenge_schularten;"
        "auf_abschlusszeugnis;ziel_id;rechtsgrundlage_paragraf;fundstelle;beleg"
    )
    found, _ = cues(
        report(
            header,
            "RP;noten;Noten;verbal | sehr gut | befriedigend;note;alle;ja;"
            "lvl:Grades | lvl:grade-1 | lvl:grade-2;§;S. 1;E",
        ),
        name="07C-bewertungsskalen.md",
    )

    assert [(cue.surface, cue.maps_to) for cue in found] == [
        ("sehr gut", ("lvl:grade-1",)),
        ("befriedigend", ("lvl:grade-2",)),
    ]


def test_a_frame_title_written_as_a_list_is_counted_not_imported() -> None:
    found, skipped = cues(report(T4, "DE-HB;Bildungsplan Physik | Mathematik Sek I;-;x;y;BNE;S. 1;E"))

    assert found == []
    assert skipped == {"T4 Rahmentitel als Liste": 1}


# --- after the third check of 10a (report-10a-third.md F1, F2, F4) ---


def test_a_list_naming_several_targets_stays_a_list_when_its_short_members_are_left() -> None:
    found, skipped = cues(
        report(
            T3,
            t3(begriff="Anforderungsbereich I | II | III", ziel="lvl:afb-I | lvl:afb-II | lvl:afb-III"),
            t3(begriff="Inhaltsfeld | … Kompetenz", ziel="schul:Inhaltsbereich | schul:Kompetenzbereich"),
        )
    )

    assert [(cue.surface, cue.maps_to) for cue in found] == [
        ("Anforderungsbereich I", ("lvl:afb-I",)),  # its label says so, with its bracket left aside
        ("Inhaltsfeld", ("schul:Inhaltsbereich",)),
    ]
    assert skipped == {"Wort zu kurz": 2}


def test_an_own_pattern_owns_only_words_for_its_own_targets() -> None:
    teil_b = Own(patterns=((r"^Teil\s+B\b", frozenset({"schul:Kompetenzbereich"})),))
    found, _ = cues(report(T3, t3(begriff="Teil B Themen")), own=teil_b)
    taken, skipped = cues(report(T3, t3(begriff="Teil B Themen", ziel="schul:Kompetenzbereich")), own=teil_b)

    assert [cue.surface for cue in found] == ["Teil B Themen"]
    assert taken == []
    assert skipped == {"Wort schon im eigenen Lexikon": 1}


def test_a_question_ending_in_a_bracket_is_no_pattern() -> None:
    (cue,), _ = cues(report(T3, t3(begriff="Was braucht das Kind (heute)?")))

    assert cue.surface == "Was braucht das Kind (heute)?"


# --- after the fourth check of 10a (report-10a-fourth.md F2, F4) ---


def test_an_own_pattern_of_a_sibling_s_target_owns_no_word_of_a_list() -> None:
    sibling = Own(patterns=((r"^Inhaltsfeld\s+\d+", frozenset({"schul:Kompetenzbereich"})),))
    found, _ = cues(
        report(
            T3,
            t3(
                begriff="Inhaltsfeld | Kompetenzbereich", ziel="schul:Inhaltsbereich | schul:Kompetenzbereich"
            ),
        ),
        own=sibling,
    )

    assert [cue.surface for cue in found] == ["Inhaltsfeld", "Kompetenzbereich"]


def test_an_own_pattern_of_the_same_target_owns_a_frame_and_a_level_step() -> None:
    header = (
        "land;skala_art;bereich_woertlich;stufen_in_reihenfolge_woertlich;form;jahrgaenge_schularten;"
        "auf_abschlusszeugnis;ziel_id;rechtsgrundlage_paragraf;fundstelle;beleg"
    )
    own = Own(
        patterns=((r"^Rahmen BNE\b", frozenset({"qz:BNE"})), (r"^sehr gut\b", frozenset({"lvl:grade-1"})))
    )
    frames, _ = cues(report(T4, "DE-NW;Rahmen BNE;-;x;y;BNE;S. 1;E"), own=own)
    levels, _ = cues(
        report(
            header, "BW;noten;Noten;sehr gut | befriedigend;note;alle;ja;lvl:grade-1 | lvl:grade-2;§ 5;S. 1;E"
        ),
        name="07A-bewertungsskalen.md",
        own=own,
    )

    assert frames == []
    assert [cue.surface for cue in levels] == ["befriedigend"]


def test_a_repeated_group_marks_a_pattern_unanchored_too() -> None:
    found, skipped = cues(report(T3, t3(begriff="(Teil )+B")))

    assert found == []
    assert skipped == {"T3 Begriff ist Muster oder Auslassung": 1}
