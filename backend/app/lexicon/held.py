"""The cues that hold a new term already (plan M1 10.5, 10e E3), for the editors to see before they make it a
cue: an active cue of the term's sector whose word has the term's key, or whose pattern matches the term as
a numbered heading ("Lernfeld 1") from its start, whatever its regions - as the research's importer matches,
which leaves out a new cue the own lexicon holds so (recherche_cues.own_holds); a research cue of the same
word stands beside it."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.lexicon import PatternTimeout, pattern_starts
from app.lexicon.new_terms import NewTerm, term_key

type TermKey = tuple[str, tuple[str, ...], str]  # a term's sector IRI, regions and key


@dataclass(frozen=True)
class HeldCue:
    iri: str
    sector_iri: str  # of its profile
    own: bool  # the sector's own lexicon; else the research's (a source under recherche-ergebnisse/)
    surface_form: str | None
    pattern: str | None
    maps_to: tuple[str, ...]
    role: str  # its IRI
    regions: tuple[str, ...]  # their IRIs, sorted; none: everywhere


def holding(terms: Iterable[NewTerm], cues: Iterable[HeldCue]) -> dict[TermKey, tuple[HeldCue, ...]]:
    """The cues that hold each term, the own lexicon's first, then by IRI; a term none holds is left out.
    A pattern that takes too long once holds no term after it, as a stage leaves it
    (app/pipeline/patterns.py)."""
    words: dict[tuple[str, str], list[HeldCue]] = defaultdict(list)
    patterns: dict[str, list[HeldCue]] = defaultdict(list)
    for cue in cues:
        if cue.surface_form is not None:
            words[(cue.sector_iri, term_key(cue.surface_form))].append(cue)
        if cue.pattern is not None:
            patterns[cue.sector_iri].append(cue)
    timed_out: set[str] = set()
    found: dict[TermKey, tuple[HeldCue, ...]] = {}
    for term in terms:
        held = {cue.iri: cue for cue in words[(term.sector_iri, term.key)]}
        heading = f"{term.term} 1"
        for cue in patterns[term.sector_iri]:
            if cue.iri not in held and cue.iri not in timed_out and _finds(cue, heading, timed_out):
                held[cue.iri] = cue
        if held:
            ordered = sorted(held.values(), key=lambda cue: (not cue.own, cue.iri))
            found[(term.sector_iri, term.regions, term.key)] = tuple(ordered)
    return found


def by_word(cue: HeldCue, key: str) -> bool:
    """Whether the cue holds a term of this key by its word; else, holding it, by its pattern alone - which
    the importer counts against a new cue only for one of the same targets."""
    return cue.surface_form is not None and term_key(cue.surface_form) == key


def _finds(cue: HeldCue, heading: str, timed_out: set[str]) -> bool:
    assert cue.pattern is not None  # noqa: S101 - only cues with a pattern are asked
    try:
        return pattern_starts(cue.pattern, heading)
    except PatternTimeout:
        timed_out.add(cue.iri)
        return False
