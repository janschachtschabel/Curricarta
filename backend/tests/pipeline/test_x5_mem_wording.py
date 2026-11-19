"""X5 checks a MEM statement's anchor with the wording the import looked for (app/sources/mem/anchoring.py,
``looked_for``): without the lead-in MEM puts before each statement ("Die SuS ..."), else whole where the rest
does not stand in the anchor's blocks - so that the match kind, the quote and the findings follow the search.
Every other anchor is checked with its whole wording, as before. Synthetic text only."""

import uuid

from app.db.anchors import UncheckedAnchor
from app.pipeline.anchor_check import check_wording
from app.pipeline.x5_stage import check_anchor

# one block of a list the document puts under its own lead-in, as the import's search found it
LISTED = (
    "Die Lernenden\n"
    "beobachten Wellen in einem Wasserbecken,\n"
    "vergleichen Tonhöhen verschiedener Instrumente und\n"
    "lesen Notentexte."
)


def anchor(
    wording: str, texts: tuple[str, ...] = (LISTED,), *, mem_statement: bool = True
) -> UncheckedAnchor:
    return UncheckedAnchor(uuid.uuid4(), uuid.uuid4(), wording, texts, mem_statement=mem_statement)


def test_a_mem_statement_whose_rest_stands_word_for_word_is_exact_its_quote_the_document_s_text() -> None:
    match = check_anchor(anchor("Die SuS vergleichen Tonhöhen verschiedener Instrumente"))

    assert (match.kind, match.quote) == ("exact", "vergleichen Tonhöhen verschiedener Instrumente")
    assert LISTED[match.start : match.end] == match.quote


def test_a_short_mem_statement_in_a_block_of_several_is_found_not_not_found() -> None:
    match = check_anchor(anchor("Die SuS lesen Notentexte"))

    assert (match.kind, match.quote) == ("exact", "lesen Notentexte")


def test_a_mem_statement_whose_rest_stands_only_alike_stays_fuzzy_by_the_rest() -> None:
    wording = "Die SuS vergleichen die Tonhöhen verschiedener Instrumente"

    match = check_anchor(anchor(wording))

    assert match == check_wording("vergleichen die Tonhöhen verschiedener Instrumente", (LISTED,))
    assert match.kind == "fuzzy" and match != check_wording(wording, (LISTED,))


def test_a_mem_statement_the_blocks_do_not_hold_stays_not_found() -> None:
    assert check_anchor(anchor("Die SuS bauen Raketen aus Papier")).kind == "notFound"


def test_a_mem_statement_whose_rest_stands_nowhere_is_checked_whole_as_the_search_fell_back() -> None:
    # the search found the rest nowhere and the whole wording here: the whole earns the kind
    texts = ("Die Schülerinnen und Schüler messen die Spannung im Kreis.",)
    wording = "Die Schülerinnen und Schüler messen den Strom im Kreis."
    assert check_wording("messen den Strom im Kreis.", texts).kind == "notFound"

    match = check_anchor(anchor(wording, texts))

    assert match == check_wording(wording, texts)
    assert (match.kind, match.quote) == ("fuzzy", texts[0])


def test_a_mem_statement_with_too_little_after_its_lead_in_is_checked_whole() -> None:
    texts = ("Die Lernenden lesen.",)
    assert check_wording("lesen.", texts).kind == "exact"  # what a rest alone would earn

    assert check_anchor(anchor("Die SuS lesen.", texts)) == check_wording("Die SuS lesen.", texts)


def test_an_anchor_of_no_mem_statement_is_checked_with_its_whole_wording() -> None:
    # the extraction's statements, a node's heading: as before
    wording = "Die SuS lesen Notentexte"

    match = check_anchor(anchor(wording, mem_statement=False))

    assert match == check_wording(wording, (LISTED,)) and match.kind == "notFound"
