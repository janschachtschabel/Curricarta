"""Module tables in the higher-education profile (acceptance M1, Nachtrag 11): a module handbook is
mostly one table a module, its title in the cell beside a label ("Modultitel:"), its code beside
another ("Modulnummer/-kürzel:") - Modulhandbuch B.Sc. Physik, Universität Hamburg."""

import pytest

from app.conversion.base import Block
from app.pipeline.skeleton import Skeleton
from tests.pipeline.test_skeleton import BODY, COVER, block, in_sector, skeleton, table
from tests.support import cpu_seconds

HS = "https://w3id.org/wlo/curriculum/profile/higher-education#"


def plain(made: Block) -> Block:
    """The table with no header row: its first row not set bold throughout."""
    return made.model_copy(
        update={"cells": tuple(cell.model_copy(update={"header": False}) for cell in made.cells)}
    )


def handbook(*tables: Block) -> Skeleton:
    cues, node_types = in_sector("higher-education")
    blocks = [COVER, block("p2-b1", "Pflichtmodule aus dem Fachbereich Physik:", bold=True), *tables,
              block("p9-b1", BODY)]  # fmt: skip
    return skeleton(blocks, cues, node_types)


def headings(found: Skeleton) -> list[tuple[str, int, str | None, str | None, str]]:
    return [(item.title, item.level, item.node_type, item.rule_id, item.code) for item in found.headings]


def test_each_module_table_heads_its_module_named_by_the_cell_beside_its_label() -> None:
    found = handbook(
        table("p2-b2", 1, [["", "Modultitel:", "", "Physik I (Mechanik und Wärmelehre)"],
                           ["Modulnummer/-kürzel:", "", "PHY-1", ""], ["Inhalte:", "Kinematik", "", ""]]),
        table("p3-b1", 2, [["Modultitel:", "Physik II (Elektrodynamik)"], ["Modulnummer/-kürzel:", "PHY-2"]]),
        table("p4-b1", 3, [["Modulbezeichnung", "Mathematik I"], ["Modulkürzel", "MATH 1"]]),  # no colons
    )  # fmt: skip

    assert headings(found) == [
        ("Pflichtmodule aus dem Fachbereich Physik:", 1, None, None, "1"),
        ("Physik I (Mechanik und Wärmelehre)", 2, HS + "Modul", HS + "cue-modultabelle", "PHY-1"),
        ("Physik II (Elektrodynamik)", 2, HS + "Modul", HS + "cue-modultabelle", "PHY-2"),
        ("Mathematik I", 2, HS + "Modul", HS + "cue-modultabelle", "MATH 1"),
    ]


def test_a_table_heads_no_module_where_its_label_stands_elsewhere_or_names_nothing() -> None:
    found = handbook(
        table("p3-b1", 1, [["Modul", "LP"], ["Physik I", "10"]]),  # an overview: no label
        table("p4-b1", 2, [["Semester", "Modultitel:", "Physik I"]]),  # the label not its row's first
        table("p5-b1", 3, [["Modultitel:", ""], ["Inhalte:", "Mechanik"]]),  # no title beside it
        table("p6-b1", 4, [["Modultitel:", "Titel des Moduls."], ["Modulnummer/-kürzel:", "Kürzel."]]),  # how
    )  # fmt: skip

    assert [item.title for item in found.headings] == ["Pflichtmodule aus dem Fachbereich Physik:"]


def test_a_module_s_title_wrapped_into_the_next_row_is_one_title() -> None:
    # pdfplumber parts a cell over two rows: the label's row and one without a label
    found = handbook(
        table("p3-b1", 1, [["Modultitel:", "", "Mathematik I für Studierende der Geophysik,"],
                           ["", "", "Meteorologie und Physik"], ["Modulnummer/-kürzel:", "", "MATH 1"]]),
    )  # fmt: skip

    assert headings(found)[1] == (
        "Mathematik I für Studierende der Geophysik, Meteorologie und Physik", 2, HS + "Modul",
        HS + "cue-modultabelle", "MATH 1",
    )  # fmt: skip


# review 11b-2


def test_a_header_row_naming_its_columns_is_no_label() -> None:
    found = handbook(
        table("p3-b1", 1, [["Modultitel", "LP", "Semester"], ["Physik I", "10", "1"]]),  # a study plan
        plain(table("p4-b1", 2, [["Modulbezeichnung", "ECTS"], ["Physik II", "10"]])),  # no header, no pair
    )

    assert [item.title for item in found.headings] == ["Pflichtmodule aus dem Fachbereich Physik:"]


def test_a_module_s_own_heading_before_its_table_takes_its_type_and_no_second_node_comes() -> None:
    found = handbook(
        block("p3-b1", "3.1 Physik I", bold=True),
        table("p3-b2", 1, [["Modultitel:", "Physik I"], ["Modulnummer:", "PHY-1"], ["Inhalte:", "Mechanik"]]),
    )

    # the group heading before is none: a bold line follows it at once
    assert headings(found) == [
        ("3.1 Physik I", 1, HS + "Modul", HS + "cue-modultabelle", "PHY-1")
    ]  # its label's code


def test_a_code_cell_that_is_no_code_gives_none() -> None:
    long = (
        "PHY-1 (bis WiSe 2024/25: PHY-01; siehe Anlage 3 der Fachspezifischen Bestimmungen des Fachbereichs)"
    )
    found = handbook(table("p3-b1", 1, [["Modultitel:", "Physik I"], ["Modulnummer:", long]]))

    assert headings(found)[1][4] == "1"  # assigned: its place among its siblings


@pytest.mark.parametrize(
    ("rows", "title", "code"),
    [
        ([["Modultitel:", "Physik I", "", ""], ["", "", "Leistungspunkte:", "10"]], "Physik I", "1"),
        ([["Modultitel:", "Physik I", "", ""], ["", "", "Vorlesung und Übung", ""]], "Physik I", "1"),
        ([["Modultitel:", "Physik I"], ["", "Modulnummer:", "PHY-1"]], "Physik I", "PHY-1"),  # a field
        ([["Modultitel:", "Physik I"], ["", "Dieses Modul vermittelt Grundlagen."]], "Physik I", "1"),
        ([["Modultitel:", "Theoretische"], ["", "Mechanik und"], ["", "Elektrodynamik"]],
         "Theoretische Mechanik und Elektrodynamik", "1"),  # over two rows
        ([["Modultitel:", "2 Physik I"], ["Modulnummer:", "PHY-1"]], "2 Physik I", "PHY-1"),  # numbered
        ([["Modultitel:", "Physik I"], ["Modulbezeichnung:", "Physik II"], ["Modulcode:", "PHY-1"]],
         "Physik I", "PHY-1"),  # the first title label
        ([["Modultitel:", "Physik I"], ["Modulcode:", "PHY-1"], ["Modulnummer:", "PHY-9"]],
         "Physik I", "PHY-1"),
        ([["Modultitel:", "Physik I: Mechanik und", "Modulnummer:", "PHY-1"],
          ["", "Wärmelehre", "Leistungspunkte:", "10"]],
         "Physik I: Mechanik und Wärmelehre", "1"),  # its own column alone
        ([["Modultitel:", "Physik I"], ["", "Modulnummer", "PHY-1"]], "Physik I", "PHY-1"),  # a pair
        ([["Modultitel:", "Physik I"], ["", "Leistungspunkte:", "10"]], "Physik I", "1"),  # a colon's field
    ],
    ids=["field_right", "beside", "field_below", "sentence", "two_rows", "numbered", "first_title",
         "first_code", "own_column", "label_no_colon", "colon_field"],
)  # fmt: skip
def test_a_module_s_title_takes_the_rows_it_runs_on_into_and_no_field(rows, title, code) -> None:  # type: ignore[no-untyped-def]
    found = handbook(table("p4-b1", 1, rows))

    assert headings(found)[1] == (title, 2, HS + "Modul", HS + "cue-modultabelle", code)


def test_a_label_after_the_first_rows_names_nothing() -> None:
    rows = [
        ["Lehrende:", "N. N."],
        ["Sprache:", "Deutsch"],
        ["Turnus:", "jährlich"],
        ["Modultitel:", "Physik I"],
    ]

    assert len(handbook(table("p3-b1", 1, rows)).headings) == 1


def test_a_module_s_table_before_any_heading_lies_at_the_top() -> None:
    cues, node_types = in_sector("higher-education")
    found = skeleton(
        [COVER, table("p2-b1", 1, [["Modultitel:", "Physik I"]]), block("p3-b1", BODY)], cues, node_types
    )

    assert [(item.title, item.level) for item in found.headings] == [("Physik I", 1)]


def test_a_module_s_table_lies_at_the_level_the_contents_give_it() -> None:
    cues, node_types = in_sector("higher-education")
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "2 Pflichtmodule ..... 3\n2.1 Physik I ..... 4\n2.2 Physik II ..... 5"),
        block("p3-b1", "2 Pflichtmodule", size=14, bold=True),
        block("p3-b2", "Hinweise zu den Tabellen", bold=True),
        block("p3-b3", BODY),
        table("p4-b1", 1, [["Modultitel:", "Physik I"]]),
        table("p5-b1", 2, [["Modultitel:", "Physik II"]]),
        block("p6-b1", BODY),
    ]

    found = skeleton(blocks, cues, node_types)

    assert [(item.title, item.level, item.parent) for item in found.headings] == [
        ("2 Pflichtmodule", 1, None), ("Hinweise zu den Tabellen", 2, "H1"), ("Physik I", 2, "H1"),
        ("Physik II", 2, "H1"),
    ]  # fmt: skip


def test_modules_the_contents_name_first_end_the_title_pages_at_theirs() -> None:
    cues, node_types = in_sector("higher-education")
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "Physik I ..... 3\nPhysik II ..... 4\nPhysik III ..... 5"),
        block("p2-b3", "Herausgeber: Fachbereich Physik", bold=True),  # an imprint on the contents' page
        block("p2-b4", BODY, size=9),
        table("p3-b1", 1, [["Modultitel:", "Physik I"]]),
        table("p4-b1", 2, [["Modultitel:", "Physik II"]]),
        table("p5-b1", 3, [["Modultitel:", "Physik III"]]),
        block("p6-b1", BODY),
    ]

    assert [item.title for item in skeleton(blocks, cues, node_types).headings] == [
        "Physik I",
        "Physik II",
        "Physik III",
    ]


# follow-up 11b-2


def test_a_module_s_unnumbered_heading_before_its_table_takes_the_label_s_code_not_a_word_s() -> None:
    found = handbook(
        block("p3-b1", "Physik I", bold=True),
        table("p3-b2", 1, [["Modultitel:", "Physik I"], ["Modulnummer:", "PHY-1"]]),
        block("p4-b1", "Mathematik I", bold=True),
        table("p4-b2", 2, [["Modultitel:", "Mathematik I"]]),
        table("p5-b1", 3, [["Modultitel:", "Physik II"], ["Modulnummer:", "PHY-2"]]),  # no heading of its own
    )

    assert [(item.title, item.level, item.code) for item in found.headings] == [
        ("Physik I", 1, "PHY-1"), ("Mathematik I", 1, "2"), ("Physik II", 1, "PHY-2"),
    ]  # fmt: skip  # siblings all; no "I" for a code


def test_a_heading_apart_from_its_table_or_a_second_table_alike_stays_a_heading_of_its_own() -> None:
    found = handbook(
        block("p3-b1", "Physik I", bold=True),
        block("p3-b2", BODY),  # a paragraph parts them
        table("p3-b3", 1, [["Modultitel:", "Physik I"]]),
        table("p4-b1", 2, [["Modultitel:", "Physik I"]]),  # a table alike right after it
    )

    assert [item.title for item in found.headings][-3:] == ["Physik I", "Physik I", "Physik I"]


def test_a_steckbrief_without_colons_is_a_module_where_a_second_label_tells_it() -> None:
    found = handbook(
        table("p3-b1", 1, [["Modulbezeichnung", "Experimentalphysik I"], ["Modulnummer", "PHY-1"]])
    )

    assert headings(found)[1][0::4] == ("Experimentalphysik I", "PHY-1")


@pytest.mark.parametrize(
    ("code", "kept"),
    [("PHY\N{EN DASH}1", True), ("PHY\N{HYPHEN}1", True), ("INF-B-110", True), ("MA 1001", True),
     ("-", False), ("entfällt", False), ("siehe unten", False), ("N. N.", False)],
)  # fmt: skip
def test_a_code_is_kept_where_it_has_a_code_s_shape(code: str, kept: bool) -> None:
    found = handbook(table("p3-b1", 1, [["Modultitel:", "Physik I"], ["Modulnummer:", code]]))

    assert headings(found)[1][4] == (code if kept else "1")


# overall review 11b


def higher(*blocks: Block) -> Skeleton:
    cues, node_types = in_sector("higher-education")
    return skeleton([COVER, *blocks, block("p9-b1", BODY)], cues, node_types)


def module(block_id: str, number: int, title: str, code: str | None = None) -> Block:
    rows = [["Modultitel:", title], *([["Modulnummer:", code]] if code else []), ["Inhalte:", "Mechanik"]]
    return table(block_id, number, rows)


def test_a_bold_line_between_numbered_modules_is_no_group_of_the_modules_after_it() -> None:
    found = higher(
        block("p2-b1", "3 Pflichtmodule", size=14, bold=True),
        block("p3-b1", "3.1 Physik I", bold=True), module("p3-b2", 1, "Physik I", "PHY-1"),
        block("p4-b1", "Literatur", bold=True), block("p4-b2", BODY),
        block("p5-b1", "3.2 Physik II", bold=True), module("p5-b2", 2, "Physik II", "PHY-2"),
    )  # fmt: skip

    assert [(item.title, item.level, item.parent, item.code) for item in found.headings] == [
        ("3 Pflichtmodule", 1, None, "3"), ("3.1 Physik I", 2, "H1", "PHY-1"), ("Literatur", 3, "H2", "1"),
        ("3.2 Physik II", 2, "H1", "PHY-2"),
    ]  # fmt: skip


def test_a_note_between_module_tables_is_their_sibling_not_their_group() -> None:
    found = higher(
        block("p2-b1", "2 Module", size=14, bold=True),
        block("p2-b2", "2.1 Pflichtmodule", bold=True), module("p3-b1", 1, "Physik I", "PHY-1"),
        block("p4-b1", "Anmerkung zur Prüfung", bold=True), block("p4-b2", BODY),
        module("p5-b1", 2, "Physik II", "PHY-2"), module("p6-b1", 3, "Physik III", "PHY-3"),
    )  # fmt: skip

    assert [(item.title, item.level, item.parent) for item in found.headings] == [
        ("2 Module", 1, None), ("2.1 Pflichtmodule", 2, "H1"), ("Physik I", 3, "H2"),
        ("Anmerkung zur Prüfung", 3, "H2"), ("Physik II", 3, "H2"), ("Physik III", 3, "H2"),
    ]  # fmt: skip


@pytest.mark.parametrize(
    "group",
    [["Pflichtbereich:"], ["1. Semester:"], ["Modulnummer"], ["Pflichtbereich:", "30 LP"]],
    ids=["group", "semester", "a_label_alone", "a_colon_s_pair"],
)
def test_a_study_plan_s_head_row_is_no_label_beside_a_group_row(group: list[str]) -> None:
    found = handbook(plain(table("p3-b1", 1, [["Modulbezeichnung", "ECTS"], group, ["Physik I", "10"]])))

    assert [item.title for item in found.headings] == ["Pflichtmodule aus dem Fachbereich Physik:"]


def test_a_module_s_heading_with_its_code_or_its_word_before_its_table_is_one_node() -> None:
    found = higher(
        block("p2-b1", "INF-B-110 Grundlagen der Programmierung", bold=True),
        table("p2-b2", 1, [["Modultitel:", "Grundlagen der Programmierung"], ["Modulnummer:", "INF-B-110"]]),
        block("p3-b1", "Modul 3: Datenbanken", bold=True),
        table("p3-b2", 2, [["Modultitel:", "Datenbanken"], ["Inhalte:", "SQL"]]),
    )

    assert headings(found) == [
        ("INF-B-110 Grundlagen der Programmierung", 1, HS + "Modul", HS + "cue-modultabelle", "INF-B-110"),
        ("Modul 3: Datenbanken", 1, HS + "Modul", HS + "cue-modultabelle", "3"),
    ]


def test_a_letter_inside_a_code_is_no_heading_s_code() -> None:
    found = higher(block("p2-b1", "INF-B-110 Grundlagen der Programmierung", bold=True), block("p2-b2", BODY))

    assert found.headings[0].code != "F"  # the "F" of "INF", once


def test_the_levels_are_found_in_linear_time() -> None:
    from app.pipeline import skeleton as module_of_skeleton

    numbered = module_of_skeleton._Found(0, COVER, "1 Einleitung", "1", None, large=False, matched=())
    bold = [module_of_skeleton._Found(at, COVER, f"Bereich {at}", None, None, large=False, matched=())
            for at in range(1, 40_001)]  # fmt: skip
    # 0.6 s of CPU time here (2026-11-18); looked ahead from each heading: about 11 s
    assert cpu_seconds(lambda: module_of_skeleton._raw_levels([numbered, *bold])) < 4


# follow-up of the overall review


def test_a_second_group_s_modules_lie_under_their_own_group_heading() -> None:
    numbered = higher(
        block("p2-b1", "1 Pflichtmodule", bold=True), block("p2-b2", BODY),
        module("p3-b1", 1, "Physik I", "PHY-1"), module("p4-b1", 2, "Physik II", "PHY-2"),
        block("p5-b1", "2 Wahlpflichtmodule", bold=True), block("p5-b2", BODY),
        block("p5-b3", "2.1 Schwerpunkt Astrophysik", bold=True), block("p5-b4", BODY),
        module("p6-b1", 3, "Astrophysik I", "AST-1"), module("p7-b1", 4, "Astrophysik II", "AST-2"),
    )  # fmt: skip
    sized = higher(
        block("p2-b1", "Module", size=16, bold=True), module("p3-b1", 1, "Physik I", "PHY-1"),
        block("p4-b1", "Wahlpflichtmodule", size=14, bold=True),
        module("p5-b1", 2, "Astrophysik I", "AST-1"), module("p6-b1", 3, "Astrophysik II", "AST-2"),
    )  # fmt: skip
    merged = higher(
        block("p2-b1", "3 Pflichtmodule", size=14, bold=True),
        block("p3-b1", "3.1 Physik I", bold=True), module("p3-b2", 1, "Physik I", "PHY-1"),
        block("p4-b1", "4 Wahlmodule", size=14, bold=True), block("p4-b2", BODY),
        block("p4-b3", "4.1 Schwerpunkt Astro", bold=True), block("p4-b4", BODY),
        module("p5-b1", 2, "Astrophysik I", "AST-1"),
    )  # fmt: skip

    def parents(found: Skeleton) -> dict[str, str | None]:
        titles = {item.key: item.title for item in found.headings}
        return {item.title: titles.get(item.parent or "") for item in found.headings}

    assert (
        parents(numbered)["Astrophysik I"]
        == parents(numbered)["Astrophysik II"]
        == "2.1 Schwerpunkt Astrophysik"
    )
    assert parents(sized)["Astrophysik I"] == parents(sized)["Astrophysik II"] == "Wahlpflichtmodule"
    assert parents(merged)["Astrophysik I"] == "4.1 Schwerpunkt Astro"


@pytest.mark.parametrize(
    ("heading", "tables"),
    [
        ("Modulhandbuch Physik", [("Physik", "PHY-1")]),
        ("Modulgruppe Mathematik", [("Mathematik", "MAT-1"), ("Lineare Algebra", "MAT-2")]),
        ("Modul Astrophysik", [("Physik", "PHY-1")]),
    ],
)
def test_a_group_s_heading_ending_in_a_module_s_title_is_no_module(
    heading: str, tables: list[tuple[str, str]]
) -> None:
    found = higher(
        block("p2-b1", heading, size=14, bold=True),
        *(module(f"p{3 + at}-b1", at + 1, title, code) for at, (title, code) in enumerate(tables)),
    )

    assert [item.title for item in found.headings] == [heading, *(title for title, _ in tables)]


def test_a_heading_with_the_word_modul_and_a_colon_before_the_title_is_its_module() -> None:
    found = higher(
        block("p2-b1", "Modul: Datenbanken", bold=True), module("p2-b2", 1, "Datenbanken", "INF-3")
    )

    assert [(item.title, item.code) for item in found.headings] == [("Modul: Datenbanken", "INF-3")]


def test_modules_after_a_second_group_lie_under_it_however_it_is_set() -> None:
    unnumbered = higher(
        block("p2-b1", "Pflichtmodule:", bold=True), module("p2-b2", 1, "Physik I"),
        module("p3-b1", 2, "Physik II"),
        block("p4-b1", "Wahlmodule:", bold=True), module("p4-b2", 3, "Astrophysik"),
        module("p5-b1", 4, "Optik"),
    )  # fmt: skip
    numbered = higher(
        block("p2-b1", "1 Pflichtmodule", bold=True), block("p2-b2", BODY), module("p2-b3", 1, "Physik I"),
        block("p3-b1", "1.2 Ergänzungsmodule", bold=True), block("p3-b2", BODY), module("p3-b3", 2, "Optik"),
    )  # fmt: skip

    def parent_of(found: Skeleton, title: str) -> str | None:
        titles = {item.key: item.title for item in found.headings}
        return next(titles.get(item.parent or "") for item in found.headings if item.title == title)

    assert parent_of(unnumbered, "Optik") == parent_of(unnumbered, "Astrophysik") == "Wahlmodule:"
    assert parent_of(numbered, "Optik") == "1.2 Ergänzungsmodule"
