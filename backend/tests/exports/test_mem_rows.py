"""A MEM import read for its export (app/exports/mem_rows.py, plan M2-6): the document with the plan it
names, its nodes and statements with their IRIs, origins and what MEM said of them - a rejected statement
left out - read in one snapshot."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.core.ids import new_id
from app.db.documents import DocumentError
from app.db.migrate import migrate
from app.exports.mem_rows import read_mem_document
from app.vocab.store import load_vocabulary
from tests.db.l1 import add_conversion, add_document, add_node, add_statement
from tests.support import ontology_vocabulary

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

CV = "https://w3id.org/wlo/curriculum/vocab#"
LP = "https://w3id.org/lehrplan/ontology/"
PLAN = "https://lp-sachsen.org/resource/lehrplan-141-1"
DOC = "https://example.org/kk/doc/de-sn/lp/1"


@pytest.fixture
def sync(database_url: str, preloaded_vocabulary: None) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    with psycopg.connect(database_url, autocommit=True) as opened:
        yield opened


@pytest.fixture
async def connection(database_url: str, sync: psycopg.Connection) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as opened:
        yield opened


def an_import(sync: psycopg.Connection) -> dict[str, Any]:
    """A document of an import with a node and two statements, one rejected."""
    document = add_document(
        sync, add_conversion(sync), title="Lehrplan Deutsch", iri=DOC, mem_iri=PLAN,
        mem_land_iri=LP + "LP_3000014", mem_class_iri=LP + "LP_0000438", mem_subjects=[LP + "LP_0000590"],
        mem_attribution="FWU", rights_status="amtlich",
    )  # fmt: skip
    node = add_node(
        sync, document, iri=DOC + "/1", origin_iri=CV + "orig_import", original_title="Lernbereich 1",
        title_language="de", code="1", mem_iri=PLAN + "/teil-1", mem_classes=[LP + "LP_0030050"],
        mem_properties=Jsonb({"number": "1"}),
    )  # fmt: skip
    kept = add_statement(
        sync, document, node, iri=DOC + "/1/s-1", origin_iri=CV + "orig_import", language="de",
        mem_iri=PLAN + "/teil-2", mem_classes=[LP + "LP_0000263"], mem_properties=Jsonb({"hours": "4"}),
    )  # fmt: skip
    add_statement(sync, document, node, position=2, review_status_iri=CV + "rev_rejected")
    return {"document": document, "node": node, "statement": kept}


async def test_an_import_s_rows_are_read_with_their_iris_and_what_mem_said(
    sync: psycopg.Connection, connection: psycopg.AsyncConnection
) -> None:
    made = an_import(sync)

    rows = await read_mem_document(connection, made["document"])

    document = rows.document
    assert (document["id"], document["iri"], document["title"], document["rights_status"]) == (
        made["document"], DOC, "Lehrplan Deutsch", "amtlich",
    )  # fmt: skip
    assert (document["mem_iri"], document["mem_land_iri"], document["mem_class_iri"]) == (
        PLAN, LP + "LP_3000014", LP + "LP_0000438",
    )  # fmt: skip
    assert (document["mem_subjects"], document["mem_school_types"], document["mem_licence"]) == (
        [LP + "LP_0000590"], [], None,
    )  # fmt: skip
    assert document["mem_attribution"] == "FWU" and document["frozen_at"] is None
    [node] = rows.nodes
    assert {key: node[key] for key in ("id", "parent_id", "iri", "origin_iri", "original_title", "code")} == {
        "id": made["node"], "parent_id": None, "iri": DOC + "/1", "origin_iri": CV + "orig_import",
        "original_title": "Lernbereich 1", "code": "1",
    }  # fmt: skip
    assert (node["function_iri"], node["node_type_iri"], node["title_language"]) == (
        CV + "fn_area",
        None,
        "de",
    )
    assert (node["mem_iri"], node["mem_classes"], node["mem_properties"]) == (
        PLAN + "/teil-1", [LP + "LP_0030050"], {"number": "1"},
    )  # fmt: skip
    [statement] = rows.statements  # the rejected one is none of the document's
    assert {key: statement[key] for key in ("id", "node_id", "iri", "origin_iri", "language")} == {
        "id": made["statement"], "node_id": made["node"], "iri": DOC + "/1/s-1",
        "origin_iri": CV + "orig_import", "language": "de",
    }  # fmt: skip
    assert (statement["verbatim"], statement["statement_kind_iri"], statement["subkind_iri"]) == (
        "Die Lernenden planen ihre Arbeit.", CV + "kind_learningOutcome", None,
    )  # fmt: skip
    assert (statement["mem_iri"], statement["mem_classes"], statement["mem_properties"]) == (
        PLAN + "/teil-2", [LP + "LP_0000263"], {"hours": "4"},
    )  # fmt: skip


async def test_roots_come_first_and_siblings_by_their_position(
    sync: psycopg.Connection, connection: psycopg.AsyncConnection
) -> None:
    document = add_document(sync, add_conversion(sync))
    second = add_node(sync, document, position=2)
    first = add_node(sync, document, position=1)
    child = add_node(sync, document, parent=first)
    later = add_statement(sync, document, first, position=2)
    earlier = add_statement(sync, document, first, position=1)

    rows = await read_mem_document(connection, document)

    assert [node["id"] for node in rows.nodes] == [first, second, child]
    assert [statement["id"] for statement in rows.statements] == [earlier, later]


async def test_the_rows_are_read_in_one_snapshot_or_not_at_all(
    sync: psycopg.Connection, database_url: str
) -> None:
    made = an_import(sync)
    async with await psycopg.AsyncConnection.connect(database_url) as pooled:
        await pooled.execute("SELECT 1")  # read committed, as a pool's connection after its first query
        with pytest.raises(RuntimeError, match="one snapshot"):
            await read_mem_document(pooled, made["document"])


async def test_no_document_is_a_document_error(connection: psycopg.AsyncConnection) -> None:
    with pytest.raises(DocumentError):
        await read_mem_document(connection, new_id())
