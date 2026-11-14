"""X4 where the provider fails a unit (audit 2026-11-14): the units asking beside it are answered and
written, no unit begins after it, and the run ends by it - a request refused for good as
model_refused, any other for the job's next attempt; every request booked as it ended, nothing
estimated, nothing held. A model stands in (FunctionModel)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo

from app.jobs.outcome import PermanentError
from app.pipeline.run import extract_document
from tests.pipeline.provider_support import asks, provider_failed, refusal, usage_rows, waited
from tests.pipeline.test_run import Model, a_document, a_job, context_of, rows, setup
from tests.pipeline.test_x4_statements import FIELDS, units_done, with_concurrency, x4_runs

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["provider_failed", "setup", "waited"]  # the fixtures, shared with test_run and provider_support


async def test_a_provider_s_error_in_one_unit_lets_those_asking_beside_it_finish_and_begins_no_other(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float], provider_failed: asyncio.Event
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise refusal(500)
        if asks(messages, "E3"):
            await provider_failed.wait()  # answered once E2 is given up on, never before
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


async def test_an_answer_no_model_could_read_lets_those_asking_beside_it_finish(
    setup: Any, tmp_path: Path, database_url: str, provider_failed: asyncio.Event
) -> None:
    # a proxy's page in place of an answer is the provider's fault as a refusal is
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise UnexpectedModelBehavior("an answer no model could read (invented)")
        if asks(messages, "E3"):
            await provider_failed.wait()
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 2)
    with pytest.raises(UnexpectedModelBehavior):  # the job's next attempt asks again
        await extract_document(context, job)

    assert [key for key, _, _ in await units_done(connection, document)] == ["E3"]
    assert model.units == ["E3"]
    assert await usage_rows(connection, job) == [(1, 1_100, False), ("held", 0)]
    assert [(outcome, result["failure"]) for outcome, result in await x4_runs(connection, document)] == [
        ("failed", "UnexpectedModelBehavior")
    ]


async def test_a_quota_spent_at_the_provider_ends_the_job_for_good(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float]
) -> None:
    # a 429 that says so is not waited on; the job's attempts would meet it again
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise refusal(429, code="insufficient_quota")
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 1)
    with pytest.raises(PermanentError) as ended:
        await extract_document(context, job)

    assert ended.value.code == "model_refused"
    assert (waited, model.units) == ([], [])
    assert await usage_rows(connection, job) == [(1, 0, False), ("held", 0)]
    assert [(outcome, result["failure"]) for outcome, result in await x4_runs(connection, document)] == [
        ("failed", "model_refused")
    ]


async def test_a_provider_that_never_answered_in_time_lets_those_asking_beside_it_finish(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float], provider_failed: asyncio.Event
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise ModelAPIError("gpt-6-luna", "Request timed out (invented)")
        if asks(messages, "E3"):
            await provider_failed.wait()
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 2)
    with pytest.raises(ModelAPIError):  # for the job's next attempt
        await extract_document(context, job)

    assert waited == []  # a request sent and never answered is not asked again at once
    assert [key for key, _, _ in await units_done(connection, document)] == ["E3"]
    assert model.units == ["E3"]
    # the stand-in sent nothing over the wire: E2's reservation is handed back, not estimated
    assert await usage_rows(connection, job) == [(1, 1_100, False), ("held", 0)]


async def test_a_second_provider_error_among_the_units_asking_is_dropped_and_said(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()
    both = asyncio.Barrier(2)

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2") or asks(messages, "E3"):
            await both.wait()  # both asking before either fails: the second meets the first's word
            raise refusal(400)
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 2)
    with (
        caplog.at_level("WARNING", logger="app.pipeline.side_by_side"),
        pytest.raises(PermanentError) as ended,
    ):
        await extract_document(context, job)

    assert ended.value.code == "model_refused"  # by the first
    assert model.units == []  # E4 never asked
    dropped = [record.getMessage() for record in caplog.records if "dropped" in record.getMessage()]
    assert dropped == ["a further provider error was dropped: ModelHTTPError"]
    assert await usage_rows(connection, job) == [(1, 0, False), (1, 0, False), ("held", 0)]


async def test_the_next_attempt_after_a_provider_s_error_asks_only_the_units_not_written(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float], provider_failed: asyncio.Event
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    model = Model()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise refusal(503)
        if asks(messages, "E3"):
            await provider_failed.wait()
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 2)
    with pytest.raises(ModelHTTPError):
        await extract_document(context, await a_job(connection, document.id, document.owner_id))
    again, after = await a_job(connection, document.id, document.owner_id), Model()

    await extract_document(
        with_concurrency(context_of(pool, tmp_path, after, database_url), database_url, 2), again
    )

    assert sorted(after.units) == ["E2", "E4"]  # the one that failed and the one never begun
    assert [key for key, _, _ in await units_done(connection, document)] == ["E2", "E3", "E4"]
    assert await usage_rows(connection, again) == [(1, 1_100, False), (1, 1_100, False), ("held", 0)]


async def test_a_request_the_provider_timed_out_is_left_to_the_job_s_next_attempt(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float]
) -> None:
    # a 408 is a 4xx and no refusal for good
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise refusal(408)
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 1)
    with pytest.raises(ModelHTTPError) as ended:
        await extract_document(context, job)

    assert (ended.value.status_code, waited, model.units) == (408, [], [])
    assert await usage_rows(connection, job) == [(1, 0, False), ("held", 0)]
