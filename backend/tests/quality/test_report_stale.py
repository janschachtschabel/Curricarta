"""``python -m app.quality.report``: an item no longer what was drawn - its row gone since the draw, or
changed (its wording, its origin or its first block) - and not judged is counted apart (``stale``), outside
``drawn``, ``open`` and every denominator, so that a weighted rate is said once no item still as drawn is
open. A judgement given while the item was as drawn stays in the rates, their number told beside them."""

import psycopg
import pytest

from app.db.gold import items_of, judge
from app.db.source_queries import Reader
from app.db.statement_editing import HandAnchor, edit_statement
from app.quality.report import report
from tests.quality.gold_documents import CV, WORDS, a_document, connection, done, statement_id
from tests.quality.test_report import CORRECT, WRONG, drawn
from tests.quality.test_report_anchors import an_import_judged

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents


async def test_a_judgement_given_before_the_item_changed_stays_and_an_open_stale_item_leaves(
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
    assert measures["stale"] == {
        "gone": 1, "changed": 0, "judged_before": 1, "strata": {"learningOutcome": {"gone": 1, "changed": 0}},
    }  # fmt: skip
    assert (measures["judged"], measures["open"]) == (4, 0)  # the reworded one judged as drawn: it stays
    assert measures["strata"]["learningOutcome"] == {
        "frame": 4, "drawn": 3, "judged": 3, "correct": 2, "imprecise": 0, "wrong": 1, "unjudged": 0,
    }  # fmt: skip
    assert measures["weighted"]["precision_strict"] == 0.7333  # 1/5 * 1 + 4/5 * 2/3: none open
    assert measures["pooled"]["precision_strict"] == 0.75


@pytest.mark.parametrize("change", ["kind", "anchors", "first_block"])
async def test_an_item_whose_kind_anchors_or_first_block_changed_is_no_longer_what_was_drawn(
    connection: psycopg.AsyncConnection, change: str
) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")
    sample = await drawn(connection, document, "statement")
    touched = await statement_id(connection, WORDS["confirmed"])  # its wording left as it is, at p1-b2
    reader = Reader(document.owner_id, sees_all=False)
    if change == "kind":  # an editor's: the row is the editor's since
        await edit_statement(connection, reader, touched, 1, {"statement_kind": CV + "kind_content"})
    elif change == "anchors":
        await edit_statement(connection, reader, touched, 1, {}, anchors=[HandAnchor(blocks=("p1-b3",))])
    else:  # its first block moved, the origin kept
        await connection.execute(
            "UPDATE anchor_block SET block_id = 'p1-b3' WHERE anchor_id IN"
            " (SELECT id FROM anchor WHERE statement_id = %s)",
            (touched,),
        )

    measures = (await report(connection, [sample]))["documents"][0]["statement"]

    assert measures["stale"] == {
        "gone": 0, "changed": 1, "judged_before": 0, "strata": {"learningOutcome": {"gone": 0, "changed": 1}},
    }  # fmt: skip
    assert sum(row["drawn"] for row in measures["strata"].values()) == 4


async def test_an_import_s_row_gone_since_the_draw_is_counted_apart_from_the_rows_not_found(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, strata = await an_import_judged(connection)
    judged, unjudged = strata["notFound:statement"]
    await connection.execute("DELETE FROM gold_judgement WHERE item_id = %s", (unjudged.id,))
    await connection.execute(
        "DELETE FROM statement WHERE id = ANY (%s)", ([judged.statement_id, unjudged.statement_id],)
    )

    anchors = (await report(connection, [sample]))["documents"][0]["anchor"]

    assert anchors["stale"] == {
        "gone": 1, "changed": 0, "judged_before": 1,
        "strata": {"notFound:statement": {"gone": 1, "changed": 0}},
    }  # fmt: skip
    assert anchors["not_found"] == {
        "frame": 2, "drawn": 1, "judged": 1, "open": 0, "missed": 0, "missed_rate": 0.0,
    }  # fmt: skip
    assert anchors["weighted"]["precision_strict"] == 0.4865  # the found anchors as they were
