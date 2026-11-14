"""``python -m app.quality.sheet``: a sample's judging sheet - each item with its wording and where to look
in the tree or the blocks, the cells to judge empty - as a spreadsheet opens it: UTF-8 with a BOM, ``;``
between the cells, a cell that starts like a formula written as text."""

import csv
import io
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from app.db.documents import Document
from app.db.gold import items_of
from app.db.nodes import write_subtree
from app.domain.l1 import AnchorDraft, NodeDraft
from app.domain.wording import text_hash
from app.quality.sample import Request, draw
from app.quality.sheet import NOT_ASKED, SHEET_HEADER, destination_refused, encoded, sheet_rows
from tests.db.document_of import document_of
from tests.quality.gold_documents import (
    CV,
    MODEL,
    PART,
    PROPOSED,
    WORDS,
    a_document,
    block,
    connection,
    done,
    owner,
    statement,
    statement_id,
    with_contents,
)
from tests.support import without_settings_variables

pytestmark = [pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

BASE = "http://127.0.0.1:18080"
BACKEND = Path(__file__).resolve().parents[2]


async def a_statement_sample(connection: psycopg.AsyncConnection) -> tuple[Document, int]:
    document = await a_document(connection)
    await done(connection, document, "X4")
    drawn = await draw(
        connection, Request(document.id, "statement", "pilot-1", await owner(connection, document))
    )
    return document, drawn.sample


@pytest.mark.pg
async def test_the_sheet_names_each_item_with_where_to_look(connection: psycopg.AsyncConnection) -> None:
    document, sample = await a_statement_sample(connection)

    rows = await sheet_rows(connection, sample, BASE)

    items = await items_of(connection, sample)
    assert [row["item"] for row in rows] == [str(item.id) for item in items]
    by_wording = {row["wording"]: row for row in rows}
    outcome = by_wording[WORDS["outcome"]]
    made = await statement_id(connection, WORDS["outcome"])
    assert outcome == {
        "item": outcome["item"], "mark": "m" + text_hash(WORDS["outcome"])[:12], "stratum": "learningOutcome",
        "page": "1", "path": WORDS["title"], "kind": "learningOutcome", "wording": WORDS["outcome"],
        "lead_in": "", "quote": "",
        "link": f"{BASE}/dokumente/{document.id}/baum?zeile=statement:{made}&seite=1",
        "verdict": "", "reasons": "", "expected": NOT_ASKED, "note": "",
    }  # fmt: skip
    assert by_wording[WORDS["content"]]["stratum"] == "content"
    assert WORDS["own"] not in by_wording  # the editor's: not drawn


@pytest.mark.pg
async def test_a_block_s_row_shows_its_text_and_asks_for_a_count(connection: psycopg.AsyncConnection) -> None:
    document = await document_of(connection, with_contents())
    heading = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=f"1 {PART} 1",
        anchors=(AnchorDraft(("p3-b2",), page_start=3),),
    )  # fmt: skip
    await write_subtree(connection, document.id, heading)
    await done(connection, document, "X4")
    drawn = await draw(
        connection, Request(document.id, "block", "pilot-1", await owner(connection, document))
    )

    rows = await sheet_rows(connection, drawn.sample, BASE)

    first = rows[0]
    assert first == {
        "item": first["item"], "mark": "p3-b3", "stratum": "t2:text", "page": "3", "path": "", "kind": "text",
        "wording": with_contents()[5].text, "lead_in": "", "quote": "",
        "link": f"{BASE}/quellen/{document.source_id}/bloecke?seite=3",
        "verdict": NOT_ASKED, "reasons": NOT_ASKED, "expected": "", "note": "",
    }  # fmt: skip
    assert [row["mark"] for row in rows] == ["p3-b3", "p5-b1"]


@pytest.mark.pg
async def test_a_cell_starting_like_a_formula_is_written_as_text(connection: psycopg.AsyncConnection) -> None:
    signs = ("=", "+", "-", "@")
    document = await document_of(connection, [block("p1-b1", WORDS["title"]), block("p1-b2", WORDS["long"])])
    root = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=WORDS["title"],
        anchors=(AnchorDraft(("p1-b1",), page_start=1),),
        statements=tuple(statement(f"{sign}{WORDS['outcome']}") for sign in signs),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await done(connection, document, "X4")
    drawn = await draw(
        connection, Request(document.id, "statement", "pilot-1", await owner(connection, document))
    )

    data = encoded(await sheet_rows(connection, drawn.sample, BASE))

    assert data.startswith(b"\xef\xbb\xbf")  # the BOM a spreadsheet reads UTF-8 by
    text = data.decode("utf-8-sig")
    lines = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    assert tuple(lines[0]) == SHEET_HEADER
    wordings = sorted(line[SHEET_HEADER.index("wording")] for line in lines[1:])
    assert wordings == sorted(f"'{sign}{WORDS['outcome']}" for sign in signs)
    assert "\r\n" in text  # as a spreadsheet writes its lines


def test_a_sheet_goes_to_the_local_gold_folder_or_down_a_pipe(tmp_path: Path) -> None:
    folder = tmp_path / "data" / "gold-local"
    folder.mkdir(parents=True)
    tracked = tmp_path / "backend" / "sheet.csv"
    tracked.parent.mkdir()

    with (folder / "pilot-1-statement.csv").open("wb") as local, tracked.open("wb") as elsewhere:
        assert not destination_refused(tmp_path, local.fileno())
        assert destination_refused(tmp_path, elsewhere.fileno())
        assert not destination_refused(None, elsewhere.fileno())  # no repository around the code: unknown
    reading, writing = os.pipe()
    try:
        assert not destination_refused(tmp_path, writing)
    finally:
        os.close(reading)
        os.close(writing)


def sheet_command(
    database_url: str, stdout: int | object, *arguments: str
) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.quality.sheet", *arguments],
        cwd=BACKEND,
        env=environment,
        stdout=stdout,  # type: ignore[arg-type]
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )


@pytest.mark.pg
async def test_the_command_writes_the_sheet_and_warns_what_it_holds(
    connection: psycopg.AsyncConnection, database_url: str, tmp_path: Path
) -> None:
    _, sample = await a_statement_sample(connection)
    arguments = ("--sample", str(sample), "--base-url", BASE)

    piped = sheet_command(database_url, subprocess.PIPE, *arguments)
    with (tmp_path / "sheet.csv").open("wb") as outside:  # beside the repository: not its local folder
        refused = sheet_command(database_url, outside, *arguments)
    unknown = sheet_command(database_url, subprocess.PIPE, "--sample", "999999", "--base-url", BASE)

    assert piped.returncode == 0, piped.stderr
    assert piped.stdout == encoded(await sheet_rows(connection, sample, BASE))
    [warning] = piped.stderr.splitlines()
    assert b"data/gold-local/" in warning
    assert refused.returncode == 1
    assert (tmp_path / "sheet.csv").read_bytes() == b""
    [line] = refused.stderr.splitlines()
    assert b"data/gold-local/" in line
    assert (unknown.returncode, unknown.stdout) == (1, b"")
    assert b"unknown_sample" in unknown.stderr
