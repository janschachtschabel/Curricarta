"""The cues that hold a new term already (plan M1 10.5, 10e E3): an active cue of the term's sector whose word
has the term's key, or whose pattern finds the term as a numbered heading - the own lexicon's first, as the
research's importer leaves out a new cue the own lexicon holds."""

from collections.abc import Iterator

import pytest

from app.domain.lexicon import PatternTimeout
from app.lexicon import held as held_module
from app.lexicon.held import HeldCue, by_word, holding
from app.lexicon.new_terms import gather
from tests.lexicon.test_new_terms import SCHOOL, found

UNIT = "https://w3id.org/wlo/curriculum/profile/school#Lernbereich"
FIELD = "https://w3id.org/wlo/curriculum/profile/school#Lernfeld"
ALT = "https://w3id.org/wlo/curriculum/vocab#role_alt"
OWN = "https://w3id.org/wlo/curriculum/profile/school#"
RESEARCH = "https://w3id.org/wlo/curriculum/profile/laender/school#"


def a_cue(
    name: str,
    *,
    own: bool = True,
    word: str | None = None,
    pattern: str | None = None,
    sector_iri: str = SCHOOL,
    maps_to: tuple[str, ...] = (UNIT,),
) -> HeldCue:
    return HeldCue(
        iri=(OWN if own else RESEARCH) + name,
        sector_iri=sector_iri,
        own=own,
        surface_form=word,
        pattern=pattern,
        maps_to=maps_to,
        role=ALT,
        regions=(),
    )


def key(term: str, regions: tuple[str, ...] = ("DE-NW",)) -> tuple[str, tuple[str, ...], str]:
    return (SCHOOL, regions, term.casefold())


def test_a_cue_holds_a_term_whose_word_has_its_key() -> None:
    terms = gather([found("Lernbereich"), found("Themenfeld")])
    cue = a_cue("c-1", word=" lernbereich: ")

    assert holding(terms, [cue]) == {key("Lernbereich"): (cue,)}


def test_a_cue_holds_a_term_its_pattern_finds_as_a_numbered_heading() -> None:
    terms = gather([found("Lernfeld:"), found("Lernbereich")])
    cue = a_cue("c-lf", pattern=r"^Lernfeld\s+[0-9]+", maps_to=(FIELD,))

    assert holding(terms, [cue]) == {key("Lernfeld"): (cue,)}


def test_a_cue_says_whether_its_word_holds_the_term_or_its_pattern_alone() -> None:
    # casefolded as the importer compares: "MASS" is the word "Maß"
    assert by_word(a_cue("c-1", word=" MASS: "), "maß".casefold())
    assert not by_word(a_cue("c-2", word="Lernfeld 1", pattern="^Lernfeld"), "lernfeld")
    assert not by_word(a_cue("c-3", pattern="^Lernfeld"), "lernfeld")


def test_a_cue_of_another_sector_holds_none() -> None:
    terms = gather([found("Lernbereich")])
    other = "https://example.org/vocational"
    word_cue = a_cue("c-1", word="Lernbereich", sector_iri=other)
    pattern_cue = a_cue("c-2", pattern="^Lernbereich", sector_iri=other)

    held = holding(terms, [word_cue, pattern_cue])

    assert held == {}


def test_the_own_lexicon_s_cues_come_first_then_by_iri() -> None:
    terms = gather([found("Lernbereich")])
    research = a_cue("r-1", own=False, word="Lernbereich")
    late, early = a_cue("c-2", word="Lernbereich"), a_cue("c-1", pattern="^Lernbereich")

    assert holding(terms, [research, late, early]) == {key("Lernbereich"): (early, late, research)}


def test_a_pattern_holds_a_term_only_where_it_finds_it_at_the_heading_s_start() -> None:
    # as the importer matches: an own pattern without ^ that finds the word inside a longer one holds none
    terms = gather([found("Hinweise und Umsetzungshilfen"), found("Umsetzungshilfen")])
    cue = a_cue("c-uh", pattern="Umsetzungshilfen")

    assert holding(terms, [cue]) == {key("Umsetzungshilfen"): (cue,)}


def test_a_cue_with_a_word_and_a_pattern_is_listed_once() -> None:
    terms = gather([found("Lernbereich")])
    cue = a_cue("c-1", word="Lernbereich", pattern="^Lernbereich")

    assert holding(terms, [cue]) == {key("Lernbereich"): (cue,)}


@pytest.fixture
def slow_pattern(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    asked: list[str] = []

    def matches(pattern: str, text: str) -> bool:
        asked.append(pattern)
        if pattern == "slow":
            raise PatternTimeout("too long")
        return text.startswith("Lernfeld")

    monkeypatch.setattr(held_module, "pattern_starts", matches)
    yield asked


def test_the_pattern_of_a_cue_that_holds_a_term_by_its_word_is_not_asked(slow_pattern: list[str]) -> None:
    terms = gather([found("Lernfeld")])
    cue = a_cue("c-1", word="Lernfeld", pattern="fine")

    assert holding(terms, [cue]) == {key("Lernfeld"): (cue,)}
    assert slow_pattern == []


def test_a_pattern_that_takes_too_long_is_asked_once_and_holds_nothing(slow_pattern: list[str]) -> None:
    terms = gather([found("Lernbereich"), found("Lernfeld")])
    fine = a_cue("c-2", pattern="fine")

    held = holding(terms, [a_cue("c-1", pattern="slow"), fine])

    assert held == {key("Lernfeld"): (fine,)}
    assert slow_pattern == ["slow", "fine", "fine"]
