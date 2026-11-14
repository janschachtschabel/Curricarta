"""The gold standard's commands as the operator calls them: ``judge`` reads a sheet from stdin and tells
its counts as JSON, ``report`` prints its JSON; a refusal in one line on stderr with exit code 1."""

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from app.db.gold import items_of, judge
from app.quality.report import report
from tests.quality.gold_documents import a_document, connection, done
from tests.quality.test_judge import SHEET, a_sample
from tests.quality.test_report import CORRECT, drawn
from tests.support import without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

BACKEND = Path(__file__).resolve().parents[2]


def judge_command(database_url: str, data: bytes, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.quality.judge", *arguments],
        cwd=BACKEND,
        env=environment,
        input=data,
        capture_output=True,
        timeout=120,
        check=False,
    )


async def test_the_command_reads_the_sheet_from_stdin_and_tells_the_counts(
    connection: psycopg.AsyncConnection, database_url: str
) -> None:
    sample, account = await a_sample(connection)
    arguments = ("--sample", str(sample), "--account", account)

    taken = judge_command(database_url, SHEET, *arguments)
    refused = judge_command(database_url, SHEET.replace(b";correct  ;", b";gut;"), *arguments)
    nobody = judge_command(database_url, SHEET, "--sample", str(sample), "--account", "niemand")

    assert taken.returncode == 0, taken.stderr
    assert json.loads(taken.stdout) == {
        "sample": sample, "judged": 4, "new": 4, "changed": 0, "unchanged": 0, "left_empty": 1, "refused": 0,
    }  # fmt: skip
    assert refused.returncode == 1
    assert json.loads(refused.stdout) == {
        "sample": sample, "judged": 0, "new": 0, "changed": 0, "unchanged": 0, "left_empty": 0, "refused": 1,
    }  # fmt: skip
    [line] = refused.stderr.splitlines()
    assert b"line 7: verdict_unknown" in line
    assert b"gut" not in line  # a cell's content is never told
    assert (nobody.returncode, nobody.stdout) == (1, b"")
    assert b"unknown_account" in nobody.stderr


def report_command(database_url: str, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.quality.report", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


async def test_the_command_prints_the_report(connection: psycopg.AsyncConnection, database_url: str) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")
    sample = await drawn(connection, document, "statement")
    for item in await items_of(connection, sample):
        await judge(connection, item.id, document.owner_id, CORRECT)

    printed = report_command(database_url, "--sample", str(sample))
    refused = report_command(database_url, "--sample", "999999")

    assert printed.returncode == 0, printed.stderr
    made = json.loads(printed.stdout)
    assert made == json.loads(json.dumps(await report(connection, [sample])))
    [entry] = made["documents"]
    assert entry["statement"]["weighted"]["precision_strict"] == 1.0  # all correct
    assert entry["statement"]["pooled"]["precision_strict_pooled_wilson95"] == [0.5655, 1.0]
    assert (entry["label"], entry["source_kind"], entry["regions"], entry["pages"]) == (
        "pilot-1", "extraction", ["DE-NW"], 1,
    )  # fmt: skip
    assert (refused.returncode, refused.stdout) == (1, b"")
    assert b"unknown_sample" in refused.stderr
