"""``python -m app.quality.report``: precision, recall and the anchors' judgements of gold samples as counts
and rates (plan H-3 §3.4) - each document one entry, a statement's precision weighted by the strata's
populations kept when drawn beside the pooled rate, recall by the statements found in the judged blocks
now, an anchor sample's figures over all strata and without the title pages. Never a wording."""

import json
import re
from collections.abc import Iterator

import psycopg
import pytest

from app.db.documents import Document
from app.db.gold import Item, Judgement, SampleKind, items_of, judge
from app.db.nodes import write_subtree
from app.db.review import ReviewItem, set_review
from app.db.source_queries import Reader
from app.db.statement_editing import edit_statement
from app.domain.l1 import AnchorDraft, NodeDraft
from app.quality.report import LEAF, Refused, closed, report
from app.quality.sample import Request, draw
from tests.db.document_of import document_of
from tests.quality.gold_documents import (
    CV,
    HUMAN,
    IMPORTED,
    LONG,
    MODEL,
    PART,
    PROPOSED,
    WORDS,
    a_document,
    block,
    connection,
    done,
    owner,
    statement,
    statement_id,
    with_contents,
)

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

CORRECT, IMPRECISE = Judgement("correct", (), None, None), Judgement("imprecise", ("boundary",), None, None)
WRONG = Judgement("wrong", ("node",), None, None)


async def drawn(
    connection: psycopg.AsyncConnection, document: Document, kind: SampleKind, size: int = 40
) -> int:
    request = Request(document.id, kind, "pilot-1", await owner(connection, document), size)
    return (await draw(connection, request)).sample


async def by_stratum(connection: psycopg.AsyncConnection, sample: int) -> dict[str, list[Item]]:
    found: dict[str, list[Item]] = {}
    for item in await items_of(connection, sample):
        found.setdefault(item.stratum, []).append(item)
    return found


async def test_the_report_weighs_by_the_frame_kept_when_drawn(connection: psycopg.AsyncConnection) -> None:
    document = await a_document(connection)  # five of the model's: content 1, learningOutcome 4
    await done(connection, document, "X4")
    sample = await drawn(connection, document, "statement", size=3)  # content 1, learningOutcome 2 of 4
    before = await report(connection, [sample])
    strata = await by_stratum(connection, sample)
    content, outcomes = strata["content"], strata["learningOutcome"]
    await judge(connection, content[0].id, document.owner_id, CORRECT)
    await judge(connection, outcomes[0].id, document.owner_id, CORRECT)
    await judge(connection, outcomes[1].id, document.owner_id, WRONG)
    # more statements of the model since: the frame kept when drawn weighs, not the document now
    more = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=WORDS["new"],
        statements=tuple(statement(f"{WORDS['again']} {n}", kind=CV + "kind_content") for n in range(20)),
    )  # fmt: skip
    await write_subtree(connection, document.id, more)

    after = await report(connection, [sample])

    [nothing] = before["documents"]
    assert nothing["statement"]["weighted"] == {
        "by": "frame_when_drawn", "precision_strict": None, "precision_lenient": None, "wrong_rate": None,
    }  # fmt: skip
    assert nothing["statement"]["pooled"]["precision_strict"] is None
    assert nothing["statement"]["pooled"]["precision_strict_wilson95"] is None
    assert (nothing["statement"]["judged"], nothing["statement"]["open"]) == (0, 3)
    [entry] = after["documents"]
    measures = entry["statement"]
    assert measures["strata"] == {
        "content": {
            "frame": 1, "drawn": 1, "judged": 1, "correct": 1, "imprecise": 0, "wrong": 0, "unjudged": 0,
        },
        "learningOutcome": {
            "frame": 4, "drawn": 2, "judged": 2, "correct": 1, "imprecise": 0, "wrong": 1, "unjudged": 0,
        },
    }  # fmt: skip
    # 1/5 * 1/1 + 4/5 * 1/2 - by the drawn it would be 1/3 + 2/3 * 1/2; pooled 2 of 3
    assert measures["weighted"] == {
        "by": "frame_when_drawn", "precision_strict": 0.6, "precision_lenient": 0.6, "wrong_rate": 0.4,
    }  # fmt: skip
    assert measures["pooled"] == {
        "by": "item", "judged": 3,
        "precision_strict": 0.6667, "precision_strict_wilson95": [0.2077, 0.9385],
        "precision_lenient": 0.6667, "precision_lenient_wilson95": [0.2077, 0.9385],
        "wrong_rate": 0.3333, "wrong_rate_wilson95": [0.0615, 0.7923],
    }  # fmt: skip
    assert (measures["judged"], measures["open"]) == (3, 0)
    assert measures["reasons"] == {"not_a_statement": 0, "not_in_document": 0, "node": 1, "boundary": 0,
                                   "kind": 0, "fields": 0}  # fmt: skip


async def test_a_stratum_nobody_judged_leaves_the_report_s_weighted_rate_unsaid(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")
    sample = await drawn(connection, document, "statement")
    for item in (await by_stratum(connection, sample))["learningOutcome"]:
        await judge(connection, item.id, document.owner_id, IMPRECISE)

    [entry] = (await report(connection, [sample]))["documents"]

    assert entry["statement"]["weighted"]["precision_lenient"] is None  # content drawn, not judged
    assert entry["statement"]["pooled"]["precision_lenient"] == 1.0  # all four judged imprecise
    assert entry["statement"]["pooled"]["precision_strict"] == 0.0


async def blocks_with_statements(connection: psycopg.AsyncConnection) -> Document:
    """The with_contents blocks: three of the model's statements and an editor's own in p3-b3, two of the
    model's in p5-b1 (one of them in both)."""
    document = await document_of(connection, with_contents())
    root = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=f"1 {PART} 1",
        anchors=(AnchorDraft(("p3-b2",), page_start=3),),
        statements=(
            statement(WORDS["outcome"], ("p3-b3",)),
            statement(WORDS["confirmed"], ("p3-b3",)),
            statement(WORDS["rejected"], ("p3-b3", "p5-b1")),
            statement(WORDS["content"], ("p5-b1",)),
            statement(WORDS["own"], ("p3-b3",), origin=HUMAN),
        ),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await done(connection, document, "X4")
    return document


async def test_the_model_s_statements_are_found_however_reviewed_but_an_editor_s_are_not(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await blocks_with_statements(connection)
    sample = await drawn(connection, document, "block")
    blocks = {item.block_id: item for item in await items_of(connection, sample)}
    await judge(connection, blocks["p3-b3"].id, document.owner_id, Judgement(None, (), 3, None))
    await judge(connection, blocks["p5-b1"].id, document.owner_id, Judgement(None, (), 0, None))
    found = await report(connection, [sample])
    rejected = await statement_id(connection, WORDS["rejected"])
    await set_review(connection, document.id, CV + "rev_rejected", [ReviewItem("statement", rejected, 1)])
    reworded = await statement_id(connection, WORDS["confirmed"])
    reader = Reader(document.owner_id, sees_all=False)
    assert await edit_statement(connection, reader, reworded, 1, {"verbatim": WORDS["new"]}) == 2

    after = await report(connection, [sample])

    # p3-b3: the model's three, not the editor's own; p5-b1: two where none is expected
    assert found["documents"][0]["block"] == {
        "sample": sample, "title_pages": "left_out", "judged": 2, "open": 0,
        "expected": 3, "found": 3, "recall": 1.0, "missed_blocks": 0, "surplus_blocks": 1, "surplus": 2,
    }  # fmt: skip
    # rejected since: still the model's, still found; reworded: the editor's now, found no more
    assert after["documents"][0]["block"] == found["documents"][0]["block"] | {"found": 2, "recall": 0.6667}


async def test_two_samples_of_one_document_are_one_entry(connection: psycopg.AsyncConnection) -> None:
    document = await blocks_with_statements(connection)
    statements = await drawn(connection, document, "statement")
    blocks = await drawn(connection, document, "block")
    other = await a_document(connection)
    await done(connection, other, "X4")
    elsewhere = await drawn(connection, other, "statement")

    made = await report(connection, [statements, blocks, elsewhere])

    first, second = made["documents"]
    assert [sample["kind"] for sample in first["samples"]] == ["statement", "block"]
    assert {"statement", "block"} <= first.keys() and "anchor" not in first
    assert [sample["id"] for sample in second["samples"]] == [elsewhere]
    with pytest.raises(Refused, match="kind_twice"):
        again = Request(document.id, "statement", "pilot-1", await owner(connection, document), seed="other")
        await report(connection, [statements, (await draw(connection, again)).sample])
    with pytest.raises(Refused, match="unknown_sample"):
        await report(connection, [999_999])


async def test_an_anchor_sample_is_told_over_all_strata_and_without_the_title_pages(
    connection: psycopg.AsyncConnection,
) -> None:
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
            statement(WORDS["own"], origin=IMPORTED, anchors=(lost,)),
        ),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await done(connection, document, "IM")
    sample = await drawn(connection, document, "anchor")  # all 38
    strata = await by_stratum(connection, sample)
    place = Judgement("wrong", ("wrong_place",), None, None)
    for item, judgement in (
        (strata["exact:node"][0], CORRECT),
        (strata["exact:statement"][0], CORRECT),
        (strata["exact:statement"][1], place),
        (strata["front:statement"][0], place),
        (strata["notFound:statement"][0], Judgement("wrong", ("missed",), None, None)),
    ):
        await judge(connection, item.id, document.owner_id, judgement)

    [entry] = (await report(connection, [sample]))["documents"]

    anchors = entry["anchor"]
    assert entry["source_kind"] == "mem_import"
    assert anchors["title_pages"] == "set_apart"
    assert anchors["missed"] == 1
    # all: (1 * 1 + 30 * 1/2 + 6 * 0 + 1 * 0) / 38; without front: 16 / 32
    assert anchors["weighted"]["precision_strict"] == round(16 / 38, 4)
    assert anchors["pooled"]["precision_strict"] == 0.4
    assert anchors["without_front"]["weighted"]["precision_strict"] == 0.5
    assert anchors["without_front"]["pooled"]["precision_strict"] == 0.5
    assert (anchors["without_front"]["judged"], anchors["without_front"]["open"]) == (4, 28)
    assert anchors["reasons"] == {"boundary": 0, "wrong_place": 2, "missed": 1}


def leaves(value: object, path: str = "") -> Iterator[tuple[str, object]]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield f"{path}/key", key
            yield from leaves(inner, f"{path}/{key}")
    elif isinstance(value, list):
        for inner in value:
            yield from leaves(inner, path)
    else:
        yield path, value


async def test_the_report_holds_counts_alone(connection: psycopg.AsyncConnection) -> None:
    markers = ("Zettelmarke", "Kellerfund", "Notizmarke", "Blockmarke", "Kopfmarke")
    document = await document_of(
        connection, [block("p1-b1", f"{markers[3]} {LONG}"), block("p2-b1", LONG), block("p3-b1", LONG)]
    )
    await connection.execute("UPDATE document SET title = %s WHERE id = %s", (markers[4], document.id))
    root = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=markers[1],
        anchors=(AnchorDraft(("p1-b1",), page_start=1),),
        statements=(statement(f"{markers[0]} {WORDS['outcome']}", ("p1-b1",), lead_in=markers[1]),),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await done(connection, document, "X4")
    statements, blocks = (
        await drawn(connection, document, "statement"),
        await drawn(connection, document, "block"),
    )
    for item in await items_of(connection, statements):
        await judge(connection, item.id, document.owner_id, Judgement("wrong", ("node",), None, markers[2]))
    for item in await items_of(connection, blocks):
        await judge(connection, item.id, document.owner_id, Judgement(None, (), 1, markers[2]))

    made = await report(connection, [statements, blocks])

    printed = json.dumps(made)
    assert not [marker for marker in markers if marker in printed]
    for path, leaf in leaves(made):
        assert (
            leaf is None
            or isinstance(leaf, int | float | bool)
            or (isinstance(leaf, str) and re.fullmatch(LEAF, leaf))
        ), (path, leaf)


@pytest.mark.parametrize(
    "value", [{"a": "two words"}, {"two words": 1}, {"a": ["x" * 61]}, {"a": {"b": object()}}]
)
def test_a_leaf_other_than_a_count_or_code_breaks_the_report(value: object) -> None:
    with pytest.raises(ValueError, match="counts, rates and codes"):
        closed(value)
    closed({"a": [1, 0.5, None, True, "front:statement", "x4-statements/2"]})
