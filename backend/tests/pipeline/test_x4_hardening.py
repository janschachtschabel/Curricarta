"""X4 in the job extract.run where something breaks (plan M1 7b, F11; review 7b C1-C6): a unit no window
fits ends the job before any unit is asked; an error in one unit ends the others asking beside it, the
error the job's with its cause; at most the pool's connections but one at a time; each finding of a
unit's reading names its unit; a stage that cannot be set up ends its run. A model stands in."""

import asyncio
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo

from app.jobs.outcome import PermanentError
from app.jobs.queue import LeaseLost
from app.llm import calls
from app.llm.schema import load_schema
from app.pipeline import x4_statements
from app.pipeline.run import extract_document
from tests.llm.test_client import llm_settings
from tests.pipeline.test_run import (
    BODY,
    CV,
    Model,
    a_document,
    a_job,
    a_statement,
    block,
    context_of,
    rows,
    setup,
)
from tests.pipeline.test_x3_frame import prompt_of, x3_run
from tests.pipeline.test_x4_statements import FIELDS, units_done, with_concurrency, x4_runs
from tests.support import make_settings

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run

# "Inhaltsfeld 3" alone is longer than a small context window holds; the frame's window and the
# others' leave it out
LONG = [*FIELDS[:-1], block("p3-b4", " ".join([BODY] * 120))]


async def test_a_unit_no_window_fits_ends_the_job_before_any_unit_is_asked(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=LONG)
    model = Model()
    context = context_of(pool, tmp_path, model, database_url)
    small = llm_settings(llm_context_tokens=21_000, llm_max_output_tokens=1_000)  # some 2 700 for a prefix

    with pytest.raises(PermanentError) as ended:
        await extract_document(
            replace(context, llm=small), await a_job(connection, document.id, document.owner_id)
        )

    assert ended.value.code == "prefix_too_long"
    assert [outcome for outcome, _ in await x3_run(connection, document)] == ["done"]
    assert (model.units, await x4_runs(connection, document)) == ([], [])  # none asked, no run begun


async def test_an_error_in_one_unit_ends_those_asking_beside_it_and_nothing_of_them_is_written(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if "=== EINHEIT ===\nE2 " in (prompt := prompt_of(messages)):
            await asyncio.sleep(1)  # E3 is answered meanwhile, and its write finds the lease lost
        elif "=== EINHEIT ===\nE3 " in prompt:
            await connection.execute(
                "UPDATE job SET lease_expires_at = now() - interval '1 second' WHERE id = %s", (job.id,)
            )
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 2)
    with pytest.raises(LeaseLost):
        await extract_document(context, job)

    assert await units_done(connection, document) == []
    assert "E4" not in model.units
    assert [(outcome, result["failure"]) for outcome, result in await x4_runs(connection, document)] == [
        ("failed", "LeaseLost")
    ]


def asks(messages: list[ModelMessage], key: str) -> bool:
    """Whether the request asks for the unit ``key`` - found by content: units asked side by side ask
    in no set order."""
    return f"=== EINHEIT ===\n{key} " in prompt_of(messages)


@pytest.fixture
def waited(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(calls, "_sleep", sleep)
    monkeypatch.setattr(calls, "_draw", lambda: 0.0)
    return slept


def refused(status: int) -> ModelHTTPError:
    return ModelHTTPError(status, "gpt-6-luna", body={"error": {"message": "x", "type": "server_error"}})


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
            raise refused(500)
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
            raise refused(401)  # a key the provider does not take: no attempt gets further
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
            raise refused(429)
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


async def test_the_word_that_units_went_unanswered_is_written_under_the_lease(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    job = await a_job(connection, document.id, document.owner_id)
    model = Model(units={"E4": {"unitKey": "E9", "statements": [], "checkedAbsent": []}})

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if asks(messages, "E4"):  # the last, one at a time: E2 and E3 are written
            await connection.execute(
                "UPDATE job SET lease_expires_at = now() - interval '1 second' WHERE id = %s", (job.id,)
            )
        return model(messages, info)

    context = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 1)
    with pytest.raises(LeaseLost):
        await extract_document(context, job)

    assert [key for key, _, _ in await units_done(connection, document)] == ["E2", "E3"]
    assert await rows(connection, "SELECT rule FROM validation_finding WHERE rule = 'x4.unanswered'") == []


async def test_the_error_that_ended_the_units_keeps_its_cause(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)

    async def refused(*_: Any, **__: Any) -> int:
        raise RuntimeError("the write was refused") from OSError("the database went away")

    monkeypatch.setattr(x4_statements, "write_unit", refused)
    with pytest.raises(RuntimeError) as ended:
        await extract_document(
            context_of(pool, tmp_path, Model(), database_url),
            await a_job(connection, document.id, document.owner_id),
        )

    assert isinstance(ended.value.__cause__, OSError)


async def test_the_error_that_ended_the_units_keeps_the_one_it_was_raised_in_handling(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)

    async def refused(*_: Any, **__: Any) -> int:
        try:
            raise OSError("the database went away")
        except OSError:
            raise RuntimeError("the write was refused")  # noqa: B904 - raised in handling, no cause

    monkeypatch.setattr(x4_statements, "write_unit", refused)
    with pytest.raises(RuntimeError) as ended:
        await extract_document(
            context_of(pool, tmp_path, Model(), database_url),
            await a_job(connection, document.id, document.owner_id),
        )

    logged = "".join(traceback.format_exception(ended.value))  # as the worker logs it
    assert "OSError: the database went away" in logged
    assert "ExceptionGroup" not in logged


async def test_no_more_units_are_asked_at_once_than_the_pool_leaves_beside_the_worker(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    model = Model()
    asking_now = {"now": 0, "most": 0}

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if "=== EINHEIT ===" in prompt_of(messages):
            asking_now["now"] += 1
            asking_now["most"] = max(asking_now["most"], asking_now["now"])
            await asyncio.sleep(0.2)
            asking_now["now"] -= 1
        return model(messages, info)

    settings = make_settings(database_url=database_url, extract_concurrency=4, db_pool_max_size=3)
    context = replace(context_of(pool, tmp_path, answer, database_url), settings=settings)
    await extract_document(context, await a_job(connection, document.id, document.owner_id))

    assert asking_now["most"] == 2


async def test_each_finding_of_a_unit_s_reading_names_its_unit(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    told = a_statement("p2-b3", "Aussage") | {"contextText": "im Labor"}  # in no block of it
    model = Model(units={"E2": {"unitKey": "E2", "statements": [told], "checkedAbsent": []}})

    await extract_document(
        context_of(pool, tmp_path, model, database_url),
        await a_job(connection, document.id, document.owner_id),
    )

    assert await rows(
        connection,
        "SELECT f.rule, f.details ->> 'unit' FROM validation_finding f"
        " JOIN extraction_run r ON r.id = f.run_id WHERE r.stage_iri = %s",
        CV + "stage_X4",
    ) == [("x4.value_from_surroundings", "E2")]


async def test_a_stage_whose_question_cannot_be_set_up_ends_its_run_as_failed(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    load = load_schema

    def missing(directory: Any, name: str) -> Any:
        if name == "x4-aussagen":
            raise FileNotFoundError(name)
        return load(directory, name)

    monkeypatch.setattr("app.pipeline.asking.load_schema", missing)
    with pytest.raises(FileNotFoundError):
        await extract_document(
            context_of(pool, tmp_path, Model(), database_url),
            await a_job(connection, document.id, document.owner_id),
        )

    assert [(outcome, result["failure"]) for outcome, result in await x4_runs(connection, document)] == [
        ("failed", "FileNotFoundError")
    ]
