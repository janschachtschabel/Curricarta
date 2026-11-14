"""The export of a frozen MEM import (app/api/exports.py, plan M2-6, E10): who reads the document and its
entry's content downloads its MEM Turtle; a draft, a document of no import, a state the shapes refuse
(its violations by row), a check that did not end and too many exports a minute are refused."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef

from app.api import exports
from app.api.app import create_app
from app.core.storage import ObjectNotFound
from app.exports import mem_export
from app.pipeline.shacl import ShaclTimeout
from tests.api.test_documents import PUBLIC, a_conversion, an_account, client, hidden_from_its_owner, url
from tests.db.l1 import add_document, add_node, add_statement
from tests.support import make_settings, selector_client

pytestmark = pytest.mark.pg

__all__ = ["client", "url"]  # the fixtures, shared with test_documents

CV = "https://w3id.org/wlo/curriculum/vocab#"
LP = "https://w3id.org/lehrplan/ontology/"
PLAN = "https://lp-sachsen.org/resource/lehrplan-141-1"
DOC = "https://example.org/kk/doc/de-sn/lp/1"


def an_import(url: str, owner: UUID, *, frozen: bool = True, reference: bool = False, **columns: Any) -> str:
    """A document of an import with a Bereich and a statement in it - and a reference of no target, where
    asked -, frozen unless not."""
    made = a_conversion(url, owner, uuid4().bytes * 2)  # a file of its own
    with psycopg.connect(url, autocommit=True) as connection:
        document = add_document(connection, made, **{
            "title": "Lehrplan Deutsch", "mem_iri": PLAN, "mem_land_iri": LP + "LP_3000014",
            "mem_class_iri": LP + "LP_0000438", "mem_attribution": "MEM-Schule",
        } | columns)  # fmt: skip
        node = add_node(connection, document, iri=DOC + "/1", origin_iri=CV + "orig_import",
                        mem_iri=PLAN + "/teil-1", mem_classes=[LP + "LP_0030050"])  # fmt: skip
        add_statement(connection, document, node, iri=DOC + "/1/s-1", origin_iri=CV + "orig_import",
                      mem_iri=PLAN + "/teil-2", mem_classes=[LP + "LP_0000263"])  # fmt: skip
        if reference:
            add_statement(connection, document, node, position=2, iri=DOC + "/1/s-2",
                          origin_iri=CV + "orig_import", statement_kind_iri=CV + "kind_reference",
                          mem_iri=PLAN + "/verweis", mem_classes=[LP + "LP_0030065"])  # fmt: skip
        if frozen:
            connection.execute(
                "UPDATE document SET iri = %s, frozen_at = %s WHERE id = %s",
                (DOC, datetime(2026, 11, 1, tzinfo=UTC), document),
            )
    return str(document)


def export(client: TestClient, document: str, header: dict[str, str]) -> Any:
    return client.get(f"/api/v1/documents/{document}/export.ttl", headers=header)


def test_a_reader_of_a_frozen_import_downloads_its_mem_turtle(
    in_process_shacl: None, client: TestClient, url: str
) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner)

    answer = export(client, document, header)

    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "text/turtle; charset=utf-8"
    assert answer.headers["content-disposition"].startswith("attachment;")
    assert answer.headers["content-disposition"].endswith('.ttl"')
    assert answer.headers["cache-control"] == "private, no-store"
    assert answer.headers["content-length"] == str(len(answer.content))
    graph = Graph().parse(data=answer.content, format="turtle")
    assert (URIRef(DOC), None, None) in graph and (URIRef(PLAN + "/teil-2"), None, None) in graph


def test_the_editors_export_too_and_a_stranger_finds_no_document(
    in_process_shacl: None, client: TestClient, url: str
) -> None:
    owner, _ = an_account(url)
    document = an_import(url, owner)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    _, stranger = an_account(url, "Fremd")

    assert export(client, document, editor).status_code == 200
    answer = export(client, document, stranger)
    assert (answer.status_code, answer.json()["code"]) == (404, "no_document")


@pytest.mark.parametrize(
    ("columns", "code"),
    [
        ({"frozen": False}, "export_not_frozen"),
        ({"mem_iri": None}, "not_mem_import"),
        ({"frozen": False, "mem_iri": None}, "not_mem_import"),
    ],
    ids=["a-draft", "no-import", "neither"],
)
def test_a_draft_or_a_document_of_no_import_is_not_exported(
    client: TestClient, url: str, columns: dict[str, Any], code: str
) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner, **columns)

    answer = export(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (409, code)


def test_a_state_the_shapes_refuse_answers_with_its_violations(client: TestClient, url: str) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner, mem_land_iri=None)

    answer = export(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (409, "export_invalid")
    details = answer.json()["details"]
    assert details["total"] == 1
    [violation] = details["violations"]
    assert (violation["focus"], violation["row_kind"], violation["row_id"], violation["shape"]) == (
        DOC, "document", document, "LPBundeslandShape",
    )  # fmt: skip
    assert violation["path"] and violation["message"]


def test_a_check_that_did_not_end_answers_503_with_when_to_try_again(
    client: TestClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def timing_out(*_: Any, **__: Any) -> Any:
        raise ShaclTimeout("past its time")

    monkeypatch.setattr(mem_export, "shacl_check", timing_out)
    owner, header = an_account(url)
    document = an_import(url, owner)

    answer = export(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (503, "export_unavailable")
    assert answer.headers["retry-after"]


@pytest.fixture
def one_a_minute(url: str, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=url, storage_dir=tmp_path, exports_per_minute=1))
    with selector_client(app, base_url=PUBLIC) as test_client:
        yield test_client


def test_exports_are_counted_per_minute(in_process_shacl: None, one_a_minute: TestClient, url: str) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner)

    first, second = export(one_a_minute, document, header), export(one_a_minute, document, header)

    assert first.status_code == 200
    assert (second.status_code, second.json()["code"]) == (429, "too_many_exports")
    assert second.headers["retry-after"]


def test_an_owner_whose_entry_is_hidden_exports_nothing(client: TestClient, url: str) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner)
    hidden_from_its_owner(url, document)

    answer = export(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (403, "file_hidden")


def test_the_violations_listed_are_cut_and_all_counted(
    in_process_shacl: None, client: TestClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(exports, "MAX_LISTED", 1)
    owner, header = an_account(url)
    document = an_import(
        url, owner, mem_land_iri=None, reference=True
    )  # three: no Land; the reference held by none, at nothing

    answer = export(client, document, header)

    assert (answer.json()["details"]["total"], len(answer.json()["details"]["violations"])) == (3, 1)


def test_a_refusal_before_the_export_counts_no_export(
    in_process_shacl: None, one_a_minute: TestClient, url: str
) -> None:
    owner, header = an_account(url)
    draft, frozen = an_import(url, owner, frozen=False), an_import(url, owner)

    refused, made = export(one_a_minute, draft, header), export(one_a_minute, frozen, header)

    assert (refused.status_code, made.status_code) == (409, 200)


def test_an_export_gone_from_the_store_meanwhile_is_tried_again(
    in_process_shacl: None, client: TestClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner)

    async def gone(key: str) -> Any:
        raise ObjectNotFound(key)

    monkeypatch.setattr(client.app.state.storage, "open_stream", gone)  # type: ignore[attr-defined]
    answer = export(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (503, "export_unavailable")


def test_the_export_s_refusals_are_in_the_spec(client: TestClient) -> None:
    responses = client.get("/openapi.json").json()["paths"]["/api/v1/documents/{document_id}/export.ttl"][
        "get"
    ]["responses"]

    assert {"200", "403", "404", "409", "429", "503"} <= set(responses)
    assert (
        "file_hidden" in responses["403"]["description"] and "no_document" in responses["404"]["description"]
    )


def test_an_export_that_did_not_end_counts_as_one(
    one_a_minute: TestClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def timing_out(*_: Any, **__: Any) -> Any:
        raise ShaclTimeout("past its time")

    monkeypatch.setattr(mem_export, "shacl_check", timing_out)
    owner, header = an_account(url)
    document = an_import(url, owner)

    first, second = export(one_a_minute, document, header), export(one_a_minute, document, header)

    assert (first.status_code, second.status_code) == (503, 429)
