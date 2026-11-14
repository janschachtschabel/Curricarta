"""X4 where a unit's answer is cut at the output cap (audit 2026-11-14): the unit stays open, a finding
names it with the cap, the run ends as answer_cut; no job asks it again under a cap no higher, one under
a higher cap does. A model stands in (FunctionModel)."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from app.db.findings import add_findings
from app.jobs.outcome import PermanentError
from app.jobs.queue import LeaseLost
from app.pipeline import x4_statements
from app.pipeline.run import extract_document
from app.pipeline.x4_unit import write_unit
from tests.pipeline.provider_support import usage_rows
from tests.pipeline.test_run import Model, a_document, a_job, context_of, rows, setup
from tests.pipeline.test_x3_frame import prompt_of
from tests.pipeline.test_x4_statements import FIELDS, units_done, with_concurrency, x4_runs

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run


def cutting(model: Model, *keys: str) -> Any:
    """The model's answers, but those of the units ``keys``: cut at the cap, mid-way through their output."""

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = prompt_of(messages)
        for key in keys:
            if f"=== EINHEIT ===\n{key} " in prompt:
                model.units.append(key)
                part = ToolCallPart(info.output_tools[0].name, f'{{"unitKey": "{key}", "statements": [')
                usage = RequestUsage(input_tokens=1_000, output_tokens=4_000)
                return ModelResponse(parts=[part], usage=usage, finish_reason="length")
        return model(messages, info)

    return answer


async def x4_findings(connection: Any, document: Any) -> list[tuple[Any, ...]]:
    return await rows(
        connection,
        "SELECT rule, severity, details FROM validation_finding WHERE document_id = %s AND rule LIKE 'x4.%%'"
        " ORDER BY rule, created_at",
        document.id,
    )


async def test_a_unit_whose_answer_was_cut_stays_open_is_named_with_the_cap_and_ends_the_job_as_answer_cut(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model(units={"E4": {"unitKey": "E9", "statements": [], "checkedAbsent": []}})

    with pytest.raises(PermanentError) as ended:
        await extract_document(context_of(pool, tmp_path, cutting(model, "E3"), database_url), job)

    assert ended.value.code == "answer_cut"  # before model_unanswered, which E4 is
    assert sorted(model.units) == ["E2", "E3", "E4"]  # E3 asked once
    assert [key for key, _, _ in await units_done(connection, document)] == ["E2"]
    assert [(outcome, result) for outcome, result in await x4_runs(connection, document)] == [
        ("failed", {"failure": "answer_cut"})
    ]
    assert await x4_findings(connection, document) == [
        ("x4.answer_cut", "warning", {"units": ["E3"], "cap": 4_000}),
        ("x4.unanswered", "warning", {"units": ["E4"]}),
    ]
    # E3's one request booked as it reported it; nothing held
    assert await rows(
        connection,
        "SELECT sum(requests), sum(output_tokens) FILTER (WHERE output_tokens = 4000), bool_or(estimated)"
        " FROM llm_usage WHERE job_id = %s AND purpose = 'x4.unit'",
        job.id,
    ) == [(3, 4_000, False)]
    assert await rows(connection, "SELECT count(*) FROM usage_reservation WHERE job_id = %s", job.id) == [
        (0,)
    ]


async def test_a_new_job_under_the_same_cap_asks_no_cut_unit_again_and_spends_nothing_on_it(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    model = Model()
    context = context_of(pool, tmp_path, cutting(model, "E3"), database_url)
    with pytest.raises(PermanentError):
        await extract_document(context, await a_job(connection, document.id, document.owner_id))
    again = await a_job(connection, document.id, document.owner_id)

    with pytest.raises(PermanentError) as ended:
        await extract_document(context, again)

    assert ended.value.code == "answer_cut"
    assert sorted(model.units) == ["E2", "E3", "E4"]  # none asked by the new job
    assert await rows(connection, "SELECT count(*) FROM llm_usage WHERE job_id = %s", again.id) == [(0,)]
    assert await rows(connection, "SELECT count(*) FROM usage_reservation WHERE job_id = %s", again.id) == [
        (0,)
    ]
    assert [result for _, result in await x4_runs(connection, document)] == [{"failure": "answer_cut"}] * 2
    assert await x4_findings(connection, document) == [  # named once, by the run that was cut
        ("x4.answer_cut", "warning", {"units": ["E3"], "cap": 4_000})
    ]


async def test_a_new_job_under_a_higher_cap_asks_the_cut_unit_and_the_finding_goes_once_x4_is_done(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    model = Model()
    context = context_of(pool, tmp_path, cutting(model, "E3"), database_url)
    with pytest.raises(PermanentError):
        await extract_document(context, await a_job(connection, document.id, document.owner_id))
    higher = FunctionModel(model, settings={"max_tokens": 8_000})

    await extract_document(
        replace(context, model=lambda: higher), await a_job(connection, document.id, document.owner_id)
    )

    assert sorted(model.units) == ["E2", "E3", "E3", "E4"]
    assert [key for key, _, _ in await units_done(connection, document)] == ["E2", "E3", "E4"]
    assert [outcome for outcome, _ in await x4_runs(connection, document)] == ["failed", "done"]
    assert await x4_findings(connection, document) == []


async def test_a_cut_is_named_at_once_and_no_next_attempt_pays_for_it_though_a_neighbour_s_write_broke(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    model = Model()

    async def broken(connection: Any, job: Any, document: Any, unit: Any, *args: Any, **kwargs: Any) -> Any:
        if unit.key == "E4":  # one at a time: after E3 was cut
            raise RuntimeError("the write was refused (invented)")
        return await write_unit(connection, job, document, unit, *args, **kwargs)

    monkeypatch.setattr(x4_statements, "write_unit", broken)
    context = with_concurrency(
        context_of(pool, tmp_path, cutting(model, "E3"), database_url), database_url, 1
    )
    with pytest.raises(RuntimeError):  # no answer_cut: the run passed its end by
        await extract_document(context, await a_job(connection, document.id, document.owner_id))
    assert await x4_findings(connection, document) == [
        ("x4.answer_cut", "warning", {"units": ["E3"], "cap": 4_000})
    ]
    monkeypatch.setattr(x4_statements, "write_unit", write_unit)
    again = await a_job(connection, document.id, document.owner_id)

    with pytest.raises(PermanentError) as ended:
        await extract_document(context, again)

    assert ended.value.code == "answer_cut"
    assert sorted(model.units) == ["E2", "E3", "E4", "E4"]  # E3 not asked again
    assert await usage_rows(connection, again) == [(1, 1_100, False), ("held", 0)]  # E4's alone


async def test_a_cut_unit_read_under_a_higher_cap_takes_its_finding_along_before_x4_is_done(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    model = Model(units={"E4": {"unitKey": "E9", "statements": [], "checkedAbsent": []}})
    context = context_of(pool, tmp_path, cutting(model, "E3"), database_url)
    with pytest.raises(PermanentError):
        await extract_document(context, await a_job(connection, document.id, document.owner_id))
    higher = FunctionModel(model, settings={"max_tokens": 8_000})

    with pytest.raises(PermanentError) as ended:  # E4 out of form again
        await extract_document(
            replace(context, model=lambda: higher), await a_job(connection, document.id, document.owner_id)
        )

    assert ended.value.code == "model_unanswered"
    assert [key for key, _, _ in await units_done(connection, document)] == ["E2", "E3"]
    assert [rule for rule, _, _ in await x4_findings(connection, document)] == ["x4.unanswered"] * 2


async def test_a_unit_cut_again_under_a_higher_cap_has_one_finding_with_the_higher_cap(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    model = Model()
    context = context_of(pool, tmp_path, cutting(model, "E3"), database_url)
    with pytest.raises(PermanentError):
        await extract_document(context, await a_job(connection, document.id, document.owner_id))
    higher = FunctionModel(cutting(model, "E3"), settings={"max_tokens": 8_000})

    with pytest.raises(PermanentError):
        await extract_document(
            replace(context, model=lambda: higher), await a_job(connection, document.id, document.owner_id)
        )

    assert sorted(model.units) == ["E2", "E3", "E3", "E4"]
    assert await x4_findings(connection, document) == [
        ("x4.answer_cut", "warning", {"units": ["E3"], "cap": 8_000})
    ]


async def test_a_cut_is_named_though_a_cancel_comes_as_its_finding_is_written(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    writing, written = asyncio.Event(), asyncio.Event()

    async def slow(connection: Any, document_id: Any, run_id: Any, findings: Any) -> None:
        if any(found.rule == "x4.answer_cut" for found in findings):
            writing.set()
            await asyncio.wait_for(written.wait(), 10)
        await add_findings(connection, document_id, run_id, findings)

    monkeypatch.setattr(x4_statements, "add_findings", slow)
    context = with_concurrency(
        context_of(pool, tmp_path, cutting(Model(), "E3"), database_url), database_url, 1
    )
    job = asyncio.create_task(
        extract_document(context, await a_job(connection, document.id, document.owner_id))
    )
    await asyncio.wait_for(writing.wait(), 10)
    job.cancel()
    await asyncio.sleep(0)  # the cancel reaches the unit while its finding is written
    written.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    for _ in range(200):  # the note's write goes on beside the cancel
        if await x4_findings(connection, document):
            break
        await asyncio.sleep(0.01)

    assert await x4_findings(connection, document) == [
        ("x4.answer_cut", "warning", {"units": ["E3"], "cap": 4_000})
    ]


async def test_a_cut_is_named_under_the_lease_only(setup: Any, tmp_path: Path, database_url: str) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()
    cut = cutting(model, "E3")

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if "=== EINHEIT ===\nE3 " in prompt_of(messages):  # the lease goes as E3 is answered, cut
            await connection.execute(
                "UPDATE job SET lease_expires_at = now() - interval '1 second' WHERE id = %s", (job.id,)
            )
        return cut(messages, info)  # type: ignore[no-any-return]

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 1)
    with pytest.raises(LeaseLost):
        await extract_document(context, job)

    assert await x4_findings(connection, document) == []
