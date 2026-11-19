"""X5 on the file a document is in (plan M3a A1): the Kern graph names the file by its urn:uuid, so the shapes
check it, but the file is no row of the document - a result on it is the document's finding, its focus in
the details, and X5 ends as ever. A model stands in for X1 to X4."""

from pathlib import Path
from typing import Any

import pytest
from rdflib import Graph

from app.exports.kern_rdf import CUR
from app.pipeline import x5_stage
from app.pipeline.run import extract_document
from tests.pipeline.test_run import CV, Model, a_document, a_job, context_of, rows, setup
from tests.shacl_in_process import shacl_in_process

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run


async def test_a_result_on_the_file_is_a_finding_of_the_document(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document = await a_document(connection)

    async def without_checksum(graph: Graph, **options: Any) -> Any:
        graph.remove((None, CUR.checksum, None))  # the file breaks SourceFileShape (sh:minCount 1)
        return await shacl_in_process(graph, **options)  # the real shapes, in the test's process

    monkeypatch.setattr(x5_stage, "shacl_check", without_checksum)
    await extract_document(
        context_of(pool, tmp_path, Model(), database_url),
        await a_job(connection, document.id, document.owner_id),
    )

    [(outcome,)] = await rows(
        connection,
        "SELECT outcome FROM extraction_run WHERE document_id = %s AND stage_iri = %s",
        document.id,
        CV + "stage_X5",
    )
    assert outcome == "done"
    [(file,)] = await rows(
        connection, "SELECT source_file_id FROM conversion WHERE id = %s", document.conversion_id
    )
    found = await rows(
        connection,
        "SELECT severity, focus_id, path, message, details FROM validation_finding"
        " WHERE document_id = %s AND rule = 'shacl.SourceFileShape'",
        document.id,
    )
    assert [(said, focus, path, details["focus"]) for said, focus, path, _, details in found] == [
        ("violation", document.id, "cur:checksum", f"urn:uuid:{file}")
    ]
    assert found[0][3]  # it still says what is wrong with the file
