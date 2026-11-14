"""What the gold standard's sample tests share: a database with the ontology's vocabularies, documents made
as the app makes them - their wordings made by the MEM fixtures' tool (backend/tools/mem_synth.py), never a
curriculum's -, and the stages they need marked done."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.conversion.base import Block, BlockKind
from app.db.documents import Document
from app.db.migrate import migrate
from app.db.nodes import write_subtree
from app.db.review import ReviewItem, set_review
from app.db.runs import RunStart, Stage, finish_run, start_run
from app.db.source_queries import Reader
from app.db.statement_editing import edit_statement
from app.domain.l1 import AnchorDraft, NodeDraft, StatementDraft
from app.vocab.store import load_vocabulary
from tests.db.document_of import document_of
from tests.sources.test_mem_fixtures import tool
from tests.support import ontology_vocabulary

CV = "https://w3id.org/wlo/curriculum/vocab#"
MODEL, HUMAN, IMPORTED = CV + "orig_model", CV + "orig_human", CV + "orig_import"
PROPOSED = CV + "rev_proposed"
# Wordings made by the tool the MEM fixtures are made with (backend/tools/mem_synth.py): its words alone
mem_synth = tool()
_FORMS = {  # the form each takes: its words replaced, its numbers and marks kept
    "outcome": "Die Lernenden ordnen die Kiesel am Bach.",
    "content": "Kiesel, Sand und Lehm.",
    "confirmed": "Die Lernenden messen den Bach.",
    "rejected": "Die Lernenden zählen Kiesel.",
    "reworded": "Die Lernenden zeichnen den Bach.",
    "own": "Die Lernenden sammeln Blätter.",
    "title": "Am Bach",
    "long": "Am Ufer liegen Kiesel, Sand und Lehm, und der Bach trägt sie langsam weiter.",
    "cover": "Ein Plan für das Lernen am Bach, mit Kiesel, Sand und Lehm.",
    "header": "Kopfzeile des Plans am Bach, mit Kiesel, Sand und Lehm, Seite 3",
    "short": "Kurz und knapp.",
    "again": "Noch einmal.",
    "new": "Neu.",
}
WORDS = {name: mem_synth.wording(form, seed) for seed, (name, form) in enumerate(_FORMS.items())}
LONG = WORDS["long"]  # 40 signs and more
PART = mem_synth.NOUNS[0]  # what the contents' entries and the heading name
CONTENTS = "Inhalt"  # how the contents are titled: a word of the tool's too
assert CONTENTS in mem_synth.NOUNS


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
        connection, [block("p1-b1", WORDS["title"]), block("p1-b2", LONG), block("p1-b3", LONG)]
    )
    root = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=WORDS["title"],
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
        await edit_statement(
            connection, reader, reworded, 1, {"verbatim": WORDS["reworded"] + " " + WORDS["new"]}
        )
        == 2
    )
    return document


def with_contents() -> list[Block]:
    """A cover, the contents on page 2, a header, a heading and the text it heads, a short line."""
    lines = "\n".join(f"{n} {PART} {n} {'.' * 20} {n + 2}" for n in range(1, 4))
    return [
        block("p1-b1", WORDS["cover"]),
        block("p2-b1", CONTENTS),
        block("p2-b2", lines),
        block("p3-b1", WORDS["header"], "page_header"),
        block("p3-b2", f"1 {PART} 1: {WORDS['long']}"),
        block("p3-b3", LONG),
        block("p4-b1", WORDS["short"]),
        block("p5-b1", LONG + " " + WORDS["again"]),
    ]
