"""The gold standard (migration gold, plan H-3 §3.1): samples of a document's statements, blocks or anchors,
drawn once per kind and seed, and the judgements of their items - one for each account, the latest read.

No wording is kept here: an item points at its statement, node or block, and names the hash of its wording
and its first block, so that a judgement outlives the row it was made of. Only a judgement's note may
quote; it stays in the database."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# As migration gold lists them (tests/db/test_gold_schema.py)
SampleKind = Literal["statement", "block", "anchor"]
Verdict = Literal["correct", "imprecise", "wrong"]
TitlePages = Literal["left_out", "set_apart", "unknown"]
Reason = Literal[
    "not_a_statement", "not_in_document", "node", "boundary", "kind", "fields", "wrong_place", "missed"
]

# The first draw under a document's kind and seed writes it; one at the same time, or after, finds it
_ADD = """
INSERT INTO gold_sample (kind, document_id, label, seed, size, frame, drawn_by, title_pages)
VALUES (%(kind)s, %(document)s, %(label)s, %(seed)s, %(size)s, %(frame)s, %(drawn_by)s, %(title_pages)s)
ON CONFLICT (document_id, kind, seed) DO NOTHING
RETURNING id
"""
_THERE = "SELECT id FROM gold_sample WHERE document_id = %s AND kind = %s AND seed = %s"
_ITEM = """
INSERT INTO gold_item (sample_id, stratum, place, statement_id, node_id, block_id, text_hash, first_block)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""
_SAMPLE = """
SELECT id, kind, document_id, label, seed, size, frame, drawn_by, title_pages, drawn_at
FROM gold_sample WHERE id = %s
"""
_ITEMS = """
SELECT id, sample_id, stratum, place, statement_id, node_id, block_id, text_hash, first_block
FROM gold_item WHERE sample_id = %s ORDER BY place
"""
_JUDGE = """
INSERT INTO gold_judgement (item_id, judged_by, verdict, reasons, expected, note)
VALUES (%(item)s, %(account)s, %(verdict)s, %(reasons)s, %(expected)s, %(note)s)
ON CONFLICT (item_id, judged_by) DO UPDATE SET verdict = excluded.verdict, reasons = excluded.reasons,
    expected = excluded.expected, note = excluded.note, judged_at = now()
"""
# A sheet's judgement, decided in the statement: a new one is made, a changed one replaces the account's
# own, one as it stands touches nothing (not even its time) and returns no row
_JUDGE_SHEET = """
INSERT INTO gold_judgement (item_id, judged_by, verdict, reasons, expected, note)
VALUES (%(item)s, %(account)s, %(verdict)s, %(reasons)s, %(expected)s, %(note)s)
ON CONFLICT (item_id, judged_by) DO UPDATE SET verdict = excluded.verdict, reasons = excluded.reasons,
    expected = excluded.expected, note = excluded.note, judged_at = now()
WHERE (gold_judgement.verdict, gold_judgement.reasons, gold_judgement.expected, gold_judgement.note)
    IS DISTINCT FROM (excluded.verdict, excluded.reasons, excluded.expected, excluded.note)
RETURNING xmax = 0 AS made
"""
# The latest of each item's judgements; of two at the same time, the account's id decides
_JUDGEMENTS = """
SELECT DISTINCT ON (j.item_id) j.item_id, j.verdict, j.reasons, j.expected, j.note
FROM gold_judgement j JOIN gold_item i ON i.id = j.item_id
WHERE i.sample_id = %s
ORDER BY j.item_id, j.judged_at DESC, j.judged_by DESC
"""
# The accounts among the judgements the report counts: each item's latest
_JUDGES = """
SELECT count(DISTINCT judged_by) FROM (
    SELECT DISTINCT ON (j.item_id) j.judged_by
    FROM gold_judgement j JOIN gold_item i ON i.id = j.item_id
    WHERE i.sample_id = %s
    ORDER BY j.item_id, j.judged_at DESC, j.judged_by DESC
) latest
"""


@dataclass(frozen=True)
class SampleDraft:
    kind: SampleKind
    document_id: UUID
    label: str  # how the report names the document: never its title
    seed: str
    size: int  # asked for
    frame: Mapping[str, int]  # the population of each stratum when drawn
    drawn_by: UUID  # the account
    # whether the title pages were found: a block sample left them out (left_out), an anchor sample set their
    # rows apart in the strata front:* (set_apart); unknown where not found; None for statements
    title_pages: TitlePages | None


@dataclass(frozen=True)
class Sample(SampleDraft):
    id: int
    drawn_at: datetime


@dataclass(frozen=True)
class ItemDraft:
    """What an item points at - one statement, node or block - with the hash of its wording (a statement's,
    a node's title) and its first block when drawn."""

    stratum: str
    statement_id: UUID | None = None
    node_id: UUID | None = None
    block_id: str | None = None
    text_hash: str | None = None
    first_block: str | None = None


@dataclass(frozen=True, kw_only=True)
class Item(ItemDraft):
    id: int
    sample_id: int
    place: int  # its rank in the sample, from 1


@dataclass(frozen=True)
class Judgement:
    """A verdict with its reasons (none for correct, one at least else), or a block's count alone."""

    verdict: Verdict | None
    reasons: tuple[Reason, ...]
    expected: int | None  # a block's: the statements it holds
    note: str | None  # may quote: never exported


async def add_sample(
    connection: psycopg.AsyncConnection, draft: SampleDraft, items: Sequence[ItemDraft]
) -> int:
    """The id of the document's sample of this kind and seed: written with its items, in their order, where
    none is there yet; else the one there, unchanged - also when another draw wrote it meanwhile."""
    values = {
        "kind": draft.kind,
        "document": draft.document_id,
        "label": draft.label,
        "seed": draft.seed,
        "size": draft.size,
        "frame": Jsonb(dict(draft.frame)),
        "drawn_by": draft.drawn_by,
        "title_pages": draft.title_pages,
    }
    async with connection.transaction():
        cursor = await connection.execute(_ADD, values)
        made = await cursor.fetchone()
        if made is None:
            # read after the insert waited for the draw it met: this statement sees what that one wrote
            there = await sample_drawn(connection, draft.document_id, draft.kind, draft.seed)
            if there is None:  # taken away with its document meanwhile
                raise LookupError(f"no document {draft.document_id}")
            return there
        sample = int(made[0])
        async with connection.cursor() as writing:
            await writing.executemany(
                _ITEM,
                [
                    (sample, item.stratum, place, item.statement_id, item.node_id, item.block_id,
                     item.text_hash, item.first_block)
                    for place, item in enumerate(items, start=1)
                ],
            )  # fmt: skip
    return sample


async def sample_drawn(
    connection: psycopg.AsyncConnection, document_id: UUID, kind: SampleKind, seed: str
) -> int | None:
    """The id of the document's sample of this kind and seed, where one is drawn."""
    cursor = await connection.execute(_THERE, (document_id, kind, seed))
    found = await cursor.fetchone()
    return None if found is None else int(found[0])


async def sample_by_id(connection: psycopg.AsyncConnection, sample_id: int) -> Sample | None:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_SAMPLE, (sample_id,))
        row = await cursor.fetchone()
    return None if row is None else Sample(**row)


async def items_of(connection: psycopg.AsyncConnection, sample_id: int) -> list[Item]:
    """The sample's items by their place."""
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_ITEMS, (sample_id,))
        rows = await cursor.fetchall()
    return [Item(**row) for row in rows]


async def judge(
    connection: psycopg.AsyncConnection, item_id: int, account_id: UUID, judgement: Judgement
) -> None:
    """The account's judgement of the item, over its own before; psycopg.errors.ForeignKeyViolation where the
    item or the account is not there, CheckViolation where it breaks the table's rules."""
    await connection.execute(
        _JUDGE,
        {
            "item": item_id,
            "account": account_id,
            "verdict": judgement.verdict,
            "reasons": list(judgement.reasons),
            "expected": judgement.expected,
            "note": judgement.note,
        },
    )


@dataclass(frozen=True)
class Judged:
    """What the judgements of one sheet did: made new, changed the account's own, or found it as it stood."""

    new: int
    changed: int
    unchanged: int


async def judge_all(
    connection: psycopg.AsyncConnection, account_id: UUID, judgements: Sequence[tuple[int, Judgement]]
) -> Judged:
    """The account's judgements of the items, all in one transaction or none: two imports at once meet at
    the key (item, account) and the later finds the earlier's; written in the items' order, whatever order
    they come in. ForeignKeyViolation where an item is gone."""
    new = changed = 0
    async with connection.transaction():
        # in the items' order: two imports at once take their rows' locks in one order, and wait, not deadlock
        for item_id, judgement in sorted(judgements, key=lambda judged: judged[0]):
            cursor = await connection.execute(
                _JUDGE_SHEET,
                {
                    "item": item_id,
                    "account": account_id,
                    "verdict": judgement.verdict,
                    "reasons": list(judgement.reasons),
                    "expected": judgement.expected,
                    "note": judgement.note,
                },
            )
            if (written := await cursor.fetchone()) is not None:
                new, changed = (new + 1, changed) if written[0] else (new, changed + 1)
    return Judged(new, changed, len(judgements) - new - changed)


async def judgements_of(connection: psycopg.AsyncConnection, sample_id: int) -> dict[int, Judgement]:
    """The latest judgement of each judged item of the sample, by the item's id."""
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_JUDGEMENTS, (sample_id,))
        rows = await cursor.fetchall()
    return {
        row["item_id"]: Judgement(
            verdict=row["verdict"], reasons=tuple(row["reasons"]), expected=row["expected"], note=row["note"]
        )
        for row in rows
    }


async def judges_of(connection: psycopg.AsyncConnection, sample_id: int) -> int:
    """How many accounts gave the judgements read for the sample (judgements_of): two mean a mixed figure."""
    cursor = await connection.execute(_JUDGES, (sample_id,))
    [(found,)] = await cursor.fetchall()
    return int(found)
