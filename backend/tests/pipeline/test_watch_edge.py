"""The edge the watch after X2 decides by (app/pipeline/watch.py): a run passes where what is left holds
what the rest is expected to charge and the room its reservations need at once, and stops a token below;
what another job of the account holds is not left; a run set up at the edge before its start ends done;
a second start with the quota unchanged stops again. A model stands in (FunctionModel), never a provider."""

import logging
import re
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.db.conversions import all_blocks, printed_pages
from app.db.documents import Document, document_for_job
from app.jobs.outcome import PermanentError
from app.pipeline import watch
from app.pipeline.run import extract_document
from app.pipeline.watch import watch_budget
from app.usage.ledger import usage_of
from tests.pipeline.test_run import Model, a_document, a_job, context_of, rows, setup
from tests.pipeline.test_watch import booked_rest, ended_after_x2, reckoned_now

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run


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
