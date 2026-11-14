"""A reservation a cancel came upon is handed back in a task of its own (app/llm/booking.py): an error
in it is said by its kind and not lost, and the worker waits for those under way a bounded while
before it closes its pool - the sweeper books what is left. A ledger stands in."""

import asyncio
import logging

import pytest

from app.llm import booking
from app.llm.metering import Spent
from tests.llm.test_calls import Ledger

pytestmark = pytest.mark.anyio


class Holding(Ledger):
    """Its reservation is held at once and answered once ``answered`` is set; its booking waits for
    ``booked`` and then fails where ``fails``."""

    def __init__(self, *, fails: bool = False) -> None:
        super().__init__()
        self.holding, self.answered, self.booked_now = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.fails = fails

    async def reserve(self, input_tokens: int, output_tokens: int) -> int:
        held = await super().reserve(input_tokens, output_tokens)
        self.holding.set()
        await asyncio.wait_for(self.answered.wait(), 10)
        return held

    async def book(self, reservation: int, spent: Spent) -> None:
        await asyncio.wait_for(self.booked_now.wait(), 10)
        if self.fails:
            raise ConnectionError("the database went away, with a payload (invented)")
        await super().book(reservation, spent)


async def cancelled_twice(ledger: Holding) -> None:
    """A reservation cancelled as it is made, and its caller cancelled again: the hand-back goes on alone."""
    call = asyncio.create_task(booking.reserve(ledger, 10, 20))
    await asyncio.wait_for(ledger.holding.wait(), 10)
    call.cancel()
    await asyncio.sleep(0)
    ledger.answered.set()
    await asyncio.sleep(0)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call


async def test_an_error_in_a_hand_back_no_caller_awaits_is_said_by_its_kind(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ledger = Holding(fails=True)
    await cancelled_twice(ledger)

    with caplog.at_level(logging.WARNING, logger="app.llm.booking"):
        ledger.booked_now.set()
        assert await booking.hand_backs_done(within=10) == 0

    said = [record.getMessage() for record in caplog.records if record.name == "app.llm.booking"]
    assert said == ["a reservation's hand-back failed: ConnectionError"]
    assert "payload" not in caplog.text


async def test_the_wait_for_hand_backs_under_way_gives_up_at_its_bound() -> None:
    ledger = Holding()
    await cancelled_twice(ledger)

    left = await booking.hand_backs_done(within=0.2)
    ledger.booked_now.set()
    after = await booking.hand_backs_done(within=10)

    assert (left, after) == (1, 0)
    assert ledger.booked == [(1, Spent())]
