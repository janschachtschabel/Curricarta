"""What a request's reservation becomes (app/llm/calls.py walks the run, this books it): the
reservation made whole however a cancel comes, an answer booked as it reports it, a request its run
left unbooked booked by what is known of it, and whether an answer was cut at the cap.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelResponse, ToolCallPart

from app.core.metrics import observe_llm_request
from app.llm.metering import Meter, Spent


@dataclass
class OpenRequest:
    """A request reserved and not yet booked: its input as reckoned, the requests sent before it,
    and what its answer reported once one came."""

    reservation: Any
    estimate: int
    sent_before: int
    answered: Spent | None = None


async def reserve(meter: Meter, input_tokens: int, output_tokens: int) -> Any:
    """The meter's reservation, made whole however a cancel comes: one that came while it was made -
    its row may stand, the commit's answer not yet come - is waited for and handed back unspent, as
    no request went out; left standing, the job's end would book it as abandoned, an estimate. The
    hand-back runs in a task of its own, kept until it is done: a second cancel does not stop it."""
    reserving = asyncio.ensure_future(meter.reserve(input_tokens, output_tokens))
    try:
        return await asyncio.shield(reserving)
    except asyncio.CancelledError:
        handing = asyncio.ensure_future(_hand_back(meter, reserving))
        _HANDING_BACK.add(handing)
        handing.add_done_callback(_HANDING_BACK.discard)
        await asyncio.shield(handing)
        raise


# the hand-backs under way: the loop keeps a task by a weak reference only
_HANDING_BACK: set[asyncio.Future[None]] = set()


async def _hand_back(meter: Meter, reserving: asyncio.Future[Any]) -> None:
    try:
        reservation = await reserving
    except Exception:  # none was made: nothing to hand back
        return
    await meter.book(reservation, Spent())


async def book_cut_off(meter: Meter, open_: OpenRequest, output_tokens: int, *, sent: bool) -> None:
    """Book a request its run left unbooked: what its answer reported, where one came and its
    booking failed - the meter takes a reservation once - else what was held for it (its input and
    the cap, ``output_tokens``) where it went out, the provider may have charged for it; nothing
    where it never did. Shielded: a cancel must not take the booking of a request that may be paid
    for along."""
    if open_.answered is not None:
        cost = open_.answered
    elif sent:
        observe_llm_request("unanswered", estimated_tokens=open_.estimate + output_tokens)
        cost = Spent(
            input_tokens=open_.estimate,
            output_tokens=output_tokens,
            unanswered_requests=1,
            estimated=True,
        )
    else:
        cost = Spent()
    await asyncio.shield(meter.book(open_.reservation, cost))


def cut_at_cap(response: ModelResponse, cap: int) -> bool:
    """Whether the answer stopped at the cap before its output was whole. pydantic-ai would ask again
    twice before it says so (IncompleteToolCall), each request paid for and cut alike under the same
    cap. Where the provider says it stopped at the cap (``length``), an answer is cut unless its last
    part is a tool call whose arguments are a whole JSON object - empty ones are not, they read as
    ``{}``. Where it says no reason pydantic-ai knows, two signs are needed together: the output
    reported at the cap alone may be a whole answer that took all of it, and arguments that are no
    JSON alone are an answer out of form, worth asking again."""
    last = response.parts[-1] if response.parts else None
    whole = isinstance(last, ToolCallPart) and bool(last.args) and _parses(last)
    if response.finish_reason == "length":
        return not whole
    at_cap = response.finish_reason is None and response.usage.output_tokens >= cap
    return at_cap and isinstance(last, ToolCallPart) and not whole


def _parses(call: ToolCallPart) -> bool:
    try:
        call.args_as_dict(raise_if_invalid=True)
    except (ValueError, AssertionError):
        return False
    return True


def answered(response: ModelResponse, estimate: int, output_tokens: int) -> Spent:
    """What an answer cost, as it reports it - or, where it reports no input at all (a gateway that
    counts nothing), what was held for it, as an estimate; counted."""
    usage = response.usage
    if usage.input_tokens == 0:
        observe_llm_request("answered", estimated_tokens=estimate + output_tokens)
        return Spent(input_tokens=estimate, output_tokens=output_tokens, requests=1, estimated=True)
    observe_llm_request(
        "answered",
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cache_read_tokens,
        output_tokens=usage.output_tokens,
    )
    return Spent(
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cache_read_tokens,
        output_tokens=usage.output_tokens,
        requests=1,
    )
