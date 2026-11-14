"""``python -m app.quality.report``: an item whose row is gone since the draw, or whose wording an editor
changed since, is no longer what was drawn - counted apart (``stale``), outside ``open`` and outside every
denominator, so that a weighted rate is said once no item still as drawn is open."""

import psycopg
import pytest

from app.db.gold import items_of, judge
from app.db.source_queries import Reader
from app.db.statement_editing import edit_statement
from app.quality.report import report
from tests.quality.gold_documents import WORDS, a_document, connection, done, statement_id
from tests.quality.test_report import CORRECT, WRONG, drawn
from tests.quality.test_report_anchors import an_import_judged

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents


async def test_items_gone_or_changed_since_the_draw_are_counted_apart(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await a_document(connection)  # five of the model's: content 1, learningOutcome 4
    await done(connection, document, "X4")
    sample = await drawn(connection, document, "statement")
    reworded = await statement_id(connection, WORDS["outcome"])
    taken = await statement_id(connection, WORDS["rejected"])
    for item in await items_of(connection, sample):
        if item.statement_id != taken:  # the one taken away below is never judged
            await judge(
                connection, item.id, document.owner_id, WRONG if item.statement_id == reworded else CORRECT
            )
    reader = Reader(document.owner_id, sees_all=False)
    assert await edit_statement(connection, reader, reworded, 1, {"verbatim": WORDS["new"]}) == 2
    await connection.execute("DELETE FROM statement WHERE id = %s", (taken,))

    [entry] = (await report(connection, [sample]))["documents"]

    measures = entry["statement"]
    assert measures["stale"] == {"gone": 1, "changed": 1}
    assert (measures["judged"], measures["open"]) == (3, 0)  # the changed one's judgement is not counted
    assert measures["strata"]["learningOutcome"] == {
        "frame": 4, "drawn": 2, "judged": 2, "correct": 2, "imprecise": 0, "wrong": 0, "unjudged": 0,
    }  # fmt: skip
    assert measures["weighted"]["precision_strict"] == 1.0  # none open of those still as drawn
    assert measures["pooled"]["precision_strict"] == 1.0


async def test_an_import_s_row_gone_since_the_draw_is_counted_apart_from_the_rows_not_found(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, strata = await an_import_judged(connection)
    await connection.execute(
        "DELETE FROM statement WHERE id = %s", (strata["notFound:statement"][1].statement_id,)
    )

    anchors = (await report(connection, [sample]))["documents"][0]["anchor"]

    assert anchors["stale"] == {"gone": 1, "changed": 0}
    assert anchors["not_found"] == {
        "frame": 2, "drawn": 1, "judged": 1, "open": 0, "missed": 0, "missed_rate": 0.0,
    }  # fmt: skip
    assert anchors["weighted"]["precision_strict"] == 0.4865  # the found anchors as they were
