"""Make a synthetic plan of a frozen MEM answer, for the tests (backend/tests/sources/fixtures/mem/).

MEM-Schule's data - the plans' wordings, a Land's or the KMK's - are not ours to hand on: the repository
and the images carry none of them (audit 2026-11-14). A frozen answer (tools/mem_freeze.py) stays on the
developer's disk, under data/mem-local/, which git ignores; this tool makes of it what the tests replay:

- the shape stays - which part lies under which, its classes (the ontology's, not the data), its grades,
  page, position and hours, the references and what they point at -, so that the tree, the typing rules
  and the export are tested on a plan as MEM builds them;
- every wording is made up: a label or description keeps its form alone - as many words, a word with a
  capital for one with a capital, its numbers and its punctuation -, each word taken from a fixed list by
  where it stands, never by what stood there;
- every instance IRI is renamed to one of example.org, in the order the IRIs sort, so that what the
  import orders by IRI keeps its order.

    python backend/tools/mem_synth.py <name> <frozen.json> <out.json>
"""

import json
import re
import sys
from pathlib import Path

NOUNS = (
    "Beispiel",
    "Thema",
    "Inhalt",
    "Verfahren",
    "Aufgabe",
    "Ergebnis",
    "Begriff",
    "Zusammenhang",
    "Darstellung",
    "Methode",
    "Material",
    "Abschnitt",
    "Bereich",
    "Schritt",
    "Regel",
    "Frage",
    "Antwort",
    "Merkmal",
    "Ordnung",
    "Gruppe",
    "Form",
    "Wirkung",
    "Grundlage",
    "Auswahl",
    "Übersicht",
    "Einheit",
    "Vorgang",
    "Anordnung",
    "Beobachtung",
    "Lösung",
    "Skizze",
    "Tabelle",
    "Reihe",
    "Muster",
    "Angabe",
    "Folge",
)
WORDS = (
    "beschreiben",
    "ordnen",
    "vergleichen",
    "nutzen",
    "erklären",
    "prüfen",
    "und",
    "mit",
    "für",
    "in",
    "an",
    "die",
    "der",
    "das",
    "eine",
    "ihre",
    "einfache",
    "eigene",
    "passende",
    "weitere",
    "benennen",
    "zeigen",
    "sammeln",
    "planen",
    "auswerten",
    "darstellen",
    "zu",
    "von",
    "bei",
    "nach",
    "über",
    "sowie",
    "oder",
    "gemeinsam",
    "selbstständig",
    "sachgerecht",
    "schrittweise",
)
BASE = "https://example.org/mem"
ONTOLOGY = "https://w3id.org/lehrplan/ontology/"
_WORD = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)
_SPACE = re.compile(r"(\s+)")
IRI_FIELDS = ("n", "v", "x", "target")


def wording(text: str, seed: int) -> str:
    """A made-up wording of the form of ``text``: its words replaced by where they stand, its numbers,
    punctuation and white space kept."""
    out: list[str] = []
    at = 0
    for piece in _SPACE.split(text):
        if not piece or piece.isspace():
            out.append(piece)
            continue
        lead, core, trail = _WORD.fullmatch(piece).groups()  # type: ignore[union-attr]
        if not core or any(sign.isdigit() for sign in core):
            out.append(piece)  # a number, a mark: no wording
            continue
        words = NOUNS if core[0].isupper() else WORDS
        out.append(f"{lead}{words[(seed * 31 + at * 7) % len(words)]}{trail}")
        at += 1
    return "".join(out)


def _by_number(iri: str) -> tuple[int, str]:
    found = re.search(r"[0-9]{1,15}", iri.rstrip("/").rsplit("/", 1)[-1])
    return (int(found.group()) if found else 10**16, iri)


def synthetic(name: str, frozen: dict[str, object]) -> dict[str, object]:
    """The synthetic plan of a frozen answer, as the module says."""
    closure: list[dict[str, str]] = frozen["closure"]  # type: ignore[assignment]
    references: list[dict[str, str]] = frozen["references"]  # type: ignore[assignment]
    found = {str(frozen["plan"])}
    for row in [*closure, *references]:
        found.update(row[field] for field in IRI_FIELDS if row.get(field))
        found.update(part for part in row.get("ancestors", "").split("|") if part)
    # by the first number of the last segment, then as they sort: where a plan gives its parts neither
    # position nor number the import orders them by that number (app/sources/mem/tree.py, _iri_number),
    # and the new names carry their rank as that number
    renamed = {iri: f"{BASE}/{name}/t{rank:04}" for rank, iri in enumerate(sorted(found, key=_by_number))}

    def row_of(row: dict[str, str], seed: int) -> dict[str, str]:
        made = dict(row)
        for field in IRI_FIELDS:
            if made.get(field):
                made[field] = renamed[made[field]]
        if "ancestors" in made:
            made["ancestors"] = "|".join(renamed[part] for part in made["ancestors"].split("|") if part)
        for at, field in enumerate(("label", "description")):
            if made.get(field):
                made[field] = wording(made[field], seed * 2 + at)
        return made

    made_closure = [row_of(row, at) for at, row in enumerate(closure)]
    made_references = [row_of(row, len(closure) + at) for at, row in enumerate(references)]
    # two labels made alike that were not: the later one gets a word more, so each stays to be found apart
    taken: set[str] = set()
    for at, (row, made) in enumerate(zip(closure, made_closure, strict=True)):
        extra = 0
        while made["label"] in taken and sum(other["label"] == row["label"] for other in closure) == 1:
            made["label"] = f"{wording(row['label'], at * 2)} {NOUNS[(at + extra) % len(NOUNS)]}"
            extra += 1
        taken.add(made["label"])
    return {
        "endpoint": frozen["endpoint"],
        "graph": frozen["graph"],
        "plan": renamed[str(frozen["plan"])],
        "read_at": frozen["read_at"],
        "synthetic": True,
        "closure": sorted(made_closure, key=lambda row: row["n"]),
        "references": sorted(made_references, key=lambda row: (row["x"], row["v"])),
    }


def main() -> None:
    name, source, out = sys.argv[1:4]
    frozen = json.loads(Path(source).read_text(encoding="utf-8"))
    made = synthetic(name, frozen)
    written = json.dumps(made, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    Path(out).write_bytes(written.encode("utf-8"))
    print(f"{out}: {len(made['closure'])} Teile, {len(made['references'])} Verweise")  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
