"""The terms X1 found no type for, gathered for the editors (plan M1 10.4, 10d D2): one term to a sector, its
regions and its key, however many documents name it, in the form they write most; a document of no regions
as the whole country."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import recherche_cues

from app.lexicon.new_terms import KEY_LIMIT, MIN_SIGNS, OCCURRENCES, Occurrence, gather, term_key

UNIT = "https://w3id.org/wlo/curriculum/vocab#fn_unit"
AREA = "https://w3id.org/wlo/curriculum/vocab#fn_area"
SCHOOL = "https://w3id.org/wlo/curriculum/vocab#es_school"
START = datetime(2026, 10, 1, tzinfo=UTC)


def found(
    text: str,
    regions: tuple[str, ...] = ("DE-NW",),
    *,
    sector: str = "school",
    document: uuid.UUID | None = None,
    at: int = 0,
    function: str | None = UNIT,
    block: str | None = "p1-b1",
) -> Occurrence:
    return Occurrence(
        document=document or uuid.uuid4(),
        title=f"Dokument {at}",
        created_at=START + timedelta(minutes=at),
        sector=sector,
        sector_iri=SCHOOL if sector == "school" else f"https://example.org/{sector}",
        regions=regions,
        text=text,
        block=block,
        function=function,
    )


def test_a_term_is_one_for_its_sector_regions_and_key() -> None:
    terms = gather(
        [
            found("Lernbereich", at=1),
            found(" lernbereich: ", at=2),
            found("Lernbereich", ("DE-BY",)),
            found("Lernbereich", sector="vocational"),
        ]
    )

    assert [(term.sector, term.regions, term.key, term.documents) for term in terms] == [
        ("school", ("DE-BY",), "lernbereich", 1),
        ("school", ("DE-NW",), "lernbereich", 2),
        ("vocational", ("DE-NW",), "lernbereich", 1),
    ]
    assert terms[1].term == "Lernbereich"  # of two forms once each, the first by code point
    assert terms[1].sector_iri == SCHOOL


def test_the_form_shown_is_the_one_the_documents_write_most() -> None:
    (term,) = gather([found("LERN  BEREICH :"), found("LERN BEREICH"), found("Lern bereich")])

    assert (term.key, term.term) == ("lern bereich", "LERN BEREICH")


def test_a_key_reads_a_word_as_the_lexicon_compares_it() -> None:
    assert term_key("U\u0308bungsfeld:") == term_key("Übungsfeld") == "übungsfeld"  # decomposed
    assert term_key("Straße\t der  Kompetenz :") == "strasse der kompetenz"
    assert term_key(" : ") == ""


def test_a_document_of_no_regions_counts_as_the_whole_country() -> None:
    terms = gather(
        [
            found("Leitidee", ()),
            found("Leitidee", ("DE",)),
            found("Leitidee", ("DE-NW", "DE-BY", "DE-NW")),
        ]
    )

    assert [(term.regions, term.documents) for term in terms] == [(("DE",), 2), (("DE-BY", "DE-NW"), 1)]


def test_a_blank_term_is_none() -> None:
    assert gather([found("   "), found(" : ")]) == []


def test_a_term_longer_than_a_key_may_be_is_none() -> None:
    longest = "\u00df" * (KEY_LIMIT // 2)  # casefolded "ss": a key twice as long as the word

    terms = gather([found(longest), found(longest + "\u00df"), found("x" * (KEY_LIMIT + 1))])

    assert [len(term.key) for term in terms] == [KEY_LIMIT]


def test_a_term_is_one_for_its_sector_s_iri() -> None:
    other = replace(found("Lernbereich"), sector_iri="https://example.org/sec_school_2")

    terms = gather([found("Lernbereich"), other])

    assert sorted(term.sector_iri for term in terms) == sorted([SCHOOL, "https://example.org/sec_school_2"])


def test_the_first_places_are_listed_and_every_document_counted() -> None:
    twice = uuid.uuid4()
    places = [found("Lernfeld", at=at) for at in range(OCCURRENCES + 2, 1, -1)]
    places += [found("Lernfeld", document=twice, at=1, block="p2-b1")]
    places += [found("Lernfeld", document=twice, at=1, block="p1-b1")]

    (term,) = gather(places)

    assert term.documents == OCCURRENCES + 2  # one document naming it twice is one
    assert [(place.created_at, place.block) for place in term.occurrences] == [
        (START + timedelta(minutes=1), "p1-b1"),
        (START + timedelta(minutes=1), "p2-b1"),
        *[(START + timedelta(minutes=at), "p1-b1") for at in range(2, OCCURRENCES)],
    ]


def test_the_functions_suggested_are_each_named_once_in_order() -> None:
    others = [f"https://w3id.org/wlo/curriculum/vocab#fn_{name}" for name in ("subunit", "frame", "grouping")]
    places = [found("Inhaltsfeld", function=function) for function in [UNIT, None, *others, AREA, UNIT]]

    (term,) = gather(places)

    assert term.functions == tuple(sorted([AREA, UNIT, *others]))  # a set's order would be the hash's


def test_a_word_too_short_for_a_cue_is_one_the_importer_leaves_out() -> None:
    assert MIN_SIGNS == recherche_cues.MIN_SIGNS
