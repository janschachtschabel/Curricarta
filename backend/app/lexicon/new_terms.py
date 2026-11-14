"""The terms X1 found no type for (document_profile.new_terms, plan M1 10.4), gathered for the editors: one
term to a sector, its regions and its key - the word as the lexicon compares words -, however many documents
name it, shown in the form they write most. A document of no regions counts as the whole country, as a cue
of none holds everywhere."""

import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

OCCURRENCES = 5  # the places listed with a term; every document is counted
MIN_SIGNS = 4  # a shorter word gives no cue: the research's importer (recherche_cues.py) leaves it out
KEY_LIMIT = 500  # a longer key names no level; term_review keeps none (casefolding lengthens: ß is ss)
WHOLE_COUNTRY = ("DE",)


@dataclass(frozen=True)
class Occurrence:
    """One new term of one document's profile, as X1 gave it."""

    document: UUID
    title: str | None
    created_at: datetime
    sector: str  # the notation of the document's sector ("school")
    sector_iri: str
    regions: tuple[str, ...]  # the document's, as it holds them
    text: str  # documentTerm
    block: str | None  # evidenceBlockId
    function: str | None  # the IRI of the suggested function, None where X1 gave none it knew


@dataclass(frozen=True)
class NewTerm:
    sector: str
    sector_iri: str
    regions: tuple[str, ...]  # sorted
    key: str
    term: str  # the form shown
    documents: int
    functions: tuple[str, ...]  # suggested, sorted
    occurrences: tuple[Occurrence, ...]  # the first OCCURRENCES, by document and block


def written(text: str) -> str:
    """A term as written, its spaces one, without a closing colon."""
    return " ".join(unicodedata.normalize("NFC", text).split()).rstrip(": ")


def term_key(text: str) -> str:
    """A term as the lexicon compares words (importiere_recherche's word_key), its form and spaces aside."""
    return written(text).casefold()


def regions_of(regions: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(regions))) or WHOLE_COUNTRY


def gather(found: Iterable[Occurrence]) -> list[NewTerm]:
    """The terms of these occurrences, by sector, regions and key; a blank one is none, and one whose key is
    longer than KEY_LIMIT."""
    held: dict[tuple[str, str, tuple[str, ...], str], list[Occurrence]] = defaultdict(list)
    for occurrence in found:
        key = term_key(occurrence.text)
        if key and len(key) <= KEY_LIMIT:
            group = (occurrence.sector, occurrence.sector_iri, regions_of(occurrence.regions), key)
            held[group].append(occurrence)
    return [_term(*group, places) for group, places in sorted(held.items())]


def _term(
    sector: str, sector_iri: str, regions: tuple[str, ...], key: str, places: list[Occurrence]
) -> NewTerm:
    forms = Counter(written(place.text) for place in places)
    ordered = sorted(places, key=lambda place: (place.created_at, str(place.document), place.block or ""))
    return NewTerm(
        sector=sector,
        sector_iri=sector_iri,
        regions=regions,
        key=key,
        term=min(forms, key=lambda form: (-forms[form], form)),
        documents=len({place.document for place in places}),
        functions=tuple(sorted({place.function for place in places if place.function is not None})),
        occurrences=tuple(ordered[:OCCURRENCES]),
    )
