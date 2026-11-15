"""What the retention takes from the database (app/db/retention.py): ended jobs past their time but the
one that still says how a document's work ended, a conversion's waiting or a reservation's; audit entries
past their time; the raw answers of runs past theirs, noted for the store. Never a booking of the ledger.
Rows another session holds are passed by and taken at the next sweep."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest

from app.db.migrate import migrate
from app.db.retention import (
    BATCH,
    LOCK_KEY,
    drop_ended_jobs,
    drop_old_audit,
    forget_garbage,
    garbage,
    mark_old_raw_answers,
    take_lock,
)
from app.jobs.queue import last_jobs
from tests.db.l1 import add_conversion, add_document, seed_vocabulary
from tests.db.retention_rows import (
    add_ended_run,
    add_job,
    add_reservation,
    job_ids,
    raw_key,
)
from tests.db.retention_rows import (
    garbage as noted,
)

pytestmark = [pytest.mark.pg, pytest.mark.anyio]


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


async def test_an_ended_job_past_its_time_goes_and_a_younger_one_stays(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection
) -> None:
    old = {add_job(setup, status=status) for status in ("done", "failed", "cancelled")}
    young = add_job(setup, ended_days_ago=89)

    assert await drop_ended_jobs(connection, 90) == 3

    assert job_ids(setup) == {young}
    assert old.isdisjoint(job_ids(setup))


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_a_waiting_or_running_job_never_goes_however_old(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, status: str
) -> None:
    job = add_job(setup, status=status, ended_days_ago=3000)
    # its status says it has not ended, whatever time a writer left beside it
    setup.execute("UPDATE job SET finished_at = created_at WHERE id = %s", (job,))

    assert await drop_ended_jobs(connection, 1) == 0
    assert job_ids(setup) == {job}


async def test_the_latest_job_of_a_key_stays_so_its_document_still_says_how_it_ended(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection
) -> None:
    key = "extract.run:document"
    add_job(setup, key=key, ended_days_ago=300)
    latest = add_job(setup, status="failed", key=key, ended_days_ago=200, code="run_over_budget")

    assert await drop_ended_jobs(connection, 90) == 1

    found = await last_jobs(connection, [key])
    assert (found[key].id, found[key].status, found[key].error_code) == (latest, "failed", "run_over_budget")
    assert job_ids(setup) == {latest}


async def test_a_job_a_pending_conversion_waits_for_stays(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    # a conversion asked again waits on its job; done, it no longer needs it
    job, done = add_job(setup), add_job(setup)
    setup.execute(
        "UPDATE conversion SET status = 'pending', finished_at = NULL, pages = NULL, job_id = %s"
        " WHERE id = %s",
        (job, made["conversion"]),
    )
    other = add_conversion(setup, digest=b"\x02" * 32, owner=made["owner"])
    setup.execute("UPDATE conversion SET job_id = %s WHERE id = %s", (done, other["conversion"]))

    assert await drop_ended_jobs(connection, 90) == 1

    assert job_ids(setup) == {job}
    jobs = setup.execute("SELECT id, job_id FROM conversion ORDER BY id").fetchall()
    assert dict(jobs) == {made["conversion"]: job, other["conversion"]: None}


async def test_a_job_holding_a_reservation_stays(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    # booked as spent once a sweep of the worker finds it (app/usage/ledger.py book_left_behind): till then
    # the reservation is part of what the budget holds
    job = add_job(setup, status="failed")
    add_reservation(setup, made["owner"], job)

    assert await drop_ended_jobs(connection, 90) == 0
    assert job_ids(setup) == {job}


async def test_more_jobs_than_a_batch_all_go(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection
) -> None:
    for _ in range(5):
        add_job(setup)

    assert await drop_ended_jobs(connection, 90, batch=2) == 5
    assert job_ids(setup) == set()
    assert BATCH == 1000


async def test_a_job_another_session_holds_is_passed_by_and_taken_next_time(
    database_url: str, setup: psycopg.Connection, connection: psycopg.AsyncConnection
) -> None:
    # a job ending as the sweep looks, or a reservation being booked for it: the sweep waits for neither
    held, free = add_job(setup), add_job(setup)
    with psycopg.connect(database_url) as other:
        other.execute("SELECT FROM job WHERE id = %s FOR KEY SHARE", (held,))

        assert await asyncio.wait_for(drop_ended_jobs(connection, 90), timeout=10) == 1
        assert job_ids(setup) == {held}
        other.rollback()

    assert await drop_ended_jobs(connection, 90) == 1
    assert job_ids(setup) == set()
    assert free not in job_ids(setup)


async def test_a_reservation_booked_while_the_sweep_looks_keeps_its_job(
    database_url: str, setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    job = add_job(setup, status="failed")
    with psycopg.connect(database_url) as other:
        add_reservation(other, made["owner"], job)  # not committed: it holds the job's key

        assert await asyncio.wait_for(drop_ended_jobs(connection, 90), timeout=10) == 0
        other.commit()

    assert await drop_ended_jobs(connection, 90) == 0
    assert job_ids(setup) == {job}


async def test_an_audit_entry_past_its_time_goes(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection
) -> None:
    for days in (400, 366, 364):
        setup.execute(
            "INSERT INTO audit_log (at, action) VALUES (now() - %s * interval '1 day', 'account.create')",
            (days,),
        )

    assert await drop_old_audit(connection, 365, batch=1) == 2

    left = setup.execute("SELECT round(extract(epoch FROM now() - at) / 86400) FROM audit_log").fetchall()
    assert [int(row[0]) for row in left] == [364]


async def test_a_run_s_raw_answers_past_their_time_are_noted_for_the_store_and_the_run_says_so(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    old = add_ended_run(setup, made["document"], ended_days_ago=31)
    young = add_ended_run(setup, made["document"], ended_days_ago=29)

    assert await mark_old_raw_answers(connection, 30) == 1

    assert raw_key(setup, old) is None
    assert raw_key(setup, young) == f"runs/{young}/x4"
    assert noted(setup) == [f"runs/{old}/x4/"]
    assert await garbage(connection) == [f"runs/{old}/x4/"]
    await forget_garbage(connection, f"runs/{old}/x4/")
    assert noted(setup) == []


async def test_more_runs_than_a_batch_are_all_noted(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    runs = [add_ended_run(setup, made["document"], ended_days_ago=40) for _ in range(5)]

    assert await mark_old_raw_answers(connection, 30, batch=2) == 5
    assert noted(setup) == sorted(f"runs/{run}/x4/" for run in runs)
    assert await garbage(connection, batch=2) == sorted(f"runs/{run}/x4/" for run in runs)[:2]


async def test_a_run_left_unended_loses_its_raw_answers_once_its_job_is_over(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    # a run cancelled with its attempt never ends: its start counts, unless its job still runs
    over, running = add_job(setup), add_job(setup, status="running")
    left = add_ended_run(setup, made["document"], ended_days_ago=40, job=over)
    still = add_ended_run(setup, made["document"], ended_days_ago=40, job=running)
    setup.execute("UPDATE extraction_run SET finished_at = NULL, outcome = NULL")

    assert await mark_old_raw_answers(connection, 30) == 1
    assert (raw_key(setup, left), raw_key(setup, still)) == (None, f"runs/{still}/x4")


async def test_a_time_of_nothing_keeps_everything(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    job = add_job(setup, ended_days_ago=3000)
    setup.execute(
        "INSERT INTO audit_log (at, action) VALUES (now() - interval '3000 days', 'account.create')"
    )
    run = add_ended_run(setup, made["document"], ended_days_ago=3000)

    assert await drop_ended_jobs(connection, 0) == 0
    assert await drop_old_audit(connection, 0) == 0
    assert await mark_old_raw_answers(connection, 0) == 0

    assert job_ids(setup) == {job}
    assert setup.execute("SELECT count(*) FROM audit_log").fetchone() == (1,)
    assert raw_key(setup, run) == f"runs/{run}/x4"


async def test_one_session_holds_the_sweep_s_lock_at_a_time(
    database_url: str, connection: psycopg.AsyncConnection
) -> None:
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as other:
        assert await take_lock(connection) is True
        assert await take_lock(other) is False
        await connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        assert await take_lock(other) is True
