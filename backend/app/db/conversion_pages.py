"""The pages of an engine that costs, held to what the asker has left as a conversion is booked
(app/db/conversions.py, ``record_conversion``; audit 2026-11-14).

The check takes the asker's quota row (FOR UPDATE) in the booking's transaction, after the conversion's row
and directly before the booking, so it holds the row for two statements: the account's model requests take
the same row (app/usage/ledger.py, ``reserve``), which takes it alone - no cycle. The sum after the lock sees
what another booking committed meanwhile only under read committed, which the check asks for.
"""

from uuid import UUID

import psycopg

# No row is a limit of nothing, a row's NULL no limit
_PAGE_LIMIT = "SELECT page_limit FROM quota WHERE account_id = %s FOR UPDATE"
_PAGES_SPENT = "SELECT coalesce(sum(pages), 0) FROM conversion_usage WHERE account_id = %s AND billable"


class PagesSpent(Exception):
    """The asker has fewer pages left of an engine that costs than the conversion holds: none is written."""


async def hold_to_pages_left(
    connection: psycopg.AsyncConnection, account_id: UUID | None, pages: int
) -> None:
    """PagesSpent where ``pages`` more pass what ``account_id`` has left; in the caller's transaction,
    whose rollback then takes the conversion along."""
    await connection.execute("SELECT read_committed_alone('a booking of pages')")
    cursor = await connection.execute(_PAGE_LIMIT, (account_id,))
    row = await cursor.fetchone()
    limit = 0 if row is None else row[0]
    if limit is None:
        return
    cursor = await connection.execute(_PAGES_SPENT, (account_id,))
    spent = await cursor.fetchone()
    assert spent is not None  # noqa: S101 - an aggregate always has its row
    if int(spent[0]) + pages > limit:
        raise PagesSpent(f"{pages} pages to book, {max(0, limit - int(spent[0]))} left")
