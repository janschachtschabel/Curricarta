"""A file's object and the notes on it (app/db/deleting.py, app/emptying.py): the same bytes uploaded again
are never taken by the sweep of a note left from before - whichever comes first, the sweep's emptying or the
row written anew, the other waits for the file's lock -, a file no entry holds goes at the next sweep, and a
request emptying its places beside the nightly sweep takes each object once.
Fixtures: tests/test_retention.py."""

import asyncio
import threading
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from app.core.storage import FileSystemStorage, StorageNotConfigured
from app.core.storage_async import AsyncStorage
from app.db.deleting import drop_document
from app.db.sources import StoredFile, record_upload
from app.emptying import sweep_prefixes
from app.retention import Swept, sweep
from tests.db.l1 import add_conversion, add_run
from tests.db.retention_rows import add_job, garbage
from tests.support import waiting_on_a_lock
from tests.test_retention import POLICY, connection, files, keep_answers, kept, made, objects_root, setup

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "files", "made", "objects_root", "setup"]  # the fixtures, from test_retention

DIGEST = bytes.fromhex("cd" * 32)
KEY = f"sources/{DIGEST.hex()}"


def noted(setup: psycopg.Connection, files: FileSystemStorage, key: str = KEY) -> None:
    """The object of a file taken away, still in the store, its note waiting for the sweep."""
    files.put(key, b"%PDF")
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES (%s)", (key,))


async def uploaded(connection: psycopg.AsyncConnection, owner: uuid.UUID) -> None:
    """The row of an upload of the same bytes as app/api/sources.py writes it, in the caller's transaction."""
    await record_upload(
        connection,
        owner=owner,
        stored=StoredFile(DIGEST, 4, "application/pdf", KEY),
        file_name="plan.pdf",
        received_name="plan.pdf",
        title="Plan",
    )


class Holding(FileSystemStorage):
    """A store whose deletion waits until it is let go, saying when it began."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.began, self.go = threading.Event(), threading.Event()

    def delete(self, key: str) -> None:
        self.began.set()
        assert self.go.wait(10)
        super().delete(key)


async def test_a_row_written_while_the_sweep_empties_its_object_waits_and_then_finds_it_gone(
    database_url: str,
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    noted(setup, files)
    holding = Holding(files.root)
    sweeping = asyncio.create_task(sweep(connection, AsyncStorage(holding), POLICY, dry_run=False))
    assert await asyncio.to_thread(holding.began.wait, 10)

    async with (
        await psycopg.AsyncConnection.connect(database_url) as writer,
        await psycopg.AsyncConnection.connect(database_url, autocommit=True) as look,
        writer.transaction(),
    ):
        writing = asyncio.create_task(uploaded(writer, made["owner"]))
        await waiting_on_a_lock(look, writer.info.backend_pid)
        holding.go.set()
        swept = await sweeping
        await writing

    # the upload looks once its row stands, finds the object gone and stores it anew (app/api/sources.py)
    assert swept.objects == 1
    assert not files.exists(KEY)
    assert garbage(setup) == []


async def test_a_sweep_beside_a_row_written_for_the_same_bytes_waits_and_leaves_them(
    database_url: str,
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    noted(setup, files)

    async with (
        await psycopg.AsyncConnection.connect(database_url) as writer,
        await psycopg.AsyncConnection.connect(database_url, autocommit=True) as look,
    ):
        async with writer.transaction():
            await uploaded(writer, made["owner"])
            sweeping = asyncio.create_task(sweep(connection, AsyncStorage(files), POLICY, dry_run=False))
            await waiting_on_a_lock(look, connection.info.backend_pid)
        swept = await sweeping

    assert swept.objects == 0
    assert files.get(KEY) == b"%PDF"
    assert garbage(setup) == []


async def test_a_note_left_from_before_takes_no_bytes_a_row_names_again(
    database_url: str,
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    async with await psycopg.AsyncConnection.connect(database_url) as writer, writer.transaction():
        await uploaded(writer, made["owner"])
    noted(setup, files)  # a note written beside the row, as no request writes it: the sweep looks anyway

    assert (await sweep(connection, AsyncStorage(files), POLICY, dry_run=True)).objects == 0
    swept = await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert swept.objects == 0
    assert files.get(KEY) == b"%PDF"
    assert garbage(setup) == []


async def test_a_file_no_entry_holds_goes_at_the_next_sweep(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    # a request broken between taking its entry away and its file leaves the file to the sweep
    left = add_conversion(setup, DIGEST, made["owner"])
    setup.execute("DELETE FROM source WHERE id = %s", (left["source"],))
    files.put(KEY, b"%PDF")
    setup.execute(
        "INSERT INTO conversion_usage (conversion_id, account_id, engine, pages, billable)"
        " VALUES (%s, %s, 'pdfplumber', 2, false)",
        (left["conversion"], made["owner"]),
    )

    swept = await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert swept == Swept(files=1, objects=1)
    assert not files.exists(KEY)
    assert setup.execute("SELECT count(*) FROM source_file WHERE storage_key = %s", (KEY,)).fetchone() == (0,)
    assert setup.execute(
        "SELECT count(*) FROM conversion WHERE id = %s", (left["conversion"],)
    ).fetchone() == (0,)
    assert setup.execute("SELECT count(*) FROM conversion_usage").fetchone() == (1,)  # booked, it stays
    assert garbage(setup) == []


async def test_a_file_whose_conversion_waits_stays_until_it_has_ended(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    left = add_conversion(setup, DIGEST, made["owner"])
    setup.execute("DELETE FROM source WHERE id = %s", (left["source"],))
    setup.execute(
        "UPDATE conversion SET status = 'pending', pages = NULL, printed_pages = NULL, finished_at = NULL,"
        " job_id = %s WHERE id = %s",
        (add_job(setup, status="running"), left["conversion"]),
    )

    swept = await sweep(connection, AsyncStorage(files), POLICY, dry_run=False)

    assert swept.files == 0
    assert setup.execute("SELECT count(*) FROM source_file WHERE storage_key = %s", (KEY,)).fetchone() == (1,)


async def test_emptying_beside_the_nightly_sweep_takes_each_object_once(
    database_url: str,
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> None:
    # no lock between them: an object already gone counts as taken by the other, forgetting twice is nothing
    places = await _taken_document(setup, connection, made, files)

    async with AsyncConnectionPool(database_url, min_size=1, max_size=2, open=False) as pool:
        by_request, by_sweep = await asyncio.gather(
            sweep_prefixes(pool, AsyncStorage(files), places),
            sweep(connection, AsyncStorage(files), POLICY, dry_run=False),
        )

    assert by_request + by_sweep.objects == 3
    assert kept(files) == []
    assert garbage(setup) == []


async def _taken_document(
    setup: psycopg.Connection,
    connection: psycopg.AsyncConnection,
    made: dict[str, Any],
    files: FileSystemStorage,
) -> list[str]:
    run = add_run(setup, made["document"])
    keep_answers(files, run, 1, 2, 3)
    async with connection.transaction():
        places = await drop_document(connection, made["document"])
    assert places == [f"runs/{run}/", f"exports/{made['document']}/"]
    return places


async def test_a_file_s_object_is_never_emptied_beside_the_sweep(
    database_url: str, files: FileSystemStorage, setup: psycopg.Connection
) -> None:
    async with AsyncConnectionPool(database_url, min_size=1, max_size=1, open=False) as pool:
        with pytest.raises(ValueError, match="under the file's lock"):
            await sweep_prefixes(pool, AsyncStorage(files), [KEY])


async def test_a_document_already_gone_is_none_to_take_away(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection
) -> None:
    async with connection.transaction():
        assert await drop_document(connection, uuid.uuid4()) is None
    assert garbage(setup) == []


async def test_a_file_store_whose_folder_is_not_there_forgets_no_note(
    setup: psycopg.Connection, connection: psycopg.AsyncConnection, tmp_path: Path
) -> None:
    # a sweep started without the store's volume would list nothing and forget every note for good
    setup.execute("INSERT INTO storage_garbage (prefix) VALUES ('exports/old/')")
    away = AsyncStorage(FileSystemStorage(tmp_path / "not-mounted"))

    with pytest.raises(StorageNotConfigured, match="STORAGE_DIR"):
        await sweep(connection, away, POLICY, dry_run=False)

    assert garbage(setup) == ["exports/old/"]
    setup.execute("DELETE FROM storage_garbage")
    assert await sweep(connection, away, POLICY, dry_run=False) == Swept()  # no note: nothing to lose
