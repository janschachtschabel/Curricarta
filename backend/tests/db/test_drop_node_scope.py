"""A node dropped (app/db/node_drop.py) gathers its subtree within its own document, by an index
(audit 2026-11-14): the recursion over the children and the anchors of nodes and statements each name the
document, so no row of another document is read - and on a server of many documents none is scanned."""

import os
from typing import Any

import psycopg
import pytest

from app.db.documents import create_document
from app.db.node_drop import _SUBTREE, Dropped, drop_node
from app.db.nodes import write_subtree
from app.db.source_queries import Reader
from tests.db.l1 import add_conversion
from tests.db.test_editing import extracted
from tests.db.test_nodes import anchor, connection, node, owner, statement, url

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "url"]  # the fixtures, shared with test_nodes


async def a_document(url: str, connection: psycopg.AsyncConnection) -> Any:
    """A school document whose extraction read every package, its tree three levels deep."""
    with psycopg.connect(url, autocommit=True) as sync:
        made = add_conversion(sync, digest=os.urandom(32))
    document = await create_document(
        connection, Reader(made["owner"], sees_all=False), third_party_content=False,
        source_id=made["source"], conversion_id=made["conversion"], sector="school",
    )  # fmt: skip
    await extracted(connection, document)
    await write_subtree(
        connection,
        document.id,
        node(
            statements=(statement("Sie lesen."),),
            children=(
                node("fn_unit", anchors=(anchor("p1-b1"),), statements=(statement("Sie messen."),),
                     children=(node("fn_unit", statements=(statement("Sie prüfen."),)),)),
            ),
        ),
    )  # fmt: skip
    return document


async def counts(connection: psycopg.AsyncConnection, document: Any) -> tuple[int, ...]:
    cursor = await connection.execute(
        "SELECT (SELECT count(*) FROM node WHERE document_id = %(d)s),"
        " (SELECT count(*) FROM statement WHERE document_id = %(d)s),"
        " (SELECT count(*) FROM anchor WHERE document_id = %(d)s)",
        {"d": document.id},
    )
    found = await cursor.fetchone()
    assert found is not None
    return tuple(found)


async def middle_node(connection: psycopg.AsyncConnection, document: Any) -> Any:
    cursor = await connection.execute(
        "SELECT n.id FROM node n JOIN node top ON top.id = n.parent_id"
        " WHERE n.document_id = %s AND top.parent_id IS NULL",
        (document.id,),
    )
    found = await cursor.fetchone()
    assert found is not None
    return found[0]


async def test_a_node_of_another_document_is_never_taken_along(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    first, second = await a_document(url, connection), await a_document(url, connection)
    before = await counts(connection, second)

    gone = await drop_node(connection, owner(first), await middle_node(connection, first), 1)

    assert gone == Dropped(nodes=2, statements=2)
    assert await counts(connection, first) == (1, 1, 1)  # the top and its statement, whose anchor stays
    assert await counts(connection, second) == before


TABLES = ("node", "statement", "anchor")


def scans(plan: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Each scan of the plan: its node type, the table (Seq Scan) or index it reads, its index condition."""
    found = []
    if plan["Node Type"] == "Seq Scan":
        found.append(("Seq Scan", plan["Relation Name"], ""))
    elif "Index Name" in plan:
        found.append((plan["Node Type"], plan["Index Name"], plan.get("Index Cond", "")))
    for part in plan.get("Plans", []):
        found += scans(part)
    return found


async def indexes(connection: psycopg.AsyncConnection) -> dict[str, tuple[str, str]]:
    """The table and first column of each index of the three tables, by the index's name."""
    cursor = await connection.execute(
        "SELECT c.relname, t.relname, a.attname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid"
        " JOIN pg_class t ON t.oid = i.indrelid"
        " JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]"
        " WHERE t.relname = ANY(%s)",
        (list(TABLES),),
    )
    return {index: (table, column) for index, table, column in await cursor.fetchall()}


async def test_taking_a_node_away_finds_its_rows_by_an_index(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    # Sequential scans priced out, the planner still reads a table whole where no index serves: by a
    # sequential scan, or along an index whose first column the condition leaves open
    document = await a_document(url, connection)
    node_id = await middle_node(connection, document)
    of = await indexes(connection)

    async with connection.transaction():
        await connection.execute("SET LOCAL enable_seqscan = off")
        cursor = await connection.execute(
            b"EXPLAIN (FORMAT JSON) " + _SUBTREE.encode(), {"id": node_id, "document": document.id}
        )
        found = await cursor.fetchone()

    assert found is not None
    read = scans(found[0][0]["Plan"])
    whole = [
        (kind, name, condition)
        for kind, name, condition in read
        if name in TABLES or (name in of and f"({of[name][1]} = " not in condition)
    ]
    assert whole == []
    assert {of[name][0] for _, name, _ in read if name in of} == set(TABLES)  # each read, by an index
