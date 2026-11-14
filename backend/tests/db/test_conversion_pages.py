"""The pages of an engine that costs are booked under the lock of the account's quota row (audit 2026-11-14):
two conversions done at once each sum what the other booked, and one that would pass the limit is refused
(PagesSpent) with nothing written - not the conversion done, no block, no page."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import psycopg
import pytest

from app.conversion.base import Conversion
from app.core.ids import new_id
from app.db.accounts import create_account
from app.db.conversions import PagesSpent, lock_conversion, record_conversion, start_conversion
from app.db.migrate import migrate
from app.jobs.queue import enqueue
from tests.db.test_conversions import a_file, converted
from tests.support import lock_held

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

UNSET = object()


@pytest.fixture
async def connection(database_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    migrate(database_url)
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as opened:
        yield opened


async def an_account(connection: psycopg.AsyncConnection, page_limit: int | object | None) -> UUID:
    """An account with a quota of ``page_limit`` pages (None: no limit), or without a quota (UNSET)."""
    account = await create_account(connection, f"Konto {new_id().hex[:8]}", ["nutzer"])
    if page_limit is not UNSET:
        await connection.execute(
            "INSERT INTO quota (account_id, page_limit) VALUES (%s, %s)", (account, page_limit)
        )
    return account


async def started(connection: psycopg.AsyncConnection, account: UUID) -> tuple[UUID, UUID]:
    """A conversion of a new file by Docling asked for by ``account``: (conversion, job)."""
    file_id, conversion_id = await a_file(connection), new_id()
    async with connection.transaction():
        await lock_conversion(connection, file_id, "docling")
        job_id = await enqueue(
            connection, "source.convert_docling", "test", {"conversion_id": str(conversion_id)}
        )
        await start_conversion(
            connection,
            conversion_id,
            source_file_id=file_id,
            engine="docling",
            account_id=account,
            job_id=job_id,
        )
    return conversion_id, job_id


def of_pages(pages: int) -> Conversion:
    return converted().model_copy(
        update={"engine": "docling", "pages": pages, "printed_pages": (None,) * pages}
    )


async def written(connection: psycopg.AsyncConnection, conversion_id: UUID) -> tuple[str, int, int]:
    """The conversion's status, its blocks and the pages booked for it."""
    cursor = await connection.execute(
        "SELECT status, (SELECT count(*) FROM document_block WHERE conversion_id = c.id),"
        " (SELECT coalesce(sum(pages), 0) FROM conversion_usage WHERE conversion_id = c.id)"
        " FROM conversion c WHERE id = %s",
        (conversion_id,),
    )
    found = await cursor.fetchone()
    assert found is not None
    return found[0], found[1], found[2]


async def booked(connection: psycopg.AsyncConnection, account: UUID) -> int:
    cursor = await connection.execute(
        "SELECT coalesce(sum(pages), 0) FROM conversion_usage WHERE account_id = %s AND billable", (account,)
    )
    found = await cursor.fetchone()
    assert found is not None
    return int(found[0])


async def test_of_two_conversions_booked_at_once_past_the_pages_left_one_is_refused(
    database_url: str, connection: psycopg.AsyncConnection
) -> None:
    account = await an_account(connection, page_limit=10)
    conversions = [await started(connection, account) for _ in range(2)]

    async def record(at: psycopg.AsyncConnection, conversion_id: UUID, job_id: UUID) -> bool | str:
        try:
            return await record_conversion(at, conversion_id, job_id, of_pages(8), "", billable=True)
        except PagesSpent:
            return "refused"

    async with (
        await psycopg.AsyncConnection.connect(database_url, autocommit=True) as first,
        await psycopg.AsyncConnection.connect(database_url, autocommit=True) as second,
    ):
        # both reach the quota's row (the database's only one) while another session holds it: let go,
        # they take it one by one
        with lock_held(database_url, "SELECT 1 FROM quota FOR UPDATE", at_most_s=15):
            recording = [
                asyncio.create_task(record(at, *made))
                for at, made in zip((first, second), conversions, strict=True)
            ]
            await until_waiting_or_done(
                connection, [first.info.backend_pid, second.info.backend_pid], recording
            )
        outcomes = await asyncio.gather(*recording)

    assert sorted(map(str, outcomes)) == ["True", "refused"]
    assert await booked(connection, account) == 8
    refused = conversions[outcomes.index("refused")][0]
    assert await written(connection, refused) == ("pending", 0, 0)  # rolled back whole


async def until_waiting_or_done(
    look: psycopg.AsyncConnection, pids: list[int], tasks: list[asyncio.Task[bool | str]]
) -> None:
    """Until each backend ``pids`` waits on a lock or its task is done; AssertionError after 10 s."""
    for _ in range(200):
        cursor = await look.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(%s) AND wait_event_type = 'Lock'", (pids,)
        )
        found = await cursor.fetchone()
        waiting = found[0] if found else 0
        if waiting + sum(task.done() for task in tasks) == len(tasks):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the bookings neither waited nor ended")


async def test_an_account_without_a_quota_books_no_page_that_costs(
    connection: psycopg.AsyncConnection,
) -> None:
    account = await an_account(connection, page_limit=UNSET)
    conversion_id, job_id = await started(connection, account)

    with pytest.raises(PagesSpent):
        await record_conversion(connection, conversion_id, job_id, of_pages(1), "", billable=True)

    assert await written(connection, conversion_id) == ("pending", 0, 0)


async def test_an_engine_that_costs_nothing_books_whatever_the_quota(
    connection: psycopg.AsyncConnection,
) -> None:
    account = await an_account(connection, page_limit=0)
    conversion_id, job_id = await started(connection, account)

    assert await record_conversion(connection, conversion_id, job_id, of_pages(8), "", billable=False)

    assert await written(connection, conversion_id) == ("done", 3, 8)


async def test_a_limit_of_none_books_any_number(connection: psycopg.AsyncConnection) -> None:
    account = await an_account(connection, page_limit=None)
    conversion_id, job_id = await started(connection, account)

    assert await record_conversion(connection, conversion_id, job_id, of_pages(5000), "", billable=True)

    assert await booked(connection, account) == 5000
