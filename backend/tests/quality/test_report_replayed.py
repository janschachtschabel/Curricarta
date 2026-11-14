"""``python -m app.quality.report --replayed``: beside a statement sample's measures, what a replay of the
document's kept answers (app/pipeline/replay.py) would keep and lose of its judgements - by verdict, each
judgement following its wording at its first block, whichever row holds it - and how many statements it
reads that nobody judged. The replay is handed in here; the command's own, end to end:
tests/pipeline/test_replay.py."""

from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

import psycopg
import pytest

from app.db.gold import items_of, judge
from app.db.nodes import write_subtree
from app.domain.l1 import NodeDraft
from app.domain.wording import text_hash
from app.quality.report import report
from tests.quality.gold_documents import CV, MODEL, PROPOSED, WORDS, a_document, connection, done, statement
from tests.quality.test_report import CORRECT, IMPRECISE, WRONG, drawn

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

Key = tuple[str, str]


def replaying(keys: Sequence[Key], asked: list[UUID]) -> Callable[[UUID], Awaitable[Sequence[Key]]]:
    async def replay(document_id: UUID) -> Sequence[Key]:
        asked.append(document_id)
        return keys

    return replay


async def test_a_statement_replaced_with_the_same_wording_at_the_same_block_keeps_its_judgement(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await a_document(connection)  # five of the model's, each first at p1-b2
    await done(connection, document, "X4")
    sample = await drawn(connection, document, "statement")
    for item in await items_of(connection, sample):
        await judge(connection, item.id, document.owner_id, CORRECT)
    # a new run writes the same statement anew: another row, the same wording at the same first block
    await connection.execute("DELETE FROM statement WHERE verbatim = %s", (WORDS["outcome"],))
    again = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=WORDS["title"],
        statements=(statement(WORDS["outcome"], ("p1-b3", "p1-b2")),),
    )  # fmt: skip
    await write_subtree(connection, document.id, again)
    names = ("outcome", "content", "confirmed", "rejected", "reworded")
    read_now = [(text_hash(WORDS[name]), "p1-b2") for name in names]
    asked: list[UUID] = []

    measures = (await report(connection, [sample], replay=replaying(read_now, asked)))["documents"][0][
        "statement"
    ]

    assert asked == [document.id]
    assert measures["stale"] == {"gone": 1, "changed": 0}  # its row is gone: no longer what was drawn ...
    assert measures["replayed"] == {
        "kept_correct": 5, "kept_imprecise": 0, "kept_wrong": 0,
        "gone_correct": 0, "gone_imprecise": 0, "gone_wrong": 0,
        "new_unjudged": 0,
    }  # ... yet its judgement holds for the wording read again at its block  # fmt: skip


async def test_what_a_replay_would_keep_and_lose_is_counted(connection: psycopg.AsyncConnection) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")
    sample = await drawn(connection, document, "statement")
    hashed = {text_hash(WORDS[name]): name for name in ("outcome", "content", "confirmed", "rejected")}
    verdicts = {"outcome": CORRECT, "content": IMPRECISE, "confirmed": WRONG, "rejected": WRONG}
    for item in await items_of(connection, sample):
        if item.text_hash in hashed:  # the reworded one left open
            await judge(connection, item.id, document.owner_id, verdicts[hashed[item.text_hash]])
    novel = text_hash(WORDS["new"])
    read_now = [
        (text_hash(WORDS["outcome"]), "p1-b2"),
        (text_hash(WORDS["confirmed"]), "p1-b2"),
        (text_hash(WORDS["content"]), "p1-b3"),  # at another block: another statement
        (novel, "p1-b3"),
        (novel, "p1-b3"),  # read twice: two statements nobody judged
    ]

    made = await report(connection, [sample], replay=replaying(read_now, []))
    plain = await report(connection, [sample])

    assert made["documents"][0]["statement"]["replayed"] == {
        "kept_correct": 1, "kept_imprecise": 0, "kept_wrong": 1,
        "gone_correct": 0, "gone_imprecise": 1, "gone_wrong": 1,
        "new_unjudged": 3,
    }  # fmt: skip
    assert "replayed" not in plain["documents"][0]["statement"]  # asked for with --replayed alone
