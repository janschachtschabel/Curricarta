"""A document of the first layer read for its Kern RDF (plan M1 8.3; app/exports/kern_rows.py): in one
snapshot or not at all, a region by its active concept, and none of a rejected statement's rows."""

import psycopg
import pytest

from app.db.nodes import write_subtree
from app.domain.l1 import AnchorDraft, NodeDraft, StatementDraft
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import read_document
from tests.db.document_of import document_of
from tests.exports.test_kern_rdf import CV, MODEL, PROPOSED, TEXTS, block, connection, one

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, shared with test_kern_rdf


async def test_a_document_is_read_in_one_snapshot_or_not_at_all(
    connection: psycopg.AsyncConnection, database_url: str
) -> None:
    # a pool's connection is no autocommit one: its first query opens a transaction of read committed,
    # in which each query would see the rows as they stand then - a node gone between nodes and statements
    document = await document_of(connection, [block(1, TEXTS[0])])
    async with await psycopg.AsyncConnection.connect(database_url) as pooled:
        await pooled.execute("SELECT 1")
        with pytest.raises(RuntimeError, match="one snapshot"):
            await read_document(pooled, document.id)
        await pooled.rollback()
        async with pooled.transaction():
            await pooled.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            await pooled.execute("SELECT 1")
            read = await read_document(pooled, document.id)

    assert read.document["id"] == document.id


async def test_a_region_is_its_active_concept_where_a_retired_one_shares_its_notation(
    connection: psycopg.AsyncConnection,
) -> None:
    document = await document_of(connection, [block(1, TEXTS[0])])
    release = await one(
        connection,
        "INSERT INTO vocab_release (content_hash, files) VALUES (repeat('0', 64), '{}') RETURNING id",
    )
    await connection.execute(
        "INSERT INTO vocab_concept (iri, scheme_iri, types, notation, pref_labels, alt_labels, definitions,"
        " broader, properties, retired_in)"
        " SELECT iri || '-old', scheme_iri, types, notation, pref_labels, alt_labels, definitions, broader,"
        " properties, %s FROM vocab_concept WHERE iri = %s",
        (release, "https://w3id.org/wlo/curriculum/region/DE-NW"),
    )

    made = kern_graph(await read_document(connection, document.id))

    assert sorted(str(region) for region in made.objects(None, CUR.region)) == [
        "https://w3id.org/wlo/curriculum/region/DE-NW"
    ]


async def test_a_rejected_statement_and_its_anchors_are_no_rows_of_the_document(
    connection: psycopg.AsyncConnection,
) -> None:
    # it is no part of the curriculum (Paket 9 G9): neither the export nor X5's graph holds it
    document = await document_of(connection, [block(1, TEXTS[2])])

    def said(verbatim: str, status: str) -> StatementDraft:
        return StatementDraft(
            verbatim=verbatim, kind=CV + "kind_learningOutcome", addressees=(CV + "addr_learner",),
            anchors=(AnchorDraft(("p1-b1",), page_start=1),), origin=MODEL, review_status=status,
        )  # fmt: skip

    root = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED,
        statements=(said(TEXTS[2], PROPOSED), said("Die Lernenden raten.", CV + "rev_rejected")),
    )  # fmt: skip
    await write_subtree(connection, document.id, root)

    rows = await read_document(connection, document.id)

    assert [row["verbatim"] for row in rows.statements] == [TEXTS[2]]
    assert [row["statement_id"] for row in rows.anchors] == [rows.statements[0]["id"]]


async def test_a_document_is_read_with_where_it_came_from(connection: psycopg.AsyncConnection) -> None:
    document = await document_of(connection, [block(1, TEXTS[0])])
    await connection.execute(
        "UPDATE source SET url = %s WHERE id = (SELECT source_id FROM document WHERE id = %s)",
        ("https://example.org/plaene/1.pdf", document.id),
    )
    await connection.execute(
        "UPDATE document SET mem_iri = %s, mem_attribution = 'MEM-Schule', mem_licence = %s WHERE id = %s",
        ("https://example.org/mem/plan-1", "https://creativecommons.org/licenses/by/4.0/", document.id),
    )

    read = (await read_document(connection, document.id)).document

    assert (read["source_url"], read["mem_iri"], read["mem_attribution"], read["mem_licence"]) == (
        "https://example.org/plaene/1.pdf", "https://example.org/mem/plan-1", "MEM-Schule",
        "https://creativecommons.org/licenses/by/4.0/",
    )  # fmt: skip
