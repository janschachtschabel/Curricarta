"""The sweep and its store (app/retention.py): no transaction is open while the store is asked, a store
that fails between noting and emptying leaves the notes for the next sweep, an object gone meanwhile is
taken by another; the sweep leaves a connection without autocommit idle. Fixtures: tests/test_retention.py."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.retention import Swept, sweep
from tests.db.retention_rows import add_ended_run, add_job, garbage, raw_key
from tests.test_retention import POLICY, connection, files, keep_answers, kept, made, setup

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "files", "made", "setup"]  # the fixtures, from test_retention


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
    database_url: str,
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    tmp_path: Path,
) -> None:
    breaking = BreaksOnce(tmp_path / "objects")
    run = add_ended_run(setup, made["document"], ended_days_ago=31)
    keep_answers(breaking, run, 1, 2, 3)

    with pytest.raises(OSError, match="invented"):
        await sweep(connection, AsyncStorage(breaking), POLICY, dry_run=False)
    assert raw_key(setup, run) is None  # the run says so already
    assert garbage(setup) == [f"runs/{run}/x4/"]  # and the place stays noted
    assert len(kept(breaking)) == 2

    # from another session, its own still open: the broken sweep let go of the lock
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as later:
        swept = await sweep(
            later, AsyncStorage(FileSystemStorage(tmp_path / "objects")), POLICY, dry_run=False
        )

    assert swept == Swept(jobs=0, audit_entries=0, runs=0, objects=2)
    assert kept(breaking) == []
    assert garbage(setup) == []


@pytest.mark.parametrize("dry_run", [False, True], ids=["sweep", "dry-run"])
async def test_a_sweep_on_a_connection_without_autocommit_leaves_no_transaction_open(
    database_url: str, setup: psycopg.Connection, files: FileSystemStorage, dry_run: bool
) -> None:
    # a pool's connection: the sweep needs no autocommit, only no transaction open when it begins
    add_job(setup)
    async with await psycopg.AsyncConnection.connect(database_url) as pooled:
        await sweep(pooled, AsyncStorage(files), POLICY, dry_run=dry_run)

        assert pooled.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


class IdleOnly(FileSystemStorage):
    """A store that fails a call made while the sweep's session holds a transaction open."""

    def __init__(self, root: Path, connection: psycopg.AsyncConnection) -> None:
        super().__init__(root)
        self.connection = connection
        self.calls = 0

    def _idle(self) -> None:
        self.calls += 1
        assert self.connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    def list(self, prefix: str) -> Iterator[str]:
        self._idle()
        return super().list(prefix)

    def exists(self, key: str) -> bool:
        self._idle()
        return super().exists(key)

    def delete(self, key: str) -> None:
        self._idle()
        super().delete(key)


@pytest.mark.parametrize("dry_run", [False, True], ids=["sweep", "dry-run"])
async def test_no_transaction_is_open_while_the_store_is_asked(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    tmp_path: Path,
    dry_run: bool,
) -> None:
    store = IdleOnly(tmp_path / "objects", connection)
    run = add_ended_run(setup, made["document"], ended_days_ago=31)
    keep_answers(store, run, 1, 2)
    store.put("sources/" + "ab" * 32, b"%PDF")
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES (%s)", ("sources/" + "ab" * 32,))

    swept = await sweep(connection, AsyncStorage(store), POLICY, dry_run=dry_run)

    assert swept.objects == 3
    assert store.calls >= 2


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


class EndsTheSession(FileSystemStorage):
    """A store that fails after the sweep's session was ended, as a database restart meanwhile would."""

    def __init__(self, root: Path, database_url: str, pid: int) -> None:
        super().__init__(root)
        self.database_url, self.pid = database_url, pid

    def list(self, prefix: str) -> Iterator[str]:
        with psycopg.connect(self.database_url, autocommit=True) as other:
            other.execute("SELECT pg_terminate_backend(%s)", (self.pid,))
        raise OSError("the store refused (invented)")


async def test_a_failed_unlock_hides_not_the_sweep_s_own_error(
    database_url: str, setup: psycopg.Connection, connection: psycopg.AsyncConnection, tmp_path: Path
) -> None:
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES ('exports/old/')")
    store = EndsTheSession(tmp_path / "objects", database_url, connection.info.backend_pid)

    with pytest.raises(OSError, match="invented"):
        await sweep(connection, AsyncStorage(store), POLICY, dry_run=False)
