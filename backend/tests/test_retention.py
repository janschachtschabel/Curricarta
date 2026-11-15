"""The sweep (app/retention.py ``sweep``): it takes what is past its time from the database and empties the
places noted for the store, one sweep at a time; never a booking of the ledger. A failing database step
leaves the others and the store's part to run. The store's doubles: test_retention_store.py; the command:
test_retention_command.py."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.db.migrate import migrate
from app.db.retention import LOCK_KEY
from app.retention import Policy, SweepBusy, Swept, _cause, sweep
from app.usage.ledger import set_quota, usage_of
from tests.db.l1 import add_conversion, add_document, seed_vocabulary
from tests.db.retention_rows import add_ended_run, add_job, add_usage, garbage, job_ids, raw_key

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

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


async def test_a_database_part_that_fails_still_leaves_the_noted_places_emptied(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, files: FileSystemStorage
) -> None:
    # the database refuses the audit's deletion for good: the places noted before are emptied all the same
    refuse_deleting(setup, "audit_log")
    setup.execute("INSERT INTO audit_log (at, action) VALUES (now() - interval '400 days', 'account.create')")
    files.put("exports/old/mem.ttl", b"@prefix")
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES ('exports/old/')")

    with pytest.raises(psycopg.errors.RaiseException, match="refused"):
        await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert not files.exists("exports/old/mem.ttl")
    assert garbage(setup) == []
    assert setup.execute("SELECT count(*) FROM audit_log").fetchone() == (1,)


def refuse_deleting(setup: psycopg.Connection, table: str) -> None:
    """The database refuses every deletion from ``table`` for good, as a lasting failure would."""
    setup.execute(
        "CREATE OR REPLACE FUNCTION refuse() RETURNS trigger LANGUAGE plpgsql"
        " AS $$ BEGIN RAISE EXCEPTION 'refused'; END $$"
    )
    setup.execute(f"CREATE TRIGGER refused BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION refuse()")


async def test_a_failing_step_of_the_database_part_leaves_the_others_to_run(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    # the jobs' step fails for good: the audit's and the raw answers' still run, and the error comes after
    refuse_deleting(setup, "job")
    job = add_job(setup)
    setup.execute("INSERT INTO audit_log (at, action) VALUES (now() - interval '400 days', 'account.create')")
    run = add_ended_run(setup, made["document"], ended_days_ago=31)
    keep_answers(files, run, 1)

    with pytest.raises(psycopg.errors.RaiseException, match="refused"):
        await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert job_ids(setup) == {job}
    assert setup.execute("SELECT count(*) FROM audit_log").fetchone() == (0,)
    assert raw_key(setup, run) is None and kept(files) == []


class ListingFails(FileSystemStorage):
    def list(self, prefix: str) -> Iterator[str]:
        raise OSError("the store refused (invented)")


async def test_when_both_parts_fail_the_database_s_error_is_the_one_raised(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, tmp_path: Path
) -> None:
    refuse_deleting(setup, "audit_log")
    setup.execute("INSERT INTO audit_log (at, action) VALUES (now() - interval '400 days', 'account.create')")
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES ('exports/old/')")

    with pytest.raises(psycopg.errors.RaiseException, match="refused") as raised:
        await sweep(connection, AsyncStorage(ListingFails(tmp_path / "objects")), POLICY, dry_run=False)

    assert isinstance(raised.value.__cause__, OSError)  # the store's failure, kept beside it
    assert _cause(raised.value) == "refused"  # what the command's one log line says


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


async def test_a_place_the_store_refuses_is_passed_by_and_the_others_are_emptied(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    # a device's name passes the CHECK, the store refuses it as a key for good: noted first, it stops nothing
    setup.execute(
        "INSERT INTO storage_garbage (prefix, noted_at) VALUES ('runs/con/', now() - interval '1 day'),"
        " ('sources/nul.json', now() - interval '1 day')"
    )
    run = add_ended_run(setup, made["document"], ended_days_ago=31)
    keep_answers(files, run, 1)

    swept = await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert (swept.objects, swept.refused) == (1, 2)
    assert kept(files) == []
    assert garbage(setup) == ["runs/con/", "sources/nul.json"]  # left noted, for the operator to look at
    assert (await sweep(connection, AsyncStorage(files), POLICY, dry_run=True)).refused == 2


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
