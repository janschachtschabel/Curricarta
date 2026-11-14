"""What the tests of units asked side by side (X4, X6) share where the provider fails: a unit's
request found by its content, the waits after a refusal taken away, the moment a provider's error
reached the unit, a refusal made, and the job's bookings of units."""

import asyncio
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage

from app.llm import calls
from app.pipeline.asking import Asking
from app.pipeline.side_by_side import PROVIDER_ERRORS
from tests.pipeline.test_run import rows
from tests.pipeline.test_x3_frame import prompt_of


def asks(messages: list[ModelMessage], key: str) -> bool:
    """Whether the request asks for the unit ``key`` - found by content: units asked side by side ask
    in no set order."""
    return f"=== EINHEIT ===\n{key} " in prompt_of(messages)


@pytest.fixture
def waited(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The waits after a refusal, taken instead of waited."""
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(calls, "_sleep", sleep)
    monkeypatch.setattr(calls, "_draw", lambda: 0.0)
    return slept


@pytest.fixture
def provider_failed(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """Set as a provider's error leaves a unit's request, every refusal booked - in the very step in
    which the unit takes note of it, so a unit that waits for it finishes once no further unit may
    begin, whatever the clock says."""
    failed = asyncio.Event()
    answer = Asking.answer

    async def noted(self: Asking, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await answer(self, *args, **kwargs)
        except PROVIDER_ERRORS:
            failed.set()
            raise

    monkeypatch.setattr(Asking, "answer", noted)
    return failed


def refusal(status: int, *, code: str = "server_error") -> ModelHTTPError:
    """The provider's refusal with ``status``, its error of the type and code ``code``."""
    return ModelHTTPError(status, "gpt-6-luna", body={"error": {"message": "x", "type": code, "code": code}})


async def usage_rows(connection: Any, job: Any, purpose: str = "x4.unit") -> list[tuple[Any, ...]]:
    """The job's bookings of units as (requests, tokens, estimated), and the reservations it left."""
    booked = await rows(
        connection,
        "SELECT requests, input_tokens + output_tokens, estimated FROM llm_usage"
        " WHERE job_id = %s AND purpose = %s ORDER BY 2, 1",
        job.id,
        purpose,
    )
    [(held,)] = await rows(connection, "SELECT count(*) FROM usage_reservation WHERE job_id = %s", job.id)
    return [*booked, ("held", held)]
