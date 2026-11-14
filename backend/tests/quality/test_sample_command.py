"""``python -m app.quality.sample``: a document's sample of statements, blocks or anchors drawn under a seed
and kept as the gold standard's (plan H-3 §3.2) - the model's statements as it wrote them, the blocks of the
running text, an import's anchors by how they were found, the title pages apart; the thirds by the pages."""

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.db.gold import items_of
from app.db.nodes import write_subtree
from app.domain.l1 import AnchorDraft, NodeDraft
from app.domain.wording import text_hash
from app.quality.sample import Request, draw
from tests.db.document_of import document_of
from tests.quality.gold_documents import (
    CV,
    IMPORTED,
    LONG,
    MODEL,
    PART,
    PROPOSED,
    WORDS,
    a_reviewed_document,
    block,
    connection,
    done,
    mem_synth,
    owner,
    reject,
    statement,
    with_contents,
)

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents


async def test_the_model_s_statements_are_drawn_however_reviewed_but_a_reworded_one_is_not(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await a_reviewed_document(connection)

    drawn = await draw(
        connection, Request(document.id, "statement", "pilot-1", await owner(connection, document))
    )

    assert drawn.strata == {"content": (1, 1), "learningOutcome": (3, 3)}  # by kind: in the frame, drawn
    assert not drawn.drawn_before
    items = await items_of(connection, drawn.sample)
    assert sorted((item.stratum, item.text_hash, item.first_block) for item in items) == sorted(
        [
            ("content", text_hash(WORDS["content"]), "p1-b2"),
            ("learningOutcome", text_hash(WORDS["outcome"]), "p1-b2"),
            ("learningOutcome", text_hash(WORDS["confirmed"]), "p1-b2"),
            ("learningOutcome", text_hash(WORDS["rejected"]), "p1-b2"),
        ]
    )
    assert all(item.statement_id is not None and item.node_id is None for item in items)


async def test_blocks_of_the_contents_the_title_pages_and_the_headers_are_not_drawn(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await document_of(connection, with_contents())
    heading = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=f"1 {PART} 1",
        anchors=(AnchorDraft(("p3-b2",), page_start=3),),
    )  # fmt: skip
    await write_subtree(connection, document.id, heading)
    await done(connection, document, "X4")

    drawn = await draw(
        connection, Request(document.id, "block", "pilot-1", await owner(connection, document))
    )

    items = await items_of(connection, drawn.sample)
    assert [(item.stratum, item.block_id) for item in items] == [("t2:text", "p3-b3"), ("t3:text", "p5-b1")]
    assert all(item.text_hash is None and item.first_block is None for item in items)
    assert drawn.title_pages == "left_out"
    again = await draw(
        connection, Request(document.id, "block", "pilot-1", await owner(connection, document))
    )
    assert (again.drawn_before, again.title_pages) == (True, "left_out")  # as kept, not found anew


async def test_without_contents_the_title_pages_are_unknown_and_drawn(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await document_of(
        connection, [block("p1-b1", LONG), block("p2-b1", LONG), block("p3-b1", LONG)]
    )
    await done(connection, document, "X4")

    drawn = await draw(
        connection, Request(document.id, "block", "pilot-1", await owner(connection, document))
    )

    assert drawn.strata == {"t1:text": (1, 1), "t2:text": (1, 1), "t3:text": (1, 1)}
    assert drawn.title_pages == "unknown"
    cursor = await connection.execute("SELECT title_pages FROM gold_sample WHERE id = %s", (drawn.sample,))
    assert await cursor.fetchall() == [("unknown",)]
    again = await draw(
        connection, Request(document.id, "block", "pilot-1", await owner(connection, document))
    )
    assert (again.drawn_before, again.title_pages) == (True, "unknown")


async def test_an_import_s_anchors_are_drawn_by_how_they_were_found(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await document_of(connection, [block("p1-b1", WORDS["title"]), block("p1-b2", LONG)])
    found = AnchorDraft(("p1-b2",), page_start=1, match_kind=CV + "match_whitespace")
    lost = AnchorDraft((), page_start=1, match_kind=CV + "match_notFound")
    root = NodeDraft(
        function=CV + "fn_area", origin=IMPORTED, review_status=PROPOSED, original_title=WORDS["title"],
        anchors=(AnchorDraft(("p1-b1",), page_start=1, match_kind=CV + "match_exact"),),
        statements=(
            statement(WORDS["outcome"], origin=IMPORTED, anchors=(found,)),
            statement(WORDS["content"], origin=IMPORTED, anchors=(lost,)),
            statement(WORDS["own"]),  # the model's: no import's
            statement(WORDS["rejected"], origin=IMPORTED, anchors=(found,)),  # rejected since
        ),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await reject(connection, WORDS["rejected"])
    await done(connection, document, "IM")

    drawn = await draw(connection, Request(document.id, "anchor", "mem-1", await owner(connection, document)))

    assert drawn.strata == {
        "exact:node": (1, 1),
        "notFound:statement": (1, 1),
        "whitespace:statement": (1, 1),
    }
    items = await items_of(connection, drawn.sample)
    assert [(item.stratum, item.text_hash, item.first_block, item.node_id is None) for item in items] == [
        ("exact:node", text_hash(WORDS["title"]), "p1-b1", False),
        ("notFound:statement", text_hash(WORDS["content"]), None, True),
        ("whitespace:statement", text_hash(WORDS["outcome"]), "p1-b2", True),
    ]
    assert drawn.title_pages == "unknown"  # no contents: nothing set apart


async def test_an_import_s_anchors_on_the_title_pages_are_a_stratum_apart(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await document_of(connection, with_contents())
    on_cover = AnchorDraft(("p1-b1",), page_start=1, match_kind=CV + "match_whitespace")
    in_body = AnchorDraft(("p3-b3",), page_start=3, match_kind=CV + "match_exact")
    root = NodeDraft(
        function=CV + "fn_area", origin=IMPORTED, review_status=PROPOSED, original_title=f"1 {PART} 1",
        anchors=(AnchorDraft(("p3-b2",), page_start=3, match_kind=CV + "match_exact"),),
        statements=(
            *(statement(f"{WORDS['outcome']} {n}", origin=IMPORTED, anchors=(on_cover,)) for n in range(6)),
            *(statement(f"{WORDS['content']} {n}", origin=IMPORTED, anchors=(in_body,)) for n in range(30)),
        ),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await done(connection, document, "IM")
    account = await owner(connection, document)

    drawn = await draw(connection, Request(document.id, "anchor", "mem-1", account, size=20))

    # the node's one, five of each other; the nine left by share of 30 and 6: 7.5 and 1.5, the cover's one
    # all it has left, the one over to the tie's first
    assert drawn.strata == {"exact:node": (1, 1), "exact:statement": (30, 13), "front:statement": (6, 6)}
    assert drawn.title_pages == "set_apart"  # its rows kept, in front:*
    items = await items_of(connection, drawn.sample)
    assert {item.first_block for item in items if item.stratum == "front:statement"} == {"p1-b1"}


async def test_the_thirds_are_of_the_conversion_s_pages(connection: psycopg.AsyncConnection) -> None:
    document = await document_of(
        connection, [block("p1-b1", LONG), block("p2-b1", LONG), block("p5-b1", LONG)]
    )
    # nine pages, the last four without a block: pages 1 to 3 the first third, 4 to 6 the second
    await connection.execute(
        "UPDATE conversion SET pages = 9, printed_pages = %s WHERE id = %s",
        (Jsonb([None] * 9), document.conversion_id),
    )
    await done(connection, document, "X4")

    drawn = await draw(
        connection, Request(document.id, "block", "pilot-1", await owner(connection, document))
    )

    assert drawn.strata == {"t1:text": (2, 2), "t2:text": (1, 1)}


def test_the_wordings_are_made_of_the_tool_s_words() -> None:
    known = {*mem_synth.NOUNS, *mem_synth.WORDS}
    for made in WORDS.values():
        for piece in made.split():
            word = "".join(sign for sign in piece if sign.isalpha())
            assert word in known or not word or any(sign.isdigit() for sign in piece), (made, piece)
    assert len(set(WORDS.values())) == len(WORDS)  # each its own
