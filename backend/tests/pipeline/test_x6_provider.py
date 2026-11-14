"""X6 where the provider fails a package (audit 2026-11-14): the packages asking beside it are answered
and written, no package begins after it, and the run ends by it - refused for good as model_refused,
after which X5 checks what was written, any other for the job's next attempt. A model stands in."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo

from app.jobs.outcome import PermanentError
from app.pipeline import x6_repair
from tests.pipeline.provider_support import asks, provider_failed, refusal, usage_rows, waited
from tests.pipeline.test_run import context_of, setup
from tests.pipeline.test_x4_statements import with_concurrency
from tests.pipeline.test_x6_repair import Quoting, a_repair, extracted, not_found, runs_of, wordings

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["provider_failed", "setup", "waited"]  # the fixtures, shared with test_run and provider_support


async def failures(connection: Any, document: Any) -> list[tuple[Any, ...]]:
    return [
        (stage, outcome, result.get("failure"))
        for stage, outcome, result in await runs_of(connection, document)
    ]


async def test_a_provider_s_error_in_one_package_lets_the_others_finish(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float], provider_failed: asyncio.Event
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E2", "E3", "E4"))
    job = await a_repair(connection, document)
    fixer = Quoting()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise refusal(503)
        if asks(messages, "E3"):
            await provider_failed.wait()  # answered once E2 is given up on, never before
        return fixer(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 2)
    with pytest.raises(ModelHTTPError):
        await x6_repair.repair_document(context, job)

    assert fixer.units == ["E3"]  # E4 never asked
    assert "Aussage E3" not in (written := await wordings(connection, document))
    assert {"Aussage E2", "Aussage E4"} <= set(written)
    assert await usage_rows(connection, job, "x6.unit") == [
        (1, 0, False), (1, 0, False), (1, 0, False), (1, 1_100, False), ("held", 0),
    ]  # fmt: skip
    assert await failures(connection, document) == [("X5", "done", None), ("X6", "failed", "ModelHTTPError")]


async def test_a_repair_refused_for_good_ends_without_another_attempt(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float]
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E3",))
    job = await a_repair(connection, document)

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise refusal(403)

    with pytest.raises(PermanentError) as ended:
        await x6_repair.repair_document(context_of(pool, tmp_path, answer, database_url), job)

    assert ended.value.code == "model_refused"
    assert waited == []
    assert "Aussage E3" in await wordings(connection, document)
    assert await usage_rows(connection, job, "x6.unit") == [(1, 0, False), ("held", 0)]
    assert await failures(connection, document) == [  # checked again, as a repair began
        ("X5", "done", None), ("X6", "failed", "model_refused"), ("X5", "done", None),
    ]  # fmt: skip


async def test_a_repair_refused_for_good_still_checks_what_the_packages_beside_it_wrote(
    setup: Any, tmp_path: Path, database_url: str, waited: list[float], provider_failed: asyncio.Event
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E2", "E3"))
    fixer = Quoting()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E2"):
            raise refusal(401)
        if asks(messages, "E3"):
            await provider_failed.wait()
        return fixer(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 2)
    with pytest.raises(PermanentError) as ended:
        await x6_repair.repair_document(context, await a_repair(connection, document))

    assert ended.value.code == "model_refused"
    assert await failures(connection, document) == [
        ("X5", "done", None), ("X6", "failed", "model_refused"), ("X5", "done", None),
    ]  # fmt: skip
    assert await not_found(connection, document) == ["Aussage E2"]  # E3's, written anew, checked
