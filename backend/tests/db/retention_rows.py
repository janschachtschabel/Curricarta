"""Rows the tests of the retention share: jobs ended long ago or not, a run whose raw answers lie in the
store, the ledger's bookings - written by a session of their own, as the app's writers do."""

import uuid
from typing import Any

import psycopg

from tests.db.l1 import add_run


def add_job(
    setup: psycopg.Connection,
    *,
    status: str = "done",
    ended_days_ago: int = 100,
    key: str | None = None,
    code: str | None = None,
) -> uuid.UUID:
    """A job of the system's lane, made a day before it ended ``ended_days_ago`` days ago; one waiting or
    running made that long ago and not ended. A failed one carries ``code``."""
    job = uuid.uuid4()
    setup.execute("INSERT INTO job_lane (lane) VALUES ('system') ON CONFLICT DO NOTHING")
    ended = status in ("done", "failed", "cancelled")
    lease = status == "running"
    setup.execute(
        "INSERT INTO job (id, kind, lane, status, unique_key, error, created_at, finished_at,"
        " lease_owner, lease_token, lease_expires_at)"
        " VALUES (%(id)s, 'extract.run', 'system', %(status)s, %(key)s, %(error)s,"
        " now() - make_interval(days => %(days)s + 1),"
        " CASE WHEN %(ended)s THEN now() - make_interval(days => %(days)s) END,"
        " CASE WHEN %(lease)s THEN 'worker-1' END, CASE WHEN %(lease)s THEN gen_random_uuid() END,"
        " CASE WHEN %(lease)s THEN now() + interval '1 minute' END)",
        {
            "id": job,
            "status": status,
            "key": key,
            "error": psycopg.types.json.Jsonb({"code": code, "message": "stopped"}) if code else None,
            "days": ended_days_ago,
            "ended": ended,
            "lease": lease,
        },
    )
    return job


def job_ids(setup: psycopg.Connection) -> set[uuid.UUID]:
    return {row[0] for row in setup.execute("SELECT id FROM job")}


def add_reservation(setup: psycopg.Connection, account: uuid.UUID, job: uuid.UUID) -> None:
    setup.execute(
        "INSERT INTO usage_reservation (account_id, job_id, purpose, model, input_tokens, output_tokens)"
        " VALUES (%s, %s, 'x4.unit', 'gpt-6-luna', 1200, 300)",
        (account, job),
    )


def add_usage(setup: psycopg.Connection, account: uuid.UUID, job: uuid.UUID, **columns: Any) -> None:
    values = {
        "account_id": account,
        "job_id": job,
        "purpose": "x4.unit",
        "model": "gpt-6-luna",
        "input_tokens": 1200,
        "cached_input_tokens": 1000,
        "output_tokens": 300,
        "requests": 1,
        "unanswered_requests": 0,
        "estimated": False,
        **columns,
    }
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    setup.execute(
        f"INSERT INTO llm_usage ({names}) VALUES ({marks})",  # noqa: S608 - the helper's own names
        tuple(values.values()),
    )


def add_ended_run(
    setup: psycopg.Connection, document: uuid.UUID, *, ended_days_ago: int, job: uuid.UUID | None = None
) -> uuid.UUID:
    """A run of X4 ended ``ended_days_ago`` days ago, its raw answers kept under runs/<run>/x4 as
    app/db/runs.py start_run names them."""
    run = add_run(setup, document)
    setup.execute(
        "UPDATE extraction_run SET raw_response_key = 'runs/' || id || '/x4', job_id = %(job)s,"
        " started_at = now() - make_interval(days => %(days)s + 1),"
        " finished_at = now() - make_interval(days => %(days)s),"
        " outcome = 'done' WHERE id = %(run)s",
        {"run": run, "days": ended_days_ago, "job": job},
    )
    return run


def raw_key(setup: psycopg.Connection, run: uuid.UUID) -> str | None:
    found = setup.execute("SELECT raw_response_key FROM extraction_run WHERE id = %s", (run,)).fetchone()
    assert found is not None
    return None if found[0] is None else str(found[0])


def garbage(setup: psycopg.Connection) -> list[str]:
    return [row[0] for row in setup.execute("SELECT prefix FROM storage_garbage ORDER BY prefix")]
