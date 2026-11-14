"""The store of the gold standard (app/db/gold.py): a sample written with its items in their order, read
back; an account's judgement of an item made again over its own; the latest judgement of each item."""

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.db.gold import (
    Item,
    ItemDraft,
    Judgement,
    Sample,
    SampleDraft,
    add_sample,
    items_of,
    judge,
    judgements_of,
    sample_by_id,
)
from app.db.migrate import migrate
from tests.db.l1 import add_conversion, add_document, seed_vocabulary

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

HASH = "b" * 64
CORRECT = Judgement(verdict="correct", reasons=(), expected=None, note=None)


@pytest.fixture
async def made(database_url: str) -> dict[str, Any]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_vocabulary(opened)
        made: dict[str, Any] = add_conversion(opened)
        made["document"] = add_document(opened, made)
        made["second"] = UUID(int=7)
        opened.execute("INSERT INTO account (id, name) VALUES (%s, 'zweites-konto')", (made["second"],))
    return made


@pytest.fixture
async def connection(database_url: str, made: dict[str, Any]) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as opened:
        yield opened


def draft(made: dict[str, Any]) -> SampleDraft:
    return SampleDraft(
        kind="statement",
        document_id=made["document"],
        label="pilot-1",
        seed="curricarta-h3",
        size=40,
        frame={"learningOutcome": 12, "content": 3},
        drawn_by=made["owner"],
        title_pages=None,
    )


ITEMS = [
    ItemDraft(stratum="learningOutcome", statement_id=UUID(int=1), text_hash=HASH, first_block="p1-b1"),
    ItemDraft(stratum="content", statement_id=UUID(int=2), text_hash=HASH, first_block=None),
]


async def a_sample(connection: psycopg.AsyncConnection, made: dict[str, Any]) -> tuple[int, list[Item]]:
    sample = await add_sample(connection, draft(made), ITEMS)
    return sample, await items_of(connection, sample)


async def test_a_sample_is_read_back_with_its_items_in_their_order(
    connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    sample, items = await a_sample(connection, made)

    found = await sample_by_id(connection, sample)

    assert isinstance(found, Sample)
    assert (found.id, found.kind, found.document_id, found.label, found.seed, found.size) == (
        sample, "statement", made["document"], "pilot-1", "curricarta-h3", 40
    )  # fmt: skip
    assert found.frame == {"learningOutcome": 12, "content": 3}
    assert (found.drawn_by, found.title_pages) == (made["owner"], None)
    assert [
        (item.sample_id, item.place, item.stratum, item.statement_id, item.first_block) for item in items
    ] == [
        (sample, 1, "learningOutcome", UUID(int=1), "p1-b1"),
        (sample, 2, "content", UUID(int=2), None),
    ]
    assert await sample_by_id(connection, sample + 1) is None
    assert await items_of(connection, sample + 1) == []


async def test_a_block_sample_keeps_whether_its_title_pages_were_known(
    connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    blocks = replace(draft(made), kind="block", frame={"t1:text": 1}, title_pages="unknown")

    sample = await add_sample(connection, blocks, [ItemDraft(stratum="t1:text", block_id="p1-b1")])

    found = await sample_by_id(connection, sample)
    assert found is not None and found.title_pages == "unknown"


async def test_a_sample_drawn_again_under_its_seed_is_the_one_there(
    connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    sample, _ = await a_sample(connection, made)

    again = await add_sample(connection, draft(made), ITEMS[:1])

    assert again == sample
    assert len(await items_of(connection, sample)) == 2


async def test_a_judgement_made_again_replaces_the_account_s_own(
    connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    sample, items = await a_sample(connection, made)
    await judge(connection, items[0].id, made["second"], CORRECT)
    await judge(connection, items[0].id, made["owner"], CORRECT)
    wrong = Judgement(verdict="wrong", reasons=("not_a_statement",), expected=None, note="eine Notiz")

    await judge(connection, items[0].id, made["owner"], wrong)

    cursor = await connection.execute("SELECT judged_by, verdict FROM gold_judgement ORDER BY judged_by")
    assert await cursor.fetchall() == [(made["second"], "correct"), (made["owner"], "wrong")]
    assert (await judgements_of(connection, sample))[items[0].id] == wrong


async def test_the_latest_judgement_of_an_item_is_the_one_read(
    connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    sample, items = await a_sample(connection, made)
    first, second = items
    imprecise = Judgement(verdict="imprecise", reasons=("boundary", "kind"), expected=None, note=None)
    await judge(connection, first.id, made["owner"], imprecise)
    await judge(connection, first.id, made["second"], CORRECT)
    await judge(connection, second.id, made["second"], CORRECT)
    await judge(connection, second.id, made["owner"], imprecise)
    # the second account's of the first item an hour later, the first account's of the second
    await connection.execute(
        "UPDATE gold_judgement SET judged_at = judged_at + interval '1 hour'"
        " WHERE (item_id, judged_by) IN ((%s, %s), (%s, %s))",
        (first.id, made["second"], second.id, made["owner"]),
    )

    found = await judgements_of(connection, sample)

    assert found == {first.id: CORRECT, second.id: imprecise}
    assert await judgements_of(connection, sample + 1) == {}


async def test_a_count_and_a_note_are_kept(connection: psycopg.AsyncConnection, made: dict[str, Any]) -> None:
    sample, items = await a_sample(connection, made)
    counted = Judgement(verdict=None, reasons=(), expected=3, note="drei")

    await judge(connection, items[1].id, made["owner"], counted)

    assert await judgements_of(connection, sample) == {items[1].id: counted}


async def test_a_judgement_of_an_item_that_is_not_there_is_refused(
    connection: psycopg.AsyncConnection, made: dict[str, Any]
) -> None:
    _, items = await a_sample(connection, made)

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        await judge(connection, items[-1].id + 1, made["owner"], CORRECT)

    assert refused.value.diag.constraint_name == "gold_judgement_item_id_fkey"
