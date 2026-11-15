"""What the retention takes from the database (python -m app.retention; migration 0033): jobs ended past
their time, audit entries past theirs, and the raw answers of runs past theirs - noted as places in the
store for the sweep to empty (``storage_garbage``), the run's key cleared in the same statement.

A time of 0 days keeps everything. Each batch is a transaction of its own, so nothing holds its rows
while the store is asked; the rows are chosen ``FOR UPDATE SKIP LOCKED``, so a row another session holds
- a job ending, a reservation being booked for it - is passed by and taken at the next sweep. Never a
booking of the ledger (``llm_usage``, ``conversion_usage``): a budget is the lifetime sum of its rows,
and taking one away would fill it up. One sweep at a time, under a session's advisory lock
(``take_lock``): a direct connection, never a pooler's transaction mode."""

import psycopg

BATCH = 1000
LOCK_KEY = 0x6B6B_612D_7265_7465  # the sweep's own, beside the migration's (app/db/migrate.py)

# An ended job past its time, but the one still needed: holding a reservation (booked as spent once the
# worker's sweep finds it), waited for by a conversion, or its key's latest - the one a document's state
# reads (app/jobs/queue.py last_jobs, the same order)
_CHOSEN = """
SELECT id FROM job j
WHERE j.status IN ('done', 'failed', 'cancelled') AND j.finished_at < now() - make_interval(days => %(days)s)
    AND NOT EXISTS (SELECT FROM usage_reservation r WHERE r.job_id = j.id)
    AND NOT EXISTS (SELECT FROM conversion c WHERE c.job_id = j.id AND c.status = 'pending')
    AND (j.unique_key IS NULL OR EXISTS (
        SELECT FROM job later WHERE later.unique_key = j.unique_key
            AND (later.created_at, later.id) > (j.created_at, j.id)
    ))
ORDER BY j.finished_at LIMIT %(batch)s
FOR UPDATE OF j SKIP LOCKED
"""
# In a statement of its own, under the rows' locks: a reservation or a conversion's wait committed after
# the choice began is seen here, and none can come for a job held so
_DROP = """
DELETE FROM job j WHERE j.id = ANY(%(chosen)s)
    AND NOT EXISTS (SELECT FROM usage_reservation r WHERE r.job_id = j.id)
    AND NOT EXISTS (SELECT FROM conversion c WHERE c.job_id = j.id AND c.status = 'pending')
"""
_AUDIT = """
DELETE FROM audit_log WHERE id IN (
    SELECT id FROM audit_log WHERE at < now() - make_interval(days => %(days)s) ORDER BY at LIMIT %(batch)s
)
"""
# A run's answers count from its end; a run left unended (cancelled with its attempt) from its start, once
# its job no longer runs: a keeper may still be writing beside a running one
_RAW = """
WITH chosen AS (
    SELECT r.id, r.raw_response_key FROM extraction_run r
    WHERE r.raw_response_key IS NOT NULL
        AND coalesce(r.finished_at, r.started_at) < now() - make_interval(days => %(days)s)
        AND (r.finished_at IS NOT NULL OR NOT EXISTS (
            SELECT FROM job j WHERE j.id = r.job_id AND j.status NOT IN ('done', 'failed', 'cancelled')
        ))
    ORDER BY r.started_at LIMIT %(batch)s
    FOR UPDATE OF r SKIP LOCKED
), cleared AS (
    UPDATE extraction_run r SET raw_response_key = NULL FROM chosen WHERE r.id = chosen.id
    RETURNING chosen.raw_response_key || '/' AS prefix
), noted AS (
    INSERT INTO storage_garbage (prefix) SELECT prefix FROM cleared ON CONFLICT (prefix) DO NOTHING
)
SELECT count(*) FROM cleared
"""


async def take_lock(connection: psycopg.AsyncConnection) -> bool:
    """Whether this session now holds the sweep's lock; False where another does. Held until the session
    ends or unlocks it, across the transactions of the sweep."""
    async with connection.transaction():
        cursor = await connection.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        found = await cursor.fetchone()
    return bool(found and found[0])


async def drop_ended_jobs(connection: psycopg.AsyncConnection, days: int, *, batch: int = BATCH) -> int:
    """Delete the jobs ended more than ``days`` days ago but those still needed (``_CHOSEN``), a batch a
    transaction; how many went. A conversion or run that named one keeps its row without it."""
    if not days:
        return 0
    dropped = 0
    while True:
        async with connection.transaction():
            cursor = await connection.execute(_CHOSEN, {"days": days, "batch": batch})
            chosen = [row[0] for row in await cursor.fetchall()]
            cursor = await connection.execute(_DROP, {"chosen": chosen})
            dropped += cursor.rowcount
        if len(chosen) < batch:
            return dropped


async def drop_old_audit(connection: psycopg.AsyncConnection, days: int, *, batch: int = BATCH) -> int:
    """Delete the audit entries older than ``days`` days, a batch a transaction; how many went."""
    if not days:
        return 0
    dropped = 0
    while True:
        async with connection.transaction():
            cursor = await connection.execute(_AUDIT, {"days": days, "batch": batch})
        dropped += cursor.rowcount
        if cursor.rowcount < batch:
            return dropped


async def mark_old_raw_answers(connection: psycopg.AsyncConnection, days: int, *, batch: int = BATCH) -> int:
    """Clear the raw answers' key of the runs past ``days`` days and note its place for the store
    (``runs/<run>/<stage>/``), in one statement a batch; how many runs. The objects stay until the sweep
    empties the place (``garbage``) - a sweep broken in between leaves the note for the next."""
    if not days:
        return 0
    marked = 0
    while True:
        async with connection.transaction():
            cursor = await connection.execute(_RAW, {"days": days, "batch": batch})
            found = await cursor.fetchone()
        count = int(found[0]) if found else 0
        marked += count
        if count < batch:
            return marked


async def garbage(connection: psycopg.AsyncConnection, *, batch: int = 100) -> list[str]:
    """The places in the store noted to be emptied, the longest noted first: a prefix ends in "/", an
    object's own key does not."""
    async with connection.transaction():
        cursor = await connection.execute(
            "SELECT prefix FROM storage_garbage ORDER BY noted_at, prefix LIMIT %s", (batch,)
        )
        return [row[0] for row in await cursor.fetchall()]


async def forget_garbage(connection: psycopg.AsyncConnection, prefix: str) -> None:
    """The place is empty: its note goes."""
    async with connection.transaction():
        await connection.execute("DELETE FROM storage_garbage WHERE prefix = %s", (prefix,))
