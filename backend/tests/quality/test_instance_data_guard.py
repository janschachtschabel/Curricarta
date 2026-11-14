"""The gold standard's sheets hold a third party's wordings and stay out of the repository and the images
by construction (plan H-3 §3.5): the folder they go to is named in .gitignore and .dockerignore, no sheet
lies in the tree but the synthetic fixture, and that fixture's wordings are made of the MEM tool's words."""

import csv
import io
import subprocess
from pathlib import Path

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


def _is_a_sheet(path: Path) -> bool:
    """Whether the file's first line is a judging sheet's header, in whatever order and separator."""
    with path.open("rb") as opened:
        first = opened.readline(4096)
    text = first.decode("utf-8", errors="ignore").lstrip("\N{ZERO WIDTH NO-BREAK SPACE}")
    names = {name.strip() for name in next(csv.reader(io.StringIO(text), delimiter=";"), [])}
    names |= {name.strip() for name in next(csv.reader(io.StringIO(text), delimiter=","), [])}
    return {"item", "mark", "verdict"} <= names


def test_no_judging_sheet_lies_in_the_tree(tmp_path: Path) -> None:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    files = [ROOT / name for name in listed.stdout.decode("utf-8").split("\0") if name]

    sheets = [path.relative_to(ROOT).as_posix() for path in files if path.is_file() and _is_a_sheet(path)]

    assert sheets == ["backend/tests/quality/fixtures/bogen.csv"]
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
