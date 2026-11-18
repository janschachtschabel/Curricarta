"""Emptying the places noted in ``storage_garbage`` (migration 0033): by the sweep (app/retention.py) and by
the request that noted them (app/api/deleting.py). A place is a prefix (it ends in "/"), each object under it
taken, or an object's own key. Nothing here holds a transaction open while the store is asked; a note is
forgotten once its place is empty, so one broken in between is emptied by the next sweep. An object already
gone counts as taken by another: two emptying the same place at once take each object once.

A file's object (``sources/<sha256>``) is content-addressed - the same bytes uploaded again name it once
more -, so the sweep alone empties it, under the file's lock and only while no row names it
(app/db/deleting.py)."""

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from typing import Literal

import psycopg
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from app.core.storage import FileSystemStorage, InvalidKey, ObjectNotFound, StorageNotConfigured
from app.core.storage_async import AsyncStorage
from app.db.deleting import FILE_LOCK
from app.db.retention import forget_garbage, garbage

log = logging.getLogger(__name__)


async def objects_of(storage: AsyncStorage, place: str) -> list[str]:
    """The keys of the objects a noted place holds: every one under a prefix, an object's own key if it is
    there."""
    if place.endswith("/"):
        return await storage.list(place)
    return [place] if await storage.exists(place) else []


async def empty_place(storage: AsyncStorage, place: str) -> int:
    """Take every object of a noted place from the store - under a prefix (it ends in "/") each one, else
    the object's own key; how many went. An object already gone counts as taken by another (a sweep, a
    request emptying the same place): twice at once is harmless. InvalidKey for a place the store refuses
    as a key. Asks the store alone: the caller forgets the note after, holding no connection meanwhile."""
    taken = 0
    for key in await objects_of(storage, place):
        try:
            await storage.delete(key)
        except ObjectNotFound:  # gone meanwhile: another sweep, or the request that noted it
            continue
        taken += 1
    return taken


async def sweep_prefixes(pool: AsyncConnectionPool, storage: AsyncStorage, prefixes: Sequence[str]) -> int:
    """Empty the places a request has just noted and forget each note, as far as the store lets it; how
    many objects went. A failure is a warning: the notes left stay for the next sweep, and the request has
    its answer already. A connection is taken only to forget a note, never held while the store is asked,
    and no session lock: beside the nightly sweep each object goes once, and forgetting twice is nothing.
    A file's object (sources/) is the sweep's alone, under the file's lock (``_empty_file``)."""
    taken = 0
    for place in prefixes:
        if place.startswith("sources/"):
            raise ValueError("a file's object is emptied by the sweep, under the file's lock")
        try:
            taken += await empty_place(storage, place)
            async with pool.connection() as connection:
                await forget_garbage(connection, place)
        except Exception as error:  # the request has committed: its places wait for the sweep
            log.warning("a noted place stays for the sweep: %s", type(error).__name__)
    return taken


async def _empty_file(connection: psycopg.AsyncConnection, storage: AsyncStorage, key: str) -> int:
    """Empty the note of a file's object (sources/<sha256>) and forget it under the file's lock, held by the
    sweep's session while it asks the store - no transaction open: an upload of the same bytes waits to
    write its row (app/db/sources.py file_row) until the object is gone and the note forgotten, then finds
    the object missing and stores it anew. Where a row names the object again, it stays: the note was left
    from before."""
    await _file_lock(connection, "pg_advisory_lock", key)
    try:
        async with connection.transaction():
            cursor = await connection.execute("SELECT FROM source_file WHERE storage_key = %s", (key,))
            named = await cursor.fetchone() is not None
        taken = 0 if named else await empty_place(storage, key)
        await forget_garbage(connection, key)
    except BaseException:
        # a failed unlock must not hide why the emptying stopped; the lock goes with the session then
        with contextlib.suppress(psycopg.Error):
            await _file_lock(connection, "pg_advisory_unlock", key)
        raise
    await _file_lock(connection, "pg_advisory_unlock", key)
    return taken


async def _file_lock(
    connection: psycopg.AsyncConnection, call: Literal["pg_advisory_lock", "pg_advisory_unlock"], key: str
) -> None:
    async with connection.transaction():
        await connection.execute(
            sql.SQL("SELECT {}(%s, hashtext(%s))").format(sql.Identifier(call)), (FILE_LOCK, key)
        )


async def empty_noted(connection: psycopg.AsyncConnection, storage: AsyncStorage) -> tuple[int, int]:
    """Empty every noted place and forget it; how many objects went, and how many places the store refuses
    as keys for good - passed by and left noted, the others emptied all the same. Noted meanwhile, a place
    is emptied too; any other failure of the store stops the sweep, its note kept for the next."""
    await _store_there(connection, storage)
    taken = 0
    refused: list[str] = []
    while places := await garbage(connection, passing=refused):
        for place in places:
            try:
                if place.startswith("sources/"):
                    taken += await _empty_file(connection, storage, place)
                    continue
                taken += await empty_place(storage, place)
            except InvalidKey:
                refused.append(place)
                continue
            await forget_garbage(connection, place)
    return taken, len(refused)


async def _store_there(connection: psycopg.AsyncConnection, storage: AsyncStorage) -> None:
    """StorageNotConfigured for a file store whose root is no folder while notes wait: it lists nothing, and
    the sweep would forget every note with its objects left for good - a service started without the
    store's volume."""
    files = storage.sync
    away = isinstance(files, FileSystemStorage) and not await asyncio.to_thread(files.root.is_dir)
    if away and await garbage(connection, batch=1):
        raise StorageNotConfigured(
            "STORAGE_DIR is no folder: the noted places stay for a sweep with the store"
        )
