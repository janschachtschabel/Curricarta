"""``python -m app.quality.sample``: a document's sample of statements, blocks or anchors drawn under a seed
and kept as the gold standard's (plan H-3 §3.2) - the model's statements as it wrote them, the blocks of the
running text, an import's anchors by how they were found; drawn again under its seed, the one there."""

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.conversion.base import Block, BlockKind
from app.db.documents import Document
from app.db.gold import items_of
from app.db.migrate import migrate
from app.db.nodes import write_subtree
from app.db.runs import RunStart, Stage, finish_run, start_run
from app.domain.l1 import AnchorDraft, NodeDraft, StatementDraft
from app.domain.wording import text_hash
from app.quality.sample import SEED, Drawn, Refused, Request, draw
from app.vocab.store import load_vocabulary
from tests.db.document_of import document_of
from tests.support import ontology_vocabulary, without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

BACKEND = Path(__file__).resolve().parents[2]
CV = "https://w3id.org/wlo/curriculum/vocab#"
MODEL, HUMAN, IMPORTED = CV + "orig_model", CV + "orig_human", CV + "orig_import"
PROPOSED = CV + "rev_proposed"
# wordings of the tests' own: none is a curriculum's
WORDS = {
    "outcome": "Die Lernenden ordnen Kiesel und Sand nach ihrer Farbe.",
    "content": "Kiesel, Sand und Lehm im Wechsel der Jahreszeiten.",
    "rejected": "Die Lernenden zählen die Kiesel am Bach.",
    "edited": "Die Lernenden zeichnen den Lauf des Baches.",
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
    """A document whose model wrote five statements: one rejected since, one an editor changed, one an
    editor wrote."""
    document = await document_of(
        connection, [block("p1-b1", "Am Bach"), block("p1-b2", LONG), block("p1-b3", LONG)]
    )
    root = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title="Am Bach",
        anchors=(AnchorDraft(("p1-b1",), page_start=1),),
        statements=(
            statement(WORDS["outcome"], ("p1-b3", "p1-b2")),  # its first block in reading order
            statement(WORDS["content"], kind=CV + "kind_content"),
            statement(WORDS["rejected"]),
            statement(WORDS["edited"]),
            statement(WORDS["own"], origin=HUMAN),
        ),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await reject(connection, WORDS["rejected"])
    await connection.execute("UPDATE statement SET revision = 2 WHERE verbatim = %s", (WORDS["edited"],))
    return document


async def test_statements_the_editors_touched_or_rejected_are_not_drawn(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")

    drawn = await draw(
        connection, Request(document.id, "statement", "pilot-1", await owner(connection, document))
    )

    assert drawn.strata == {"content": (1, 1), "learningOutcome": (1, 1)}  # by kind: in the frame, drawn
    assert not drawn.drawn_before
    items = await items_of(connection, drawn.sample)
    assert sorted((item.stratum, item.text_hash, item.first_block) for item in items) == [
        ("content", text_hash(WORDS["content"]), "p1-b2"),
        ("learningOutcome", text_hash(WORDS["outcome"]), "p1-b2"),
    ]
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


async def test_a_sample_drawn_again_is_the_one_there(connection: psycopg.AsyncConnection) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")
    account = await owner(connection, document)
    first = await draw(connection, Request(document.id, "statement", "pilot-1", account))
    before = await items_of(connection, first.sample)
    await connection.execute(
        "UPDATE statement SET revision = 1 WHERE verbatim = %s", (WORDS["edited"],)
    )  # one more to draw from

    again = await draw(connection, Request(document.id, "statement", "pilot-2", account, size=5))

    assert again == Drawn(first.sample, True, first.strata, None)
    assert await items_of(connection, first.sample) == before
    other = await draw(connection, Request(document.id, "statement", "pilot-1", account, seed="another"))
    assert other.sample != first.sample
    assert await count(connection, "gold_sample") == 2


async def test_two_draws_at_once_keep_one_sample(
    connection: psycopg.AsyncConnection, database_url: str
) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")
    request = Request(document.id, "statement", "pilot-1", await owner(connection, document))

    async def drawing() -> Drawn:
        async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as own:
            return await draw(own, request)

    first, second = await asyncio.gather(drawing(), drawing())

    assert first.sample == second.sample
    assert (await count(connection, "gold_sample"), await count(connection, "gold_item")) == (1, 2)


async def test_an_account_that_is_not_there_is_refused(connection: psycopg.AsyncConnection) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")

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


def sample_command(database_url: str, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.quality.sample", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


async def test_the_command_prints_the_sample_and_its_strata(
    connection: psycopg.AsyncConnection, database_url: str
) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")
    arguments = (str(document.id), "--kind", "statement", "--label", "pilot-1", "--account")
    account = await owner(connection, document)

    first = sample_command(database_url, *arguments, account, "--size", "2")
    refused = sample_command(database_url, *arguments, "niemand")

    assert first.returncode == 0, first.stderr
    printed = json.loads(first.stdout)
    assert printed == {
        "sample": printed["sample"], "kind": "statement", "seed": SEED, "drawn_before": False,
        "strata": {"content": {"frame": 1, "drawn": 1}, "learningOutcome": {"frame": 1, "drawn": 1}},
    }  # fmt: skip
    assert isinstance(printed["sample"], int)
    assert (refused.returncode, refused.stdout) == (1, b"")
    [line] = refused.stderr.splitlines()
    assert b"unknown_account" in line


@pytest.mark.parametrize(
    "arguments",
    [
        (),
        ("no-id", "--kind", "statement", "--label", "pilot-1", "--account", "a"),
        ("01a1951f-692d-7a7c-9470-8b70074d6685", "--kind", "node", "--label", "pilot-1", "--account", "a"),
        ("01a1951f-692d-7a7c-9470-8b70074d6685", "--kind", "block", "--label", "Pilot 1", "--account", "a"),
        (
            "01a1951f-692d-7a7c-9470-8b70074d6685",
            "--kind",
            "block",
            "--label",
            "p",
            "--account",
            "a",
            "--size",
            "0",
        ),
        (
            "01a1951f-692d-7a7c-9470-8b70074d6685",
            "--kind",
            "block",
            "--label",
            "p",
            "--account",
            "a",
            "--seed",
            "a b",
        ),
    ],
    ids=["nothing", "no-id", "no-kind", "label-with-space", "size-0", "seed-with-space"],
)
def test_a_call_amiss_is_told_by_its_exit_code(database_url: str, arguments: tuple[str, ...]) -> None:
    done = sample_command(database_url, *arguments)

    assert done.returncode == 2
    assert b"usage: python -m app.quality.sample" in done.stderr
