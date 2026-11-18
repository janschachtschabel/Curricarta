"""Taking a document or a register entry away (app/api/deleting.py), and a file no entry holds any more.

What the store holds for them is noted in ``storage_garbage`` in the transaction that lets go of what
named it, and emptied after the commit - by the request, or by the next sweep (python -m app.retention)
where the store was away: a document's runs (``runs/<run>/``) and exports (``exports/<document>/``), a
file's object (``sources/<sha256>``, one key). A file's object is content-addressed: the same bytes uploaded
or fetched again name it once more. So a file's row is written, and taken away, under the file's own lock
(``lock_file``), and the row written takes the note on its object away; the sweep empties such a note under
the same lock and only while no row names the object (app/retention.py)."""

from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

import psycopg

# The two-key form of an advisory lock: its keys are apart from the one-key locks (the sweep's, the
# migration's). The second key is the hash of the file's storage key - two files sharing it only wait
FILE_LOCK = 0x736F_7572

_RUNS = "SELECT 'runs/' || id || '/' FROM extraction_run WHERE document_id = %s ORDER BY started_at, id"
_NOTE = "INSERT INTO storage_garbage (prefix) SELECT unnest(%s::text[]) ON CONFLICT (prefix) DO NOTHING"
# A job of the entry waiting or running: a conversion of its file asked and not done, or its fetch
_OPEN_JOB = """
SELECT job_id FROM conversion WHERE source_file_id = %(file)s AND status = 'pending'
UNION ALL
SELECT id FROM job
WHERE kind = 'source.fetch' AND status IN ('queued', 'running') AND payload->>'source_id' = %(source)s::text
LIMIT 1
"""
# The file, locked, where no entry holds it and no conversion of it waits
_ORPHAN = """
SELECT storage_key FROM source_file f WHERE f.id = %s
    AND NOT EXISTS (SELECT FROM source s WHERE s.file_id = f.id)
    AND NOT EXISTS (SELECT FROM conversion c WHERE c.source_file_id = f.id AND c.status = 'pending')
FOR UPDATE OF f
"""
_ORPHANS = """
SELECT f.id FROM source_file f
WHERE NOT EXISTS (SELECT FROM source s WHERE s.file_id = f.id)
    AND NOT EXISTS (SELECT FROM conversion c WHERE c.source_file_id = f.id AND c.status = 'pending')
    AND f.id <> ALL(%s)
ORDER BY f.created_at, f.id LIMIT %s
"""


EntryCode = Literal["seed_entry", "has_documents", "job_open"]


class EntryHeld(Exception):
    """The entry is not taken away: ``seed_entry`` (of no account), ``has_documents`` (``count`` of them),
    ``job_open`` (``job_id``: a conversion of its file or its fetch waits or runs)."""

    def __init__(
        self,
        code: Literal["seed_entry", "has_documents", "job_open"],
        *,
        count: int = 0,
        job_id: UUID | None = None,
    ) -> None:
        super().__init__(f"the entry stays: {code}")
        self.code, self.count, self.job_id = code, count, job_id


async def lock_file(connection: psycopg.AsyncConnection, storage_key: str) -> None:
    """Wait for, then hold until the transaction ends, the lock of the file stored under ``storage_key``:
    its row written (app/db/sources.py file_row), taken away (``drop_orphan_file``) and its object emptied
    (the sweep, under the same keys as a session's lock) one at a time."""
    await connection.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (FILE_LOCK, storage_key))


async def hold_entry(connection: psycopg.AsyncConnection, source_id: UUID) -> bool:
    """Hold the entry against its taking away until the caller's transaction ends - a conversion asked for
    of its file: taken away first, it is not there (False); asked first, the taking away waits for the
    conversion to stand and is refused (``job_open``). Without it a deletion beside the asking saw no pending
    conversion, and the file went with the conversion just asked."""
    cursor = await connection.execute("SELECT FROM source WHERE id = %s FOR KEY SHARE", (source_id,))
    return await cursor.fetchone() is not None


async def drop_document(connection: psycopg.AsyncConnection, document_id: UUID) -> list[str] | None:
    """Take the document away with all it holds - its tree, runs, findings, units, gold samples cascade -
    and note the places of its runs' raw answers and of its exports; the places, None where there is no
    such document. Within the caller's transaction, which holds the tree's lock (app/db/editing.py
    guard_document): no job of the document waits or runs, none is started meanwhile. Its entry, its
    conversion, its jobs and the ledger's bookings stay."""
    cursor = await connection.execute(_RUNS, (document_id,))
    places = [row[0] for row in await cursor.fetchall()] + [f"exports/{document_id}/"]
    cursor = await connection.execute("DELETE FROM document WHERE id = %s", (document_id,))
    if cursor.rowcount == 0:
        return None
    await connection.execute(_NOTE, (places,))
    return places


async def drop_source(connection: psycopg.AsyncConnection, source_id: UUID, entry: dict[str, Any]) -> None:
    """Take the entry away with how its file came, within the caller's transaction, which read ``entry``
    locked (app/db/source_queries.py get_source, ``for_update``); EntryHeld where it stays. Its file stays
    for ``drop_orphan_file``, in a transaction after: another entry may hold it."""
    if entry["owner_id"] is None:
        raise EntryHeld("seed_entry")
    cursor = await connection.execute("SELECT count(*) FROM document WHERE source_id = %s", (source_id,))
    found = await cursor.fetchone()
    if found and found[0]:
        raise EntryHeld("has_documents", count=int(found[0]))
    cursor = await connection.execute(_OPEN_JOB, {"file": entry["file_id"], "source": source_id})
    if (job := await cursor.fetchone()) is not None:  # a conversion's job may be gone: none to name
        raise EntryHeld("job_open", job_id=job[0])
    await connection.execute("DELETE FROM acquisition WHERE source_id = %s", (source_id,))
    await connection.execute("DELETE FROM source WHERE id = %s", (source_id,))


async def drop_orphan_file(connection: psycopg.AsyncConnection, file_id: UUID) -> str | None:
    """Where no entry holds the file and no conversion of it waits: take its row away with its conversions
    (their blocks cascade; the pages they booked stay) and note its object; the object's key, else None.
    Within the caller's transaction, under the file's lock: an upload of the same bytes meanwhile either
    finds the row still there or writes it anew - and takes the note away."""
    cursor = await connection.execute("SELECT storage_key FROM source_file WHERE id = %s", (file_id,))
    if (found := await cursor.fetchone()) is None:
        return None
    await lock_file(connection, found[0])
    cursor = await connection.execute(_ORPHAN, (file_id,))
    if (orphan := await cursor.fetchone()) is None:
        return None
    key = str(orphan[0])
    await connection.execute("DELETE FROM conversion WHERE source_file_id = %s", (file_id,))
    await connection.execute("DELETE FROM source_file WHERE id = %s", (file_id,))
    await connection.execute(_NOTE, ([key],))
    return key


async def orphan_files(
    connection: psycopg.AsyncConnection, *, batch: int = 100, passing: Sequence[UUID] = ()
) -> list[UUID]:
    """Files no entry holds, as a request broken after taking its entry away leaves them; unlocked - each
    is looked at again under its lock (``drop_orphan_file``); but those ``passing`` names."""
    cursor = await connection.execute(_ORPHANS, (list(passing), batch))
    return [row[0] for row in await cursor.fetchall()]
