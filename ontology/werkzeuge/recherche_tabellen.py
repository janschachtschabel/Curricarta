"""The tables of the research results (recherche-ergebnisse/*.md), as the importer and the report read them.

A result file holds csv blocks; a table is known by its header line, not by the heading above it -
headings vary, some are missing. Fields are split at every ";": the research writes no csv quoting, and a '"'
in a field is text. A row with another number of fields than its header - an unescaped ";" in a field, a row
broken over two lines - is "shifted": its line is returned apart and the row is never read as data (plan M1
10a R1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_BLOCK = re.compile(r"^```csv[ \t]*\n(.*?)^```", re.S | re.M)


@dataclass(frozen=True)
class Row:
    """A data row: the line it stands on in its file (from 1), its fields by the header's names, stripped."""

    line: int
    values: dict[str, str]

    def __getitem__(self, column: str) -> str:
        """The field of `column`; empty where the table has no such column."""
        return self.values.get(column, "")


@dataclass(frozen=True)
class Table:
    header: tuple[str, ...]
    rows: tuple[Row, ...]
    shifted: tuple[int, ...]  # the lines of rows whose number of fields differs from the header's

    def has(self, *columns: str) -> bool:
        return set(columns) <= set(self.header)


def read_tables(text: str) -> list[Table]:
    """Every csv block of `text` (its lines ended by a line feed alone, as read_text gives them) as a table,
    in the order they stand; blank lines are no rows."""
    tables = []
    for block in _BLOCK.finditer(text):
        first = text.count("\n", 0, block.start(1)) + 1
        lines = [
            (first + offset, line) for offset, line in enumerate(block.group(1).split("\n")) if line.strip()
        ]
        if not lines:
            continue
        header = tuple(field.strip() for field in lines[0][1].split(";"))
        rows: list[Row] = []
        shifted: list[int] = []
        for number, line in lines[1:]:
            fields = [field.strip() for field in line.split(";")]
            if len(fields) == len(header):
                rows.append(Row(number, dict(zip(header, fields, strict=True))))
            else:
                shifted.append(number)
        tables.append(Table(header, tuple(rows), tuple(shifted)))
    return tables


def read_report(path: Path) -> list[Table]:
    return read_tables(path.read_text(encoding="utf-8"))
