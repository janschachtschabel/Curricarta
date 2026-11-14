"""The gold report holds counts, rates and codes alone (plan H-3 §3.5): no wording, quote, note or title
passes it, and a report that would carry another leaf is refused rather than printed."""

import json
import re
from collections.abc import Iterator

import psycopg
import pytest

from app.core.ids import new_id
from app.db.gold import ItemDraft, Judgement, SampleDraft, add_sample, items_of, judge
from app.db.nodes import write_subtree
from app.domain.l1 import AnchorDraft, NodeDraft
from app.quality.report import Refused, closed, report
from app.quality.report_sections import LEAF
from tests.db.document_of import document_of
from tests.quality.gold_documents import (
    CV,
    LONG,
    MODEL,
    PROPOSED,
    WORDS,
    a_document,
    block,
    connection,
    done,
    statement,
)
from tests.quality.test_report import drawn

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents


async def test_a_report_that_would_not_be_closed_is_refused(connection: psycopg.AsyncConnection) -> None:
    document = await a_document(connection)
    draft = SampleDraft("statement", document.id, "pilot-1", "s", 1, {"x" * 61: 1}, document.owner_id, None)
    sample = await add_sample(connection, draft, [ItemDraft("x" * 61, statement_id=new_id())])

    with pytest.raises(Refused, match="report_not_closed"):
        await report(connection, [sample])


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
