"""backend/tools/measure_sessions.py: how long the server's sessions sat idle in a transaction, held one,
ran one statement or waited on a lock, per application name - the numbers the pool's session timeouts
are chosen from."""

import asyncio
import importlib.util
import json
import threading
import time
from pathlib import Path
from typing import Any

import psycopg
import pytest

from tests.support import lock_held, waiting_on_a_lock

pytestmark = pytest.mark.pg

INTERVAL_S = 0.05


def tool() -> Any:
    """backend/tools/measure_sessions.py, which is no package: loaded by its path."""
    spec = importlib.util.spec_from_file_location(
        "measure_sessions", Path(__file__).parents[2] / "tools" / "measure_sessions.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure_sessions = tool()


def in_the_background(url: str, name: str, work: str, *, hold_s: float) -> threading.Thread:
    """A session named ``name`` that runs ``work`` in a transaction, keeps it open ``hold_s``, rolls back."""
    started = threading.Event()

    def run() -> None:
        with psycopg.connect(url, application_name=name) as connection:
            connection.execute(work)
            started.set()
            time.sleep(hold_s)
            connection.rollback()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(10)
    return thread


def statement_running(url: str, name: str, statement: str) -> threading.Thread:
    """A session named ``name`` running ``statement`` in the background, seen running on return."""

    def run() -> None:
        with psycopg.connect(url, application_name=name, autocommit=True) as connection:
            connection.execute(statement)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    with psycopg.connect(url, autocommit=True) as look:
        for _ in range(200):
            seen = look.execute(
                "SELECT 1 FROM pg_stat_activity WHERE application_name = %s AND state = 'active'", (name,)
            ).fetchone()
            if seen:
                return thread
            time.sleep(0.02)
    raise AssertionError(f"{name} never ran its statement")


def test_a_session_idle_in_a_transaction_is_reported_with_how_long(database_url: str) -> None:
    holder = in_the_background(database_url, "measure-idle", "SELECT 1", hold_s=0.3)

    found = measure_sessions.measure(database_url, seconds=3.0, interval_s=INTERVAL_S)
    holder.join(10)

    idle = found["measure-idle"]
    assert idle["max_idle_in_transaction_s"] >= 0.2
    assert idle["max_transaction_s"] >= 0.2
    assert idle["samples"] >= 1
    # the transaction ended within the window: an idle that went on would read 3.0; the bound is six
    # times the 0.3 s it was held, for a busy runner
    assert idle["max_idle_in_transaction_s"] < 2.0


@pytest.mark.anyio
async def test_a_session_waiting_for_a_lock_is_reported(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("CREATE TABLE probe (id int)")
    async with (
        await psycopg.AsyncConnection.connect(database_url, application_name="measure-waiter") as waiter,
        await psycopg.AsyncConnection.connect(database_url, autocommit=True) as look,
    ):
        with lock_held(database_url, "LOCK TABLE probe IN ACCESS EXCLUSIVE MODE", at_most_s=5):
            waiting = asyncio.create_task(waiter.execute("SELECT count(*) FROM probe"))
            await waiting_on_a_lock(look, waiter.info.backend_pid)
            found = await asyncio.to_thread(
                measure_sessions.measure, database_url, seconds=0.3, interval_s=INTERVAL_S
            )
        await waiting  # the lock let go, the count goes through

    assert found["measure-waiter"]["max_lock_wait_s"] >= 0.2
    assert found["measure-waiter"]["max_statement_s"] >= 0.2


def test_without_queries_asked_for_no_statement_s_text_is_printed(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CURRICARTA_TEST_DATABASE_URL", database_url)
    printed = {}
    for flags in ([], ["--queries"]):
        running = statement_running(
            database_url, "measure-text", "SELECT pg_sleep(1) AS marker_of_the_statement"
        )
        assert measure_sessions.main(["--seconds", "0.3", "--interval-ms", "50", *flags]) == 0
        printed[bool(flags)] = capsys.readouterr().out
        running.join(10)

    assert "marker_of_the_statement" not in printed[False]
    assert json.loads(printed[False])["measure-text"]["max_statement_s"] > 0
    # the same run with --queries names it: the first test is not empty for want of the session
    assert "marker_of_the_statement" in printed[True]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--seconds", "0"],
        ["--seconds", "86401"],
        ["--seconds", "1", "--interval-ms", "0"],
        ["--seconds", "1", "--interval-ms", "-5"],
        ["--seconds", "1", "--interval-ms", "60001"],
    ],
)
def test_a_run_without_an_end_or_in_a_tight_loop_is_refused(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CURRICARTA_TEST_DATABASE_URL", raising=False)  # refused before it would connect

    with pytest.raises(SystemExit) as refused:
        measure_sessions.main(arguments)

    assert refused.value.code == 2
