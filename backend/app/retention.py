"""``python -m app.retention [--dry-run]``: the sweep of what is past its time (RETENTION_JOBS_DAYS,
RETENTION_AUDIT_DAYS, RETENTION_RAW_ANSWERS_DAYS; 0 keeps everything), started by the operators' timer.

It takes from the database the jobs and audit entries past their time and notes the places of the raw
answers past theirs (app/db/retention.py), then empties each noted place in the store - a prefix (it ends
in "/") of every object under it, an object's own key of that object - and forgets the note once the place
is empty. An object already gone counts as taken. Each step is a short transaction of its own, none open
while the store is asked: a sweep broken between noting and emptying leaves the notes, and the next sweep
empties them. One sweep at a time, under a session's advisory lock on its own direct connection - without
the session timeouts of the API's and the workers' pools, as the other commands. Never a booking of the
ledger: a budget is the lifetime sum of its rows.

``--dry-run`` counts what a sweep would take and changes nothing: the database's part runs in ONE
transaction rolled back at its end - holding its row locks (old ended jobs, old runs) until then -, and the
store is only listed, after it. Prints one line of JSON, counts alone - never a key, a title or a
wording: ``jobs``, ``audit_entries``, ``runs`` (whose raw answers were let go), ``objects`` (taken from the
store), ``refused`` (noted places the store refuses as keys, passed by and left noted). It ends in one of
three ways: done, the JSON line and exit code 0; a failure, no JSON, one log line and exit code 1 (a
database step that failed is raised after the others and the store's part ran); notes passed by, the
JSON line, one log line with their count and exit code 1. Exit code 3, with one log line, where another
sweep holds the lock.
"""

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.core.storage import InvalidKey, ObjectNotFound, StorageNotConfigured, open_storage
from app.core.storage_async import AsyncStorage
from app.db.pool import CONNECTION_OPTIONS
from app.db.retention import (
    LOCK_KEY,
    drop_ended_jobs,
    drop_old_audit,
    forget_garbage,
    garbage,
    mark_old_raw_answers,
    take_lock,
)

log = logging.getLogger("app.retention")  # also when run as __main__

BUSY = 3


class SweepBusy(Exception):
    """Another sweep holds the lock."""


@dataclass(frozen=True)
class Policy:
    """How many days each kind of row is kept; 0 keeps it for good."""

    jobs_days: int
    audit_days: int
    raw_answers_days: int

    @classmethod
    def of(cls, settings: Settings) -> "Policy":
        return cls(
            settings.retention_jobs_days, settings.retention_audit_days, settings.retention_raw_answers_days
        )


@dataclass
class Swept:
    jobs: int = 0
    audit_entries: int = 0
    runs: int = 0  # whose raw answers were let go
    objects: int = 0  # taken from the store
    refused: int = 0  # noted places the store refuses as keys (a device's name): passed by, left noted


async def sweep(
    connection: psycopg.AsyncConnection, storage: AsyncStorage, policy: Policy, *, dry_run: bool
) -> Swept:
    """One sweep, as the module says, on ``connection`` - in autocommit or with no transaction open (each
    step opens its own, and none is left open after); its session holds the lock for the sweep's time.
    SweepBusy where another session holds it."""
    if not await take_lock(connection):
        raise SweepBusy
    try:
        swept = await _sweep(connection, storage, policy, dry_run=dry_run)
    except BaseException:
        # a failed unlock must not hide why the sweep stopped; the lock goes with the session then
        with contextlib.suppress(psycopg.Error):
            await _unlock(connection)
        raise
    await _unlock(connection)
    return swept


async def _sweep(
    connection: psycopg.AsyncConnection, storage: AsyncStorage, policy: Policy, *, dry_run: bool
) -> Swept:
    """Each step runs whatever an earlier one met: a database step that fails leaves the others to run, and
    the places noted before are emptied all the same - else a lasting failure would keep them in the store
    for good. The first database error is raised at the end; a store's failure after it is its cause."""
    swept = Swept()
    if not dry_run:
        failure = await _rows(connection, policy, swept)
        try:
            swept.objects, swept.refused = await _empty(connection, storage)
        except Exception as store_failure:
            if failure is not None:
                raise failure from store_failure
            raise
        if failure is not None:
            raise failure
        return swept
    async with connection.transaction(force_rollback=True):
        failure = await _rows(connection, policy, swept)
        places = await _all_places(connection)
    for place in places:
        try:
            swept.objects += len(await _objects(storage, place))
        except InvalidKey:
            swept.refused += 1
    if failure is not None:
        raise failure
    return swept


async def _unlock(connection: psycopg.AsyncConnection) -> None:
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


async def _rows(connection: psycopg.AsyncConnection, policy: Policy, swept: Swept) -> psycopg.Error | None:
    """The database's three steps into ``swept``, each run whatever the one before met; the first error."""
    failure: psycopg.Error | None = None
    steps = (
        ("jobs", drop_ended_jobs, policy.jobs_days),
        ("audit_entries", drop_old_audit, policy.audit_days),
        ("runs", mark_old_raw_answers, policy.raw_answers_days),
    )
    for name, step, days in steps:
        try:
            setattr(swept, name, await step(connection, days))
        except psycopg.Error as error:
            failure = failure or error
    return failure


async def _all_places(connection: psycopg.AsyncConnection) -> list[str]:
    """Every noted place, each forgotten as it is read: in the dry run's transaction, rolled back after."""
    places: list[str] = []
    while found := await garbage(connection):
        for place in found:
            await forget_garbage(connection, place)
        places += found
    return places


async def _objects(storage: AsyncStorage, place: str) -> list[str]:
    """The keys of the objects a noted place holds: every one under a prefix, an object's own key if it is
    there."""
    if place.endswith("/"):
        return await storage.list(place)
    return [place] if await storage.exists(place) else []


async def _empty(connection: psycopg.AsyncConnection, storage: AsyncStorage) -> tuple[int, int]:
    """Empty every noted place and forget it; how many objects went, and how many places the store refuses
    as keys for good - passed by and left noted, the others emptied all the same. Noted meanwhile, a place
    is emptied too; any other failure of the store stops the sweep, its note kept for the next."""
    taken = 0
    refused: list[str] = []
    while places := await garbage(connection, passing=refused):
        for place in places:
            try:
                keys = await _objects(storage, place)
            except InvalidKey:
                refused.append(place)
                continue
            for key in keys:
                try:
                    await storage.delete(key)
                except ObjectNotFound:  # gone meanwhile: another sweep, or the request that noted it
                    continue
                taken += 1
            await forget_garbage(connection, place)
    return taken, len(refused)


async def _run(settings: Settings, policy: Policy, *, dry_run: bool) -> Swept:
    url = settings.database_url.get_secret_value()
    options = {**CONNECTION_OPTIONS, "application_name": "curricarta-retention"}
    async with await psycopg.AsyncConnection.connect(url, autocommit=True, **options) as connection:
        storage = AsyncStorage(await asyncio.to_thread(open_storage, settings))
        return await sweep(connection, storage, policy, dry_run=dry_run)


def _cause(error: BaseException) -> str:
    """What stopped the sweep, in one line and without its data: a database error's primary message
    (DETAIL may quote a row), the setting a store not configured lacks, a store's error code, else the
    error's kind."""
    if isinstance(error, psycopg.Error):
        message = error.diag.message_primary or str(error)
        return " ".join(message.split())
    # names the setting it lacks; with S3 also the bucket's name - a setting's value, no secret
    if isinstance(error, StorageNotConfigured):
        return str(error)
    code = getattr(error, "response", {}).get("Error", {}).get("Code") if hasattr(error, "response") else None
    return type(error).__name__ + (f" ({code})" if code else "")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.retention", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="count what a sweep would take, change nothing"
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        swept = asyncio.run(
            _run(settings, Policy.of(settings), dry_run=args.dry_run), loop_factory=asyncio.SelectorEventLoop
        )
    except SweepBusy:
        log.warning("another sweep holds the lock: nothing taken")
        return BUSY
    except Exception as error:  # any failure ends the command in one line, never a traceback
        log.error("retention stopped: %s", _cause(error))
        return 1
    sys.stdout.write(json.dumps(asdict(swept)) + "\n")
    sys.stdout.flush()
    if swept.refused:
        log.error("retention left %d noted place(s) the store refuses as keys", swept.refused)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
