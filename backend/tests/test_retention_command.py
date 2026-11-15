"""``python -m app.retention [--dry-run]`` run as the operators run it: one line of JSON with counts alone,
never a key, a title or a wording; exit code 3 beside another sweep, 1 on a failure or a place the store
refuses, each in one log line. Fixtures: tests/test_retention.py."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app.core.storage import FileSystemStorage
from app.db.retention import LOCK_KEY
from tests.db.retention_rows import add_ended_run, add_job, garbage, job_ids, raw_key
from tests.support import without_settings_variables
from tests.test_retention import files, keep_answers, made, setup

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["files", "made", "setup"]  # the fixtures, from test_retention

BACKEND = Path(__file__).resolve().parents[1]


def run_command(
    url: str, store: Path | None, *arguments: str, log_format: str = "json"
) -> subprocess.CompletedProcess[str]:
    """The command as the operators run it; ``store`` None names no store at all."""
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": url, "LOG_FORMAT": log_format}
    if store is not None:
        environment["STORAGE_DIR"] = str(store)
    return subprocess.run(  # noqa: S603 - this interpreter and a fixed module
        [sys.executable, "-m", "app.retention", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("arguments", [["--dry-run"], []], ids=["dry-run", "sweep"])
async def test_the_command_prints_counts_and_no_wording(
    database_url: str,
    setup: psycopg.Connection,
    made: dict[str, Any],
    files: FileSystemStorage,
    arguments: list[str],
) -> None:
    run = add_ended_run(setup, made["document"], ended_days_ago=40)
    keep_answers(files, run, 1)
    add_job(setup, ended_days_ago=100)
    setup.execute(
        "INSERT INTO audit_log (at, action, subject, details) VALUES (now() - interval '400 days',"
        " 'document.edit', %s, '{\"title\": \"Lehrplan Erdkunde\"}')",
        (str(made["document"]),),
    )

    done = run_command(database_url, files.root, *arguments)

    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"jobs": 1, "audit_entries": 1, "runs": 1, "objects": 1, "refused": 0}
    for told in (done.stdout, done.stderr):
        assert str(run) not in told and str(made["document"]) not in told
        assert "runs/" not in told and "Erdkunde" not in told
    assert (raw_key(setup, run) is None) is (arguments == [])


def test_a_place_the_store_refuses_ends_the_command_with_1_in_one_log_line(
    database_url: str, setup: psycopg.Connection, tmp_path: Path
) -> None:
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES ('runs/con/'), ('exports/old/')")

    done = run_command(database_url, tmp_path / "objects")

    assert done.returncode == 1
    assert json.loads(done.stdout) == {"jobs": 0, "audit_entries": 0, "runs": 0, "objects": 0, "refused": 1}
    [line] = done.stderr.splitlines()
    assert "1 noted place(s) the store refuses" in json.loads(line)["message"]
    assert "con" not in line
    assert garbage(setup) == ["runs/con/"]


def test_two_sweeps_at_once_do_not_run_side_by_side(
    database_url: str, setup: psycopg.Connection, tmp_path: Path
) -> None:
    job = add_job(setup)
    with psycopg.connect(database_url, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))  # the other sweep, running

        second = run_command(database_url, tmp_path / "objects")

    assert second.returncode == 3, second.stderr
    assert second.stdout == ""
    assert len(second.stderr.splitlines()) == 1
    assert "another sweep" in json.loads(second.stderr)["message"]
    assert job_ids(setup) == {job}


@pytest.mark.parametrize("log_format", ["json", "text"])
def test_a_database_away_ends_with_1_in_one_log_line(tmp_path: Path, log_format: str) -> None:
    wrong = "away-invented"  # an invented password: no server listens
    url = make_conninfo("postgresql://curricarta@127.0.0.1:1/curricarta", password=wrong)

    refused = run_command(url, tmp_path / "objects", log_format=log_format)

    assert refused.returncode == 1
    assert refused.stdout == ""
    lines = refused.stderr.splitlines()
    assert len(lines) == 1, refused.stderr
    message = json.loads(lines[0])["message"] if log_format == "json" else lines[0]
    assert "retention stopped" in message
    assert "away-invented" not in refused.stderr


def test_a_store_not_configured_names_the_setting_in_one_log_line(
    database_url: str, setup: psycopg.Connection
) -> None:
    refused = run_command(database_url, None)

    assert refused.returncode == 1
    [line] = refused.stderr.splitlines()
    assert "STORAGE_DIR is needed" in json.loads(line)["message"]
