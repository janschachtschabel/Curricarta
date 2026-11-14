"""The watch after X2 (app/pipeline/watch.py): once the units are cut, a job reckons what the rest of
its run is expected to charge and ends as run_over_budget, before X3 asks, where what is left of the
account's quota does not hold it; X1 and X2 stay, and a new job with budget goes on at X3. A model
stands in (FunctionModel), never a provider."""

import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo

from app.db.conversions import all_blocks, printed_pages
from app.db.documents import Document, document_for_job
from app.db.runs import done_stages
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from app.llm.client import cost_weights
from app.pipeline import watch
from app.pipeline.ground import ground_of
from app.pipeline.reckoned import expected_charge, owed_requests
from app.pipeline.run import extract_document
from app.pipeline.watch import watch_budget
from tests.llm.test_client import llm_settings
from tests.pipeline.test_run import Model, a_document, a_job, context_of, is_profile, rows, setup
from tests.pipeline.test_x4_statements import with_concurrency
from tests.support import unwatched

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run

UNCACHED_FIRST = 5  # X3 and the EXTRACT_CONCURRENCY (4) units that begin beside it


def tightening(connection: psycopg.AsyncConnection, document: Document, model: Model) -> Any:
    """``model``, but once the profile is answered the account's limit falls to 4,000: X1's outline,
    reserved before, is booked (3,000 spent), and the rest of the run finds 1,000 left."""

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not is_profile(messages):
            await connection.execute(
                "UPDATE quota SET token_limit = 4000 WHERE account_id = %s", (document.owner_id,)
            )
        return model(messages, info)

    return answer


async def ended_after_x2(
    setup: tuple[Any, psycopg.AsyncConnection], tmp_path: Path, database_url: str, model: Model
) -> tuple[Document, PermanentError]:
    pool, connection = setup
    document = await a_document(connection)
    context = context_of(pool, tmp_path, tightening(connection, document, model), database_url)
    with pytest.raises(PermanentError) as ended:
        await extract_document(context, await a_job(connection, document.id, document.owner_id))
    return document, ended.value


async def reckoned_now(
    connection: psycopg.AsyncConnection, context: JobContext, document: Document
) -> tuple[int, int]:
    """What the rest owes the document now, as the watch reckons it: units and the expected charge."""
    current = await document_for_job(connection, document.id)
    assert current is not None and context.llm is not None and context.model is not None
    blocks = await all_blocks(connection, current.conversion_id)
    printed = await printed_pages(connection, current.conversion_id)
    ground = await ground_of(connection, current)
    requests, units = await owed_requests(
        connection,
        context.llm,
        current,
        blocks,
        printed,
        ground,
        context.model(),
        context.settings.ontology_dir,
    )
    weights = cost_weights(context.llm)
    return units, expected_charge(requests, weights, uncached_first=UNCACHED_FIRST)


async def test_a_run_whose_rest_the_budget_does_not_hold_ends_after_x2_and_asks_nothing_more(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    _, connection = setup
    model = Model()

    document, ended = await ended_after_x2(setup, tmp_path, database_url, model)

    assert ended.code == "run_over_budget"
    assert re.fullmatch(
        r"the rest of the run is expected to charge \d+ tokens, 1000 are left \(2 units, prefix \d+\)",
        ended.message,
    )
    assert await done_stages(connection, document.id) == {"X1", "X2"}
    assert (model.asked, model.units) == (["profile", "outline"], [])  # neither the frame nor a unit
    assert await rows(
        connection,
        "SELECT count(*) FROM llm_usage WHERE account_id = %s AND purpose IN ('x3.frame', 'x4.unit')",
        document.owner_id,
    ) == [(0,)]
    assert await rows(
        connection, "SELECT count(*) FROM usage_reservation WHERE account_id = %s", document.owner_id
    ) == [(0,)]


async def test_a_new_job_with_budget_goes_on_at_x3(setup: Any, tmp_path: Path, database_url: str) -> None:
    pool, connection = setup
    model = Model()
    document, _ = await ended_after_x2(setup, tmp_path, database_url, model)
    await connection.execute(
        "UPDATE quota SET token_limit = 1000000000 WHERE account_id = %s", (document.owner_id,)
    )

    made = await extract_document(
        context_of(pool, tmp_path, model, database_url),
        await a_job(connection, document.id, document.owner_id),
    )

    assert made["stages"] == ["X1", "X2", "X3", "X4", "X5"]
    assert model.asked == ["profile", "outline", "frame"]  # X1 is not asked again
    assert sorted(model.units) == ["E1", "E2"]
    assert await done_stages(connection, document.id) == {"X1", "X2", "X3", "X4", "X5"}


async def test_an_account_without_a_limit_is_not_watched(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # nothing is reckoned for it either: the reckoning reads every unit's question
    pool, connection = setup
    document = await a_document(connection, token_limit=None)

    async def reckoning(*_: Any) -> Any:
        raise AssertionError("an account without a limit was reckoned")

    monkeypatch.setattr(watch, "owed_requests", reckoning)

    made = await extract_document(
        context_of(pool, tmp_path, Model(), database_url),
        await a_job(connection, document.id, document.owner_id),
    )

    assert made["stages"] == ["X1", "X2", "X3", "X4", "X5"]


async def test_the_watch_switched_off_lets_the_run_spend_until_the_budget_ends(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # as before the watch: X3's reservation finds too little left
    pool, connection = setup
    document = await a_document(connection)
    model = Model()
    context = context_of(pool, tmp_path, tightening(connection, document, model), database_url)

    with pytest.raises(PermanentError) as ended:
        await extract_document(
            unwatched(context, database_url), await a_job(connection, document.id, document.owner_id)
        )

    assert ended.value.code == "budget_exhausted"
    assert await done_stages(connection, document.id) == {"X1", "X2"}


async def test_units_done_before_are_not_reckoned_again(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # a job ended at the quota midway through X4, one unit at a time: E1 written, E2 open
    pool, connection = setup
    document = await a_document(connection)
    model = Model()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        made = model(messages, info)
        if model.units == ["E1"]:
            await connection.execute(
                "UPDATE quota SET token_limit = 4500 WHERE account_id = %s", (document.owner_id,)
            )
        return made

    first = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 1)
    with pytest.raises(PermanentError) as ended:
        await extract_document(first, await a_job(connection, document.id, document.owner_id))
    assert ended.value.code == "budget_exhausted"
    await connection.execute(
        "UPDATE quota SET token_limit = 1000000000 WHERE account_id = %s", (document.owner_id,)
    )
    context = context_of(pool, tmp_path, Model(), database_url)
    current = await document_for_job(connection, document.id)
    assert current is not None
    blocks = await all_blocks(connection, current.conversion_id)
    printed = await printed_pages(connection, current.conversion_id)

    watched = await watch_budget(
        context, await a_job(connection, document.id, document.owner_id), current, blocks, printed
    )

    assert watched is not None
    assert (watched.units, watched.expected) == await reckoned_now(connection, context, document)
    assert watched.units == 1  # E2 alone; X3 is done and not reckoned either
    assert watched.ceiling == 1_000_000_000
    assert watched.left is not None and watched.expected < watched.left


async def test_a_run_the_budget_holds_logs_what_it_reckoned(
    setup: Any, tmp_path: Path, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    pool, connection = setup
    document = await a_document(connection, token_limit=1_000_000_000)

    with caplog.at_level(logging.INFO, logger="app.pipeline.watch"):
        made = await extract_document(
            context_of(pool, tmp_path, Model(), database_url),
            await a_job(connection, document.id, document.owner_id),
        )

    assert made["stages"] == ["X1", "X2", "X3", "X4", "X5"]
    [line] = caplog.messages
    found = re.fullmatch(
        r"budget watch: 2 units, prefix (\d+), expected (\d+) of 1000000000, (\d+) left", line
    )
    assert found is not None
    prefix, expected, left = (int(group) for group in found.groups())
    assert prefix > 0 and 0 < expected <= left < 1_000_000_000


async def test_a_prefix_no_window_fits_stays_the_stage_s_refusal(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # though the budget would not hold the rest either: the stage's own word comes first, as before
    pool, connection = setup
    document, _ = await ended_after_x2(setup, tmp_path, database_url, Model())
    narrow = replace(
        context_of(pool, tmp_path, Model(), database_url), llm=llm_settings(llm_context_tokens=20_000)
    )

    with pytest.raises(PermanentError) as ended:
        await extract_document(narrow, await a_job(connection, document.id, document.owner_id))

    assert ended.value.code == "prefix_too_long"
    assert await done_stages(connection, document.id) == {"X1", "X2"}
