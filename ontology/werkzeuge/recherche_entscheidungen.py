"""The editors' decisions on the research cues and the new cues they took from the documents' terms (plan M1
10.3, 10.4), as python -m app.lexicon.export_reviews writes them to recherche-ergebnisse/entscheidungen.json
and the importer (importiere_recherche.py) folds them into the files it generates: a confirmed cue verified at
the editors' strength - up to 0.9, only with where they found it -, a rejected one left out; a new cue
unverified at 0.7, as the research found one at the document. The file is checked whole; anything outside its
form is refused (ValueError), before anything is written."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from recherche_cues import Cue

FILE = "recherche-ergebnisse/entscheidungen.json"
FORMAT = 2  # as the export writes it
LOWEST, HIGHEST = Decimal("0.5"), Decimal("0.9")
NEW_STRENGTH = "0.7"  # a new cue's, as the research's found at the document (Beleg E): X1 names its block
NEW_ROLES = frozenset({"pref", "alt", "cue"})  # negative and homonym need hints a new cue has none of
TAKEN = "Neuer Begriff eines Dokuments (X1), von der Redaktion als Hinweis übernommen"
_REGION = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")


@dataclass(frozen=True)
class Decision:
    decision: str  # confirmed, rejected
    strength: str | None  # a confirmation's, as written ("0.90")
    evidence: str | None  # where the editors found a confirmed cue
    note: str | None


@dataclass(frozen=True)
class NewTerm:
    """A new cue the editors took from a document's term."""

    profile: str  # the IRI of its sector's terminology profile
    regions: tuple[str, ...]  # DE-XX, or DE for the whole country; sorted
    surface_form: str
    maps_to: str  # the IRI of a node type of the profile
    role: str  # pref, alt, cue
    note: str | None


def decided(ontology: Path) -> tuple[dict[str, Decision], list[NewTerm]]:
    """The decisions under the ontology by their cue's IRI and the new cues in the file's order, the file read
    once; none where it is not there."""
    held = _held(ontology)
    if held is None:
        return {}, []
    return _decisions(held), [_new_term(entry) for entry in held["new_terms"]]


def decisions_of(ontology: Path) -> dict[str, Decision]:
    """The decisions under the ontology by their cue's IRI; none where the file is not there."""
    return decided(ontology)[0]


def _decisions(held: dict[str, Any]) -> dict[str, Decision]:
    found: dict[str, Decision] = {}
    for entry in held["decisions"]:
        cue, decision = _entry(entry)
        if cue in found:
            raise ValueError(f"{FILE}: {cue} ist zweimal entschieden")
        found[cue] = decision
    return found


def taken(term: NewTerm, target: str) -> Cue:
    """The cue a new term gives, its target as the importer names it (a prefixed name)."""
    notes = {TAKEN} | ({f"Anmerkung der Redaktion zum neuen Begriff: {term.note}"} if term.note else set())
    return Cue(
        surface=term.surface_form,
        role=term.role,
        kind="term",
        maps_to=(target,),
        regions=term.regions,
        strength=NEW_STRENGTH,
        sources=(Path(FILE).name,),
        notes=tuple(sorted(notes)),
    )


def applied(cue: Cue, decision: Decision) -> Cue | None:
    """The cue as the decision leaves it: verified at its strength with the editors' notes; None, rejected."""
    if decision.strength is None:  # a rejection: _entry gives every confirmation its strength
        return None
    notes = {*cue.notes, f"Von der Redaktion geprüft: {decision.evidence}"}
    if decision.note:
        notes.add(f"Anmerkung der Redaktion: {decision.note}")
    return replace(cue, strength=decision.strength, verified=True, notes=tuple(sorted(notes)))


def _held(ontology: Path) -> dict[str, Any] | None:
    path = ontology / FILE
    if not path.exists():
        return None
    try:
        held = json.loads(path.read_text(encoding="utf-8-sig"))  # a Windows shell may begin it with a BOM
    except ValueError as error:
        raise ValueError(f"{FILE} ist kein JSON: {error}") from error
    if (
        not isinstance(held, dict)
        or held.get("format") != FORMAT
        or not isinstance(held.get("decisions"), list)
        or not isinstance(held.get("new_terms"), list)
    ):
        raise ValueError(f"{FILE}: erwartet {{'format': {FORMAT}, 'decisions': [...], 'new_terms': [...]}}")
    return held


def _new_term(entry: Any) -> NewTerm:
    if not isinstance(entry, dict):
        raise ValueError(f"{FILE}: ein neuer Hinweis ist ein Objekt: {entry!r}")
    word, regions, note = entry.get("surface_form"), entry.get("regions"), entry.get("note")
    if not isinstance(word, str) or not word.strip():
        raise ValueError(f"{FILE}: ein neuer Hinweis nennt sein Wort (surface_form): {entry!r}")
    if not isinstance(regions, list) or not regions:
        raise ValueError(f"{FILE}: {word}: regions ist eine Liste von Ländern")
    if not all(isinstance(region, str) and _REGION.fullmatch(region) for region in regions):
        raise ValueError(f"{FILE}: {word}: ein Land ist ein Code wie DE-NW, nicht {regions!r}")
    for name in ("profile", "maps_to"):
        if not isinstance(entry.get(name), str) or not entry[name]:
            raise ValueError(f"{FILE}: {word}: {name} ist eine IRI")
    if entry.get("role") not in NEW_ROLES:
        raise ValueError(f"{FILE}: {word}: role ist pref, alt oder cue, nicht {entry.get('role')!r}")
    if note is not None and not isinstance(note, str):
        raise ValueError(f"{FILE}: {word}: note ist Text oder null")
    return NewTerm(
        entry["profile"], tuple(sorted(set(regions))), word.strip(), entry["maps_to"], entry["role"], note
    )


def _entry(entry: Any) -> tuple[str, Decision]:
    if not isinstance(entry, dict) or not isinstance(entry.get("cue"), str) or not entry["cue"]:
        raise ValueError(f"{FILE}: eine Entscheidung nennt ihren Cue (cue): {entry!r}")
    cue, kind, note = entry["cue"], entry.get("decision"), entry.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError(f"{FILE}: {cue}: note ist Text oder null")
    if kind == "rejected":
        if entry.get("strength") is not None:
            raise ValueError(f"{FILE}: {cue}: eine Verwerfung hat keine Stärke")
        return cue, Decision("rejected", None, None, note)
    if kind != "confirmed":
        raise ValueError(f"{FILE}: {cue}: decision ist confirmed oder rejected, nicht {kind!r}")
    strength, evidence = entry.get("strength"), entry.get("evidence")
    if not isinstance(strength, str) or not _within(strength):
        raise ValueError(f"{FILE}: {cue}: eine Bestätigung nennt ihre Stärke als Text von 0.5 bis 0.9")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError(f"{FILE}: {cue}: eine Bestätigung nennt, wo die Redaktion den Cue fand (evidence)")
    return cue, Decision("confirmed", strength, evidence.strip(), note)


def _within(strength: str) -> bool:
    try:
        return LOWEST <= Decimal(strength) <= HIGHEST
    except InvalidOperation:
        return False
