"""The pool's sessions carry the server's limits (app/db/pool.py, ``session_options``): a transaction idle
past DB_IDLE_IN_TRANSACTION_TIMEOUT_S is ended and its locks go, a statement past DB_STATEMENT_TIMEOUT_S is
cancelled where one is set, and the server notices a client gone silent by its own keepalives. The connections
of the commands (the migration, the licence amendment) take none of them: they wait for their lock as long as
it takes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from app.db.pool import CONNECTION_OPTIONS, create_pool, worker_pool
from app.jobs.queue import Job, claim, enqueue, hold_lease, requeue_expired
from app.jobs.worker import Worker
from tests.support import make_settings

pytestmark = [pytest.mark.pg, pytest.mark.anyio]


@asynccontextmanager
async def pool_of(
    url: str, *, statement_timeout: bool = False, **settings: object
) -> AsyncIterator[AsyncConnectionPool]:
    pool = create_pool(make_settings(database_url=url, **settings), statement_timeout=statement_timeout)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
def url(database_url: str) -> str:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("CREATE TABLE probe (id int PRIMARY KEY)")
        connection.execute("INSERT INTO probe VALUES (1)")
    return database_url


async def test_a_session_idle_in_a_transaction_past_its_time_is_ended_and_lets_its_locks_go(url: str) -> None:
    async with pool_of(url, db_idle_in_transaction_timeout_s=1) as pool, pool.connection() as held:
        await held.execute("SELECT id FROM probe WHERE id = 1 FOR UPDATE")
        await asyncio.sleep(1.5)

        with psycopg.connect(url) as other:
            taken = other.execute("SELECT id FROM probe WHERE id = 1 FOR UPDATE NOWAIT").fetchone()
        # the server ended the first session: its next word meets the error the server left
        with pytest.raises(psycopg.errors.IdleInTransactionSessionTimeout):
            await held.execute("SELECT 1")

    assert taken == (1,)


async def test_a_transaction_that_keeps_working_is_not_ended(url: str) -> None:
    async with pool_of(url, db_idle_in_transaction_timeout_s=2) as pool, pool.connection() as working:
        for _ in range(7):  # 2.8 s in all, past the timeout, never idle for 2 s
            await working.execute("UPDATE probe SET id = id WHERE id = 1")
            await asyncio.sleep(0.4)
        await working.commit()


async def test_a_statement_past_its_time_is_cancelled_only_where_one_is_set(url: str) -> None:
    async with (
        pool_of(url, db_statement_timeout_s=1, statement_timeout=True) as limited,
        limited.connection() as connection,
    ):
        with pytest.raises(psycopg.errors.QueryCanceled):
            await connection.execute("SELECT pg_sleep(1.5)")
    async with pool_of(url) as unlimited, unlimited.connection() as connection:
        await connection.execute("SELECT pg_sleep(1.5)")


async def test_a_pool_not_asked_for_the_statement_timeout_takes_none_whatever_is_set(url: str) -> None:
    # the safe side for a caller that forgets the flag: no step of its is cancelled behind a lock
    pool = create_pool(make_settings(database_url=url, db_statement_timeout_s=1))
    await pool.open(wait=True)
    try:
        async with pool.connection() as connection:
            await connection.execute("SELECT pg_sleep(1.5)")
    finally:
        await pool.close()


async def test_the_server_notices_a_client_gone_silent(url: str) -> None:
    # over TCP, as the test server is reached; over a Unix socket the server has no keepalives to set
    async with pool_of(url) as pool, pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT current_setting('tcp_keepalives_idle'), current_setting('tcp_keepalives_interval'),"
            " current_setting('tcp_keepalives_count')"
        )
        found = await cursor.fetchone()

    assert found == ("30", "10", "3")


def test_the_migration_s_connection_keeps_waiting_for_its_lock() -> None:
    # the commands connect with CONNECTION_OPTIONS: a migration waits for the lock of another as long as it
    # runs (tests/db/test_migrate.py), and no session timeout of the pool's may end it meanwhile
    assert "options" not in CONNECTION_OPTIONS


async def settings_of(pool: AsyncConnectionPool, *names: str) -> tuple[str, ...]:
    async with pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT array_agg(current_setting(n) ORDER BY o)"
            " FROM unnest(%s::text[]) WITH ORDINALITY AS t(n, o)",
            (list(names),),
        )
        found = await cursor.fetchone()
    assert found is not None
    return tuple(found[0])


async def test_the_options_of_the_database_url_stay_beside_the_pool_s(url: str) -> None:
    # an operator's own (a schema of its own on a shared server): the commands keep them, so must the pool
    own = make_conninfo(url, options="-c search_path=elsewhere,public -c statement_timeout=9000")
    async with pool_of(own, db_statement_timeout_s=1, statement_timeout=True) as pool:
        found = await settings_of(
            pool, "search_path", "statement_timeout", "idle_in_transaction_session_timeout"
        )

    # the pool's come after the URL's: on the same parameter the pool's win
    assert found == ("elsewhere,public", "1s", "5min")


async def test_without_timeouts_the_pool_sends_no_options_of_its_own(url: str) -> None:
    # the way behind a pooler that refuses options at the start of a session: the values come from the role
    plain = create_pool(make_settings(database_url=url, db_idle_in_transaction_timeout_s=0))
    own = make_conninfo(url, options="-c search_path=elsewhere,public")
    async with pool_of(own, db_idle_in_transaction_timeout_s=0) as kept:
        found = await settings_of(kept, "search_path", "tcp_keepalives_idle")

    assert isinstance(plain.kwargs, dict) and "options" not in plain.kwargs
    assert found[0] == "elsewhere,public"
    assert found[1] != "30"  # the server's own keepalives, none of the pool's


async def test_the_worker_s_pool_never_cancels_a_statement(url: str) -> None:
    # set for every container by mistake, the statement timeout would cancel a heartbeat waiting behind the
    # lease and a booking waiting for the quota row: each a paid retry
    pool = worker_pool(make_settings(database_url=url, db_statement_timeout_s=1))
    await pool.open(wait=True)
    try:
        found = await settings_of(
            pool, "statement_timeout", "idle_in_transaction_session_timeout", "application_name"
        )
    finally:
        await pool.close()

    assert found == ("0", "5min", "curricarta-worker")


async def test_a_dead_worker_s_job_is_handed_back_once_its_session_is_ended(url: str) -> None:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as sweeper:
        await enqueue(sweeper, "test.work", "account-a", {})
        job = await claim(sweeper, "gone", ["test.work"], 1)
        assert job is not None
        async with pool_of(url, db_idle_in_transaction_timeout_s=1) as pool:
            # the attempt writes under its lease and then hangs: the job's row stays locked, and a sweep
            # passes it by while the session lives. Should the attempt wake, its commit meets the end
            with pytest.raises(psycopg.errors.IdleInTransactionSessionTimeout):
                async with pool.connection() as stuck:
                    await hold_lease(stuck, job)
                    await asyncio.sleep(2.5)

                    handed_back = await requeue_expired(sweeper)

    assert handed_back == ["queued"]


async def test_a_job_whose_session_was_ended_is_tried_again(url: str) -> None:
    # what the worker makes of it: a handler's error like any other, not a database away for a moment
    async def idles(job: Job) -> None:
        async with pool.connection() as connection:
            await connection.execute("SELECT id FROM probe WHERE id = 1 FOR UPDATE")
            await asyncio.sleep(1.5)
            await connection.execute("SELECT 1")

    async with pool_of(url, db_idle_in_transaction_timeout_s=1) as pool:
        async with pool.connection() as connection:
            job_id = await enqueue(connection, "test.work", "account-a", {}, max_attempts=3)
        await Worker(pool, {"test.work": idles}, owner="w1").run_once()
        async with pool.connection() as connection:
            cursor = await connection.execute("SELECT status, error FROM job WHERE id = %s", (job_id,))
            found = await cursor.fetchone()

    assert found == ("queued", {"code": "handler_error", "message": "IdleInTransactionSessionTimeout"})
