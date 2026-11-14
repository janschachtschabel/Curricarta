"""The gold standard's sheets hold a third party's wordings and stay out of the repository and the images
by construction (plan H-3 §3.5): the folder they go to is named in .gitignore and .dockerignore, no sheet
lies in the tree but the synthetic fixture, and that fixture's wordings are made of the MEM tool's words."""

import csv
import io
import subprocess
from pathlib import Path

import pytest

from app.quality.sheet import LOCAL_FOLDER, encoded
from app.quality.sheet_read import read_sheet
from tests.sources.test_mem_fixtures import mem_synth

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"
LOCAL = LOCAL_FOLDER.as_posix()


def _rules(name: str) -> list[str]:
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def test_the_local_gold_folder_is_ignored_by_git() -> None:
    ignored = subprocess.run(  # noqa: S603 - git of this machine, a path of the repository
        ["git", "check-ignore", "-q", f"{LOCAL}/pilot-1-statement.csv"],  # noqa: S607
        cwd=ROOT,
        check=False,
    )
    rules = _rules(".gitignore")

    assert ignored.returncode == 0
    assert f"/{LOCAL}/" in rules
    assert [rule for rule in rules if rule.startswith("!/data")] == ["!/data/seed/"]


def test_the_local_gold_folder_stays_out_of_the_images() -> None:
    rules = _rules(".dockerignore")

    assert LOCAL in rules
    assert [rule for rule in rules if rule.startswith("!data")] == ["!data/seed"]


_WIDTHS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))
SHOWN = {"wording", "quote", "verdict", "shown"}  # what a sheet shows of the document, or asks of its judge


def _is_a_sheet(path: Path) -> bool:
    """Whether one of the file's first lines is a judging sheet's header - ``item`` and ``mark`` with a
    column that shows a wording or asks for a verdict -, whatever the encoding its BOM names (UTF-8,
    UTF-16), the line ends, the order and the separator."""
    with path.open("rb") as opened:
        start = opened.read(16_384)
    encoding = next((name for bom, name in _WIDTHS if start.startswith(bom)), "utf-8")
    text = start.decode(encoding, errors="ignore").removeprefix(BOM)
    for line in text.splitlines()[:5]:
        for separator in (";", ",", "\t"):
            names = {name.strip().strip('"') for name in line.split(separator)}
            if {"item", "mark"} <= names and names & SHOWN:
                return True
    return False


HEADER = "item;mark;shown;stratum;page;path;kind;wording;lead_in;quote;link;verdict;reasons;expected;note"
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"


@pytest.mark.parametrize(
    ("data", "sheet"),
    [
        (b"item;mark;stratum;wording;expected\r\n1;p3-b3;t2:text;x;\r\n", True),  # verdict deleted
        (f"{BOM}Bogen pilot-1\r\n{HEADER}\r\n".encode(), True),  # a title row above the header
        (f"{BOM}{HEADER}\n1;m0\n".encode("utf-16-le"), True),  # UTF-16, LF
        (f"{BOM}{HEADER}\r\n1;m0\r\n".encode("utf-16-le"), True),  # what PowerShell 5.1 writes on >
        (f"{BOM}{HEADER}\r\n".encode("utf-16-be"), True),
        (f"{HEADER}\r1;m0\r".encode(), True),  # CR alone
        (HEADER.replace(";", ",").encode(), True),
        (HEADER.replace(";", "\t").encode(), True),
        (b"item;mark;shown\r\n", True),  # cut down to what proves a judgement
        (b"item;mark;stratum\r\n", False),  # nothing a sheet shows or asks
        (b"name;value\r\nitem;mark\r\n", False),
        (b"\xff\xfe\x00", False),  # a broken sign: no error, no sheet
    ],
    ids=["no-verdict", "title-row", "utf-16-lf", "utf-16-crlf", "utf-16-be", "cr", "commas", "tabs",
         "shown-marks", "no-shown-column", "other", "broken"],
)  # fmt: skip
def test_a_sheet_is_known_however_it_was_saved(tmp_path: Path, data: bytes, sheet: bool) -> None:
    saved = tmp_path / "saved.csv"
    saved.write_bytes(data)

    assert _is_a_sheet(saved) is sheet


WORKBOOKS = (".xlsx", ".xlsm", ".xls", ".ods", ".numbers")  # a sheet saved by a spreadsheet as its own


def _found(root: Path, names: list[str]) -> list[str]:
    """The listed files that are a judging sheet - a text file with its header, or any workbook, which
    the guard cannot read into and so takes for one -, by their path under ``root``."""
    files = [root / name for name in names]
    return [
        path.relative_to(root).as_posix()
        for path in files
        if path.is_file() and (path.suffix.lower() in WORKBOOKS or _is_a_sheet(path))
    ]


def test_a_workbook_in_the_tree_is_taken_for_a_sheet(tmp_path: Path) -> None:
    for name, data in (
        ("docs/pilot-1.xlsx", b"PK\x03\x04"),
        ("data/Plan.ODS", b"PK\x03\x04"),
        ("old.xls", b"\xd0\xcf\x11\xe0"),
        ("notes.csv", b"name;value\r\n"),
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)

    found = _found(tmp_path, ["docs/pilot-1.xlsx", "data/Plan.ODS", "old.xls", "notes.csv"])

    assert found == ["docs/pilot-1.xlsx", "data/Plan.ODS", "old.xls"]


def test_no_judging_sheet_lies_in_the_tree(tmp_path: Path) -> None:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    )

    sheets = _found(ROOT, [name for name in listed.stdout.decode("utf-8").split("\0") if name])

    assert sheets == ["backend/tests/quality/fixtures/bogen.csv"]  # each other one named here
    made = tmp_path / "sheet.csv"
    made.write_bytes(encoded([]))
    assert _is_a_sheet(made)  # as the tool writes it


def test_a_gold_fixture_s_wordings_are_made_of_the_tool_s_words() -> None:
    data = (FIXTURES / "bogen.csv").read_bytes()
    text = data.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text, newline=""), delimiter=";"))
    known = {*mem_synth.NOUNS, *mem_synth.WORDS}

    assert read_sheet(data)  # the importer reads it
    written = [row[column] for row in rows for column in ("wording", "note") if row[column]]
    assert len(written) >= 6
    for cell in written:
        for piece in cell.split():
            word = "".join(sign for sign in piece if sign.isalpha())
            assert word in known or not word, piece
