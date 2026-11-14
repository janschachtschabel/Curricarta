"""The report's anchor section (plan H-3 §1.2, §3.4): the found anchors' precision over the strata that
are not ``notFound:*``, all of them and again without the title pages' (``front:*``), and beside it the
rows the import did not find - how many there are, were drawn, judged, are open, and how many of them hold
a wording that is there after all. Each weighted rate is said once no drawn item of the strata it is made
of is open."""

import psycopg
import pytest

from app.db.gold import Item, Judgement, judge
from app.db.nodes import write_subtree
from app.domain.l1 import AnchorDraft, NodeDraft
from app.quality.report import report
from tests.db.document_of import document_of
from tests.quality.gold_documents import (
    CV,
    IMPORTED,
    PART,
    PROPOSED,
    WORDS,
    connection,
    done,
    statement,
    with_contents,
)  # fmt: skip
from tests.quality.test_report import CORRECT, IMPRECISE, by_stratum, drawn

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

PLACE = Judgement("wrong", ("wrong_place",), None, None)
MISSED = Judgement("wrong", ("missed",), None, None)
VERDICTS = {
    "exact:node": [CORRECT],
    "exact:statement": [CORRECT] * 15 + [IMPRECISE] * 10 + [PLACE] * 5,
    "front:statement": [CORRECT] * 2 + [PLACE] * 4,
    "notFound:statement": [CORRECT, MISSED],  # rightly not found; there after all
}


async def an_import_judged(
    connection: psycopg.AsyncConnection,
) -> tuple[int, dict[str, list[Item]]]:
    """An import of 39 rows - a node, 30 statements found in the body, 6 on the cover, 2 not found -, all
    drawn and each judged as VERDICTS says."""
    document = await document_of(connection, with_contents())
    on_cover = AnchorDraft(("p1-b1",), page_start=1, match_kind=CV + "match_whitespace")
    in_body = AnchorDraft(("p3-b3",), page_start=3, match_kind=CV + "match_exact")
    lost = AnchorDraft((), page_start=1, match_kind=CV + "match_notFound")
    root = NodeDraft(
        function=CV + "fn_area", origin=IMPORTED, review_status=PROPOSED, original_title=f"1 {PART} 1",
        anchors=(AnchorDraft(("p3-b2",), page_start=3, match_kind=CV + "match_exact"),),
        statements=(
            *(statement(f"{WORDS['outcome']} {n}", origin=IMPORTED, anchors=(on_cover,)) for n in range(6)),
            *(statement(f"{WORDS['content']} {n}", origin=IMPORTED, anchors=(in_body,)) for n in range(30)),
            *(statement(f"{WORDS['own']} {n}", origin=IMPORTED, anchors=(lost,)) for n in range(2)),
        ),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await done(connection, document, "IM")
    sample = await drawn(connection, document, "anchor")  # all 39
    strata = await by_stratum(connection, sample)
    for stratum, judgements in VERDICTS.items():
        for item, judgement in zip(strata[stratum], judgements, strict=True):
            await judge(connection, item.id, document.owner_id, judgement)
    return sample, strata


async def test_an_anchor_sample_tells_the_found_anchors_precision_and_the_missed_wordings_apart(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, _ = await an_import_judged(connection)

    [entry] = (await report(connection, [sample]))["documents"]

    anchors = entry["anchor"]
    assert entry["source_kind"] == "mem_import"
    assert anchors["title_pages"] == "set_apart"
    assert set(anchors["strata"]) == {"exact:node", "exact:statement", "front:statement"}  # found ones
    # found, all: strict (1 + 15 + 2) / 37, lenient (1 + 25 + 2) / 37, wrong (5 + 4) / 37
    assert anchors["weighted"] == {
        "by": "frame_when_drawn", "open": 0,
        "precision_strict": 0.4865, "precision_lenient": 0.7568, "wrong_rate": 0.2432,
    }  # fmt: skip
    assert (anchors["judged"], anchors["open"], anchors["pooled"]["precision_strict"]) == (37, 0, 0.4865)
    # without the title pages: 16 / 31, 26 / 31, 5 / 31
    without = anchors["without_front"]
    assert (without["weighted"]["precision_strict"], without["weighted"]["precision_lenient"]) == (
        0.5161,
        0.8387,
    )
    assert (without["weighted"]["wrong_rate"], without["judged"], without["open"]) == (0.1613, 31, 0)
    assert anchors["not_found"] == {
        "frame": 2, "drawn": 2, "judged": 2, "open": 0, "missed": 1, "missed_rate": 0.5,
    }  # fmt: skip
    assert anchors["reasons"] == {"boundary": 10, "wrong_place": 9}


async def test_each_weighted_rate_waits_for_the_strata_it_is_made_of(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, strata = await an_import_judged(connection)
    forget = "DELETE FROM gold_judgement WHERE item_id = %s"
    await connection.execute(forget, (strata["notFound:statement"][1].id,))

    a_lost_row_open = (await report(connection, [sample]))["documents"][0]["anchor"]
    await connection.execute(forget, (strata["front:statement"][0].id,))
    a_front_row_open = (await report(connection, [sample]))["documents"][0]["anchor"]

    # a row not found is no anchor: the precision is said, the open row told beside it
    assert a_lost_row_open["weighted"]["precision_strict"] == 0.4865
    assert a_lost_row_open["not_found"] == {
        "frame": 2, "drawn": 2, "judged": 1, "open": 1, "missed": 0, "missed_rate": 0.0,
    }  # fmt: skip
    # a cover row open: the figure over all found strata waits, the one without the title pages does not
    assert a_front_row_open["weighted"]["precision_strict"] is None
    assert (a_front_row_open["weighted"]["open"], a_front_row_open["open"]) == (1, 1)
    assert a_front_row_open["without_front"]["weighted"]["precision_strict"] == 0.5161
    assert a_front_row_open["without_front"]["open"] == 0
