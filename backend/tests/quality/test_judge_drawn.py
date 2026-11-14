"""``python -m app.quality.judge``: a sheet proves what its judge saw - each row the mark of the wording
shown (``shown``), empty where the row was no longer what was drawn when the sheet was written. A judgement
is taken where it equals the item's mark, whenever the sheet comes back; otherwise the sheet is refused at
the line (``item_not_as_drawn``). A sheet without the column is refused as such."""

import csv
import io

import psycopg
import pytest

from app.db.gold import items_of, judgements_of
from app.db.source_queries import Reader
from app.db.statement_editing import edit_statement
from app.quality.judge import SheetRefused, Taken, take_in
from app.quality.sheet import encoded, sheet_rows
from tests.quality.gold_documents import WORDS, connection, count, statement_id
from tests.quality.test_judge import a_sample

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

BASE = "http://127.0.0.1:18080"


async def reword(connection: psycopg.AsyncConnection, account: str, verbatim: str) -> None:
    """An editor's change through the app: the row is the editor's since."""
    cursor = await connection.execute("SELECT id FROM account WHERE name = %s", (account,))
    [(owner,)] = await cursor.fetchall()
    said = await statement_id(connection, verbatim)
    reader = Reader(owner, sees_all=False)
    assert await edit_statement(connection, reader, said, 1, {"verbatim": WORDS["new"]})


def judged_all(rows: list[dict[str, str]]) -> bytes:
    return encoded([row | {"verdict": "correct", "reasons": ""} for row in rows])


async def test_a_sheet_written_before_a_change_is_taken_after_it_and_again(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, account = await a_sample(connection)
    sheet = judged_all(await sheet_rows(connection, sample, BASE))
    await reword(connection, account, WORDS["outcome"])

    first = await take_in(connection, sample, account, sheet)
    await reword(connection, account, WORDS["content"])  # a later change blocks no import again
    again = await take_in(connection, sample, account, sheet)

    assert first == Taken(judged=5, new=5, changed=0, unchanged=0, left_empty=0)
    assert again == Taken(judged=5, new=0, changed=0, unchanged=5, left_empty=0)
    assert len(await judgements_of(connection, sample)) == 5


async def test_a_sheet_written_after_a_change_is_refused_at_the_changed_line(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, account = await a_sample(connection)
    await reword(connection, account, WORDS["outcome"])
    rows = await sheet_rows(connection, sample, BASE)  # the row says changed, its verdict n/a
    changed = next(at for at, row in enumerate(rows) if row["kind"] == "changed")

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, judged_all(rows))  # the judge filled it in all the same

    assert rows[changed]["shown"] == ""
    assert refused.value.problems == [f"line {changed + 2}: item_not_as_drawn"]
    assert await count(connection, "gold_judgement") == 0


async def test_a_sheet_without_the_shown_marks_is_refused_as_such(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, account = await a_sample(connection)
    rows = await sheet_rows(connection, sample, BASE)
    table = list(csv.reader(io.StringIO(judged_all(rows).decode("utf-8-sig"), newline=""), delimiter=";"))
    at = table[0].index("shown")
    older = io.StringIO(newline="")
    csv.writer(older, delimiter=";", lineterminator="\r\n").writerows(
        row[:at] + row[at + 1 :] for row in table
    )

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, older.getvalue().encode("utf-8"))

    assert refused.value.problems == ["line 1: column_shown_missing"]
    assert [item.id for item in await items_of(connection, sample)]  # the sample stands
    assert await count(connection, "gold_judgement") == 0
