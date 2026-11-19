"""A MEM wording looked for in the whole document, in the plan's order (app/pipeline/anchor_search.py, plan M2
E3/E4): from the block of the part before on, then before it, stage by stage as anchor_check has them -
word for word anywhere before a fuzzy passage after; page headers and footers and the contents are no part
of the text; a wording not found gets the page of the part before it, else the first."""

from collections.abc import Sequence

import pytest

from app.conversion.base import Block, BlockKind
from app.pipeline.anchor_check import MAX_FUZZY
from app.pipeline.anchor_search import Found, SearchText, estimated_page, find, search_text


def block(page: int, number: int, text: str, kind: BlockKind = "text") -> Block:
    return Block(
        id=f"p{page}-b{number}",
        page=page,
        kind=kind,
        text=text,
        bbox=None,
        font_size=None,
        bold=False,
        italic=False,
    )


BLOCKS = [
    block(1, 1, "Lehrplan Physik", "page_header"),
    block(1, 2, "Inhalt"),
    block(1, 3, "1 Optik 3"),
    block(2, 1, "1 Optik"),
    block(2, 2, "Die Schülerinnen und Schüler beschreiben die Ausbreitung von Licht."),
    block(2, 3, "Seite 2", "page_footer"),
    block(3, 1, "2 Mechanik"),
    block(3, 2, "Die Schülerinnen und Schüler beschreiben die Ausbreitung von Licht."),
    block(3, 3, "Sie erklären Kräfte an Beispielen aus dem Alltag und"),
    block(4, 1, "messen Geschwindigkeiten mit einfachen Mitteln."),
]
CONTENTS = frozenset({1, 2})  # "Inhalt" and its line


def searched(blocks: Sequence[Block] = BLOCKS, contents: frozenset[int] = CONTENTS) -> SearchText:
    return search_text(blocks, contents)


def test_a_wording_is_found_in_its_block_with_its_page_and_stage() -> None:
    found = find("1 Optik", searched(), None)

    assert found is not None
    assert (found.block_ids, found.page, found.stage) == (("p2-b1",), 2, "exact")


def test_a_wording_across_two_blocks_names_both() -> None:
    found = find("Kräfte an Beispielen aus dem Alltag und messen Geschwindigkeiten", searched(), None)

    assert found is not None
    assert (found.block_ids, found.page, found.stage) == (("p3-b3", "p4-b1"), 3, "whitespace")


def test_a_repeated_wording_is_found_after_the_part_before_it() -> None:
    # the same sentence under Optik and under Mechanik: the second part takes the second place
    first = find("1 Optik", searched(), None)
    mechanik = find("2 Mechanik", searched(), first)
    assert mechanik is not None

    again = find("Die Schülerinnen und Schüler beschreiben die Ausbreitung von Licht.", searched(), mechanik)

    assert again is not None and again.block_ids == ("p3-b2",)


def test_a_wording_before_the_part_before_it_is_found_there_too() -> None:
    later = find("2 Mechanik", searched(), None)

    earlier = find("1 Optik", searched(), later)

    assert earlier is not None and earlier.block_ids == ("p2-b1",)


def test_a_wording_word_for_word_before_wins_over_a_fuzzy_passage_after() -> None:
    blocks = [
        block(1, 1, "Sie prüfen die Aussagen eines Textes."),
        block(2, 1, "Anfang"),
        block(3, 1, "Sie prüften die Aussage des Textes."),
    ]
    start = find("Anfang", searched(blocks, frozenset()), None)

    found = find("Sie prüfen die Aussagen eines Textes.", searched(blocks, frozenset()), start)

    assert found is not None and (found.block_ids, found.stage) == (("p1-b1",), "exact")


def test_a_wording_beginning_just_before_the_block_of_the_part_before_is_found() -> None:
    # the window before reaches past the block's start by twice the wording's length
    blocks = [block(1, 1, "Kapitel"), block(1, 2, "Ziele des Unterrichts"), block(1, 3, "und weiter")]
    start = find("Ziele des Unterrichts", searched(blocks, frozenset()), None)

    found = find("Kapitel Ziele", searched(blocks, frozenset()), start)

    assert found is not None and found.block_ids == ("p1-b1", "p1-b2")


def test_page_headers_footers_and_the_contents_are_no_part_of_the_text() -> None:
    assert find("Lehrplan Physik", searched(), None) is None
    assert find("Seite 2", searched(), None) is None
    assert find("1 Optik 3", searched(), None) is None


def test_a_wording_in_the_contents_and_the_body_is_found_in_the_body() -> None:
    found = find("Optik", searched(), None)

    assert found is not None and found.block_ids == ("p2-b1",)


def test_the_later_stages_find_what_word_for_word_does_not() -> None:
    elided = find("Die Schülerinnen und Schüler … von Licht.", searched(), None)
    normalized = find("die schülerinnen und schüler beschreiben die ausbreitung von licht", searched(), None)
    fuzzy = find("Die Schülerinnen und Schüler beschreiben die Ausbreitung des Lichts.", searched(), None)

    assert elided is not None and elided.stage == "elided"
    assert normalized is not None and normalized.stage == "normalized"
    assert fuzzy is not None and fuzzy.stage == "fuzzy"


def test_a_wording_the_document_does_not_hold_is_not_found() -> None:
    assert find("Thermodynamik der Sterne", searched(), None) is None
    assert find("   ", searched(), None) is None
    assert find("Optik", search_text([], frozenset()), None) is None


def test_a_wording_past_the_fuzzy_bound_is_looked_for_word_for_word_alone() -> None:
    long_text = " ".join(f"Wort{n}" for n in range(MAX_FUZZY // 4))
    blocks = [block(1, 1, long_text)]

    assert find(long_text, searched(blocks, frozenset()), None) is not None
    assert find(long_text.replace("Wort1 ", "Wert1 "), searched(blocks, frozenset()), None) is None


def test_a_wording_not_found_gets_the_page_of_the_part_before_else_the_first() -> None:
    before = Found(block_ids=("p3-b1",), page=3, stage="exact", start=0, end=1)

    assert estimated_page(searched(), before) == 3
    assert estimated_page(searched(), None) == 2  # the first page of the text: the header's is none of it
    assert estimated_page(search_text([], frozenset()), None) == 1


def test_the_search_after_starts_at_the_block_of_the_part_before_not_at_its_place_in_it() -> None:
    # the part before was found inside its block ("Optik"); the next wording opens that block, and stands
    # earlier in the document as well: from the block's start on, the block's own words come first
    blocks = [block(1, 1, "Ziele und Inhalte"), block(2, 1, "Ziele und Inhalte der Optik")]
    text = searched(blocks, frozenset())
    before = find("der Optik", text, None)

    found = find("Ziele und Inhalte", text, before)

    assert found is not None and found.block_ids == ("p2-b1",)


def test_the_window_before_ends_at_a_line_end_never_inside_a_word() -> None:
    # cut at the part before plus twice the wording, it would end inside "Lernfeld 12" - and take "Lernfeld 1"
    blocks = [block(1, 1, "Einleitung"), block(2, 1, "Übersicht:Lernfeld 12 Inhalte")]
    text = searched(blocks, frozenset())
    before = find("Übersicht", text, None)

    found = find("Lernfeld 1", text, before)

    assert found is None or found.stage != "exact"


def test_a_normalized_place_before_wins_over_a_fuzzy_passage_after() -> None:
    # a line-end hyphen leaves the wording to the normalized stage; after the part before, a sentence alike
    blocks = [
        block(1, 1, "Die Lernen-\nden beschreiben Licht und Schatten."),
        block(2, 1, "Anfang"),
        block(3, 1, "Die Lernenden beschrieben Licht und Schatten."),
    ]
    text = searched(blocks, frozenset())
    before = find("Anfang", text, None)

    found = find("Die Lernenden beschreiben Licht und Schatten.", text, before)

    assert found is not None and (found.block_ids, found.stage) == (("p1-b1",), "normalized")


def test_a_word_a_hyphen_and_a_space_part_inside_a_block_is_found_normalized() -> None:
    # task A1: pdfplumber keeps a line-end hyphen inside a block and makes the break a space
    blocks = [block(1, 1, "Anfang"), block(2, 1, "Die Lernenden deuten Schwingungsbil- der im Versuch.")]

    found = find("Die Lernenden deuten Schwingungsbilder im Versuch.", searched(blocks, frozenset()), None)

    assert found is not None and (found.block_ids, found.stage) == (("p2-b1",), "normalized")


def test_a_fuzzy_passage_after_stays_where_nothing_before_is_better() -> None:
    blocks = [
        block(1, 1, "Etwas anderes."),
        block(2, 1, "Anfang"),
        block(3, 1, "Die Lernenden beschrieben Licht."),
    ]
    text = searched(blocks, frozenset())

    found = find("Die Lernenden beschreiben Licht.", text, find("Anfang", text, None))

    assert found is not None and (found.block_ids, found.stage) == (("p3-b1",), "fuzzy")


def test_a_wording_spread_over_much_whitespace_before_the_block_is_found() -> None:
    # the window before reaches twice the wording's length past the block's start: a match across a run
    # of whitespace is longer than the wording
    blocks = [block(1, 1, "Kapitel"), block(1, 2, "Ziele          des Unterrichts")]
    text = searched(blocks, frozenset())
    before = find("des Unterrichts", text, None)

    found = find("Kapitel Ziele des", text, before)

    assert found is not None and (found.block_ids, found.stage) == (("p1-b1", "p1-b2"), "whitespace")


def test_a_place_found_in_another_text_is_refused() -> None:
    elsewhere = Found(block_ids=("p9-b1",), page=9, stage="exact", start=10_000, end=10_005)

    with pytest.raises(ValueError, match="another text"):
        find("Optik", searched(), elsewhere)


def test_the_window_before_reaches_twice_the_wording_past_a_line_end_inside_the_block() -> None:
    # the part before's block holds a line end; the match runs across it, longer than the wording by its
    # whitespace: only a window of twice the wording, to the next line end after it, holds the match
    blocks = [
        block(1, 1, "Kapitel"),
        block(1, 2, "Ziele des" + " " * 25 + "\nUnterrichts"),
        block(1, 3, "weiter"),
    ]
    text = searched(blocks, frozenset())
    before = find("Unterrichts", text, None)

    found = find("Kapitel Ziele des Unterrichts", text, before)

    assert found is not None and (found.block_ids, found.stage) == (("p1-b1", "p1-b2"), "whitespace")


def test_of_two_fuzzy_passages_the_one_after_the_part_before_is_kept() -> None:
    blocks = [
        block(1, 1, "Die Lernenden beschrieben Licht."),
        block(2, 1, "Anfang"),
        block(3, 1, "Die Lernenden beschrieben Licht."),
    ]
    text = searched(blocks, frozenset())

    found = find("Die Lernenden beschreiben Licht.", text, find("Anfang", text, None))

    assert found is not None and (found.block_ids, found.stage) == (("p3-b1",), "fuzzy")
