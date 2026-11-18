"""The table of contents as real documents print it (acceptance M1, Nachtrag 11): entries wrapped over
lines and blocks, pages set as a column of their own, a heading after the contents, a part on a divider
page, numberings set apart and pages counted by the print the PDF reprints."""

import pytest

from app.conversion.base import Block
from app.pipeline.skeleton import Skeleton
from app.pipeline.toc import leading_number, number_depth, title_key
from tests.pipeline.test_skeleton import BODY, COVER, block, shape, skeleton, table, titles
from tests.support import CPU_GRAIN_S, cpu_growth

LEADER = "." * 40


def entries_of(blocks: list[Block]) -> list[tuple[str, str, int | None]]:
    return [(entry.title, entry.page, entry.level) for entry in skeleton(blocks).contents.entries]


def listed(lines: list[str], last: str = "p6-b1") -> list[Block]:
    """A cover, the titled contents of ``lines`` in one block, and a paragraph on page ``last``."""
    return [COVER, block("p2-b1", "Inhalt", size=16), block("p2-b2", "\n".join(lines)), block(last, BODY)]


def body(*headings: tuple[str, str]) -> list[Block]:
    """Each heading on its block id, bold, with a paragraph after it."""
    return [
        made
        for block_id, words in headings
        for made in (
            block(block_id, words, size=12, bold=True),
            block(f"{block_id}9", BODY, size=11),  # p3-b1 has its paragraph in p3-b19
        )
    ]


def parts_contents() -> list[Block]:
    """Contents of parts each in a block of its own, a part's title wrapped over two and four lines
    (Hochbauberufe BW 2026, acceptance M1)."""
    return [
        COVER,
        block("p2-b1", "Inhaltsverzeichnis", size=12),
        block("p2-b2", f"Teil I Vorbemerkungen{LEADER} 3", size=12),
        block(
            "p2-b3",
            "Teil II Lernfelder Maurer und Maurerin; Hochbaufacharbeiter und\n"
            f"Hochbaufacharbeiterin, Schwerpunkt Maurerarbeiten{LEADER} 4",
            size=12,
        ),
        block(
            "p2-b4",
            "Teil III Lernfelder Bauwerksmechaniker für Abbruch und Betontrenntechnik und\n"
            "Bauwerksmechanikerin für Abbruch und Betontrenntechnik;\n"
            "Hochbaufacharbeiter und Hochbaufacharbeiterin, Schwerpunkt Abbruch- und\n"
            f"Betontrenntechnikarbeiten {'.' * 100} 6",
            size=12,
        ),
        block("p2-b5", f"Teil IV Lesehinweise{LEADER} 8", size=12),
        *body(
            ("p3-b1", "Teil I Vorbemerkungen"),
            ("p4-b1", "Teil II Lernfelder Maurer und Maurerin"),
            ("p6-b1", "Teil III Lernfelder Bauwerksmechaniker"),
            ("p8-b1", "Teil IV Lesehinweise"),
        ),
    ]


def test_an_entry_wrapped_in_a_block_of_its_own_is_one_entry() -> None:
    assert entries_of(parts_contents()) == [
        ("Teil I Vorbemerkungen", "3", None),
        (
            "Teil II Lernfelder Maurer und Maurerin; Hochbaufacharbeiter und Hochbaufacharbeiterin, "
            "Schwerpunkt Maurerarbeiten",
            "4",
            None,
        ),
        (
            "Teil III Lernfelder Bauwerksmechaniker für Abbruch und Betontrenntechnik und "
            "Bauwerksmechanikerin für Abbruch und Betontrenntechnik; Hochbaufacharbeiter und "
            "Hochbaufacharbeiterin, Schwerpunkt Abbruch- und Betontrenntechnikarbeiten",
            "6",
            None,
        ),
        ("Teil IV Lesehinweise", "8", None),
    ]
    assert titles(skeleton(parts_contents()))[0] == "Teil I Vorbemerkungen"


@pytest.mark.parametrize(
    ("lines", "wrapped"),
    [
        (
            ["1 Einleitung ..... 3", "2 Kompetenzen im Bereich der Erkenntnisgewinnung und",
             "Kommunikation ..... 4", "3 Inhalte ..... 6"],
            "2 Kompetenzen im Bereich der Erkenntnisgewinnung und Kommunikation",
        ),
        (  # no leaders: the numbering says where an entry begins
            ["1 Einleitung 3", "2 Kompetenzen im Bereich der", "Erkenntnisgewinnung 4", "3 Inhalte 6"],
            "2 Kompetenzen im Bereich der Erkenntnisgewinnung",
        ),
    ],
)  # fmt: skip
def test_a_numbered_entry_wrapped_within_its_block_is_one_entry(lines: list[str], wrapped: str) -> None:
    assert entries_of(listed(lines)) == [("1 Einleitung", "3", 1), (wrapped, "4", 1), ("3 Inhalte", "6", 1)]


def test_an_entry_never_goes_on_into_a_line_numbered_as_its_own() -> None:
    lines = ["1 Einleitung und", "2 Ziele ..... 4", "3 Inhalte ..... 5", "4 Anhang ..... 6"]

    assert [title for title, _, _ in entries_of(listed(lines))] == ["2 Ziele", "3 Inhalte", "4 Anhang"]


def test_an_entry_goes_on_over_four_lines_at_most() -> None:
    lines = [
        "1 Einleitung ..... 3", "2 Ein Titel", "über fünf", "Zeilen", "Hinweg", "Mehr ..... 4",
        "3 Inhalte ..... 6", "4 Anhang ..... 7", "5 Glossar ..... 8",
    ]  # fmt: skip

    assert [title for title, _, _ in entries_of(listed(lines, "p9-b1"))] == [
        "1 Einleitung", "Mehr", "3 Inhalte", "4 Anhang", "5 Glossar",
    ]  # fmt: skip


def column_contents() -> list[Block]:
    """Contents whose pages pdfplumber set apart as a column, a block of titles and a block of their
    pages in turn (RLP Physik 7-10 Berlin-Brandenburg, acceptance M1)."""
    return [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "1 Kompetenzentwicklung im Fach Physik", size=11),
        block("p2-b3", "3", size=11),
        block("p2-b4", "1.1 Ziele des Unterrichts\n1.2 Fachbezogene Kompetenzen", size=11),
        block("p2-b5", "3\n4", size=11),
        block("p2-b6", "2 Kompetenzen und Standards", size=11),
        block("p2-b7", "9", size=11),
        *body(
            ("p3-b1", "1 Kompetenzentwicklung im Fach Physik"),
            ("p3-b2", "1.1 Ziele des Unterrichts"),
            ("p4-b1", "1.2 Fachbezogene Kompetenzen"),
            ("p9-b1", "2 Kompetenzen und Standards"),
        ),
    ]


def test_pages_set_apart_as_a_column_are_their_titles_pages() -> None:
    found = skeleton(column_contents())

    assert entries_of(column_contents()) == [
        ("1 Kompetenzentwicklung im Fach Physik", "3", 1),
        ("1.1 Ziele des Unterrichts", "3", 2),
        ("1.2 Fachbezogene Kompetenzen", "4", 2),
        ("2 Kompetenzen und Standards", "9", 1),
    ]
    assert titles(found) == [
        "1 Kompetenzentwicklung im Fach Physik",
        "1.1 Ziele des Unterrichts",
        "1.2 Fachbezogene Kompetenzen",
        "2 Kompetenzen und Standards",
    ]  # neither the contents' title nor their lines, nor the cover


def test_a_column_of_numbers_is_no_contents_pages_where_it_holds_another_count() -> None:
    blocks = column_contents()
    blocks[4] = block("p2-b5", "3\n4\n5", size=11)  # three pages for two titles

    assert [title for title, _, _ in entries_of(blocks)] == []


def test_an_entry_wrapped_into_the_next_block_is_one_entry() -> None:
    # the first line set smaller than the second, each a block (Modulhandbuch Physik Hamburg)
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "ORIENTIERUNGSEINHEIT ..... 3", size=11, bold=True),
        block("p2-b3", "MATHEMATIK I FÜR STUDIERENDE DER GEOPHYSIK, METEOROLOGIE", size=9, bold=True),
        block("p2-b4", "UND PHYSIK ..... 4", size=11, bold=True),
        block("p2-b5", "PROSEMINAR ..... 6", size=11, bold=True),
        block("p6-b1", BODY),
    ]  # fmt: skip

    found = skeleton(blocks)

    assert entries_of(blocks) == [
        ("ORIENTIERUNGSEINHEIT", "3", None),
        ("MATHEMATIK I FÜR STUDIERENDE DER GEOPHYSIK, METEOROLOGIE UND PHYSIK", "4", None),
        ("PROSEMINAR", "6", None),
    ]
    assert found.contents.positions == frozenset(range(1, 6))


def test_entries_wrapped_a_line_a_block_are_each_one_entry() -> None:
    # set with a line and a half between the lines: each line a block
    lines = [
        "1 Einleitung ..... 4", "2 Kompetenzen im Bereich der Erkenntnisgewinnung und",
        "Kommunikation ..... 5",
        "3 Inhalte und Themenfelder des", "Unterrichts ..... 6", "4 Anhang ..... 8",
    ]  # fmt: skip
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=16),
        *(block(f"p2-b{at}", line) for at, line in enumerate(lines, start=2)),
        block("p8-b1", BODY),
    ]

    assert entries_of(blocks) == [
        ("1 Einleitung", "4", 1),
        ("2 Kompetenzen im Bereich der Erkenntnisgewinnung und Kommunikation", "5", 1),
        ("3 Inhalte und Themenfelder des Unterrichts", "6", 1),
        ("4 Anhang", "8", 1),
    ]
    assert skeleton(blocks).contents.positions == frozenset(range(1, 8))


def test_a_part_without_a_page_between_entries_keeps_the_contents_one() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=16),
        block("p2-b2", "Vorwort ..... 3", size=11),
        block("p2-b3", "Teil A Grundlagen", size=12, bold=True),
        block("p2-b4", "A.1 Leitgedanken ..... 4\nA.2 Ziele ..... 4", size=11),
        block("p2-b5", "Teil B Lernfelder", size=12, bold=True),
        block("p2-b6", "B.1 Lernfeld 1 ..... 5", size=11),
        *body(("p3-b1", "Vorwort"), ("p4-b1", "A.1 Leitgedanken"), ("p5-b1", "B.1 Lernfeld 1")),
    ]

    found = skeleton(blocks)

    assert [title for title, _, _ in entries_of(blocks)] == [
        "Vorwort", "A.1 Leitgedanken", "A.2 Ziele", "B.1 Lernfeld 1",
    ]  # fmt: skip
    assert "Teil A Grundlagen" not in titles(found)
    assert found.contents.positions == frozenset(range(1, 7))


def topics_document() -> list[Block]:
    """Contents naming numbered topics, an overview naming them again without their numbers (number
    and title a block each), then each topic a table titled in its first row's second cell (RLP Physik
    7-10 Berlin-Brandenburg, acceptance M1)."""
    return [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block(
            "p2-b2",
            "3 Themen und Inhalte ..... 3\n3.1 Thermisches Verhalten von Körpern ..... 5\n"
            "3.2 Wechselwirkung und Kraft ..... 6",
            size=11,
        ),
        block("p3-b1", "3 Themen und Inhalte", size=14, bold=True),
        block("p3-b2", BODY, size=11),
        block("p4-b1", "3.1", size=11),
        block("p4-b2", "Thermisches Verhalten von Körpern", size=11),
        block("p4-b3", "3.2", size=11),
        block("p4-b4", "Wechselwirkung und Kraft", size=11),
        table("p5-b1", 1, [["", "3.1 Thermisches Verhalten von Körpern", ""], [BODY, "", ""]]),
        table("p6-b1", 2, [["", "3.2 Wechselwirkung und Kraft", ""], [BODY, "", ""]]),
    ]


def test_a_table_the_contents_name_in_its_first_row_is_a_heading() -> None:
    assert shape(skeleton(topics_document())) == [
        ("3 Themen und Inhalte", 1, None),
        ("3.1 Thermisches Verhalten von Körpern", 2, "H1"),
        ("3.2 Wechselwirkung und Kraft", 2, "H1"),
    ]  # the overview's lines are none: the topics' own headings bear the contents' numbers


def test_a_line_the_contents_name_without_its_number_is_their_heading_where_none_bears_it() -> None:
    blocks = [*topics_document()[:-2], block("p6-b1", BODY)]  # the overview alone names the topics

    assert titles(skeleton(blocks)) == [
        "3 Themen und Inhalte",
        "Thermisches Verhalten von Körpern",
        "Wechselwirkung und Kraft",
    ]


def gazette_reprint(titled: bool) -> list[Block]:
    """An official gazette's reprint of six pages whose contents count the booklet's, 3 to 116
    (Grundsätze elementarer Bildung Brandenburg, Amtsblatt MBJS 18/2024, acceptance M1)."""
    contents = (
        "1 . Einleitung . . . . . . 3\n2 . Bildung im Kindesalter . . . . . . 6\n"
        "6 .2 .4 Regeln aushandeln . . . . . . 49\n7 .10 Digitale Medien . . . . . . 116"
    )
    title = [block("p2-b1", "Inhalt", size=9)] if titled else []
    return [
        COVER,
        *title,
        block("p2-b2", contents, size=9),
        *body(
            ("p3-b1", "1. Einleitung"),
            ("p4-b1", "2. Bildung im Kindesalter"),
            ("p5-b1", "6.2.4 Regeln aushandeln"),
            ("p6-b1", "7.10 Digitale Medien"),
        ),
    ]


def test_titled_contents_counting_past_the_document_keep_their_entries() -> None:
    found = skeleton(gazette_reprint(titled=True))

    assert entries_of(gazette_reprint(titled=True)) == [
        ("1 . Einleitung", "3", 1),
        ("2 . Bildung im Kindesalter", "6", 1),
        ("6 .2 .4 Regeln aushandeln", "49", 3),
        ("7 .10 Digitale Medien", "116", 2),
    ]
    assert found.contents.positions == frozenset({1, 2})
    assert titles(found)[0] == "1. Einleitung"


def test_untitled_contents_counting_past_the_document_are_none() -> None:
    assert entries_of(gazette_reprint(titled=False)) == []


def heading_after(contents: str, heading: Block, foreword: int = 0) -> list[Block]:
    """Contents on the page after a ``foreword`` of so many pages, the first chapter's ``heading``
    on the next page, its paragraph, and the pages the contents name."""
    page = 2 + foreword
    before = [block(f"p{at}-b1", BODY) for at in range(2, page)]
    return [
        COVER,
        *before,
        block(f"p{page}-b1", "Inhalt", size=14, bold=True),
        block(f"p{page}-b2", contents),
        heading,
        block(f"p{page + 1}-b9", BODY),
        block(f"p{page + 6}-b1", BODY),
    ]


LEADERS = "1 Einleitung 2026 ..... 3\n2 Ziele ..... 4\n3 Inhalte ..... 5"
UNLISTED = "1 Kompetenzen der Jahrgangsstufe 10 ..... 3\n2 Inhalte ..... 5\n3 Anhang ..... 7"
LEADERLESS = "1 Grundlagen 3\n2 Inhalte 5\n3 Anhang 7"
NAMED_ALIKE = "1 Einleitung 2026 3\n2 Ziele 4\n3 Inhalte 5"
NAMED_WITHIN = "1 Kompetenzen der Jahrgangsstufe 7 3\n2 Ziele 4\n3 Inhalte 5"


@pytest.mark.parametrize(
    ("contents", "heading"),
    [
        (LEADERS, block("p3-b1", "1 Einleitung 2026", size=16, bold=True)),  # the contents name it
        (UNLISTED, block("p3-b1", "1 Kompetenzen der Jahrgangsstufe 10", size=13, bold=True)),  # larger
        (LEADERLESS, block("p3-b1", "1 Kompetenzen der Jahrgangsstufe 10", size=13, bold=True)),
        # set alike, no leaders: the contents naming it alone tell
        (NAMED_ALIKE, block("p3-b1", "1 Einleitung 2026", size=10, bold=True)),
        # its number a page within the document: nothing but the contents naming it tells
        (NAMED_WITHIN, block("p3-b1", "1 Kompetenzen der Jahrgangsstufe 7", size=10, bold=True)),
    ],
    ids=["named", "leaders_larger", "leaderless_larger", "named_alike", "named_within"],
)
@pytest.mark.parametrize("foreword", [0, 5], ids=["up_front", "behind_a_foreword"])
def test_a_heading_ending_in_a_number_after_the_contents_is_no_entry(
    contents: str, heading: Block, foreword: int
) -> None:
    moved_id = heading.id.replace("p3-", f"p{3 + foreword}-")
    moved = block(moved_id, heading.text, size=heading.font_size, bold=True)
    blocks = heading_after(contents, moved, foreword)

    found = skeleton(blocks)

    assert len(found.contents.entries) == 3  # the contents' own
    assert found.contents.positions == frozenset({1 + foreword, 2 + foreword})
    assert moved.text in titles(found)
    assert found.contents.front_end == 2 + foreword


def test_contents_going_on_a_page_on_set_alike_stay_one() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "Teil A Grundlagen ..... 3", size=12, bold=True),
        block("p2-b3", "1 Einleitung ..... 3\n2 Ziele ..... 4", size=10),
        block("p3-b1", "Teil C Anhang ..... 9", size=12, bold=True),  # its parts set as large on p2
        block("p3-b2", "3 Glossar ..... 9", size=10),
        block("p9-b1", BODY),
    ]

    assert [title for title, _, _ in entries_of(blocks)] == [
        "Teil A Grundlagen", "1 Einleitung", "2 Ziele", "Teil C Anhang", "3 Glossar",
    ]  # fmt: skip


def test_a_part_without_a_page_in_a_block_of_its_own_after_the_title_heads_its_divider_page() -> None:
    # pdfplumber: the part's line set bold, a block of its own after the contents' title
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "Teil A Grundlagen", size=11, bold=True),
        block("p2-b3", "A.1 Leitgedanken ..... 4\nA.2 Ziele ..... 4\nTeil B Lernfelder ..... 5", size=11),
        block("p2-b4", "Herausgeber: Ministerium für Bildung", size=9),
        block("p3-b1", "Teil A Grundlagen", size=16, bold=True),
        block("p4-b1", "A.1 Leitgedanken", size=12, bold=True),
        block("p4-b2", BODY, size=11),
        block("p5-b1", "Teil B Lernfelder", size=16, bold=True),
        block("p5-b2", BODY, size=11),
    ]

    found = skeleton(blocks)

    assert titles(found) == ["Teil A Grundlagen", "A.1 Leitgedanken", "Teil B Lernfelder"]
    assert found.contents.positions == frozenset({1, 2, 3})


def test_a_namesake_of_a_part_without_a_page_after_the_first_chapter_moves_no_start() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "Teil A Grundlagen\nA.1 Leitgedanken ..... 4\nA.2 Ziele ..... 5\nA.3 Inhalte ..... 6"),
        block("p3-b1", "Vorwort der Ministerin", size=12, bold=True),  # title pages, before A.1's page
        block("p3-b2", BODY, size=11),
        block("p4-b1", "A.1 Leitgedanken", size=12, bold=True),
        block("p4-b2", BODY, size=11),
        block("p5-b1", "Teil A Grundlagen", size=12, bold=True),  # a namesake behind the first chapter
        block("p6-b1", BODY, size=11),
    ]

    assert titles(skeleton(blocks))[0] == "A.1 Leitgedanken"


@pytest.mark.parametrize(
    ("title", "number"),
    [
        ("A.1 Leitgedanken", "A.1"),  # a part's letter leads its chapters' numbering
        ("B.2.3 Ziele", "B.2.3"),
        ("6 .2 .4 Regeln aushandeln", "6.2.4"),  # set apart, as an official gazette prints it
        ("3 .1 Interessen und Themen", "3.1"),
        ("1 . Einleitung", "1"),
        ("A. Grundlagen", "A"),
        ("2024 . Fassung", None),  # a year leads no numbering, set apart neither
    ],
)
def test_a_numbering_is_read_as_a_part_leads_it_and_a_gazette_sets_it(title: str, number: str | None) -> None:
    assert leading_number(title) == number


def test_a_numbering_set_apart_lies_as_deep_and_keys_its_title_as_its_heading_s() -> None:
    entry, heading = "6 .2 .4 Regeln aushandeln", "6.2.4 Regeln aushandeln"

    assert number_depth(leading_number(entry) or "") == 3
    assert title_key(entry) == title_key(heading) == "regelnaushandeln"


# review 11b-1


def test_contents_of_a_line_a_block_are_read_in_linear_time() -> None:
    found: list[Skeleton] = []

    def read(part: float) -> None:
        lines = int(4000 * part)
        entries = [
            block(f"p2-b{at}", f"Stichwort Nummer {at} ..... {3 + at // 100}") for at in range(2, lines + 2)
        ]
        found[:] = [skeleton([COVER, block("p2-b1", "Inhalt", size=16), *entries, block("p60-b1", BODY)])]

    # the work grows with the lines, not with their square (tests/support.cpu_growth)
    half, whole = cpu_growth(read)
    assert whole < 3 * half + CPU_GRAIN_S, f"CPU time: {half:.2f} s for half, {whole:.2f} s for all"
    # and one wide bound: 0.3 s of CPU time here (2026-11-18); looked back over the run at each block: 21 s
    assert whole < 3
    assert len(found[0].contents.entries) == 4000


def test_an_imprint_the_contents_list_without_a_page_never_heads_the_parts() -> None:
    contents = (
        "Teil I Vorbemerkungen ..... 3\nTeil II Bildungsauftrag ..... 4\n"
        "Teil III Didaktische Grundsätze ..... 5"
    )
    blocks = [
        COVER,
        block("p2-b1", "Inhaltsverzeichnis", size=12),
        block("p2-b2", contents + "\nImpressum", size=12),
        block("p2-b3", "Impressum", size=14, bold=True),
        block("p2-b4", "Herausgeber:", size=9),
        block("p2-b5", "Ministerium für Kultus, Thiergartenstraße 1", size=9),
        *body(
            ("p3-b1", "Teil I Vorbemerkungen"),
            ("p4-b1", "Teil II Bildungsauftrag"),
            ("p5-b1", "Teil III Didaktische Grundsätze"),
        ),
    ]

    assert titles(skeleton(blocks)) == [
        "Teil I Vorbemerkungen", "Teil II Bildungsauftrag", "Teil III Didaktische Grundsätze",
    ]  # fmt: skip


@pytest.mark.parametrize("title", ["Inhalt", "Gliederung"])
def test_titled_lines_counting_past_the_document_move_no_start_past_them(title: str) -> None:
    # hours where pages would stand: the chapters after them are no title pages
    blocks = [
        COVER,
        block("p2-b1", "Vorwort", size=14, bold=True),
        block("p2-b2", BODY),
        block("p3-b1", title, size=14, bold=True),
        block("p3-b2", "1 Grundlagen 40\n2 Fachtheorie 80\n3 Fachpraxis 120"),
        *body(
            ("p4-b1", "1 Einleitung"), ("p5-b1", "2 Ziele"),
            ("p6-b1", "Grundlagen"), ("p7-b1", "Fachtheorie"),
        ),
        block("p20-b1", BODY),
    ]  # fmt: skip

    assert titles(skeleton(blocks)) == ["1 Einleitung", "2 Ziele", "Grundlagen", "Fachtheorie"]


@pytest.mark.parametrize("heading", ["1 Leitbild 2030", "1 Kompetenzen der Jahrgangsstufe 10"])
def test_a_heading_set_as_the_contents_whose_number_runs_past_the_document_is_no_entry(heading: str) -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "1 Grundlagen 3\n2 Inhalte 5\n3 Anhang 7"),
        block("p3-b1", heading, bold=True),
        block("p3-b2", BODY),
        block("p8-b1", BODY),
    ]

    found = skeleton(blocks)

    assert [entry.title for entry in found.contents.entries] == ["1 Grundlagen", "2 Inhalte", "3 Anhang"]
    assert heading in titles(found)


def test_an_outline_with_hours_deep_in_under_its_title_is_no_contents() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "1 Einleitung ..... 3\n2 Ausbildung ..... 5\n3 Anhang ..... 15"),
        *body(("p3-b1", "1 Einleitung"), ("p5-b1", "2 Ausbildung")),
        block("p8-b1", "Gliederung", size=12, bold=True),
        block("p8-b2", "1 Grundlagen 40\n2 Fachtheorie 80\n3 Fachpraxis 120"),
        *body(("p9-b1", "Grundlagen"), ("p15-b1", "3 Anhang")),
        block("p20-b1", BODY),
    ]

    found = skeleton(blocks)

    assert "Gliederung" in titles(found)
    assert [entry.title for entry in found.contents.entries] == ["1 Einleitung", "2 Ausbildung", "3 Anhang"]


def test_a_table_s_column_head_the_contents_name_without_a_number_heads_nothing() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "Einleitung ..... 3\nKompetenzen ..... 4\nInhalte ..... 6"),
        *body(("p3-b1", "Einleitung"), ("p4-b1", "Kompetenzen")),
        table("p4-b3", 1, [["", "Kompetenzen", "Inhalte"], ["Physik", "beschreiben", "Licht"]]),
        *body(("p6-b1", "Inhalte")),
    ]

    assert "p4-b3" not in [heading.block_id for heading in skeleton(blocks).headings]


def test_a_numbered_entry_s_lines_join_in_its_block_without_a_sign_running_on() -> None:
    lines = ["1 Einleitung ..... 3", "2 Ein Titel", "Zeilen ..... 4", "3 Inhalte ..... 6"]

    assert [title for title, _, _ in entries_of(listed(lines))] == [
        "1 Einleitung",
        "2 Ein Titel Zeilen",
        "3 Inhalte",
    ]


def test_a_block_of_no_entry_at_the_top_of_the_next_page_parts_the_contents() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=16),
        block("p2-b2", "1 Einleitung ..... 3\n2 Ziele ..... 4\n3 Inhalte ..... 5"),
        block("p3-b1", "Anhang und Glossar"),
        block("p3-b2", "4 Glossar ..... 9\n5 Index ..... 10\n6 Literatur ..... 11"),
        block("p12-b1", BODY),
    ]

    assert 3 not in skeleton(blocks).contents.positions


def test_lines_an_entry_took_from_the_block_before_are_no_lines_without_a_page() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "MATHEMATIK I FÜR STUDIERENDE DER GEOPHYSIK, METEOROLOGIE", size=9, bold=True),
        block("p2-b3", "UND PHYSIK ..... 4", size=11, bold=True),
        block("p2-b4", "PROSEMINAR ..... 6", size=11, bold=True),
        block("p2-b5", "ANHANG ..... 7", size=11, bold=True),
        block("p7-b1", BODY),
    ]

    found = skeleton(blocks)

    assert (
        found.contents.entries[0].title
        == "MATHEMATIK I FÜR STUDIERENDE DER GEOPHYSIK, METEOROLOGIE UND PHYSIK"
    )
    assert found.contents.pageless == ()


def test_a_heading_without_the_contents_leaders_on_a_later_page_closes_them() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "1 Einleitung ..... 3\n2 Ziele ..... 4\n3 Inhalte ..... 5"),
        block("p3-b1", "1 Kompetenzen der Jahrgangsstufe 10", bold=True),  # set as the contents
        block("p3-b2", BODY),
        block("p12-b1", BODY),
    ]

    assert "1 Kompetenzen der Jahrgangsstufe 10" in titles(skeleton(blocks))


def test_an_entry_set_larger_on_the_contents_page_stays_theirs() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "1 Einleitung ..... 3\n2 Ziele ..... 4\n3 Inhalte ..... 5"),
        block("p2-b3", "Teil B ..... 9", size=12, bold=True),
        block("p12-b1", BODY),
    ]

    assert [title for title, _, _ in entries_of(blocks)][-1] == "Teil B"


def test_an_imprint_the_contents_list_last_on_a_page_of_its_own_heads_nothing() -> None:
    contents = "Teil I Vorbemerkungen ..... 4\nTeil II Bildungsauftrag ..... 5\nTeil III Grundsätze ..... 6"
    blocks = [
        COVER,
        block("p2-b1", "Inhaltsverzeichnis", size=12),
        block("p2-b2", contents + "\nImpressum", size=12),
        block("p3-b1", "Impressum", size=14, bold=True),  # a page of its own after the contents
        block("p3-b2", "Herausgeber: Ministerium für Kultus", size=9),
        *body(
            ("p4-b1", "Teil I Vorbemerkungen"), ("p5-b1", "Teil II Bildungsauftrag"),
            ("p6-b1", "Teil III Grundsätze"),
        ),
    ]  # fmt: skip

    assert titles(skeleton(blocks))[0] == "Teil I Vorbemerkungen"


def test_a_part_named_without_a_page_heads_no_namesake_on_the_contents_page() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "Teil A Grundlagen\nA.1 Leitgedanken ..... 4\nA.2 Ziele ..... 4\nA.3 Inhalte ..... 5"),
        block("p2-b3", "Teil A Grundlagen", size=16, bold=True),  # on the contents' page: no divider
        block("p2-b4", BODY, size=9),
        *body(("p4-b1", "A.1 Leitgedanken"), ("p5-b1", "A.3 Inhalte")),
    ]

    assert titles(skeleton(blocks))[0] == "A.1 Leitgedanken"


def test_a_bold_heading_without_a_number_lies_below_the_numbered_one_before_it() -> None:
    # Grundsätze elementarer Bildung: every heading in the body's size, the numbered sections' parts
    # bold - they lay at the top, siblings of the chapters
    blocks = [
        COVER,
        block("p2-b1", "Vorwort der Herausgeber", bold=True),  # before any numbered: at the top
        block("p2-b2", BODY),
        block("p3-b1", "1. Einleitung", bold=True),
        block("p3-b2", BODY),
        block("p4-b1", "6.1.1 Spielen", bold=True),
        block("p4-b2", BODY),
        block("p4-b3", "Pädagogisches Handeln", bold=True),
        block("p4-b4", BODY),
        block("p5-b1", "6.1.2 Essen", bold=True),
        block("p5-b2", BODY),
    ]

    assert shape(skeleton(blocks)) == [
        ("Vorwort der Herausgeber", 1, None),
        ("1. Einleitung", 1, None),
        ("6.1.1 Spielen", 2, "H2"),
        ("Pädagogisches Handeln", 3, "H3"),
        ("6.1.2 Essen", 2, "H2"),
    ]


def bold_headings(*titles: str) -> list[Block]:
    """The titles as bold headings in the body's size, each on a page of its own with a paragraph."""
    return [
        COVER,
        *(made for page, title in enumerate(titles, start=2)
          for made in (block(f"p{page}-b1", title, bold=True), block(f"p{page}-b2", BODY))),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("titles", "expected"),
    [
        (  # unnumbered parts, numbered sections: a part after a section is no part of it
            ["Teil A Grundlagen", "A.1 Ziele", "A.2 Aufgaben", "Teil B Fächer", "B.1 Mathematik",
             "B.2 Physik"],
            [("Teil A Grundlagen", 1, None), ("A.1 Ziele", 2, "H1"), ("A.2 Aufgaben", 2, "H1"),
             ("Teil B Fächer", 1, None), ("B.1 Mathematik", 2, "H4"), ("B.2 Physik", 2, "H4")],
        ),
        (  # the numbering begins deep: a chapter's next sections begin anew
            ["Kompetenzen", "1.1 Ziele", "1.2 Aufgaben", "Inhalte", "2.1 Mechanik", "2.2 Optik"],
            [("Kompetenzen", 1, None), ("1.1 Ziele", 2, "H1"), ("1.2 Aufgaben", 2, "H1"),
             ("Inhalte", 1, None), ("2.1 Mechanik", 2, "H4"), ("2.2 Optik", 2, "H4")],
        ),
        (  # back matter with a part's word stays at the top
            ["1 Grundlagen", "1.1 Ziele", "Anhang"],
            [("1 Grundlagen", 1, None), ("1.1 Ziele", 2, "H1"), ("Anhang", 1, None)],
        ),
    ],
    ids=["parts", "deep", "annex"],
)  # fmt: skip
def test_a_bold_heading_without_a_number_lies_below_a_numbered_one_only_where_its_numbering_goes_on(
    titles: list[str], expected: list[tuple[str, int, str | None]]
) -> None:
    assert shape(skeleton(bold_headings(*titles))) == expected


def test_three_entries_the_last_on_a_page_of_its_own_behind_a_leader_stay_the_contents() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "Vorwort ..... 3\n1 Einleitung ..... 5"),
        block("p3-b1", "Anhang ..... 30"),  # its page past the document's twenty: a reprint's
        *body(("p4-b1", "Vorwort"), ("p5-b1", "1 Einleitung")),
        block("p20-b1", BODY),
    ]

    found = skeleton(blocks)

    assert found.contents.front_end == 2
    assert titles(found) == ["Vorwort", "1 Einleitung"]


def test_a_later_block_s_lines_before_its_entries_are_no_lines_without_a_page() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhaltsverzeichnis", size=12),
        block("p2-b2", "Teil I Vorbemerkungen ..... 4\nTeil II Bildungsauftrag ..... 5", size=12),
        block("p2-b3", "Impressum\nTeil III Grundsätze ..... 6", size=12),
        block("p3-b1", "Impressum", size=14, bold=True),
        block("p3-b2", "Herausgeber: Ministerium für Kultus", size=9),
        *body(
            ("p4-b1", "Teil I Vorbemerkungen"),
            ("p5-b1", "Teil II Bildungsauftrag"),
            ("p6-b1", "Teil III Grundsätze"),
        ),
    ]

    found = skeleton(blocks)

    assert found.contents.pageless == ()
    assert titles(found)[0] == "Teil I Vorbemerkungen"


def test_a_heading_the_contents_name_without_a_number_stays_beside_the_numbered_chapters() -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", "1 Grundlagen ..... 3\n1.1 Ziele ..... 4\nLiteratur ..... 5"),
        block("p3-b1", "1 Grundlagen", bold=True),
        block("p3-b2", BODY),
        block("p4-b1", "1.1 Ziele", bold=True),
        block("p4-b2", BODY),
        block("p5-b1", "Literatur", bold=True),  # named by the contents, no part's word
        block("p5-b2", BODY),
    ]

    assert shape(skeleton(blocks)) == [
        ("1 Grundlagen", 1, None), ("1.1 Ziele", 2, "H1"), ("Literatur", 1, None),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("contents", "last", "kept"),
    [
        ("1 Vorwort 3\n2 Einleitung 5", "3 Anhang 30", 3),  # no leaders, three: none is dropped
        ("Vorwort ..... 3\n1 Einleitung ..... 5\n2 Ziele ..... 6", "Anhang ..... 30", 4),  # its leader
    ],
    ids=["three", "leader"],
)
def test_an_entry_alone_on_the_next_page_counting_past_the_document_stays_theirs(
    contents: str, last: str, kept: int
) -> None:
    blocks = [
        COVER,
        block("p2-b1", "Inhalt", size=14, bold=True),
        block("p2-b2", contents),
        block("p3-b1", last),
        *body(("p4-b1", "Vorwort"), ("p5-b1", "1 Einleitung")),
        block("p20-b1", BODY),
    ]

    found = skeleton(blocks)

    assert len(found.contents.entries) == kept
    assert found.contents.front_end == 2


# audit 2026-11-14 (C): the leader pattern backtracked in quadratic time on a long line of fill signs,
# holding the interpreter: a document of one such line froze its worker for minutes, attempt after attempt


@pytest.mark.parametrize("fill", [".", "_", "· ", ". "])
def test_a_long_line_of_fill_signs_is_no_entry_and_costs_no_time(fill: str) -> None:
    entries = [block(f"p2-b{at}", f"Stichwort Nummer {at} ..... {at}") for at in range(3, 8)]
    found: list[Skeleton] = []

    def read(part: float) -> None:
        long_line = block("p2-b2", "Stichwort " + fill * int(40_000 * part))
        found[:] = [
            skeleton([COVER, block("p2-b1", "Inhalt", size=16), long_line, *entries, block("p60-b1", BODY)])
        ]

    # the work grows with the line, not with its square (tests/support.cpu_growth)
    half, whole = cpu_growth(read)
    assert whole < 3 * half + CPU_GRAIN_S, f"CPU time: {half:.2f} s for half, {whole:.2f} s for all"
    # and one wide bound: 0.02 s of CPU time here (2026-11-18); 40,000 signs took a minute and more
    assert whole < 2
    assert "Stichwort" not in {entry.title for entry in found[0].contents.entries}
