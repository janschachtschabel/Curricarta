"""``python -m app.retention [--dry-run]``: the sweep takes what is past its time from the database and the
places noted for the store from the store, one sweep at a time, and prints its counts - never a key, a
title or a wording. A sweep broken between noting a place and emptying it is finished by the next."""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.db.migrate import migrate
from app.db.retention import LOCK_KEY
from app.retention import Policy, SweepBusy, Swept, sweep
from app.usage.ledger import set_quota, usage_of
from tests.db.l1 import add_conversion, add_document, seed_vocabulary
from tests.db.retention_rows import add_ended_run, add_job, add_usage, garbage, job_ids, raw_key
from tests.support import without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

BACKEND = Path(__file__).resolve().parents[1]
POLICY = Policy(jobs_days=90, audit_days=365, raw_answers_days=30)


@pytest.fixture
def setup(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_vocabulary(opened)
        yield opened


@pytest.fixture
async def connection(database_url: str, setup: psycopg.Connection) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as opened:
        yield opened


@pytest.fixture
def made(setup: psycopg.Connection) -> dict[str, Any]:
    made = add_conversion(setup)
    made["document"] = add_document(setup, made)
    return made


@pytest.fixture
def files(tmp_path: Path) -> FileSystemStorage:
    return FileSystemStorage(tmp_path / "objects")


def keep_answers(files: FileSystemStorage, run: uuid.UUID, *numbers: int) -> None:
    for number in numbers:
        files.put(f"runs/{run}/x4/{number}.json", b'[{"kind": "response"}]')


def kept(files: FileSystemStorage) -> list[str]:
    return sorted(files.list("runs/")) if (files.root / "runs").exists() else []


async def test_a_run_s_raw_answers_past_their_time_leave_the_store_and_the_run_says_so(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    old = add_ended_run(setup, made["document"], ended_days_ago=31)
    young = add_ended_run(setup, made["document"], ended_days_ago=1)
    keep_answers(files, old, 1, 3)  # a gap where an answer was never kept
    keep_answers(files, young, 1)

    swept = await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert swept == Swept(jobs=0, audit_entries=0, runs=1, objects=2)
    assert kept(files) == [f"runs/{young}/x4/1.json"]
    assert (raw_key(setup, old), raw_key(setup, young)) == (None, f"runs/{young}/x4")
    assert garbage(setup) == []


async def test_a_frozen_document_s_runs_lose_their_raw_answers_like_any(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    # its statements stay as they were frozen; the answers they were read from are evidence for a while
    run = add_ended_run(setup, made["document"], ended_days_ago=31)
    keep_answers(files, run, 1)
    setup.execute(
        "UPDATE document SET iri = 'https://example.org/doc/de/amt/lehrplan/2024', frozen_at = now()"
        " WHERE id = %s",
        (made["document"],),
    )

    swept = await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert (swept.runs, swept.objects) == (1, 1)
    assert kept(files) == []
    assert raw_key(setup, run) is None


async def test_the_ledger_s_rows_are_never_swept(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    # the budget is the lifetime sum of the bookings: taking one away with its job would fill it up again
    account = made["owner"]
    await set_quota(connection, account, token_limit=100_000, page_limit=50)
    job = add_job(setup, ended_days_ago=400)
    add_usage(setup, account, job)
    add_usage(setup, account, job, estimated=True, requests=0, unanswered_requests=1)
    setup.execute(
        "INSERT INTO conversion_usage (conversion_id, account_id, engine, pages, billable)"
        " VALUES (%s, %s, 'docling', 7, true)",
        (made["conversion"], account),
    )
    before = await usage_of(connection, account)

    swept = await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert swept.jobs == 1 and job not in job_ids(setup)
    assert await usage_of(connection, account) == before
    assert before.tokens_spent > 0 and before.pages_spent == 7
    counted = setup.execute(
        "SELECT (SELECT count(*) FROM llm_usage WHERE job_id = %s), (SELECT count(*) FROM conversion_usage)",
        (job,),
    ).fetchone()
    assert counted == (2, 1)


class BreaksOnce(FileSystemStorage):
    """A store whose second deletion fails, as a service may refuse one."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.deleted = 0

    def delete(self, key: str) -> None:
        self.deleted += 1
        if self.deleted == 2:
            raise OSError("the store refused (invented)")
        super().delete(key)


async def test_a_sweep_broken_between_marking_and_deleting_is_finished_by_the_next(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any], tmp_path: Path
) -> None:
    breaking = BreaksOnce(tmp_path / "objects")
    run = add_ended_run(setup, made["document"], ended_days_ago=31)
    keep_answers(breaking, run, 1, 2, 3)

    with pytest.raises(OSError, match="invented"):
        await sweep(connection, AsyncStorage(breaking), POLICY, dry_run=False)
    assert raw_key(setup, run) is None  # the run says so already
    assert garbage(setup) == [f"runs/{run}/x4/"]  # and the place stays noted
    assert len(kept(breaking)) == 2

    swept = await sweep(
        connection, AsyncStorage(FileSystemStorage(tmp_path / "objects")), POLICY, dry_run=False
    )

    assert swept == Swept(jobs=0, audit_entries=0, runs=0, objects=2)
    assert kept(breaking) == []
    assert garbage(setup) == []


async def test_a_garbage_entry_naming_one_object_takes_that_object_alone(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, files: FileSystemStorage
) -> None:
    # a file no entry holds is noted by its own key (sources/<sha256>), not as a prefix
    gone, beside = "sources/" + "ab" * 32, "sources/" + "ab" * 32 + "cd"
    files.put(gone, b"%PDF")
    files.put(beside, b"%PDF")
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES (%s), ('exports/none/')", (gone,))

    swept = await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert swept.objects == 1
    assert sorted(files.list("sources/")) == [beside]
    assert garbage(setup) == []


async def test_a_place_already_empty_is_forgotten(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, files: FileSystemStorage
) -> None:
    # another sweep, or the request that noted it, emptied it first: nothing missing is an error
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES ('runs/none/x4/'), ('sources/none')")

    assert (await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)).objects == 0
    assert garbage(setup) == []


async def test_a_dry_run_counts_and_changes_nothing(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    job = add_job(setup, ended_days_ago=100)
    setup.execute("INSERT INTO audit_log (at, action) VALUES (now() - interval '400 days', 'account.create')")
    run = add_ended_run(setup, made["document"], ended_days_ago=40)
    keep_answers(files, run, 1, 2)
    files.put("exports/old/mem.ttl", b"@prefix")
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES ('exports/old/')")
    expected = Swept(jobs=1, audit_entries=1, runs=1, objects=3)

    assert await sweep(connection, AsyncStorage(files), POLICY, dry_run=True) == expected

    assert job_ids(setup) == {job}
    assert setup.execute("SELECT count(*) FROM audit_log").fetchone() == (1,)
    assert raw_key(setup, run) == f"runs/{run}/x4"
    assert garbage(setup) == ["exports/old/"]
    assert len(kept(files)) == 2 and files.exists("exports/old/mem.ttl")
    assert await sweep(connection, AsyncStorage(files), POLICY, dry_run=False) == expected


async def test_a_sweep_while_another_holds_the_lock_takes_nothing(
    database_url: str,
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    files: FileSystemStorage,
) -> None:
    job = add_job(setup)
    with psycopg.connect(database_url, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))

        with pytest.raises(SweepBusy):
            await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)
    assert job_ids(setup) == {job}
    assert (await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)).jobs == 1
    # the lock goes with the sweep, its session still open: another session's sweep takes it
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as later:
        assert (await sweep(later, AsyncStorage(files), POLICY, dry_run=False)).jobs == 0


class GoneMeanwhile(FileSystemStorage):
    """A store whose listing names an object another process deletes before the sweep does."""

    def list(self, prefix: str) -> Iterator[str]:
        return iter([*super().list(prefix), prefix + "9.json"])


async def test_an_object_gone_meanwhile_counts_as_taken_by_another(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any], tmp_path: Path
) -> None:
    store = GoneMeanwhile(tmp_path / "objects")
    run = add_ended_run(setup, made["document"], ended_days_ago=31)
    keep_answers(store, run, 1)

    swept = await sweep(connection, AsyncStorage(store), POLICY, dry_run=False)

    assert swept.objects == 1  # its own deletion; the other's is not counted twice
    assert garbage(setup) == []


def run_command(
    url: str, store: Path, *arguments: str, log_format: str = "json"
) -> subprocess.CompletedProcess[str]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": url, "STORAGE_DIR": str(store), "LOG_FORMAT": log_format}
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
    assert json.loads(lines[0]) == {"jobs": 1, "audit_entries": 1, "runs": 1, "objects": 1}
    for told in (done.stdout, done.stderr):
        assert str(run) not in told and str(made["document"]) not in told
        assert "runs/" not in told and "Erdkunde" not in told
    assert (raw_key(setup, run) is None) is (arguments == [])


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
