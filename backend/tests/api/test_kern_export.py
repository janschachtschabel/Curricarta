"""The Kern export of a frozen document (app/api/kern_export.py, plan M3a C2): who reads the document and
its entry's content downloads its Curriculum-Kern Turtle under the IRIs freezing gave - an extracted
document as an import from MEM-Schule; a draft, a document frozen before its specifications were named, a
build that did not end and too many exports a minute, of either kind, are refused."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS

from app.api.app import create_app
from app.core.storage import ObjectNotFound
from app.exports import kern_export
from app.exports.kern_rdf import CUR
from tests.api.test_documents import PUBLIC, an_account, client, hidden_from_its_owner, url
from tests.api.test_exports import an_import
from tests.api.test_exports import export as mem_export
from tests.api.test_freeze import BASE, a_violation, freezing, ready
from tests.db.l1 import add_specification
from tests.exports import kern_children
from tests.support import make_settings, selector_client

pytestmark = pytest.mark.pg
__all__ = ["client", "freezing", "url"]  # the fixtures, shared with test_documents and test_freeze


def kern(client: TestClient, document: str, header: dict[str, str]) -> Any:
    return client.get(f"/api/v1/documents/{document}/kern.ttl", headers=header)


def frozen(client: TestClient, url: str, *, violation: bool = False) -> tuple[str, dict[str, str], str]:
    """A document extracted, made ready and frozen by an editor - a violation accepted, where asked: its id,
    the editor's header and its IRI."""
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    document, _ = ready(client, url, editor)
    if violation:
        a_violation(url, document)
    answer = client.post(
        f"/api/v1/documents/{document}/freeze", headers=editor, json={"accept_violations": violation}
    )
    assert answer.status_code == 200, answer.text
    return document, editor, answer.json()["iri"]


def test_a_frozen_extracted_document_is_exported_under_its_iris(freezing: TestClient, url: str) -> None:
    document, editor, iri = frozen(freezing, url)

    answer = kern(freezing, document, editor)

    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "text/turtle; charset=utf-8"
    assert answer.headers["content-disposition"] == f'attachment; filename="kern-{document}-r1.ttl"'
    assert answer.headers["cache-control"] == "private, no-store"
    assert answer.headers["content-length"] == str(len(answer.content))
    assert answer.headers["curricarta-accepted-violations"] == "0"
    graph = Graph().parse(data=answer.content, format="turtle")
    named = {str(term) for triple in graph for term in (triple[0], triple[2]) if isinstance(term, URIRef)}
    assert not [term for term in named if term.startswith("urn:uuid:")]
    rows = [*graph.subjects(None, CUR.CurriculumNode), *graph.subjects(None, CUR.Statement)]
    assert len(rows) == 2 and all(str(row).startswith(iri + "/") for row in rows)
    assert (URIRef(iri), DCTERMS.rights, Literal("Rechtestatus der Wortlaute: unklar", lang="de")) in graph
    assert iri.startswith(BASE)


def test_accepted_violations_are_counted_in_the_answer_and_the_file(freezing: TestClient, url: str) -> None:
    document, editor, _ = frozen(freezing, url, violation=True)

    answer = kern(freezing, document, editor)

    assert answer.status_code == 200, answer.text
    assert answer.headers["curricarta-accepted-violations"] == "1"
    assert "# accepted violations: 1\n" in answer.text


def test_a_frozen_mem_import_has_both_exports(in_process_shacl: None, client: TestClient, url: str) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner)

    made, kept = mem_export(client, document, header), kern(client, document, header)

    assert (made.status_code, kept.status_code) == (200, 200), kept.text
    assert made.content != kept.content
    graph = Graph().parse(data=kept.content, format="turtle")
    assert (None, None, CUR.Document) in graph and (None, None, CUR.Statement) in graph


def test_a_stranger_gets_404_and_a_hidden_entry_403(client: TestClient, url: str) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner)
    _, stranger = an_account(url, "Fremd")

    answer = kern(client, document, stranger)
    assert (answer.status_code, answer.json()["code"]) == (404, "no_document")

    hidden_from_its_owner(url, document)
    answer = kern(client, document, header)
    assert (answer.status_code, answer.json()["code"]) == (403, "file_hidden")


def test_a_draft_is_not_exported(client: TestClient, url: str) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner, frozen=False)

    answer = kern(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (409, "export_not_frozen")


def test_a_document_frozen_before_its_specifications_were_named_is_unnamed(
    client: TestClient, url: str
) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner, frozen=False)
    with psycopg.connect(url, autocommit=True) as connection:
        add_specification(connection, UUID(document))  # no IRI: frozen before they were named
        connection.execute(
            "UPDATE document SET iri = %s, frozen_at = %s WHERE id = %s",
            ("https://example.org/kk/doc/de-sn/lp/1", datetime(2026, 11, 1, tzinfo=UTC), document),
        )

    answer = kern(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (409, "export_unnamed")
    assert "python -m app.db.name_frozen" in answer.json()["message"]


def test_a_build_that_did_not_end_answers_503_with_when_to_try_again(
    client: TestClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kern_export, "build_child", kern_children.sleeping)
    client.app.state.kern_exporter._timeout_s = 0.5  # type: ignore[attr-defined]
    owner, header = an_account(url)
    document = an_import(url, owner)

    answer = kern(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (503, "export_unavailable")
    assert answer.headers["retry-after"]


def test_an_export_gone_from_the_store_meanwhile_is_tried_again(
    client: TestClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner)

    async def gone(key: str) -> Any:
        raise ObjectNotFound(key)

    monkeypatch.setattr(client.app.state.storage, "open_stream", gone)  # type: ignore[attr-defined]
    answer = kern(client, document, header)

    assert (answer.status_code, answer.json()["code"]) == (503, "export_unavailable")


@pytest.fixture
def one_a_minute(url: str, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=url, storage_dir=tmp_path, exports_per_minute=1))
    with selector_client(app, base_url=PUBLIC) as test_client:
        yield test_client


def test_exports_of_both_kinds_count_against_one_limit(
    in_process_shacl: None, one_a_minute: TestClient, url: str
) -> None:
    owner, header = an_account(url)
    document = an_import(url, owner)

    first, second = mem_export(one_a_minute, document, header), kern(one_a_minute, document, header)

    assert first.status_code == 200
    assert (second.status_code, second.json()["code"]) == (429, "too_many_exports")
    assert second.headers["retry-after"]


def test_the_export_s_refusals_are_in_the_spec(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    responses = paths["/api/v1/documents/{document_id}/kern.ttl"]["get"]["responses"]

    assert {"200", "403", "404", "409", "429", "503"} <= set(responses)
    assert "export_not_frozen" in responses["409"]["description"]
    assert "export_unnamed" in responses["409"]["description"]
    assert "file_hidden" in responses["403"]["description"]
