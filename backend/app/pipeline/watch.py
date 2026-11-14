"""The watch after X2 (plan H-3, 3.6): once X2 has cut the units, and before X3 or X4 asks the model,
a job of ``extract.run`` reckons what the rest of its run needs (app/pipeline/reckoned.py) and ends as
``run_over_budget`` where the account's quota has not that much left. Nothing is sent; X1 and X2 stay
done, and a new job - with more budget, or with the watch off - goes on at X3.

What the rest needs is two figures. ``expected``: what X3 (where open) and each unit X4 would ask are
expected to charge (``expected_charge``: each shared part read from the cache but for the first requests
of each prefix asked at once, each answer at the measured mean). ``room``: what the requests asked at
once hold beyond that while they wait (``room_for``) - a request reserves its input and its whole output
cap at the output weight, books about a tenth of it, and once one reservation is refused X4 begins no
further unit and the run ends ``budget_exhausted``, paid for in part. The watch lets a run pass only
where ``expected + room`` is left.

What is left is read as a reservation reads it (app/usage/ledger.py, ``usage_of``): the limit less what
the account spent and what its requests hold - this job's and those of its other jobs -, under the job's
lease, after the reckoning (which may take long for a long document; the limit alone is read before, to
pass over an account without one). It is a look at one moment, not a reservation: other jobs of the
account may spend what it saw left, and a run may charge more than expected (an answer out of form asks
again, a cache dropped is read whole, answers longer than the mean). So a run the watch let pass may
still end as ``budget_exhausted`` when a reservation finds too little - the quota stays the hard stop
behind it, and the units done stay. EXTRACT_BUDGET_WATCH turns it off; an account without a limit is not
watched.

To stop a run after X2 on purpose (a pilot): set the account's limit to what it spent so far plus X1's
``charged_at_most`` from the estimate, and start. The run ends ``run_over_budget`` after X2 where the rest
needs more than X1's reservations leave over - for a small document it may not, and the run goes on past
X2, the account spending no more than its limit. Then read the failure's numbers, run the estimate again,
raise the limit to the spend plus at least ``charged_expected + room``, and start again: the stop cost no
request, X1 and X2 stay, and the new start is admitted (spent below the limit).
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
from app.pipeline.reckoned import expected_charge, owed_questions, room_for, statement_units
from app.pipeline.side_by_side import at_once
from app.pipeline.x4_question import unit_questions
from app.usage.ledger import usage_of

log = logging.getLogger("app.pipeline.watch")


@dataclass(frozen=True)
class Watched:
    units: int  # the units X4 would ask
    prefix_tokens: int  # X3's prefix, counted plainly
    expected: int  # what the rest is expected to charge, weighed
    room: int  # what the requests asked at once hold beyond their expected charge
    ceiling: int  # the account's limit
    left: int | None  # of it, what is neither spent nor held


async def watch_budget(
    context: JobContext, job: Job, document: Document, blocks: Sequence[Block], printed: Sequence[str | None]
) -> Watched | None:
    """What the rest of the run on ``document`` - X2 done on it - needs beside what its account has
    left, logged; None where the watch is off, the account has no limit, or X3 and X4 are done.
    PermanentError ``run_over_budget`` where ``expected + room`` is more than is left;
    ``prefix_too_long`` (and ``model_not_configured``) as the stages would end the job."""
    if not context.settings.extract_budget_watch:
        return None
    async with context.pool.connection() as connection:
        if {"X3", "X4"} <= await done_stages(connection, document.id):
            return None
        if (await usage_of(connection, document.owner_id)).token_limit is None:
            return None
        model, _ = model_of(context)
        assert context.llm is not None  # noqa: S101 - the stage has its model (model_of)
        ground = await ground_of(connection, document)
        owing = await owed_questions(connection, context.llm, document, blocks, printed, ground, model)
    # the counting outside the pool, as X4 counts: every unit's question, seconds for a long document
    requests = await owing.requests(model, context.settings.ontology_dir)
    prefix = await owing.prefix_tokens()
    weights, first, units = cost_weights(context.llm), at_once(context.settings), len(owing.units)
    expected = expected_charge(requests, weights, uncached_first=first)
    room = room_for(requests, weights, at_once=first, units=units)
    async with context.pool.connection() as connection, connection.transaction():
        await hold_lease(connection, job)
        usage = await usage_of(connection, document.owner_id)
    if usage.token_limit is None:  # lifted while the rest was reckoned
        return None
    watched = Watched(units, prefix, expected, room, usage.token_limit, usage.tokens_left)
    log.info(
        "budget watch: %d units, prefix %d, expected %d, room %d, limit %d, %s left",
        units, prefix, expected, room, watched.ceiling, watched.left,
    )  # fmt: skip
    if watched.left is not None and expected + room > watched.left:
        raise PermanentError(
            "run_over_budget",
            f"the rest of the run is expected to charge {expected} tokens and to hold {room} more at once,"
            f" {watched.left} are left ({units} units, prefix {prefix})",
        )
    return watched


async def check_windows(
    context: JobContext, document: Document, blocks: Sequence[Block], printed: Sequence[str | None]
) -> None:
    """PermanentError (prefix_too_long) where a unit X4 would ask fits no window - checked before X3
    asks, in every run, so that a document whose units X4 would refuse pays for no frame. The watch,
    where it looks, has checked them as it reckoned. X4's prefix lacks X3's choice lists here: X4
    checks again before it asks."""
    model, _ = model_of(context)
    assert context.llm is not None  # noqa: S101 - the stage has its model (model_of)
    async with context.pool.connection() as connection:
        units = await statement_units(connection, document, model)
        ground = await ground_of(connection, document)
        questions = await unit_questions(connection, context.llm, document, blocks, printed, ground, model)
    await questions.check(units)  # counted outside the pool, as X4 counts
