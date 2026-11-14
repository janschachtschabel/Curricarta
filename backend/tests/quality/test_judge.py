"""``python -m app.quality.judge``: a judging sheet comes back from a spreadsheet and its judgements go in -
by item and mark, all or nothing; a row left empty is no judgement; a sheet that breaks a rule is refused
as a whole with the row named; the wording and the other shown columns are never read."""

import asyncio
import csv
import io
from pathlib import Path

import psycopg
import pytest

from app.db.gold import Judgement, items_of, judgements_of
from app.db.nodes import write_subtree
from app.domain.l1 import AnchorDraft, NodeDraft
from app.quality.judge import SheetRefused, Taken, take_in
from app.quality.sample import Request, draw
from app.quality.sheet import mark
from tests.db.document_of import document_of
from tests.quality.gold_documents import (
    CV,
    IMPORTED,
    LONG,
    PROPOSED,
    WORDS,
    a_document,
    block,
    connection,
    count,
    done,
    owner,
    statement,
    with_contents,
)

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

SHEET = (Path(__file__).parent / "fixtures" / "bogen.csv").read_bytes()
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
HEADER = "note;verdict;reasons;item;mark;stratum;wording;expected;shown"
# by physical line: the header, items 1 and 2, item 3 over two lines (its note runs on), items 4 and 5
ROWS = SHEET.decode("utf-8-sig").split("\r\n")
EXPECTED = {
    1: Judgement("correct", (), None, None),
    2: Judgement("imprecise", ("boundary", "kind"), None, None),
    3: Judgement("wrong", ("not_a_statement",), None, "Begriff; selbstständig\r\nSchritt"),
    5: Judgement("correct", (), None, None),
}


async def a_sample(connection: psycopg.AsyncConnection) -> tuple[int, str]:
    """The statement sample bogen.csv is the sheet of, and its judge's name."""
    document = await a_document(connection)
    await done(connection, document, "X4")
    account = await owner(connection, document)
    drawn = await draw(connection, Request(document.id, "statement", "pilot-1", account))
    return drawn.sample, account


def edited(*rows: str, header: str = HEADER) -> bytes:
    """A sheet of the header and rows given, each a line, as the spreadsheet saved the fixture."""
    return (BOM + "\r\n".join((header, *rows)) + "\r\n").encode("utf-8")


async def test_judgements_come_in_by_item_and_mark(connection: psycopg.AsyncConnection) -> None:
    sample, account = await a_sample(connection)
    commas = io.StringIO(newline="")
    csv.writer(commas, lineterminator="\n").writerows(
        csv.reader(io.StringIO(SHEET.decode("utf-8-sig"), newline=""), delimiter=";")
    )

    first = await take_in(connection, sample, account, SHEET)
    again = await take_in(connection, sample, account, SHEET)
    as_commas = await take_in(connection, sample, account, commas.getvalue().encode("utf-8"))  # no BOM, LF

    assert first == Taken(judged=4, new=4, changed=0, unchanged=0, left_empty=1)
    assert again == Taken(judged=4, new=0, changed=0, unchanged=4, left_empty=1)  # nothing changes
    assert as_commas == again
    assert await judgements_of(connection, sample) == EXPECTED
    changed = SHEET.replace(b";correct;;1;", b";wrong;node;1;")
    assert await take_in(connection, sample, account, changed) == Taken(4, 0, 1, 3, 1)
    assert (await judgements_of(connection, sample))[1] == Judgement("wrong", ("node",), None, None)


async def test_a_row_left_empty_is_no_judgement(connection: psycopg.AsyncConnection) -> None:
    sample, account = await a_sample(connection)
    await take_in(connection, sample, account, SHEET)
    blank = ROWS[1].replace(";correct;", ";;", 1)  # item 1 left empty now

    taken = await take_in(connection, sample, account, edited(blank, ";;;;;;;", ""))

    assert taken == Taken(judged=0, new=0, changed=0, unchanged=0, left_empty=1)
    assert (await judgements_of(connection, sample))[1] == EXPECTED[1]  # an empty cell takes nothing away
    assert await count(connection, "gold_judgement") == 4


async def test_a_sheet_of_another_database_is_refused_whole(connection: psycopg.AsyncConnection) -> None:
    sample, account = await a_sample(connection)
    other = SHEET.replace(b";ma8fb47665142;", b";ma8fb47665143;")

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, other)

    assert refused.value.problems == ["line 4: mark_differs"]  # the row's first line: its note runs on
    assert await count(connection, "gold_judgement") == 0


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        (";korrekt;;1;m676f35a0284b;;;n/a", "verdict_unknown"),
        (";wrong;spelling;1;m676f35a0284b;;;n/a", "reasons_amiss"),
        (";wrong;boundary;1;m676f35a0284b;;;n/a", "reasons_amiss"),  # an imprecise one's
        (";wrong;wrong_place;1;m676f35a0284b;;;n/a", "reasons_amiss"),  # an anchor's
        (";correct;kind;1;m676f35a0284b;;;n/a", "reasons_amiss"),
        (";imprecise;;1;m676f35a0284b;;;n/a", "reasons_amiss"),
        (";;kind;1;m676f35a0284b;;;n/a", "reasons_amiss"),  # reasons without a verdict
        (";correct;;1;m676f35a0284b;;;3", "count_not_asked"),
        ("Begriff;;;1;m676f35a0284b;;;n/a", "note_alone"),
        (";correct;;99;m676f35a0284b;;;n/a", "item_unknown"),  # no item at all
        (";correct;;eins;m676f35a0284b;;;n/a", "item_unknown"),
    ],
    ids=["verdict", "reason", "reason-of-another", "anchor-s-reason", "correct-with-reason",
         "imprecise-without", "reason-alone", "count", "note-alone", "no-item", "no-number"],
)  # fmt: skip
async def test_a_verdict_or_reason_outside_the_list_refuses_the_sheet_and_names_the_row(
    connection: psycopg.AsyncConnection, row: str, problem: str
) -> None:
    sample, account = await a_sample(connection)

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, edited(ROWS[2], row))  # a good row before it

    assert refused.value.problems == [f"line 3: {problem}"]
    assert await count(connection, "gold_judgement") == 0  # not the good row either


async def test_a_duplicated_row_refuses_the_sheet(connection: psycopg.AsyncConnection) -> None:
    sample, account = await a_sample(connection)

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, edited(ROWS[2], ROWS[5], ROWS[2]))

    assert refused.value.problems == ["line 4: item_twice"]
    assert await count(connection, "gold_judgement") == 0


async def test_a_block_is_judged_by_a_count_alone(connection: psycopg.AsyncConnection) -> None:
    document = await document_of(connection, with_contents())
    await done(connection, document, "X4")
    account = await owner(connection, document)
    sample = (await draw(connection, Request(document.id, "block", "pilot-1", account))).sample
    header = "item;mark;shown;verdict;reasons;expected"
    first, second, third = (
        f"{item.id};{item.block_id};{item.block_id}" for item in await items_of(connection, sample)
    )

    taken = await take_in(
        connection, sample, account, edited(f"{first};n/a;n/a;3", f"{second};;; 0 ", header=header)
    )
    with pytest.raises(SheetRefused) as refused:
        await take_in(
            connection, sample, account,
            edited(f"{first};correct;;", f"{second};;;drei", f"{third};;;501", header=header),
        )  # fmt: skip

    assert taken == Taken(judged=2, new=2, changed=0, unchanged=0, left_empty=0)
    counts = sorted((j.expected, j.verdict) for j in (await judgements_of(connection, sample)).values())
    assert counts == [(0, None), (3, None)]
    assert refused.value.problems == [
        "line 2: verdict_not_asked",
        "line 3: count_amiss",
        "line 4: count_amiss",
    ]


async def test_an_anchor_not_found_is_wrong_where_its_wording_is_there(
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
        ),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)
    await done(connection, document, "IM")
    account = await owner(connection, document)
    sample = (await draw(connection, Request(document.id, "anchor", "mem-1", account))).sample
    items = {
        item.stratum: f"{item.id};{mark(item)};{mark(item)}" for item in await items_of(connection, sample)
    }
    header = "item;mark;shown;verdict;reasons"
    missed, misplaced = items["notFound:statement"], items["whitespace:statement"]

    taken = await take_in(
        connection, sample, account,
        edited(f"{missed};wrong;missed", f"{misplaced};wrong;wrong_place", header=header),
    )  # fmt: skip
    with pytest.raises(SheetRefused) as refused:
        await take_in(
            connection, sample, account,
            edited(f"{missed};wrong;wrong_place", f"{misplaced};wrong;missed", header=header),
        )  # fmt: skip

    assert taken.new == 2
    assert refused.value.problems == ["line 2: reasons_amiss", "line 3: reasons_amiss"]


async def test_the_wording_column_is_never_read_back(connection: psycopg.AsyncConnection) -> None:
    sample, account = await a_sample(connection)
    shown = "item;mark;shown;verdict;reasons;expected;wording;quote"
    bare = "item;mark;shown;verdict;reasons;expected"

    taken = await take_in(
        connection, sample, account,
        edited(
            '1;m676f35a0284b;m676f35a0284b;correct;;n/a;"=HYPERLINK(""x"");wrong;not_a_statement";@',
            header=shown,
        ),
    )  # fmt: skip
    without = await take_in(
        connection, sample, account, edited("1;m676f35a0284b;m676f35a0284b;correct;;n/a", header=bare)
    )

    assert taken == Taken(judged=1, new=1, changed=0, unchanged=0, left_empty=0)
    assert without == Taken(judged=1, new=0, changed=0, unchanged=1, left_empty=0)
    assert (await judgements_of(connection, sample))[1] == EXPECTED[1]


async def test_a_note_is_cut_to_what_the_table_holds_or_refused(connection: psycopg.AsyncConnection) -> None:
    sample, account = await a_sample(connection)
    longest = "a" * 500

    taken = await take_in(
        connection, sample, account, edited(f"{longest}   ;correct;;1;m676f35a0284b;;;n/a;m676f35a0284b")
    )
    with pytest.raises(SheetRefused) as refused:
        await take_in(
            connection, sample, account, edited(f"{longest}b;correct;;1;m676f35a0284b;;;n/a;m676f35a0284b")
        )

    assert taken.new == 1
    assert (await judgements_of(connection, sample))[1].note == longest  # the spaces after it cut
    assert refused.value.problems == ["line 2: note_too_long"]


async def test_two_imports_at_once_leave_one_judgement_each(
    connection: psycopg.AsyncConnection, database_url: str
) -> None:
    sample, account = await a_sample(connection)

    async def one() -> Taken:
        async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as other:
            return await take_in(other, sample, account, SHEET)

    first, second = await asyncio.gather(one(), one())

    assert sorted([first.new, second.new]) == [0, 4]
    assert sorted([first.unchanged, second.unchanged]) == [0, 4]
    assert await count(connection, "gold_judgement") == 4
