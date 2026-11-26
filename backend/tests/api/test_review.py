"""The editors' review through the API (plan M1 9.5; Paket 9 G1, G8): one status for many nodes and
statements of a document, all or nothing, by the editors alone, audited; a stale row names each that
stands otherwise."""

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.api.test_document_tree import a_document
from tests.api.test_documents import an_account, client, rows, url
from tests.api.test_node_editing import a_node
from tests.api.test_statement_editing import a_statement
from tests.api.test_values import LVL, values
from tests.db.l1 import CV, add_entity, add_specification
from tests.db.l2 import add_value

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents


def test_the_editors_confirm_nodes_and_statements_at_once(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url)
    node = a_node(url, document)
    said = a_statement(url, document, node)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    items = [{"kind": "node", "id": node, "revision": 1}, {"kind": "statement", "id": said, "revision": 1}]

    answer = client.post(
        f"/api/v1/documents/{document}/review", headers=editor, json={"status": "confirmed", "items": items}
    )

    assert answer.status_code == 200, answer.text
    assert answer.json() == {
        "revisions": [{"id": node, "revision": 2}, {"id": said, "revision": 2}],
        "nodes": [],  # none moved as a value's holder
    }
    assert rows(
        url, "SELECT review_status_iri FROM node UNION ALL SELECT review_status_iri FROM statement"
    ) == [(CV + "rev_confirmed",), (CV + "rev_confirmed",)]
    assert rows(url, "SELECT action, subject, details FROM audit_log WHERE action = 'review.set'") == [
        ("review.set", f"document:{document}", {"status": "confirmed", "items": 2})
    ]


def test_the_editors_review_a_holder_s_values_as_its_rows(client: TestClient, url: str) -> None:
    # a value is a row of its own, with its own origin and review status (plan M3a D2): reviewed so too
    document, _ = a_document(client, url)
    node = a_node(url, document)
    other, _ = a_document(client, url, name="Andere", digest=b"\x02" * 32)
    with psycopg.connect(url, autocommit=True) as connection:
        level = add_value(connection, "level_assignment", uuid.UUID(document), "node_id", uuid.UUID(node))
        workload = add_value(connection, "workload", uuid.UUID(document), "node_id", uuid.UUID(node))
        period = add_value(connection, "time_span", uuid.UUID(document), "workload_id", workload)
        elsewhere = add_value(
            connection, "level_assignment", uuid.UUID(other), "node_id", uuid.UUID(a_node(url, other))
        )
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    items = [
        {"kind": "level_assignment", "id": str(level), "revision": 1},
        {"kind": "workload", "id": str(workload), "revision": 1},
        {"kind": "time_span", "id": str(period), "revision": 1},
    ]
    path = f"/api/v1/documents/{document}/review"

    answer = client.post(path, headers=editor, json={"status": "confirmed", "items": items})
    foreign = client.post(path, headers=editor, json={
        "status": "rejected", "items": [{"kind": "level_assignment", "id": str(elsewhere), "revision": 1}],
    })  # fmt: skip

    assert answer.status_code == 200, answer.text
    assert [row["revision"] for row in answer.json()["revisions"]] == [2, 2, 2]
    assert (
        rows(
            url,
            "SELECT review_status_iri, origin_iri FROM level_assignment WHERE id = %s UNION ALL"
            " SELECT review_status_iri, origin_iri FROM workload UNION ALL"
            " SELECT review_status_iri, origin_iri FROM time_span",
            level,
        )
        == [(CV + "rev_confirmed", CV + "orig_human")] * 3
    )  # a review is no edit: the origin stays
    assert (foreign.status_code, foreign.json()["details"]["stale"][0]["current"]) == (409, None)
    assert rows(url, "SELECT review_status_iri FROM level_assignment WHERE id = %s", elsewhere) == [
        (CV + "rev_proposed",)
    ]


@pytest.mark.parametrize(
    ("status", "kept"),
    [("rejected", [{"level": LVL + "EQF-5"}]), ("confirmed", [])],
    ids=["changed", "dropped"],
)
def test_a_set_of_values_read_before_their_review_is_stale(
    client: TestClient, url: str, status: str, kept: list[dict[str, str]]
) -> None:
    # the holder's revision is the one token of its set of values (app/db/values.py): a review of a value
    # counts it too, so a view read before the review neither undoes nor drops what the editors decided
    document, owner = a_document(client, url)
    node = a_node(url, document)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    path = f"/api/v1/nodes/{node}/values"
    first = client.put(path, headers=owner, json=values(level_assignments=[{"level": LVL + "EQF-4"}]))
    level = first.json()["values"]["level_assignments"][0]["id"]
    review = client.post(f"/api/v1/documents/{document}/review", headers=editor, json={
        "status": status, "items": [{"kind": "level_assignment", "id": level, "revision": 1}],
    })  # fmt: skip

    stale = client.put(path, headers=owner, json=values(
        first.json()["revision"], level_assignments=[{"id": level} | each for each in kept],
    ))  # fmt: skip

    assert review.status_code == 200, review.text
    assert stale.status_code == 409, stale.text
    assert (stale.json()["code"], stale.json()["details"]["current"]["revision"]) == ("stale_revision", 3)
    assert rows(url, "SELECT level_iri, review_status_iri FROM level_assignment") == [
        (LVL + "EQF-4", CV + "rev_" + status)
    ]


def test_a_holder_reviewed_with_its_values_counts_its_revision_once(client: TestClient, url: str) -> None:
    # a period's holder is its workload's; a holder named in the review is answered with its revision after
    document, _ = a_document(client, url)
    node = a_node(url, document)
    said = a_statement(url, document, node)
    with psycopg.connect(url, autocommit=True) as connection:
        workload = add_value(connection, "workload", uuid.UUID(document), "node_id", uuid.UUID(node))
        period = add_value(connection, "time_span", uuid.UUID(document), "workload_id", workload)
        level = add_value(
            connection, "level_assignment", uuid.UUID(document), "statement_id", uuid.UUID(said)
        )
        specification = add_specification(connection, uuid.UUID(document))
        laid_down = add_value(connection, "workload", uuid.UUID(document), "specification_id", specification)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    items = [
        {"kind": "node", "id": node, "revision": 1},
        {"kind": "time_span", "id": str(period), "revision": 1},
        {"kind": "level_assignment", "id": str(level), "revision": 1},
        {"kind": "workload", "id": str(laid_down), "revision": 1},
    ]

    answer = client.post(
        f"/api/v1/documents/{document}/review", headers=editor, json={"status": "confirmed", "items": items}
    )

    assert answer.status_code == 200, answer.text
    assert [row["revision"] for row in answer.json()["revisions"]] == [2, 2, 2, 2]
    assert rows(
        url,
        "SELECT revision FROM node UNION ALL SELECT revision FROM statement"
        " UNION ALL SELECT revision FROM specification",
    ) == [(2,), (2,), (2,)]
    assert rows(url, "SELECT revision FROM workload WHERE id = %s", workload) == [(1,)]  # not reviewed


def test_a_rule_s_level_is_not_reviewed_with_the_values(client: TestClient, url: str) -> None:
    # a level at a rules frame part is the rules' (plan M3a I): no reader shows it, so none reviews it yet
    document, _ = a_document(client, url)
    with psycopg.connect(url, autocommit=True) as connection:
        part = add_entity(connection, "frame_part")
        connection.execute(
            "INSERT INTO frame_part (id, document_id, part_kind, content, origin_scheme, origin_iri,"
            " review_status_scheme, review_status_iri, position)"
            " VALUES (%s, %s, 'rules', '{}', %s, %s, %s, %s, 1)",
            (part, document, CV + "Origins", CV + "orig_source", CV + "ReviewStatuses", CV + "rev_proposed"),
        )
        level = add_value(connection, "level_assignment", uuid.UUID(document), "frame_part_id", part)
    _, editor = an_account(url, "Redaktion", ("redaktion",))

    answer = client.post(f"/api/v1/documents/{document}/review", headers=editor, json={
        "status": "rejected", "items": [{"kind": "level_assignment", "id": str(level), "revision": 1}],
    })  # fmt: skip

    assert (answer.status_code, answer.json()["details"]["stale"][0]["current"]) == (409, None)
    assert rows(url, "SELECT review_status_iri FROM level_assignment") == [(CV + "rev_proposed",)]


def test_a_stale_row_leaves_all_and_is_named_with_its_revision(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url)
    node = a_node(url, document)
    _, admin = an_account(url, "Verwaltung", ("admin",))
    gone = str(uuid.uuid4())
    items = [{"kind": "node", "id": node, "revision": 2}, {"kind": "statement", "id": gone, "revision": 1}]

    answer = client.post(
        f"/api/v1/documents/{document}/review", headers=admin, json={"status": "rejected", "items": items}
    )

    assert (answer.status_code, answer.json()["code"]) == (409, "stale_revision")
    assert answer.json()["details"] == {
        "stale": [
            {"kind": "node", "id": node, "current": 1},
            {"kind": "statement", "id": gone, "current": None},
        ]
    }
    assert rows(url, "SELECT revision FROM node") == [(1,)]


def test_the_owner_reviews_not_and_to_another_the_document_is_none(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    node = a_node(url, document)
    _, stranger = an_account(url, "Fremde")
    review = {"status": "confirmed", "items": [{"kind": "node", "id": node, "revision": 1}]}

    by_owner = client.post(f"/api/v1/documents/{document}/review", headers=owner, json=review)
    by_stranger = client.post(f"/api/v1/documents/{document}/review", headers=stranger, json=review)

    assert (by_owner.status_code, by_owner.json()["code"]) == (403, "not_editor")
    assert (by_stranger.status_code, by_stranger.json()["code"]) == (404, "no_document")
    assert client.post(f"/api/v1/documents/{document}/review", json=review).status_code == 401
    assert rows(url, "SELECT revision FROM node") == [(1,)]


def test_a_review_names_a_status_and_a_row_at_least(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    node = a_node(url, document)

    for review in (
        {"status": "confirmed", "items": []},
        {"status": "approved", "items": [{"kind": "node", "id": node, "revision": 1}]},
        {"status": "confirmed", "items": [{"kind": "anchor", "id": node, "revision": 1}]},
    ):
        answer = client.post(f"/api/v1/documents/{document}/review", headers=editor, json=review)
        assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")


def test_no_review_is_set_once_the_document_is_frozen(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    node = a_node(url, document)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "UPDATE document SET iri = 'https://example.org/curriculum/1', frozen_at = now() WHERE id = %s",
            (document,),
        )

    answer = client.post(
        f"/api/v1/documents/{document}/review",
        headers=editor,
        json={"status": "confirmed", "items": [{"kind": "node", "id": node, "revision": 1}]},
    )

    assert (answer.status_code, answer.json()["code"]) == (409, "frozen")
    assert rows(url, "SELECT revision FROM node") == [(1,)]


def test_no_review_is_set_beside_an_open_job(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url, ended=False)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    node = a_node(url, document)

    answer = client.post(
        f"/api/v1/documents/{document}/review",
        headers=editor,
        json={"status": "confirmed", "items": [{"kind": "node", "id": node, "revision": 1}]},
    )

    assert (answer.status_code, answer.json()["code"], answer.json()["details"]) == (409, "job_open", {})
