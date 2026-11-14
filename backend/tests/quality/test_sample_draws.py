"""Drawing a sample as the gold standard keeps it (app/quality/sample.py ``draw``): drawn again under its
seed, the one there; two draws at once, one sample; a document, account or stage not there, refused."""

import asyncio
from typing import Any

import psycopg
import pytest

from app.db.gold import add_sample, items_of
from app.db.runs import Stage
from app.quality.sample import Drawn, Refused, Request, draw
from tests.quality.gold_documents import (
    MODEL,
    WORDS,
    a_document,
    a_reviewed_document,
    connection,
    count,
    done,
    owner,
)
from tests.support import waiting_on_a_lock

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents


async def test_a_sample_drawn_again_is_the_one_there(connection: psycopg.AsyncConnection) -> None:
    document = await a_reviewed_document(connection)
    account = await owner(connection, document)
    first = await draw(connection, Request(document.id, "statement", "pilot-1", account))
    before = await items_of(connection, first.sample)
    await connection.execute(
        "UPDATE statement SET origin_iri = %s WHERE verbatim = %s", (MODEL, WORDS["own"])
    )  # one more to draw from

    again = await draw(connection, Request(document.id, "statement", "pilot-2", account, size=5))

    # the one there, as kept: its label and size, and the call told it asked for others
    assert again == Drawn(first.sample, True, first.strata, None, "pilot-1", 40, "differs")
    same = await draw(connection, Request(document.id, "statement", "pilot-1", account, size=40))
    assert (same.drawn_before, same.call) == (True, "same")
    assert await items_of(connection, first.sample) == before
    other = await draw(connection, Request(document.id, "statement", "pilot-1", account, seed="another"))
    assert other.sample != first.sample
    assert await count(connection, "gold_sample") == 2


async def test_two_draws_at_once_keep_one_sample(
    connection: psycopg.AsyncConnection, database_url: str
) -> None:
    document = await a_reviewed_document(connection)
    request = Request(document.id, "statement", "pilot-1", await owner(connection, document))
    async with await psycopg.AsyncConnection.connect(database_url) as first:  # its draw not yet committed
        held = await draw(first, request)
        async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as second:
            # the second finds no sample yet, draws, and its insert waits for the first's
            drawing = asyncio.create_task(draw(second, request))
            await waiting_on_a_lock(connection, second.info.backend_pid)
            await first.commit()
            later = await drawing

    assert later.sample == held.sample
    assert not later.drawn_before  # it drew, and kept the one the first wrote
    assert (await count(connection, "gold_sample"), await count(connection, "gold_item")) == (1, 4)


async def test_an_account_that_is_not_there_is_refused(connection: psycopg.AsyncConnection) -> None:
    document = await a_reviewed_document(connection)

    with pytest.raises(Refused) as refused:
        await draw(connection, Request(document.id, "statement", "pilot-1", "niemand"))

    assert refused.value.code == "unknown_account"
    assert await count(connection, "gold_sample") == 0


@pytest.mark.parametrize(("kind", "stage"), [("statement", None), ("block", "IM"), ("anchor", "X4")])
async def test_an_extraction_not_done_is_refused(
    connection: psycopg.AsyncConnection, kind: Any, stage: Stage | None
) -> None:
    document = await a_document(connection)
    if stage is not None:  # the other kind's stage done
        await done(connection, document, stage)

    with pytest.raises(Refused) as refused:
        await draw(connection, Request(document.id, kind, "pilot-1", await owner(connection, document)))

    assert refused.value.code == "extraction_not_done"
    assert await count(connection, "gold_sample") == 0


async def test_a_document_that_is_not_there_is_refused(connection: psycopg.AsyncConnection) -> None:
    document = await a_document(connection)
    request = Request(document.owner_id, "statement", "pilot-1", await owner(connection, document))

    with pytest.raises(Refused) as refused:
        await draw(connection, request)

    assert refused.value.code == "unknown_document"


async def test_a_document_taken_away_while_drawn_is_refused(
    connection: psycopg.AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = await a_reviewed_document(connection)

    async def after_it_went(opened: psycopg.AsyncConnection, *args: Any) -> int:
        await connection.execute("DELETE FROM document WHERE id = %s", (document.id,))
        return await add_sample(opened, *args)

    monkeypatch.setattr("app.quality.sample.add_sample", after_it_went)

    with pytest.raises(Refused) as refused:
        await draw(
            connection, Request(document.id, "statement", "pilot-1", await owner(connection, document))
        )

    assert refused.value.code == "unknown_document"
    assert await count(connection, "gold_sample") == 0
