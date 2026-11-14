"""X4 where a unit's answer is cut at the output cap (audit 2026-11-14): the unit stays open, a finding
names it with the cap, the run ends as answer_cut; no job asks it again under a cap no higher, one under
a higher cap does. A model stands in (FunctionModel)."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from app.jobs.outcome import PermanentError
from app.pipeline.run import extract_document
from tests.pipeline.test_run import Model, a_document, a_job, context_of, rows, setup
from tests.pipeline.test_x3_frame import prompt_of
from tests.pipeline.test_x4_statements import FIELDS, units_done, x4_runs

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
