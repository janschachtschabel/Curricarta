"""A stopping worker waits a bounded while for the reservations handed back after a cancel before it
closes its pool (app/jobs/worker.py ``_serve``, app/llm/booking.py ``hand_backs_done``): run in the
test's own loop, told to stop at once, the order of the two is seen."""

import os
from typing import Any
from unittest import mock

import pytest
from psycopg_pool import AsyncConnectionPool

from app.db.migrate import migrate
from app.jobs import worker
from app.llm import booking
from tests.jobs.test_worker_main import free_port
from tests.support import throwaway_store, without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]


async def test_a_stopping_worker_waits_for_hand_backs_before_its_pool_closes(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate(database_url)
    seen: list[Any] = []
    close = AsyncConnectionPool.close

    async def drained(*, within: float) -> int:
        seen.append(("drained", within))
        return 0

    async def closed(self: AsyncConnectionPool, *args: Any, **kwargs: Any) -> None:
        seen.append("closed")
        await close(self, *args, **kwargs)

    monkeypatch.setattr(booking, "hand_backs_done", drained)
    monkeypatch.setattr(AsyncConnectionPool, "close", closed)
    monkeypatch.setattr(worker, "_stop_on_signals", lambda stop: stop.set())  # no signal handler here
    with without_settings_variables():
        invented = {
            "DATABASE_URL": database_url,
            "STORAGE_DIR": str(throwaway_store()),
            "INTERNAL_PORT": str(free_port()),
            "JOB_POLL_S": "0.1",
        }
        with mock.patch.dict(os.environ, invented):
            assert await worker._serve() == 0

    assert seen[:2] == [("drained", worker.HAND_BACKS_WAIT_S), "closed"]
