"""A judging sheet as it comes back from a spreadsheet or an editor, read into its rows: UTF-8 with or
without a BOM - else the Windows code page a spreadsheet saves "CSV" in -, ``;`` or ``,`` between the
cells (the header's tells which), any line end, the columns in any order and any of them dropped but
``item`` and ``mark``. Only the columns the importer reads are kept, their cells stripped; the wording
and the other shown columns are never read. Whatever cannot be read refuses the sheet at its line."""

import csv
import io
from dataclasses import dataclass

READ = ("item", "mark", "verdict", "reasons", "expected", "note")
NEEDED = ("item", "mark")
_BOM = b"\xef\xbb\xbf"
_WIDE = (b"\xff\xfe", b"\xfe\xff")  # UTF-16's marks: a "Unicode text" save, tabs between its cells


class SheetRefused(Exception):
    """The sheet as a whole: each problem as ``line <n>: <code>``, never a cell's content."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class SheetLine:
    line: int  # where the row begins in the file, the header's 1
    cells: dict[str, str]  # by the columns READ the sheet has, stripped


def _text(data: bytes) -> str:
    if data.startswith(_WIDE) or b"\x00" in data:
        line = data[: max(data.find(b"\x00"), 0)].count(b"\n") + 1
        raise SheetRefused([f"line {line}: encoding_unknown"])
    data = data.removeprefix(_BOM)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as undecodable:
        raise SheetRefused([f"line {data[: undecodable.start].count(b'\n') + 1}: encoding_unknown"]) from None


def read_sheet(data: bytes) -> list[SheetLine]:
    """The sheet's rows with a cell in a column read, by their line; SheetRefused where it cannot be read."""
    text = _text(data)
    first = text.split("\n", 1)[0]
    delimiter = ";" if ";" in first else "," if "," in first else None
    if delimiter is None:
        raise SheetRefused(["line 1: delimiter_unknown"])
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        header = [name.strip() for name in next(reader)]
        if any(header.count(name) > 1 for name in READ):
            raise SheetRefused(["line 1: column_twice"])
        if any(name not in header for name in NEEDED):
            raise SheetRefused(["line 1: column_missing"])
        at = {name: header.index(name) for name in READ if name in header}
        lines: list[SheetLine] = []
        begins = reader.line_num + 1
        for row in reader:
            cells = {name: row[index].strip() if index < len(row) else "" for name, index in at.items()}
            if any(row_cell.strip() for row_cell in row):
                lines.append(SheetLine(begins, cells))
            begins = reader.line_num + 1
    except csv.Error:
        raise SheetRefused([f"line {reader.line_num}: row_unreadable"]) from None
    return lines
