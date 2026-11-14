"""Report on the research results (recherche-ergebnisse/*.md) before and beside their import (plan M1
10.2, 10b).

Read as the importer reads them (recherche_tabellen.py) and checked against the same model (model_of of
importiere_recherche.py), for every report:
  - per table (named by its header's first columns): its rows, the rows whose number of fields differs
    from the header (an unescaped ";" or a broken row), by line, and the share of evidence E;
  - values outside the briefs' lists (rolle, abgleich_vorliste, funktion, beleg, a frame's entspricht, and
    fundort where the brief lists it), and targets the model does not know - a scheme only for a level
    system;
  - what the import makes of the report: its cues and what gave none, by reason, as the importer counts;
  - corrections the research offers to words of the own lexicon - they never enter it (10a); the editors
    decide.
Exit code 1 where any row is shifted - the research has to be mended before it is trusted -, 2 where no
report was read, else 0.

Usage: python -I werkzeuge/pruefe_recherche.py <ontology-dir> [report ...]
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves the tool's own folder out
from importiere_recherche import SECTORS, model_of
from recherche_cues import (
    COMPARED,
    CROSS_CUTTING,
    OCCURS_IN,
    ROLES,
    STRENGTH,
    Model,
    Own,
    bracketed,
    cross_cutting_names,
    cues_of,
    own_holds,
    paired,
    parts,
)
from recherche_tabellen import Row, Table, read_report

# where a term stands: the briefs' names - the importer's, the vocabulary's own, and one it has no place for
PLACES = set(OCCURS_IN) | {"randspalte"}
PLACED = ("01", "02", "03")  # the briefs with such a list; those of 04 and 05 let the research name the place
FUNCTION = re.compile(
    r"^(dokumenttyp|gliederung:\w+|aussage:\w+|niveau|zeit|verbindlichkeit|querschnittsmarker|"
    r"verweismarker|kontext|lernort|feld|regel|anerkennung|sonstiges)$"
)
_EMPTY = ("", "-")


def _outside(row: Row, placed: bool) -> list[str]:
    """The row's values outside the briefs' lists, as "column=value"; its fundort only where `placed`."""
    found = []
    if row["rolle"] not in _EMPTY and row["rolle"] not in ROLES:
        found.append(f"rolle={row['rolle']}")
    if row["abgleich_vorliste"] not in _EMPTY and row["abgleich_vorliste"] not in COMPARED:
        found.append(f"abgleich_vorliste={row['abgleich_vorliste']}")
    found += [
        f"funktion={part}"
        for part in parts(row["funktion"])
        if part not in _EMPTY and not FUNCTION.match(part)
    ]
    if placed:
        found += [
            f"fundort={part}" for part in parts(row["fundort"]) if part not in _EMPTY and part not in PLACES
        ]
    if row["beleg"] and row["beleg"][:1] not in STRENGTH:
        found.append(f"beleg={row['beleg']}")
    if "rahmen_titel" in row.values:
        named = cross_cutting_names(row["entspricht"])
        found += [f"entspricht={part}" for part in named if part not in CROSS_CUTTING and part != "sonstiges"]
    return found


def _unknown(row: Row, model: Model) -> list[str]:
    """The row's targets the model does not know. A level system names its scheme at its place, in its
    targets or in its name's brackets, and the importer leaves it out; any other row has no scheme to name."""
    levels = "stufen_in_reihenfolge_woertlich" in row.values
    named = parts(row["ziel_id"]) + (bracketed(row["system"]) if levels else [])
    known = model.targets | model.schemes if levels else model.targets
    return [part for part in named if part not in ("neu", "-") and part not in known]


def _table(table: Table, model: Model, placed: bool) -> list[str]:
    rows = table.rows
    marks = [row["beleg"][:1] for row in rows if "beleg" in row.values]
    share = f"Beleg E {round(100 * marks.count('E') / len(marks))} %" if marks else "ohne Beleg"
    where = f" (Zeile {', '.join(map(str, table.shifted))})" if table.shifted else ""
    lines = [
        f"  [{';'.join(table.header[:3])}…] {len(rows)} Zeilen, "
        f"verschoben {len(table.shifted)}{where}, {share}"
    ]
    outside = Counter(value for row in rows for value in _outside(row, placed))
    unknown = Counter(target for row in rows for target in _unknown(row, model))
    if outside:
        lines.append(
            "    außerhalb der Listen: " + ", ".join(f"{key} x{n}" for key, n in outside.most_common())
        )
    if unknown:
        lines.append("    unbekannte Ziele: " + ", ".join(f"{key} x{n}" for key, n in unknown.most_common()))
    return lines


def _corrections(tables: list[Table], own: Own, model: Model) -> list[str]:
    """The research's corrections to words the own lexicon holds, by word or pattern (own_holds), for the
    targets the word stands for in its row (paired; all of them where it stands for none): the importer takes
    none of them. By line."""
    found = []
    for table in tables:
        for row in table.rows:
            if row["abgleich_vorliste"] != "korrigiert":
                continue
            members, targets = parts(row["begriff_woertlich"]), parts(row["ziel_id"])
            for word in members:
                if own_holds(own, word, paired(word, members, targets, model) or targets):
                    to = f" (zu {row['hinweis_id']})" if row["hinweis_id"] else ""
                    found.append(f"    Zeile {row.line}: „{word}“ → {row['ziel_id'] or '(ohne Ziel)'}{to}")
    return found


def report(ontology: Path, files: Sequence[Path] = ()) -> tuple[list[str], int]:
    """The report's lines on `files` (every report of the ontology where none are named) and its exit code:
    1 where a row is shifted, 2 where no report was read - a wrong folder is no clean research."""
    model, own = model_of(ontology)
    paths = list(files) or sorted((ontology / "recherche-ergebnisse").glob("*.md"))
    lines: list[str] = []
    shifted = 0
    for path in paths:
        if path.name == "README.md":
            continue
        tables = read_report(path)
        lines.append(f"== {path.name}")
        for table in tables:
            lines += _table(table, model, path.name[:2] in PLACED)
            shifted += len(table.shifted)
        sector = SECTORS.get(path.name[:2])
        if sector is None:
            continue
        cues, missed = cues_of(path.name, tables, model, own[sector])
        why = ", ".join(f"{reason} x{n}" for reason, n in missed.most_common())
        lines.append(f"  Import: {len(cues)} Cues" + (f"; ohne Cue: {why}" if why else ""))
        corrections = _corrections(tables, own[sector], model)
        if corrections:
            lines += ["  Korrekturvorschläge zu Wörtern des eigenen Lexikons:", *corrections]
    if not lines:
        return ["keine Berichte gelesen"], 2
    lines.append(f"verschobene Zeilen: {shifted}" + (" - der Bericht scheitert" if shifted else ""))
    return lines, 1 if shifted else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    lines, code = report(Path(sys.argv[1]), [Path(name) for name in sys.argv[2:]])
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
