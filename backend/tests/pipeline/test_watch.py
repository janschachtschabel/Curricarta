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
from app.pipeline.reckoned import expected_charge, owed_requests, room_for
from app.pipeline.run import extract_document
from app.pipeline.watch import watch_budget
from app.usage.ledger import usage_of
from tests.llm.test_client import llm_settings
from tests.pipeline.test_run import Model, a_document, a_job, context_of, is_profile, rows, setup
from tests.pipeline.test_x4_hardening import LONG
from tests.pipeline.test_x4_statements import with_concurrency
from tests.support import unwatched

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run

AT_ONCE = 4  # the units X4 asks at once: EXTRACT_CONCURRENCY, the pool leaving room for it
# a context in which X3's window fits and that of "Inhaltsfeld 3" of LONG does not (test_x4_hardening)
SMALL = llm_settings(llm_context_tokens=21_000, llm_max_output_tokens=1_000)


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
) -> tuple[int, int, int]:
    """What the rest owes the document now, as the watch reckons it: units, the expected charge and the
    room the reservations asked at once need beside it."""
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
    room = room_for(requests, weights, at_once=AT_ONCE, units=units)
    return units, expected_charge(requests, weights, uncached_first=AT_ONCE), room


async def spent(connection: psycopg.AsyncConnection, document: Document) -> int:
    return (await usage_of(connection, document.owner_id)).tokens_spent


async def limit(connection: psycopg.AsyncConnection, document: Document, tokens: int) -> None:
    await connection.execute(
        "UPDATE quota SET token_limit = %s WHERE account_id = %s", (tokens, document.owner_id)
    )


async def watched_now(
    setup: tuple[Any, psycopg.AsyncConnection], tmp_path: Path, database_url: str, document: Document
) -> watch.Watched | None:
    pool, connection = setup
    current = await document_for_job(connection, document.id)
    assert current is not None
    blocks = await all_blocks(connection, current.conversion_id)
    printed = await printed_pages(connection, current.conversion_id)
    job = await a_job(connection, document.id, document.owner_id)
    return await watch_budget(
        context_of(pool, tmp_path, Model(), database_url), job, current, blocks, printed
    )


async def booked_rest(connection: psycopg.AsyncConnection, document: Document) -> list[tuple[Any, ...]]:
    return await rows(
        connection,
        "SELECT purpose, count(*) FROM llm_usage WHERE account_id = %s AND purpose IN ('x3.frame', 'x4.unit')"
        " GROUP BY purpose ORDER BY purpose",
        document.owner_id,
    )


async def test_a_run_the_reservations_would_stop_midway_is_stopped_after_x2_with_nothing_booked(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # left as much as the rest is expected to charge: X3 would be booked, then the units' reservations -
    # each its input and its whole cap at the output weight - would find too little, and the run would end
    # budget_exhausted midway, paid for; the watch counts the room they need and stops it before
    pool, connection = setup
    model = Model()
    document, _ = await ended_after_x2(setup, tmp_path, database_url, model)
    context = context_of(pool, tmp_path, model, database_url)
    _, expected, _ = await reckoned_now(connection, context, document)
    await limit(connection, document, await spent(connection, document) + expected)

    with pytest.raises(PermanentError) as ended:
        await extract_document(context, await a_job(connection, document.id, document.owner_id))

    assert ended.value.code == "run_over_budget"
    assert await booked_rest(connection, document) == []
    assert (model.asked, model.units) == (["profile", "outline"], [])


async def test_the_watch_passes_where_expected_and_room_are_left_and_stops_a_token_below(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document, _ = await ended_after_x2(setup, tmp_path, database_url, Model())
    context = context_of(pool, tmp_path, Model(), database_url)
    units, expected, room = await reckoned_now(connection, context, document)
    exact = await spent(connection, document) + expected + room
    await limit(connection, document, exact)

    watched = await watched_now(setup, tmp_path, database_url, document)
    await limit(connection, document, exact - 1)
    with pytest.raises(PermanentError) as ended:
        await watched_now(setup, tmp_path, database_url, document)

    assert watched is not None
    assert (watched.units, watched.expected, watched.room) == (units, expected, room)
    # two units at once, each holding its cap (4,000 here) at five beyond the answer it is expected to give
    assert (units, room) == (2, 2 * (4_000 - 1_100) * 5)
    assert (watched.ceiling, watched.left) == (exact, expected + room)
    assert ended.value.code == "run_over_budget"
    assert f"{expected} tokens and to hold {room} more at once, {expected + room - 1} are left" in str(
        ended.value
    )


async def test_what_another_job_of_the_account_holds_is_not_left(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # a reservation of a second job of the account, a request it waits on: the rest no longer fits
    pool, connection = setup
    document, _ = await ended_after_x2(setup, tmp_path, database_url, Model())
    context = context_of(pool, tmp_path, Model(), database_url)
    _, expected, room = await reckoned_now(connection, context, document)
    await limit(connection, document, await spent(connection, document) + expected + room)
    other = await a_job(connection, document.id, document.owner_id)
    await connection.execute(
        "INSERT INTO usage_reservation (account_id, job_id, purpose, model, input_tokens, output_tokens)"
        " VALUES (%s, %s, 'x4.unit', 'gpt-6-luna', 1, 1)",
        (document.owner_id, other.id),
    )

    with pytest.raises(PermanentError) as ended:
        await watched_now(setup, tmp_path, database_url, document)

    assert ended.value.code == "run_over_budget"
    assert f"{expected + room - 2} are left" in str(ended.value)  # its input and output, 1 each


async def test_a_run_with_its_limit_set_before_it_starts_passes_the_watch_and_ends_done(
    setup: Any, tmp_path: Path, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    # a twin, stopped after X2, tells what the rest needs; the run set up with as much beside what X1
    # spends passes the watch at its edge, and the room is enough: every reservation fits to the end
    pool, connection = setup
    twin, _ = await ended_after_x2(setup, tmp_path, database_url, Model())
    _, expected, room = await reckoned_now(
        connection, context_of(pool, tmp_path, Model(), database_url), twin
    )
    document = await a_document(connection, token_limit=await spent(connection, twin) + expected + room)

    with caplog.at_level(logging.INFO, logger="app.pipeline.watch"):
        made = await extract_document(
            context_of(pool, tmp_path, Model(), database_url),
            await a_job(connection, document.id, document.owner_id),
        )

    assert made["stages"] == ["X1", "X2", "X3", "X4", "X5"]
    [line] = caplog.messages
    assert re.fullmatch(
        rf"budget watch: 2 units, prefix \d+, expected {expected}, room {room}, limit \d+,"
        rf" {expected + room} left",
        line,
    )
    assert await booked_rest(connection, document) == [("x3.frame", 1), ("x4.unit", 2)]


async def test_a_second_start_with_the_quota_unchanged_stops_again_and_asks_nothing(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    model = Model()
    document, _ = await ended_after_x2(setup, tmp_path, database_url, model)

    with pytest.raises(PermanentError) as ended:
        await extract_document(
            context_of(pool, tmp_path, model, database_url),
            await a_job(connection, document.id, document.owner_id),
        )

    assert ended.value.code == "run_over_budget"
    assert (model.asked, model.units) == (["profile", "outline"], [])
    assert await rows(
        connection,
        "SELECT replace(stage_iri, %s, ''), count(*) FROM extraction_run WHERE document_id = %s"
        " GROUP BY stage_iri ORDER BY stage_iri",
        "https://w3id.org/wlo/curriculum/vocab#stage_",
        document.id,
    ) == [("X1", 1), ("X2", 1)]
    assert await booked_rest(connection, document) == []


async def test_a_run_whose_rest_the_budget_does_not_hold_ends_after_x2_and_asks_nothing_more(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    _, connection = setup
    model = Model()

    document, ended = await ended_after_x2(setup, tmp_path, database_url, model)

    assert ended.code == "run_over_budget"
    assert re.fullmatch(
        r"the rest of the run is expected to charge \d+ tokens and to hold \d+ more at once, 1000 are left"
        r" \(2 units, prefix \d+\)",
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

    monkeypatch.setattr(watch, "owed_questions", reckoning)

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
    assert (watched.units, watched.expected, watched.room) == await reckoned_now(
        connection, context, document
    )
    assert watched.units == 1  # E2 alone; X3 is done and not reckoned either
    assert watched.ceiling == 1_000_000_000
    assert watched.left is not None and watched.expected + watched.room < watched.left


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
        r"budget watch: 2 units, prefix (\d+), expected (\d+), room (\d+), limit 1000000000, (\d+) left", line
    )
    assert found is not None
    prefix, expected, room, left = (int(group) for group in found.groups())
    assert prefix > 0 and expected > 0 and expected + room <= left < 1_000_000_000


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


@pytest.mark.parametrize("account", ["watched", "without_limit", "watch_off"])
async def test_a_unit_no_window_fits_ends_the_job_before_x3_asks_in_any_run(
    setup: Any, tmp_path: Path, database_url: str, account: str
) -> None:
    # X3's window fits, one unit's does not: X4 would end the job before it asked a unit - so X3, asked
    # first, would be paid for nothing; every run checks the units' windows before X3 asks, watched or not
    pool, connection = setup
    document = await a_document(connection, blocks=LONG, token_limit=None)
    model = Model()
    answer = tightening(connection, document, model) if account == "watched" else model
    context = replace(context_of(pool, tmp_path, answer, database_url), llm=SMALL)
    if account == "watch_off":
        context = replace(unwatched(context, database_url), llm=SMALL)

    with pytest.raises(PermanentError) as ended:
        await extract_document(context, await a_job(connection, document.id, document.owner_id))

    assert ended.value.code == "prefix_too_long"
    assert await done_stages(connection, document.id) == {"X1", "X2"}
    assert (model.asked, model.units) == (["profile", "outline"], [])
    assert await booked_rest(connection, document) == []
