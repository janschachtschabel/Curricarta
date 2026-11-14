"""The connection the measuring commands read with (plan H-3: the usage report, the replay, the gold
report): one transaction, REPEATABLE READ and READ ONLY - one snapshot of the database for the whole
command, whatever a job writes meanwhile, and no write at all."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg

from app.db.pool import CONNECTION_OPTIONS


@asynccontextmanager
async def snapshot(url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    """A connection to ``url`` inside a transaction that reads one snapshot and refuses every write."""
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True, **CONNECTION_OPTIONS) as connection,
        connection.transaction(),
    ):
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        yield connection
