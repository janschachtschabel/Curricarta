"""The units of a stage asked side by side (X4, app/pipeline/x4_statements.py; X6, x6_repair.py).

At most EXTRACT_CONCURRENCY are asked at once, and never more than the database's pool leaves beside the
worker's own work: each unit asking holds one connection at a time. An error a unit raises ends every
unit still asking - a lease lost, a cancel, the database - and is raised as itself, its cause and the
error it was raised in handling its own. A provider's error is not one of them (audit 2026-11-14): the
unit keeps the first (``PROVIDER_ERRORS``, ``first_of``) and returns, no unit begins after it, those
asking are answered and written - cut off, each would be booked at its full reservation - and the run
ends by it once they are (``fail_by_provider``).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import NoReturn

from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior

from app.core.settings import Settings
from app.jobs.outcome import PermanentError
from app.llm.calls import quota_spent

log = logging.getLogger(__name__)

# a refusal (an HTTP error), a provider never reached or that never answered (a timeout), and an
# answer no model could read - a proxy's page in its place, which Chat Completions says by
# UnexpectedModelBehavior and the Responses API by ModelAPIError (app/llm/calls.py)
PROVIDER_ERRORS = (ModelHTTPError, ModelAPIError, UnexpectedModelBehavior)
# a 4xx that is no refusal for good: a request that timed out, a rate limit
_PASSING = (408, 429)


def at_once(settings: Settings) -> int:
    """How many units are asked at once: EXTRACT_CONCURRENCY, never more than the pool leaves beside
    the worker's own work. The reckoning of a run (app/pipeline/watch.py, estimate.py) counts by it."""
    return max(1, min(settings.extract_concurrency, settings.db_pool_max_size - 1))


async def ask_side_by_side[T](
    settings: Settings, units: Sequence[T], ask: Callable[[T], Awaitable[None]]
) -> None:
    """``ask`` each of ``units``, side by side as the module says; the first error any raised."""
    gate = asyncio.Semaphore(at_once(settings))

    async def one(unit: T) -> None:
        async with gate:
            await ask(unit)

    failed: Exception | None = None
    try:
        async with asyncio.TaskGroup() as group:
            for unit in units:
                group.create_task(one(unit))
    except ExceptionGroup as broken:  # the first error ended the others: it is the run's
        failed = broken.exceptions[0]
    if failed is not None:
        # raised outside the handler: its cause and the error it was raised in handling stay its own
        raise failed


def first_of(kept: Exception | None, error: Exception) -> Exception:
    """The provider's error a run keeps: the first its units met; a further one is dropped and said,
    by its kind alone."""
    if kept is None:
        return error
    log.warning("a further provider error was dropped: %s", type(error).__name__)
    return kept


def fail_by_provider(error: Exception) -> NoReturn:
    """End a run by the provider's error that one of its units met: a request refused for good - a 4xx
    but 408 and 429, a key, a model's name or a request the provider does not take, and a 429 that
    says the quota at the provider is spent - as ``model_refused``, which no new attempt mends; any
    other as itself, for the job's next attempt."""
    if isinstance(error, ModelHTTPError) and (
        (400 <= error.status_code < 500 and error.status_code not in _PASSING) or quota_spent(error)
    ):
        raise PermanentError("model_refused", "the provider refused the request for good") from error
    raise error
