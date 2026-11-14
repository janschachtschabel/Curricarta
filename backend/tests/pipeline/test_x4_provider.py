"""X4 where the provider fails a unit (audit 2026-11-14): the units asking beside it are answered and
written, no unit begins after it, and the run ends by it - a request refused for good as
model_refused, any other for the job's next attempt; every request booked as it ended, nothing
estimated, nothing held. A model stands in (FunctionModel)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo

from app.jobs.outcome import PermanentError
from app.pipeline.run import extract_document
from tests.pipeline.provider_support import asks, refusal, usage_rows, waited
from tests.pipeline.test_run import Model, a_document, a_job, context_of, rows, setup
from tests.pipeline.test_x4_statements import FIELDS, units_done, with_concurrency, x4_runs

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup", "waited"]  # the fixtures, shared with test_run and provider_support


async def test_a_provider_s_error_in_one_unit_lets_those_asking_beside_it_finish_and_begins_no_other(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float]
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()
    e2_asked = []

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            e2_asked.append(1)
            raise refusal(500)
        if asks(messages, "E3"):
            while len(e2_asked) < 3:  # E2 given up on while E3 is asked
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.3)  # and its place at the gate taken by E4 meanwhile
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 2)
    with pytest.raises(ModelHTTPError) as ended:
        await extract_document(context, job)

    assert ended.value.status_code == 500  # the job's next attempt asks again
    assert waited == [20.0, 40.0]
    assert [key for key, _, _ in await units_done(connection, document)] == ["E3"]
    assert model.units == ["E3"]  # E4 never asked
    # E2's three refusals a request each, E3's answer as it reported it: nothing estimated, nothing held
    assert await usage_rows(connection, job) == [
        (1, 0, False), (1, 0, False), (1, 0, False), (1, 1_100, False), ("held", 0),
    ]  # fmt: skip
    [(estimated,)] = await rows(
        connection, "SELECT count(*) FROM llm_usage WHERE job_id = %s AND estimated", job.id
    )
    assert estimated == 0
    assert [(outcome, result["failure"]) for outcome, result in await x4_runs(connection, document)] == [
        ("failed", "ModelHTTPError")
    ]


async def test_a_request_refused_for_good_ends_the_job_without_another_attempt(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float]
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise refusal(401)  # a key the provider does not take: no attempt gets further
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 1)
    with pytest.raises(PermanentError) as ended:
        await extract_document(context, job)

    assert ended.value.code == "model_refused"
    assert isinstance(ended.value.__cause__, ModelHTTPError)
    assert (waited, model.units) == ([], [])  # not waited on; E2 the first, no unit begun after it
    assert await usage_rows(connection, job) == [(1, 0, False), ("held", 0)]
    assert [(outcome, result["failure"]) for outcome, result in await x4_runs(connection, document)] == [
        ("failed", "model_refused")
    ]


async def test_a_rate_limit_that_outlasts_its_waits_is_left_to_the_job_s_next_attempt(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float]
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise refusal(429)
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 1)
    with pytest.raises(ModelHTTPError) as ended:
        await extract_document(context, job)

    assert ended.value.status_code == 429  # no PermanentError: the queue asks again
    assert (waited, model.units) == ([20.0, 40.0], [])
    assert await usage_rows(connection, job) == [(1, 0, False)] * 3 + [("held", 0)]
    assert [(outcome, result["failure"]) for outcome, result in await x4_runs(connection, document)] == [
        ("failed", "ModelHTTPError")
    ]
