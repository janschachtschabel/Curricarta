"""A judging sheet as a spreadsheet, an editor or a shell hands it back: what the importer reads of it
and what it refuses at its line - an encoding it cannot tell, a separator it does not know, a mark a
spreadsheet turned into a number, an item that is no item of the sheet's sample."""

import psycopg
import pytest

from app.db.gold import ItemDraft, SampleDraft, add_sample, items_of, judgements_of
from app.db.nodes import write_subtree
from app.domain.l1 import NodeDraft
from app.domain.wording import text_hash
from app.quality.judge import SheetRefused, take_in
from app.quality.sample import Request, draw
from app.quality.sheet import encoded, sheet_rows
from tests.quality.gold_documents import (
    CV,
    MODEL,
    PROPOSED,
    WORDS,
    a_document,
    connection,
    mem_synth,
    owner,
    statement,
    statement_id,
)
from tests.quality.test_judge import BOM, EXPECTED, SHEET, a_sample, edited

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        (SHEET.replace(b";", b"\t"), "line 1: delimiter_unknown"),
        (SHEET.replace(b";mark;", b";marke;"), "line 1: column_missing"),
        (SHEET.replace(b"note;verdict", b"verdict;verdict"), "line 1: column_twice"),
        ((BOM + SHEET.decode("utf-8-sig")).encode("utf-16-le"), "line 1: encoding_unknown"),
        (SHEET.replace(b"Schritt", b"Schritt\x81"), "line 5: encoding_unknown"),  # neither UTF-8 nor cp1252
    ],
    ids=["tabs", "no-mark", "twice", "utf-16", "undecodable"],
)
async def test_a_sheet_the_importer_cannot_read_is_refused_at_its_line(
    connection: psycopg.AsyncConnection, data: bytes, problem: str
) -> None:
    sample, account = await a_sample(connection)

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, data)

    assert refused.value.problems == [problem]


async def test_a_sheet_saved_in_the_spreadsheet_s_own_encoding_comes_in(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, account = await a_sample(connection)
    windows = SHEET.decode("utf-8-sig").encode("cp1252")  # as a spreadsheet saves "CSV" in Western Europe

    taken = await take_in(connection, sample, account, windows)

    assert taken.new == 4
    assert (await judgements_of(connection, sample))[3].note == EXPECTED[3].note


async def test_a_sheet_that_states_utf8_by_its_bom_is_read_as_utf8_alone(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, account = await a_sample(connection)
    broken = SHEET.replace(b"Schritt", b"Schritt\xe4")  # a cp1252 sign in a sheet whose BOM says UTF-8

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, broken)

    assert refused.value.problems == ["line 5: encoding_unknown"]


async def test_a_mark_of_digits_alone_comes_back_as_it_went(connection: psycopg.AsyncConnection) -> None:
    document = await a_document(connection)
    # a wording whose hash begins with twelve digits: a number to a spreadsheet, were it not for the m
    wording = next(
        made
        for seed in range(100_000)
        if (made := mem_synth.wording("Die Lernenden ordnen den Bach.", seed))
        and text_hash(made)[:12].isdigit()
    )
    under = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title=WORDS["title"],
        statements=(statement(wording, kind=CV + "kind_content"),),
    )  # fmt: skip
    await write_subtree(connection, document.id, under)
    draft = SampleDraft("statement", document.id, "pilot-1", "s", 1, {"content": 1}, document.owner_id, None)
    item = ItemDraft(
        "content", statement_id=await statement_id(connection, wording), text_hash=text_hash(wording)
    )
    sample = await add_sample(connection, draft, [item])
    [row] = await sheet_rows(connection, sample, "http://127.0.0.1:18080")
    row["verdict"] = "correct"

    taken = await take_in(connection, sample, await owner(connection, document), encoded([row]))

    assert row["mark"] == "m" + text_hash(wording)[:12] and row["mark"][1:].isdigit()
    assert taken.new == 1


@pytest.mark.parametrize("cell", ["1.23457E+11", "123456789012", "6.76E+35", "676f35a0284b"])
async def test_a_mark_a_spreadsheet_turned_into_a_number_is_refused_as_such(
    connection: psycopg.AsyncConnection, cell: str
) -> None:
    sample, account = await a_sample(connection)

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, edited(f";correct;;1;{cell};;;n/a"))

    assert refused.value.problems == ["line 2: mark_mangled"]  # not another database's sheet


@pytest.mark.parametrize(
    ("row", "problem"),
    [(";correct;;\N{SUPERSCRIPT TWO};m676f35a0284b;;;n/a", "item_unknown"),
     (";correct;;\N{FULLWIDTH DIGIT ONE};m676f35a0284b;;;n/a", "item_unknown")],
    ids=["superscript", "wide-digit"],
)  # fmt: skip
async def test_a_sign_that_is_a_digit_to_unicode_alone_is_no_number(
    connection: psycopg.AsyncConnection, row: str, problem: str
) -> None:
    sample, account = await a_sample(connection)

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, edited(row))

    assert refused.value.problems == [f"line 2: {problem}"]


async def test_an_item_of_another_sample_of_the_document_is_refused(
    connection: psycopg.AsyncConnection,
) -> None:
    sample, account = await a_sample(connection)
    cursor = await connection.execute("SELECT document_id FROM gold_sample WHERE id = %s", (sample,))
    [(document,)] = await cursor.fetchall()
    other = (await draw(connection, Request(document, "statement", "pilot-1", account, seed="other"))).sample
    stranger = (await items_of(connection, other))[0]
    mark = "m" + (stranger.text_hash or "")[:12]  # the same statement, so the same mark: another id

    with pytest.raises(SheetRefused) as refused:
        await take_in(connection, sample, account, edited(f";correct;;{stranger.id};{mark};;;n/a"))

    assert refused.value.problems == ["line 2: item_unknown"]
