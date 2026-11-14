"""The watch after X2 (plan H-3, 3.6): once X2 has cut the units, and before X3 or X4 asks the model,
a job of ``extract.run`` reckons what the rest of its run is expected to charge
(app/pipeline/reckoned.py, expected_charge: X3 where open and each unit X4 would ask, each shared part
read from the cache but for the first 1 + EXTRACT_CONCURRENCY requests, each answer at the measured
mean) and ends as ``run_over_budget`` where that is more than the account's quota has left. Nothing is
sent; X1 and X2 stay done, and a new job - with more budget, or with the watch off - goes on at X3.

What is left is read as a reservation reads it (app/usage/ledger.py, ``usage_of``): the limit less
what the account spent and what its requests hold - this job's and those of its other jobs -, under
the job's lease. It is a look at one moment, not a reservation: other jobs of the account may spend
what it saw left, and a run may charge more than expected (an answer out of form asks again, a cache
dropped is read whole). So a run the watch let pass may still end as ``budget_exhausted`` when a
reservation finds too little - the quota stays the hard stop behind it, and the units done stay.
EXTRACT_BUDGET_WATCH turns it off; an account without a limit is not watched. An operator who wants a
run to stop after X2 sets the account's limit just above what X1 and X2 spent.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.conversion.base import Block
from app.db.documents import Document
from app.db.runs import done_stages
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from app.jobs.queue import Job, hold_lease
from app.llm.client import cost_weights
from app.pipeline.asking import model_of
from app.pipeline.ground import ground_of
from app.pipeline.reckoned import expected_charge, owed_requests, prefix_tokens
from app.usage.ledger import usage_of

log = logging.getLogger("app.pipeline.watch")


@dataclass(frozen=True)
class Watched:
    units: int  # the units X4 would ask
    prefix_tokens: int  # X3's prefix, counted plainly
    expected: int  # what the rest is expected to charge, weighed
    ceiling: int  # the account's limit
    left: int | None  # of it, what is neither spent nor held


async def watch_budget(
    context: JobContext, job: Job, document: Document, blocks: Sequence[Block], printed: Sequence[str | None]
) -> Watched | None:
    """What the rest of the run on ``document`` - X2 done on it - is expected to charge beside what
    its account has left, logged; None where the watch is off, the account has no limit, or X3 and X4
    are done. PermanentError ``run_over_budget`` where the rest is expected to charge more than is
    left; ``prefix_too_long`` (and ``model_not_configured``) as the stage would end the job."""
    if not context.settings.extract_budget_watch:
        return None
    async with context.pool.connection() as connection:
        if {"X3", "X4"} <= await done_stages(connection, document.id):
            return None
        async with connection.transaction():
            await hold_lease(connection, job)
            usage = await usage_of(connection, document.owner_id)
    if usage.token_limit is None:
        return None
    model, _ = model_of(context)
    assert context.llm is not None  # noqa: S101 - the stage has its model (model_of)
    async with context.pool.connection() as connection:
        ground = await ground_of(connection, document)
        # the reckoning reads every unit's question: seconds for a large prefix, counted in threads
        requests, units = await owed_requests(
            connection, context.llm, document, blocks, printed, ground, model, context.settings.ontology_dir
        )
        prefix = await prefix_tokens(connection, context.llm, document, blocks, printed)
    first = 1 + context.settings.extract_concurrency  # X3 and the units beside it, before the cache holds
    expected = expected_charge(requests, cost_weights(context.llm), uncached_first=first)
    watched = Watched(units, prefix, expected, usage.token_limit, usage.tokens_left)
    log.info(
        "budget watch: %d units, prefix %d, expected %d of %d, %s left",
        units, prefix, expected, watched.ceiling, watched.left,
    )  # fmt: skip
    if watched.left is not None and expected > watched.left:
        raise PermanentError(
            "run_over_budget",
            f"the rest of the run is expected to charge {expected} tokens, {watched.left} are left"
            f" ({units} units, prefix {prefix})",
        )
    return watched
