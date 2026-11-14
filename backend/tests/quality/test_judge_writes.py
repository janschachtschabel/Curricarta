"""A sheet's judgements are written all or none (plan H-3 §3.3): the database refusing the last of them
leaves none of the others, and an item or account gone between the reading and the writing comes out as
the refusal that names it."""

from collections.abc import Sequence
from typing import Any

import psycopg
import pytest

from app.core.ids import new_id
from app.db.gold import Item, Judgement, items_of, judge_all
from app.quality import judge
from app.quality.judge import Refused, take_in
from tests.quality.gold_documents import connection, count
from tests.quality.test_judge import SHEET, a_sample

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

CORRECT = Judgement("correct", (), None, None)


async def test_a_judgement_the_database_refuses_last_leaves_none_written(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, account = await a_sample(connection)
    cursor = await connection.execute("SELECT id FROM account WHERE name = %s", (account,))
    [(judge_id,)] = await cursor.fetchall()
    first, second, *_ = await items_of(connection, sample)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await judge_all(connection, judge_id, [(first.id, CORRECT), (second.id, CORRECT), (999_999, CORRECT)])

    assert await count(connection, "gold_judgement") == 0


async def test_judgements_are_written_in_the_items_order_whatever_order_they_come_in(
    connection: psycopg.AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, account = await a_sample(connection)
    cursor = await connection.execute("SELECT id FROM account WHERE name = %s", (account,))
    [(judge_id,)] = await cursor.fetchall()
    items = [item.id for item in await items_of(connection, sample)]
    written: list[int] = []
    execute = connection.execute

    async def watched(query: Any, params: Any = None, **options: Any) -> Any:
        if isinstance(params, dict) and "item" in params:
            written.append(params["item"])
        return await execute(query, params, **options)

    monkeypatch.setattr(connection, "execute", watched)

    await judge_all(connection, judge_id, [(item, CORRECT) for item in reversed(items)])

    assert written == sorted(items)  # one lock order for every import: two at once wait, never deadlock


def _then(connection: psycopg.AsyncConnection, statement: str, value: Any) -> Any:
    """items_of, after which the statement takes something away: as if another hand did it meanwhile."""

    async def reading(reader: psycopg.AsyncConnection, sample_id: int) -> Sequence[Item]:
        found = await items_of(reader, sample_id)
        await connection.execute(statement, (value(found) if callable(value) else value,))
        return found

    return reading


async def test_an_item_gone_while_the_sheet_is_read_refuses_it_as_the_sample_s(
    connection: psycopg.AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, account = await a_sample(connection)
    last = _then(connection, "DELETE FROM gold_item WHERE id = %s", lambda items: items[-1].id)
    monkeypatch.setattr(judge, "items_of", last)

    with pytest.raises(Refused) as refused:
        await take_in(connection, sample, account, SHEET)

    assert refused.value.code == "unknown_sample"
    assert await count(connection, "gold_judgement") == 0


async def test_an_account_gone_while_the_sheet_is_read_refuses_it_as_the_account_s(
    connection: psycopg.AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, _ = await a_sample(connection)
    other = new_id()
    await connection.execute("INSERT INTO account (id, name) VALUES (%s, 'zweite')", (other,))
    monkeypatch.setattr(judge, "items_of", _then(connection, "DELETE FROM account WHERE id = %s", other))

    with pytest.raises(Refused) as refused:
        await take_in(connection, sample, "zweite", SHEET)

    assert refused.value.code == "unknown_account"
    assert await count(connection, "gold_judgement") == 0
