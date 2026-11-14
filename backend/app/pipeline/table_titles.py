"""A table's title where a label in its first rows names it (plan M1, Nachtrag 11b-2): a module
handbook is one table a module, its name in the cell beside "Modultitel:", its code beside
"Modulnummer/-kürzel:" (Modulhandbuch B.Sc. Physik, Universität Hamburg). The labels are the
profile's cues for a table's cell (``cv:ck_tablePattern`` with ``cv:mark_tableCell``): one naming a
node type gives the title, one naming ``cur:code`` the code. A label is the first cell with text of
one of the table's first LABEL_ROWS rows, in a table of keys and values - with its colon, or a pair
of cells where another pair of the first rows begins with a label a cue names -; what it names is
the next cell with text in its row, a title with the rows it runs on into in its own column.
"""

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from app.conversion.base import Block
from app.domain.lexicon import NEGATIVE, ActiveCue
from app.pipeline.patterns import PatternSearch

LABEL_ROWS = 3
MOST_WRAPPED = 2  # rows a title may run on into
# A code as a label gives it: a token or three of letters, digits and joins ("PHY-AP 1", "MATH 4",
# "PHY-1" with a PDF's typographic dash), a digit or two capitals in it - no remark ("entfällt", "-"): the
# node's code is 100 signs at most and a key
_JOINS = r"./\-\N{HYPHEN}\N{NON-BREAKING HYPHEN}\N{EN DASH}\N{EM DASH}"
_CODE_SHAPE = re.compile(rf"(?=.{{1,30}}$)(?=.*(?:\d|[A-ZÄÖÜ]{{2}}))[\w{_JOINS}]+(?: [\w{_JOINS}]+){{0,2}}")
_CV = "https://w3id.org/wlo/curriculum/vocab#"
_TABLE_PATTERN = _CV + "ck_tablePattern"
_CELL = _CV + "mark_tableCell"
_CODE = "https://w3id.org/wlo/curriculum/core#code"


@dataclass(frozen=True)
class Labels:
    titles: tuple[ActiveCue, ...]  # the labels naming a node type: a table's title beside them
    codes: tuple[ActiveCue, ...]  # those naming a code


@dataclass(frozen=True)
class Labelled:
    titles: tuple[str, ...]  # its title with the rows it runs on into, then without them
    code: str | None
    cues: tuple[ActiveCue, ...]  # the labels that found its title


@dataclass(frozen=True)
class _Cell:
    column: int
    text: str


def table_labels(cues: Iterable[ActiveCue], node_types: Collection[str]) -> Labels:
    """The document's active cues for a table's labels."""
    labels = [
        found
        for found in cues
        if found.cue.kind == _TABLE_PATTERN
        and found.cue.layout_signal == _CELL
        and found.cue.role != NEGATIVE
        and found.cue.pattern is not None
    ]
    return Labels(
        tuple(found for found in labels if any(target in node_types for target in found.cue.maps_to)),
        tuple(found for found in labels if _CODE in found.cue.maps_to),
    )


def read_labels(block: Block, labels: Labels, search: PatternSearch) -> Labelled | None:
    """The title and code a table's labels give it, where one names its title; else None."""
    if block.kind != "table" or not labels.titles:
        return None
    titles: tuple[str, ...] = ()
    code: str | None = None
    found: tuple[ActiveCue, ...] = ()
    rows = _rows(block)
    first = rows[:LABEL_ROWS]
    for at, row in enumerate(first):
        if not _labels(row, [other for other in first if other is not row], labels, search):
            continue
        label, value = row[0].text, row[1]
        if not titles and (hits := tuple(cue for cue in labels.titles if search.found(cue.cue, label))):
            wrapped = _wrapped(value, rows[at + 1 : at + 1 + MOST_WRAPPED], labels, search)
            titles, found = tuple(dict.fromkeys((wrapped, value.text))), hits
        elif code is None and any(search.found(cue.cue, label) for cue in labels.codes):
            code = value.text if _CODE_SHAPE.fullmatch(value.text) else None
    return Labelled(titles, code, found) if titles else None


def _labels(row: list[_Cell], others: list[list[_Cell]], labels: Labels, search: PatternSearch) -> bool:
    """Whether a row is a label's and its value's: a label with its colon, or a pair of cells where
    another of the first rows begins with a label too - a table of keys and values; "Modultitel |
    LP | Semester" or "Modulbezeichnung | ECTS" heads a study plan's columns."""
    if len(row) < 2:
        return False
    if row[0].text.endswith(":"):
        return True
    return len(row) == 2 and any(
        len(other) >= 2 and _a_cue(other[0].text, labels, search) for other in others
    )


def _wrapped(value: _Cell, after: list[list[_Cell]], labels: Labels, search: PatternSearch) -> str:
    """A title with the rows it runs on into: pdfplumber parts a cell over rows, the next holding
    text in the title's column, no field of its own (a label, a colon's); what stands right of it
    is the next column's."""
    parts = [value.text]
    for row in after:
        if not row or row[0].column != value.column or _a_label(row[0].text, labels, search):
            break
        parts.append(row[0].text)
    return " ".join(parts)


def _a_label(text: str, labels: Labels, search: PatternSearch) -> bool:
    return text.endswith(":") or any(search.found(cue.cue, text) for cue in (*labels.titles, *labels.codes))


def _rows(block: Block) -> list[list[_Cell]]:
    """A table's rows in order, each its cells with text from left to right."""
    rows: dict[int, list[_Cell]] = {}
    for cell in block.cells:
        if text := " ".join(cell.text.split()):
            rows.setdefault(cell.row, []).append(_Cell(cell.column, text))
    return [sorted(rows[row], key=lambda cell: cell.column) for row in sorted(rows)]


def _a_cue(text: str, labels: Labels, search: PatternSearch) -> bool:
    """Whether a cell is a label a cue names - no colon alone ("Pflichtbereich:" groups a plan's rows)."""
    return any(search.found(cue.cue, text) for cue in (*labels.titles, *labels.codes))
