"""How long the database's sessions sit idle in a transaction, hold one, run one statement or wait on a lock,
per application name: the numbers the pool's session timeouts are chosen from.

    python backend/tools/measure_sessions.py --seconds N [--interval-ms 50] [--queries]

It samples pg_stat_activity (and pg_locks for when a wait began) of the server CURRICARTA_TEST_DATABASE_URL
names, every --interval-ms, for --seconds, while a workload runs beside it, and prints JSON: per application
name (the API names itself curricarta-api, the worker curricarta-worker; a session that gave none is "") the
longest of each measure seen and in how many samples the name was seen. A number is a lower bound: a pause
between two samples, or shorter than one interval, is not seen whole. --queries adds the first 80 characters
of the statement behind each longest value - for synthetic data only: the text may quote what a statement
writes. Without it no statement's text is read at all.

Only against a server that is yours: the sample is server-wide (every database, every application on it),
and --queries prints other applications' statements too. Sessions of other roles are seen only by a member
of pg_read_all_stats (or a superuser); without that privilege they drop out without a word, and a run looks
clean that saw nothing. --seconds runs up to a day, --interval-ms from 10 ms to a minute.
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg import sql

URL_VARIABLE = "CURRICARTA_TEST_DATABASE_URL"
MEASURES = ("max_idle_in_transaction_s", "max_transaction_s", "max_statement_s", "max_lock_wait_s")
QUERY_CHARS = 80
MAX_SECONDS = 86_400.0
INTERVAL_MS = (10.0, 60_000.0)

# Seconds as the server's clock has them at the sample; a lock wait from pg_locks.waitstart, which can be
# null for a moment after the wait began (then 0). Only client sessions, never this one.
_SAMPLE = """
SELECT a.application_name,
       CASE WHEN a.state LIKE 'idle in transaction%'
            THEN extract(epoch FROM clock_timestamp() - a.state_change) ELSE 0 END,
       coalesce(extract(epoch FROM clock_timestamp() - a.xact_start), 0),
       CASE WHEN a.state = 'active' THEN extract(epoch FROM clock_timestamp() - a.query_start) ELSE 0 END,
       CASE WHEN a.wait_event_type = 'Lock' THEN coalesce(
            (SELECT extract(epoch FROM clock_timestamp() - min(l.waitstart))
               FROM pg_locks l WHERE l.pid = a.pid AND NOT l.granted), 0) ELSE 0 END,
       {query}
  FROM pg_stat_activity a
 WHERE a.backend_type = 'client backend' AND a.pid <> pg_backend_pid()
"""


def sample(connection: psycopg.Connection[Any], *, queries: bool) -> list[tuple[Any, ...]]:
    """One look at the server's sessions: (name, idle in transaction, transaction, statement, lock wait,
    statement text or None) each, durations in seconds."""
    text = sql.SQL("left(a.query, {})").format(QUERY_CHARS) if queries else sql.SQL("NULL")
    return connection.execute(sql.SQL(_SAMPLE).format(query=text)).fetchall()


def fold(found: dict[str, dict[str, Any]], rows: list[tuple[Any, ...]], *, queries: bool) -> None:
    """The rows of one sample into the longest values per name."""
    for name in {row[0] for row in rows}:
        entry = found.setdefault(name, {**dict.fromkeys(MEASURES, 0.0), "samples": 0})
        entry["samples"] += 1
    for name, *durations, text in rows:
        entry = found[name]
        for measure, value in zip(MEASURES, durations, strict=True):
            if float(value) > entry[measure]:
                entry[measure] = float(value)
                if queries:
                    entry.setdefault("queries", {})[measure] = text


def measure(url: str, *, seconds: float, interval_s: float = 0.05, queries: bool = False) -> dict[str, Any]:
    """The longest values per application name over ``seconds``, a sample every ``interval_s``."""
    found: dict[str, dict[str, Any]] = {}
    with psycopg.connect(url, autocommit=True, application_name="curricarta-measure") as connection:
        deadline = time.monotonic() + seconds
        while True:
            started = time.monotonic()
            fold(found, sample(connection, queries=queries), queries=queries)
            if started >= deadline:
                break
            time.sleep(max(0.0, min(interval_s - (time.monotonic() - started), deadline - time.monotonic())))
    for entry in found.values():
        for name in MEASURES:
            entry[name] = round(entry[name], 3)
    return dict(sorted(found.items()))


def _bounded(low: float, high: float, *, low_included: bool) -> Callable[[str], float]:
    """An argparse type: a number within the bounds, else the parser's own error (exit code 2)."""

    def parse(text: str) -> float:
        value = float(text)
        if not (low <= value if low_included else low < value) or value > high:
            raise argparse.ArgumentTypeError(f"must lie between {low:g} and {high:g}")
        return value

    return parse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--seconds",
        type=_bounded(0, MAX_SECONDS, low_included=False),
        required=True,
        help="how long to sample",
    )
    parser.add_argument(
        "--interval-ms",
        type=_bounded(*INTERVAL_MS, low_included=True),
        default=50.0,
        help="between two samples",
    )
    parser.add_argument(
        "--queries", action="store_true", help="name each longest value's statement (synthetic data only)"
    )
    arguments = parser.parse_args(argv)
    url = os.environ.get(URL_VARIABLE)
    if not url:
        print(f"{URL_VARIABLE} is not set", file=sys.stderr)
        return 2
    found = measure(
        url, seconds=arguments.seconds, interval_s=arguments.interval_ms / 1000, queries=arguments.queries
    )
    print(json.dumps(found, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
