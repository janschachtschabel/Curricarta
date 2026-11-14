"""Import the Länderrecherche (recherche-ergebnisse/*.md) into the lexicon (plan M1 10a).

Writes profile/laender/<bereich>-<land>.ttl: one file per sector and land - a row of the whole country or of
several lands in <bereich>-DE.ttl -, each cue attached to its sector's terminology profile (cur:hasCue), the
way the generated lexica are. A cue's IRI is a hash of what it says, so the editors' decisions on it
(cue_review, plan M1 10c) keep their key from one run to the next; the same cue from several rows is one, its
values together and its strength the highest. The editors' decisions
(recherche-ergebnisse/entscheidungen.json, recherche_entscheidungen.py) bring in the new cues they took from
the documents' terms - unverified, as the research's, but none the own lexicon holds, too short or of an
unknown target or land - and apply to the cues they name, whatever gave them: confirmed ones verified,
rejected ones left out. The same research and the same decisions give the same bytes. Each report's cues and
what gave none, by reason, are reported, and the decisions by outcome - those whose cue the research no
longer gives by IRI.

Usage: python -I werkzeuge/importiere_recherche.py <ontology-dir>
"""

from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

from rdflib import RDF, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, SKOS

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves the tool's own folder out
from recherche_cues import MIN_SIGNS, Cue, Model, Own, cues_of, label_keys, merged, own_holds, word_key
from recherche_entscheidungen import FILE as DECISIONS
from recherche_entscheidungen import Decision, NewTerm, applied, decided, taken
from recherche_tabellen import read_report

PREFIXES = {
    "cur": "https://w3id.org/wlo/curriculum/core#",
    "cv": "https://w3id.org/wlo/curriculum/vocab#",
    "lvl": "https://w3id.org/wlo/curriculum/level/",
    "qz": "https://w3id.org/wlo/curriculum/crosscutting/",
    "kd": "https://w3id.org/wlo/curriculum/dimension/",
    "ctx": "https://w3id.org/wlo/curriculum/context/",
    "fld": "https://w3id.org/wlo/curriculum/field/",
    "land": "https://w3id.org/wlo/curriculum/region/",
    "schul": "https://w3id.org/wlo/curriculum/profile/school#",
    "elem": "https://w3id.org/wlo/curriculum/profile/early-childhood#",
    "beruf": "https://w3id.org/wlo/curriculum/profile/vocational#",
    "hs": "https://w3id.org/wlo/curriculum/profile/higher-education#",
    "eb": "https://w3id.org/wlo/curriculum/profile/adult-education#",
}
# a report's sector by the number its name begins with (recherche-auftraege/README.md)
SECTORS = {"01": "schule", "02": "elementar", "03": "beruf", "04": "hochschule", "05": "erwachsenenbildung"}
SECTORS |= {"06": "schule", "07": "schule"}
PROFILE_PREFIX = {"schule": "schul", "elementar": "elem", "beruf": "beruf", "hochschule": "hs"}
PROFILE_PREFIX |= {"erwachsenenbildung": "eb"}
FOLDER = "profile/laender"
HEADER = (
    "# GENERIERT von werkzeuge/importiere_recherche.py aus recherche-ergebnisse/ (Länderrecherche,\n"
    "# ungeprüft). Nicht von Hand ändern: die Redaktion entscheidet über cue_review (Plan M1 10c).\n"
)
MARK = b"# GENERIERT von werkzeuge/importiere_recherche.py"  # how a file this tool wrote begins
_FILE = re.compile(rf"{FOLDER}/[a-z]+-[A-Z]{{2}}(-[A-Z0-9]{{1,3}})?\.ttl")  # a sector's, and a land's code
CUR = Namespace(PREFIXES["cur"])
CV = Namespace(PREFIXES["cv"])
LAND = Namespace(PREFIXES["land"])
# what is no target of a cue: a scheme of concepts, a profile, a cue
SCHEMES = {SKOS.ConceptScheme, CUR.LevelScheme, CUR.CompetencyModel, CUR.OperatorList}
NO_TARGET = SCHEMES | {CUR.TerminologyProfile, CUR.LexicalCue}


def _prefixed(iri: str) -> str | None:
    for prefix, namespace in PREFIXES.items():
        if iri.startswith(namespace):
            return f"{prefix}:{iri[len(namespace) :]}"
    return None


def model_of(ontology: Path) -> tuple[Model, dict[str, Own]]:
    """What the research is checked against - the model's targets, schemes and labels from its core,
    vocabularies and the sectors' own profiles, not the files this tool writes - and each sector's own
    lexicon, its words and patterns."""
    graph = Graph()
    for folder in ("ontologie", "vokabulare", "profile"):
        for path in sorted((ontology / folder).glob("*.ttl")):
            graph.parse(path)
    typed = {kind: {str(s) for s in graph.subjects(RDF.type, kind)} for kind in NO_TARGET}
    excluded = set().union(*typed.values())
    schemes = {name for kind in SCHEMES for iri in typed[kind] if (name := _prefixed(iri))}
    targets = {name for s in set(graph.subjects()) if str(s) not in excluded and (name := _prefixed(str(s)))}
    labels: dict[str, frozenset[str]] = {}
    for target in targets:
        subject = URIRef(PREFIXES[target.split(":", 1)[0]] + target.split(":", 1)[1])
        said = [*graph.objects(subject, SKOS.prefLabel), *graph.objects(subject, SKOS.altLabel)]
        said += [*graph.objects(subject, SKOS.notation)]
        labels[target] = frozenset(key for label in said for key in label_keys(str(label)))
    own = {}
    for sector, prefix in PROFILE_PREFIX.items():
        profile = URIRef(PREFIXES[prefix] + "Terminology")
        cues = list(graph.objects(profile, CUR.hasCue))
        words = frozenset(word_key(str(word)) for cue in cues for word in graph.objects(cue, CUR.surfaceForm))
        patterns = tuple(
            sorted(
                (
                    str(pattern),
                    frozenset(name for t in graph.objects(cue, CUR.mapsTo) if (name := _prefixed(str(t)))),
                )
                for cue in cues
                for pattern in graph.objects(cue, CUR.pattern)
            )
        )
        own[sector] = Own(words, patterns)
    return Model(frozenset(targets), frozenset(schemes), labels), own


def _expand(name: str) -> URIRef:
    prefix, local = name.split(":", 1)
    return URIRef(PREFIXES[prefix] + local)


def _land(cue: Cue) -> str:
    """The land of the file a cue stands in: its own where it names one, the whole country otherwise."""
    return cue.regions[0] if len(cue.regions) == 1 else "DE"


def _iri(sector: str, cue: Cue) -> URIRef:
    said = "|".join([cue.kind, ",".join(cue.regions), cue.surface, ",".join(cue.maps_to), cue.role])
    digest = hashlib.sha256(said.encode("utf-8")).hexdigest()[:12]
    return URIRef(f"{PREFIXES[PROFILE_PREFIX[sector]]}re-{_land(cue)}-{digest}")


def _graph(sector: str, cues: dict[URIRef, Cue]) -> Graph:
    graph = Graph()
    for prefix, namespace in PREFIXES.items():
        graph.bind(prefix, namespace)
    graph.bind("dct", DCTERMS)
    graph.bind("skos", SKOS)
    profile = _expand(f"{PROFILE_PREFIX[sector]}:Terminology")
    for iri, cue in cues.items():
        graph.add((profile, CUR.hasCue, iri))
        graph.add((iri, RDF.type, CUR.LexicalCue))
        graph.add((iri, CUR.surfaceForm, Literal(cue.surface)))
        graph.add((iri, CUR.cueRole, CV[f"role_{cue.role}"]))
        graph.add((iri, CUR.cueKind, CV[f"ck_{cue.kind}"]))
        for target in cue.maps_to:
            graph.add((iri, CUR.mapsTo, _expand(target)))
        for region in cue.regions:
            graph.add((iri, CUR.scopeRegion, LAND[region]))
        for place in cue.occurs_in:
            graph.add((iri, CUR.occursIn, CV[f"occ_{place}"]))
        for hint in cue.recognition:
            graph.add((iri, CUR.recognitionHint, Literal(hint, lang="de")))
        for hint in cue.negative:
            graph.add((iri, CUR.negativeHint, Literal(hint, lang="de")))
        if cue.pattern:
            graph.add((iri, CUR.pattern, Literal(cue.pattern)))
        for example in cue.examples:
            graph.add((iri, CUR.positiveExample, Literal(example)))
        graph.add((iri, CUR.strength, Literal(cue.strength, datatype=XSD.decimal)))
        graph.add((iri, CUR.verified, Literal(cue.verified)))
        for source in cue.sources:
            graph.add((iri, DCTERMS.source, Literal(f"recherche-ergebnisse/{source}")))
        for note in cue.notes:
            graph.add((iri, SKOS.editorialNote, Literal(note, lang="de")))
    return graph


def import_reports(
    ontology: Path, unmatched: list[str] | None = None
) -> tuple[dict[str, bytes], dict[str, Counter[str]]]:
    """The files the research gives, by their path under the ontology, and per report its cues ("Cues") and
    what gave none, by reason - the editors' decisions applied, counted under their file's name; `unmatched`,
    where given, takes the IRIs of the decisions whose cue the research no longer gives."""
    model, own = model_of(ontology)
    decisions, terms = decided(ontology)
    by_file: dict[tuple[str, str], dict[URIRef, Cue]] = {}
    reported: dict[str, Counter[str]] = {}
    for path in sorted((ontology / "recherche-ergebnisse").glob("*.md")):
        sector = SECTORS.get(path.name[:2])
        if sector is None:
            continue
        cues, missed = cues_of(path.name, read_report(path), model, own[sector])
        reported[path.name] = Counter({"Cues": len(cues)}) + missed
        for cue in cues:
            held = by_file.setdefault((sector, _land(cue)), {})
            iri = _iri(sector, cue)
            held[iri] = merged(held[iri], cue) if iri in held else cue
    if decisions or terms:
        outcomes = _take(by_file, terms, model, own)  # before the decisions: one on its IRI applies to it
        outcomes += _decide(by_file, decisions, [] if unmatched is None else unmatched)
        reported[Path(DECISIONS).name] = outcomes
    files = {}
    for (sector, land), of_file in sorted(by_file.items()):
        if not of_file:  # the editors rejected every cue
            continue
        turtle = _graph(sector, of_file).serialize(format="turtle")
        files[f"{FOLDER}/{sector}-{land}.ttl"] = (HEADER + turtle).replace("\r\n", "\n").encode("utf-8")
    return files, reported


def _take(
    by_file: dict[tuple[str, str], dict[URIRef, Cue]], terms: list[NewTerm], model: Model, own: dict[str, Own]
) -> Counter[str]:
    """Each new cue the files can take in its land's file, one with the same cue the research gives; what was
    taken, and why the others were not."""
    outcomes: Counter[str] = Counter()
    sectors = {PREFIXES[prefix] + "Terminology": sector for sector, prefix in PROFILE_PREFIX.items()}
    for term in terms:
        sector, target = sectors.get(term.profile), _prefixed(term.maps_to)
        if sector is None:
            raise ValueError(
                f"{DECISIONS}: {term.surface_form}: profile ist keins der Bereiche: {term.profile}"
            )
        if target is None:
            raise ValueError(
                f"{DECISIONS}: {term.surface_form}: maps_to liegt in keinem Namensraum: {term.maps_to}"
            )
        if len(term.surface_form) < MIN_SIGNS:
            outcomes["neuer Hinweis: zu kurz"] += 1
        elif target not in model.targets:
            outcomes["neuer Hinweis: Ziel unbekannt"] += 1
        elif any(f"land:{region}" not in model.targets for region in term.regions):
            outcomes["neuer Hinweis: Land unbekannt"] += 1  # a file of it would stop the vocabularies loading
        elif own_holds(own[sector], term.surface_form, [target]):
            outcomes["neuer Hinweis: Wort des eigenen Lexikons"] += 1
        else:
            cue = taken(term, target)
            held = by_file.setdefault((sector, _land(cue)), {})
            iri = _iri(sector, cue)
            held[iri] = merged(held[iri], cue) if iri in held else cue
            outcomes["neuer Hinweis"] += 1
    return outcomes


def _decide(
    by_file: dict[tuple[str, str], dict[URIRef, Cue]], decisions: dict[str, Decision], unmatched: list[str]
) -> Counter[str]:
    """Each decided cue as its decision leaves it, in place; what was decided, by outcome, and in `unmatched`
    the decisions whose cue is none of the research's."""
    outcomes: Counter[str] = Counter()
    given = {str(iri) for of_file in by_file.values() for iri in of_file}
    missing = [cue for cue in decisions if cue not in given]
    unmatched += missing
    for of_file in by_file.values():
        for iri in [iri for iri in of_file if str(iri) in decisions]:
            cue = applied(of_file[iri], decisions[str(iri)])
            if cue is None:
                del of_file[iri]
                outcomes["verworfen"] += 1
            else:
                of_file[iri] = cue
                outcomes["bestätigt"] += 1
    if missing:
        outcomes["Entscheidung ohne Cue"] = len(missing)
    return outcomes


def write_files(ontology: Path, files: dict[str, bytes]) -> None:
    """Write the generated files; a file this tool generated that the research no longer gives goes, any
    other file stays - and is never overwritten; a name that is no land's file is refused (ValueError, nothing
    written: a row's land is the research's text)."""
    for name in files:
        if not _FILE.fullmatch(name):
            raise ValueError(f"{name!r} ist kein Name einer Länderdatei; nichts geschrieben")
    folder = ontology / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    for name in files:
        held = ontology / name
        if held.exists() and not held.read_bytes().startswith(MARK):
            raise ValueError(f"{name} ist nicht von importiere_recherche.py geschrieben; nichts geschrieben")
    for path in folder.glob("*.ttl"):
        if f"{FOLDER}/{path.name}" not in files and path.read_bytes().startswith(MARK):
            path.unlink()
    for name, content in files.items():
        (ontology / name).write_bytes(content)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ontology = Path(sys.argv[1])
    unmatched: list[str] = []
    files, reported = import_reports(ontology, unmatched)
    write_files(ontology, files)
    counted = reported.pop(Path(DECISIONS).name, None)
    for report, counts in reported.items():
        missed = [f"{reason} x{count}" for reason, count in counts.most_common() if reason != "Cues"]
        print(f"{report}: {counts['Cues']} Cues" + (f"; ohne Cue: {', '.join(missed)}" if missed else ""))
    total = sum(reported.values(), Counter())
    total.pop("Cues", None)  # a report's cues before the same cue from several rows is one
    written = sum(content.count(b" a cur:LexicalCue") for content in files.values())
    print(f"zusammen {written} Cues in {len(files)} Dateien; ohne Cue: {dict(total.most_common())}")
    if counted:
        print(f"Entscheidungen der Redaktion: {dict(counted.most_common())}")
    for cue in unmatched:  # a changed row gives a new IRI: the editors decide on that cue anew
        print(f"  ohne Cue: {cue}")


if __name__ == "__main__":
    main()
