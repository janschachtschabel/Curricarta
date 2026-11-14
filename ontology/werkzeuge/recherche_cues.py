"""What the rows of one research report become as lexicon cues (plan M1 10a R4-R7).

Terms (T3), cross-cutting frames (T4) and levels (T5, scales) become cues only with a target the model
knows; heading patterns (T2) only where a structural term of the same report and numbered examples carry them.
A word the sector's own lexicon already holds gives no research cue: an own cue holds in every land, and a
research cue scoped to one would outrank it there. Every cue is unverified, its strength by the row's evidence
(E 0.7, S 0.6, A 0.5 - never above 0.7 before an editor's sample). A row that gives no cue is counted by its
reason, never guessed. Targets are written as prefixed names ("schul:Inhaltsbereich"); the importer expands
them.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from recherche_tabellen import Row, Table

ROLES = frozenset({"pref", "alt", "cue", "negative", "homonym"})
MATCHES = frozenset({"neu", "korrigiert"})  # of the Vorliste: a new word, or a correction offered beside it
COMPARED = MATCHES | {"bestaetigt", "nicht_gefunden"}  # the Vorliste comparison's four values
STRENGTH = {"E": "0.7", "S": "0.6", "A": "0.5"}
OCCURS_IN = {
    "titel": "titlePage",
    "inhaltsverzeichnis": "toc",
    "ueberschrift": "heading",
    "tabellenkopf": "tableHeader",
    "fliesstext": "body",
    "kasten": "box",
    "kopfzeile": "headerFooter",
}
OCCURS_IN |= {
    name: name for name in OCCURS_IN.values()
}  # the vocabulary's own names, as some rows wrote them
# the research's names of cross-cutting objectives (recherche-auftraege/01-schule-land.md) and the hub's
CROSS_CUTTING = {
    "BNE": "qz:BNE",
    "Medienbildung/Digitale Welt": "qz:DigitalWorld",
    "Demokratie": "qz:Democracy",
    "Berufliche Orientierung": "qz:CareerOrientation",
    "Verbraucherbildung": "qz:ConsumerEducation",
    "Gesundheit": "qz:Health",
    "Vielfalt/Inklusion": "qz:Diversity",
    "Sprachbildung": "qz:LanguageEducation",
    "Interkulturalität": "qz:Intercultural",
    "Interkulturalitaet": "qz:Intercultural",
    "Werte": "qz:Values",
}
_SEPARATED = re.compile(r"\s*\|\s*")
_LISTED = re.compile(r"\s*[|,]\s*")
_BRACKETS = re.compile(r"\s*\([^)]*\)")
_QUOTE_MARKS = '„"“'
_QUOTED = re.compile(r"[„\"“]([^„\"“”]+)[“”\"]")
_BRACKETED = re.compile(r"\[([^\]]*)\]")
_ELLIPSIS = re.compile(r"…|\.\.\.")  # a template, not a word
# a pattern written as a term: anchored, or with a group, a repetition, a class or an escape of a pattern
_PATTERN = re.compile(r"^\^|\$$|\(\?|\)[+*]|\\[sSdDwWb]|\[[^\]]*-[^\]]*\]")
MIN_SIGNS = 4  # a shorter word is found inside too many others (the lexicon excerpt matches parts of words)
_NUMBER = r"\s+(?:\d+(?:\.\d+)*|[IVXLC]+|[A-Z])\b"


@dataclass(frozen=True)
class Model:
    """What rows are checked against: the targets by prefixed name - no schemes, profiles or cues -, the
    schemes, and each target's labels (preferred, alternative, notation; casefolded)."""

    targets: frozenset[str]
    schemes: frozenset[str] = frozenset()
    labels: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Own:
    """The sector's own lexicon, which the research adds to and never doubles: its words (by `word_key`) and
    its patterns, each with the targets of its cue."""

    words: frozenset[str] = frozenset()
    patterns: tuple[tuple[str, frozenset[str]], ...] = ()


NONE_OWN = Own()  # a report checked against no own lexicon


def label_keys(label: str) -> frozenset[str]:
    """A label or word as compared with another: by its key, and by the key without its bracketed part."""
    return frozenset({word_key(label), word_key(_BRACKETS.sub("", label))})


def word_key(word: str) -> str:
    """A word as the own lexicon and the research are compared: casefolded, without a closing colon."""
    return word.strip().casefold().rstrip(": ")


@dataclass(frozen=True)
class Cue:
    surface: str
    role: str  # pref, alt, cue, negative, homonym
    kind: str  # term, headingPattern
    maps_to: tuple[str, ...]  # prefixed names, sorted
    regions: tuple[str, ...]  # DE-XX, or DE for the whole country
    strength: str
    sources: tuple[str, ...]  # the reports' file names
    notes: tuple[str, ...]  # where the research found it, what else it says; sorted
    occurs_in: tuple[str, ...] = ()
    recognition: tuple[str, ...] = ()
    negative: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    pattern: str | None = None
    verified: bool = False  # by the editors' decision alone (recherche_entscheidungen.py)


@dataclass
class _Report:
    name: str
    model: Model
    own: Own
    cues: list[Cue] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    # a structural term of the report (T3, funktion gliederung:*) by (region, term): its targets
    structural: dict[tuple[tuple[str, ...], str], tuple[str, ...]] = field(default_factory=dict)
    # a cross-cutting frame of the report (T4) by (region, title): where its cue stands in `cues`
    frames: dict[tuple[tuple[str, ...], str], int] = field(default_factory=dict)

    def evidence(self, row: Row) -> tuple[str, str]:
        """The row's strength and its note of where the research found it."""
        mark = row["beleg"][:1] if row["beleg"][:1] in STRENGTH else "A"
        return STRENGTH[mark], f"Länderrecherche, Beleg {mark}: {row['fundstelle']}"

    def owned(self, word: str, targets: Iterable[str]) -> bool:
        """Whether the own lexicon holds the word (own_holds), counted so."""
        if own_holds(self.own, word, targets):
            self.skipped["Wort schon im eigenen Lexikon"] += 1
            return True
        return False

    def short(self, word: str) -> bool:
        if len(word) < MIN_SIGNS:
            self.skipped["Wort zu kurz"] += 1
            return True
        return False

    def named(self, word: str, target: str) -> bool:
        return names(self.model, word, target)


def own_holds(own: Own, word: str, targets: Iterable[str]) -> bool:
    """Whether the own lexicon holds the word - as a word, or as a heading one of its patterns finds
    ("Lernfeld 1") for one of the same targets: a pattern of other targets competes with no word."""
    numbered = f"{word.strip().rstrip(': ')} 1"
    wanted = set(targets)
    return word_key(word) in own.words or any(
        bool(wanted & own_targets) and re.match(pattern, numbered) is not None
        for pattern, own_targets in own.patterns
    )


def names(model: Model, word: str, target: str) -> bool:
    """Whether a word names the target - one of its labels, with or without the word's bracketed part."""
    return bool(label_keys(word) & model.labels.get(target, frozenset()))


def paired(word: str, members: Sequence[str], targets: Sequence[str], model: Model) -> list[str] | None:
    """The targets a row's word stands for. One word, or words for one target (synonyms): every target. Words
    listed with several targets name a set, not a list in order - so the row says, whatever of it is left: the
    one target the word names, None where it names none or several."""
    if len(members) <= 1 or len(targets) <= 1:
        return list(targets)
    named = [target for target in targets if names(model, word, target)]
    return named if len(named) == 1 else None


def cross_cutting_names(text: str) -> list[str]:
    """The objectives a frame's `entspricht` names: listed with "|" or ",", what a bracket adds left aside."""
    return [name for part in _LISTED.split(text) if (name := _BRACKETS.sub("", part).strip())]


def regions(land: str) -> tuple[str, ...]:
    """The regions a row's `land` names: "BW" as DE-BW, "alle" and none as the whole country."""
    found = []
    for part in _SEPARATED.split(land.replace(",", "|")):
        if not part or part.lower() == "alle" or part == "DE":
            found.append("DE")
        else:
            found.append(part if part.startswith("DE-") else f"DE-{part}")
    return tuple(sorted(set(found)))


def parts(text: str) -> list[str]:
    """The parts of a field the research separates with " | "."""
    return [part for part in _SEPARATED.split(text) if part]


def _targets(text: str, model: Model) -> list[str] | None:
    """The row's targets in its order where every one is a target the model knows; None otherwise - also for
    an older list form with commas, which is no target the model knows."""
    targets = list(dict.fromkeys(parts(text)))
    return targets if targets and all(target in model.targets for target in targets) else None


def _examples(text: str) -> tuple[str, ...]:
    """The quoted parts of a field that begins with a quote; else the field itself, quotes and all."""
    text = text.strip()
    if text[:1] in _QUOTE_MARKS:
        return tuple(part.strip() for part in _QUOTED.findall(text) if part.strip())
    return (text,) if text else ()


def _occurrences(text: str) -> tuple[str, ...]:
    return tuple(sorted({OCCURS_IN[part] for part in parts(text) if part in OCCURS_IN}))


def _term(report: _Report, row: Row) -> None:
    match = row["abgleich_vorliste"]
    if match not in MATCHES:
        known = match in COMPARED
        report.skipped[f"T3 {match}" if known else "T3 Abgleich unklar"] += 1
        return
    role = row["rolle"]
    if role not in ROLES:
        report.skipped["T3 ohne Rolle"] += 1
        return
    if role == "homonym" and not row["erkennungsmerkmal"]:
        report.skipped["T3 Homonym ohne Erkennungsmerkmal"] += 1
        return
    members = parts(row["begriff_woertlich"])
    words = [word for word in members if not _ELLIPSIS.search(word)]
    if _PATTERN.search(row["begriff_woertlich"]) or not words:
        report.skipped["T3 Begriff ist Muster oder Auslassung"] += 1
        return
    targets = _targets(row["ziel_id"], report.model)
    if targets is None:
        report.skipped["T3 ohne bekanntes Ziel"] += 1
        return
    pairs: list[tuple[str, list[str]]] = []
    for word in words:
        if report.short(word):
            continue
        word_targets = paired(word, members, targets, report.model)
        if word_targets is None:
            report.skipped["T3 Liste mit mehreren Zielen"] += 1
        else:
            pairs.append((word, word_targets))
    strength, found = report.evidence(row)
    notes = [found]
    if row["plangeneration_oder_gueltig_ab"]:
        notes.append(f"Plangeneration laut Länderrecherche: {row['plangeneration_oder_gueltig_ab']}")
    if match == "korrigiert":
        to = f" zu {row['hinweis_id']}" if row["hinweis_id"] else ""
        notes.append(f"Korrekturvorschlag der Länderrecherche{to}")
    scope = regions(row["land"])
    for word, word_targets in pairs:
        if report.owned(word, word_targets):
            continue
        maps_to = tuple(sorted(word_targets))
        report.cues.append(
            Cue(
                surface=word,
                role=role,
                kind="term",
                maps_to=maps_to,
                regions=scope,
                strength=strength,
                sources=(report.name,),
                notes=tuple(sorted(notes)),
                occurs_in=_occurrences(row["fundort"]),
                recognition=(row["erkennungsmerkmal"],) if row["erkennungsmerkmal"] else (),
                negative=(row["abgrenzung_verwechslung"],) if row["abgrenzung_verwechslung"] else (),
                examples=_examples(row["beispiel_woertlich"]),
            )
        )
        if row["funktion"].startswith("gliederung:"):
            report.structural[(scope, word.casefold())] = maps_to


def _cross_cutting(report: _Report, row: Row) -> None:
    named = cross_cutting_names(row["entspricht"])
    targets = tuple(sorted({CROSS_CUTTING[part] for part in named if part in CROSS_CUTTING}))
    if not targets or not all(target in report.model.targets for target in targets):
        report.skipped["T4 ohne bekanntes Querschnittsziel"] += 1
        return
    if _SEPARATED.search(row["rahmen_titel"]):
        report.skipped["T4 Rahmentitel als Liste"] += 1
        return
    if report.owned(row["rahmen_titel"], targets) or report.short(row["rahmen_titel"]):
        return
    strength, found = report.evidence(row)
    marks = [("Kürzel oder Symbol", row["kuerzel_oder_symbol"]), ("markiert", row["markierung_wo"])]
    hint = "; ".join(f"{label}: {value}" for label, value in marks if value)
    cue = Cue(
        surface=row["rahmen_titel"],
        role="cue",
        kind="term",
        maps_to=targets,
        regions=regions(row["land"]),
        strength=strength,
        sources=(report.name,),
        notes=(found,),
        recognition=(hint,) if hint else (),
    )
    # the research lists a frame once per objective it serves: one cue for the frame, with all of them
    key = (cue.regions, cue.surface)
    if key not in report.frames:
        report.frames[key] = len(report.cues)
        report.cues.append(cue)
        return
    report.cues[report.frames[key]] = merged(report.cues[report.frames[key]], cue)


def merged(one: Cue, other: Cue) -> Cue:
    """The same cue from two rows: every value of each together, its strength the highest."""
    return replace(
        one,
        maps_to=tuple(sorted(set(one.maps_to) | set(other.maps_to))),
        sources=tuple(sorted(set(one.sources) | set(other.sources))),
        strength=str(max(Decimal(one.strength), Decimal(other.strength))),
        notes=tuple(sorted(set(one.notes) | set(other.notes))),
        occurs_in=tuple(sorted(set(one.occurs_in) | set(other.occurs_in))),
        recognition=tuple(sorted(set(one.recognition) | set(other.recognition))),
        negative=tuple(sorted(set(one.negative) | set(other.negative))),
        examples=tuple(sorted(set(one.examples) | set(other.examples))),
    )


def _levels(report: _Report, row: Row, steps: str, ids: list[str]) -> None:
    """Each step of a level system named with its level, paired in order once the system's scheme is left
    out; counts that do not agree, or a step that names another level of the row, pair nothing."""
    names = parts(steps)
    if len(names) == len(ids):  # a scheme named at its place leaves with its name
        names = [name for name, level in zip(names, ids, strict=True) if level not in report.model.schemes]
    ids = [level for level in ids if level not in report.model.schemes]
    if not names or len(ids) != len(names):
        report.skipped["Niveaus: Stufen und Ziele ungleich viele"] += 1
        return
    if not all(level in report.model.targets for level in ids):
        report.skipped["Niveaus ohne bekanntes Ziel"] += 1
        return
    for name, level in zip(names, ids, strict=True):
        if any(report.named(name, other) for other in ids if other != level):
            report.skipped["Niveaus: Reihenfolge widerspricht Label"] += 1
            return
    strength, found = report.evidence(row)
    for name, level in zip(names, ids, strict=True):
        if not report.owned(name, (level,)) and not report.short(name):
            cue = Cue(name, "cue", "term", (level,), regions(row["land"]), strength, (report.name,), (found,))
            report.cues.append(cue)


def bracketed(system: str) -> list[str]:
    """The level ids a system's name gives in brackets ("Abschlüsse [lvl:a | lvl:b]")."""
    found = _BRACKETED.search(system)
    return parts(found.group(1)) if found else []


def _heading_patterns(report: _Report, row: Row) -> None:
    """A heading pattern for each structural term of the report a level of this outline begins with, where
    the outline's numbered examples begin with it and the pattern hits them all."""
    scope = regions(row["land"])
    levels = [row[column].casefold() for column in row.values if column.startswith("ebene_") and row[column]]
    quoted = _QUOTED.findall(row["nummerierung_beispiele"])
    strength, found = report.evidence(row)
    for (term_scope, term), targets in report.structural.items():
        if term_scope != scope or not any(
            level == term or level.startswith(term + " ") or level.startswith(term + ":") for level in levels
        ):
            continue
        examples = tuple(example.strip() for example in quoted if example.strip().casefold().startswith(term))
        surface = examples[0][: len(term)] if examples else term
        pattern = "^" + r"\s+".join(re.escape(word) for word in surface.split()) + _NUMBER
        if not examples or not all(re.match(pattern, example) for example in examples):
            continue
        report.cues.append(
            Cue(
                surface,
                "cue",
                "headingPattern",
                targets,
                scope,
                strength,
                (report.name,),
                (found,),
                occurs_in=("heading",),
                examples=examples,
                pattern=pattern,
            )
        )


def cues_of(
    name: str, tables: list[Table], model: Model, own: Own = NONE_OWN
) -> tuple[list[Cue], Counter[str]]:
    """The cues the report `name` gives - terms first, heading patterns after, in the order its rows stand -
    and what it gave none for, by reason; `own` is the sector's own lexicon."""
    report = _Report(name, model, own)
    outlines: list[Row] = []
    for table in tables:
        report.skipped["verschoben"] += len(table.shifted)
        for row in table.rows:
            if table.has("begriff_woertlich", "ziel_id", "rolle"):
                _term(report, row)
            elif table.has("rahmen_titel", "entspricht"):
                _cross_cutting(report, row)
            elif table.has("prinzip_oder_thema_woertlich", "entspricht"):
                report.skipped["T4 Elementar (Prinzipien)"] += 1
            elif table.has("system", "stufen_in_reihenfolge_woertlich"):
                _levels(report, row, row["stufen_in_reihenfolge_woertlich"], bracketed(row["system"]))
            elif table.has("skala_art", "stufen_in_reihenfolge_woertlich", "ziel_id"):
                _levels(report, row, row["stufen_in_reihenfolge_woertlich"], parts(row["ziel_id"]))
            elif table.has("system", "stufen_in_reihenfolge"):
                report.skipped["Niveaus ohne lvl-Ziele"] += 1
            elif table.has("ebene_1", "nummerierung_beispiele"):
                outlines.append(row)
    for row in outlines:
        _heading_patterns(report, row)
    return report.cues, +report.skipped
