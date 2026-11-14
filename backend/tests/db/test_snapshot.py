"""The connection a measuring command reads with (app/db/snapshot.py): one snapshot of the database for the
whole command, a job writing meanwhile unseen, and no write at all."""

import psycopg
import pytest

from app.db.migrate import migrate
from app.db.snapshot import snapshot

pytestmark = [pytest.mark.pg, pytest.mark.anyio]


async def test_a_snapshot_refuses_every_write(database_url: str) -> None:
    migrate(database_url)

    async with snapshot(database_url) as connection:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            await connection.execute("INSERT INTO account (id, name) VALUES (gen_random_uuid(), 'x')")


async def test_a_snapshot_sees_nothing_written_after_it_began(database_url: str) -> None:
    migrate(database_url)
    async with (
        await psycopg.AsyncConnection.connect(database_url, autocommit=True) as writer,
        snapshot(database_url) as connection,
    ):
        before = await (await connection.execute("SELECT count(*) FROM account")).fetchone()
        await writer.execute("INSERT INTO account (id, name) VALUES (gen_random_uuid(), 'meanwhile')")
        after = await (await connection.execute("SELECT count(*) FROM account")).fetchone()

    assert before == after
