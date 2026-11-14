"""``python -m app.quality.sample``: a document's sample of statements, blocks or anchors drawn under a seed
and kept as the gold standard's (plan H-3 §3.2) - the model's statements as it wrote them, the blocks of the
running text, an import's anchors by how they were found; drawn again under its seed, the one there."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.conversion.base import Block, BlockKind
from app.db.documents import Document
from app.db.gold import add_sample, items_of
from app.db.migrate import migrate
from app.db.nodes import write_subtree
from app.db.review import ReviewItem, set_review
from app.db.runs import RunStart, Stage, finish_run, start_run
from app.db.source_queries import Reader
from app.db.statement_editing import edit_statement
from app.domain.l1 import AnchorDraft, NodeDraft, StatementDraft
from app.domain.wording import text_hash
from app.quality.sample import Drawn, Refused, Request, draw
from app.vocab.store import load_vocabulary
from tests.db.document_of import document_of
from tests.support import ontology_vocabulary, waiting_on_a_lock

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

CV = "https://w3id.org/wlo/curriculum/vocab#"
MODEL, HUMAN, IMPORTED = CV + "orig_model", CV + "orig_human", CV + "orig_import"
PROPOSED = CV + "rev_proposed"
# wordings of the tests' own: none is a curriculum's
WORDS = {
    "outcome": "Die Lernenden ordnen Kiesel und Sand nach ihrer Farbe.",
    "content": "Kiesel, Sand und Lehm im Wechsel der Jahreszeiten.",
    "confirmed": "Die Lernenden messen den Bach am Morgen.",
    "rejected": "Die Lernenden zählen die Kiesel am Bach.",
    "reworded": "Die Lernenden zeichnen den Lauf des Baches.",
    "own": "Die Lernenden sammeln Blätter am Ufer.",
}
LONG = "Am Ufer liegen Kiesel, Sand und Lehm, und der Bach trägt sie langsam weiter."  # 40 signs and more


def block(block_id: str, text: str, kind: BlockKind = "text") -> Block:
    page = int(block_id[1 : block_id.index("-")])
    return Block(
        id=block_id, page=page, kind=kind, text=text, bbox=None, font_size=11, bold=False, italic=False
    )


@pytest.fixture
async def connection(database_url: str, preloaded_vocabulary: None) -> AsyncIterator[psycopg.AsyncConnection]:
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as opened:
        yield opened


async def done(connection: psycopg.AsyncConnection, document: Document, stage: Stage) -> None:
    run = await start_run(connection, RunStart(document.id, None, None, stage, None, None, None, None))
    await finish_run(connection, run, "done", {})


async def owner(connection: psycopg.AsyncConnection, document: Document) -> str:
    cursor = await connection.execute("SELECT name FROM account WHERE id = %s", (document.owner_id,))
    [(name,)] = await cursor.fetchall()
    return str(name)


async def count(connection: psycopg.AsyncConnection, table: str) -> int:
    cursor = await connection.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - the tests' own names
    [(found,)] = await cursor.fetchall()
    return int(found)


async def reject(connection: psycopg.AsyncConnection, verbatim: str) -> None:
    await connection.execute(
        "UPDATE statement SET review_status_iri = %s WHERE verbatim = %s", (CV + "rev_rejected", verbatim)
    )


def statement(verbatim: str, blocks: tuple[str, ...] = ("p1-b2",), **fields: Any) -> StatementDraft:
    values: dict[str, Any] = {
        "kind": CV + "kind_learningOutcome", "addressees": (CV + "addr_learner",),
        "anchors": (AnchorDraft(blocks, page_start=1),), "origin": MODEL, "review_status": PROPOSED,
    } | fields  # fmt: skip
    return StatementDraft(verbatim=verbatim, **values)


async def a_document(connection: psycopg.AsyncConnection) -> Document:
    """A document whose model wrote five statements, and an editor one."""
    document = await document_of(
        connection, [block("p1-b1", "Am Bach"), block("p1-b2", LONG), block("p1-b3", LONG)]
    )
    root = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title="Am Bach",
        anchors=(AnchorDraft(("p1-b1",), page_start=1),),
        statements=(
            statement(WORDS["outcome"], ("p1-b3", "p1-b2")),  # its first block in reading order
            statement(WORDS["content"], kind=CV + "kind_content"),
            statement(WORDS["confirmed"]),
            statement(WORDS["rejected"]),
            statement(WORDS["reworded"]),
            statement(WORDS["own"], origin=HUMAN),
        ),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    return document


async def statement_id(connection: psycopg.AsyncConnection, verbatim: str) -> UUID:
    cursor = await connection.execute("SELECT id FROM statement WHERE verbatim = %s", (verbatim,))
    [(found,)] = await cursor.fetchall()
    return UUID(str(found))


async def a_reviewed_document(connection: psycopg.AsyncConnection) -> Document:
    """The document after X4, as the app leaves it once editors looked: one statement confirmed, one
    rejected - a review counts the revision up and keeps the origin -, one reworded, the editor's since."""
    document = await a_document(connection)
    await done(connection, document, "X4")
    for verbatim, status in (
        (WORDS["confirmed"], CV + "rev_confirmed"),
        (WORDS["rejected"], CV + "rev_rejected"),
    ):
        await set_review(
            connection,
            document.id,
            status,
            [ReviewItem("statement", await statement_id(connection, verbatim), 1)],
        )
    reworded = await statement_id(connection, WORDS["reworded"])
    reader = Reader(document.owner_id, sees_all=False)
    assert (
        await edit_statement(connection, reader, reworded, 1, {"verbatim": WORDS["reworded"] + " Neu."}) == 2
    )
    return document


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


def with_contents() -> list[Block]:
    """A cover, the contents on page 2, a header, a heading and the text it heads, a short line."""
    lines = "\n".join(f"{n} Teil {n} {'.' * 20} {n + 2}" for n in range(1, 4))
    return [
        block("p1-b1", "Ein Plan für das Lernen am Bach, mit Kiesel, Sand und Lehm"),
        block("p2-b1", "Inhalt"),
        block("p2-b2", lines),
        block("p3-b1", "Kopfzeile des Plans am Bach, mit Kiesel, Sand und Lehm, Seite 3", "page_header"),
        block("p3-b2", "1 Teil 1: der Bach, der Kiesel, der Sand und der Lehm am Ufer"),
        block("p3-b3", LONG),
        block("p4-b1", "Kurz und knapp."),
        block("p5-b1", LONG + " Noch einmal."),
    ]


async def test_blocks_of_the_contents_the_title_pages_and_the_headers_are_not_drawn(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await document_of(connection, with_contents())
    heading = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title="1 Teil 1",
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
    document = await document_of(connection, [block("p1-b1", "Am Bach"), block("p1-b2", LONG)])
    found = AnchorDraft(("p1-b2",), page_start=1, match_kind=CV + "match_whitespace")
    lost = AnchorDraft((), page_start=1, match_kind=CV + "match_notFound")
    root = NodeDraft(
        function=CV + "fn_area", origin=IMPORTED, review_status=PROPOSED, original_title="Am Bach",
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
        ("exact:node", text_hash("Am Bach"), "p1-b1", False),
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
        function=CV + "fn_area", origin=IMPORTED, review_status=PROPOSED, original_title="1 Teil 1",
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
    assert drawn.title_pages == "left_out"
    items = await items_of(connection, drawn.sample)
    assert {item.first_block for item in items if item.stratum == "front:statement"} == {"p1-b1"}


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
