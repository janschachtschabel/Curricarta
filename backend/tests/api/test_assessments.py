"""A document's assessments through the API (plan M3a J; app/api/assessments.py): read with what they assess,
the levels at them and what an assessment may be a part of; one added, edited on its revision and taken away
with its parts, the levels at one set as a whole - a grade where a node's is refused - by the document's
owner and the editors, audited by fields and counts alone; refused with the field and why, with the
assessment as it stands for a stale revision, and to a stranger as no assessment at all."""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.api.test_document_tree import a_document
from tests.api.test_documents import an_account, client, hidden_from_its_owner, rows, url
from tests.db.l1 import CV, add_node, add_specification, add_statement

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents

EXAM, PART = CV + "ak_exam", CV + "ak_examPart"
GRADE = {"level": "https://w3id.org/wlo/curriculum/level/grade-2"}


def holders(url: str, document: str) -> dict[str, str]:
    """A specification, a node and a statement of the document, by kind."""
    with psycopg.connect(url, autocommit=True) as connection:
        specification = add_specification(connection, uuid.UUID(document), key="lp", title="Physik")
        node = add_node(connection, uuid.UUID(document), code="LF 1", original_title="Optik")
        statement = add_statement(connection, uuid.UUID(document), node, verbatim="Sie messen.")
    return {"specification": str(specification), "node": str(node), "statement": str(statement)}


def values(revision: int, *levels: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_revision": revision,
        "level_assignments": list(levels),
        "time_spans": [],
        "workloads": [],
    }


def added(client: TestClient, document: str, header: dict[str, str], **body: Any) -> dict[str, Any]:
    answer = client.post(f"/api/v1/documents/{document}/assessments", headers=header, json=body)
    assert answer.status_code == 201, answer.text
    return dict(answer.json())


def test_an_assessment_is_added_read_edited_and_taken_away(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    held = holders(url, document)
    _, editor = an_account(url, "Redaktion", ("redaktion",))

    exam = added(client, document, owner, parent_id=held["specification"], assessment_kind=EXAM,
                 label="Abschlussprüfung", duration_minutes=240, graded=True)  # fmt: skip
    part = added(client, document, editor, parent_id=exam["id"], assessment_kind=PART, weight_percent=37.5,
                 targets=[held["node"], held["statement"]])  # fmt: skip
    listed = client.get(f"/api/v1/documents/{document}/assessments", headers=owner)

    stated = ("parent_kind", "parent_id", "label", "duration_minutes", "graded")
    assert tuple(exam[key] for key in stated) == (
        "specification", held["specification"], "Abschlussprüfung", 240, True,
    )  # fmt: skip
    assert (exam["origin"], exam["review_status"], exam["revision"]) == (
        CV + "orig_human",
        CV + "rev_proposed",
        1,
    )
    assert (part["parent_kind"], part["weight_percent"], part["position"]) == ("assessment", 37.5, 1)
    assert [(each["kind"], each["label"]) for each in part["targets"]] == [
        ("node", "LF 1 Optik"), ("statement", "Sie messen."),
    ]  # fmt: skip
    read = listed.json()
    assert (listed.status_code, read["editable"], read["closed"]) == (200, True, None)
    assert [each["id"] for each in read["assessments"]] == [exam["id"], part["id"]]
    assert [(each["kind"], each["label"]) for each in read["choices"]] == [
        ("specification", "Physik"), ("node", "LF 1 Optik"),
    ]  # fmt: skip
    assert {EXAM, PART} <= {kind["iri"] for kind in read["kinds"]}
    assert [kind["label"] for kind in read["kinds"]] == sorted(
        (kind["label"] for kind in read["kinds"]), key=str.casefold
    )

    path = f"/api/v1/assessments/{part['id']}"
    edited = client.patch(
        path, headers=owner, json={"expected_revision": 1, "label": "Teil 1", "targets": []}
    )
    stale = client.patch(path, headers=owner, json={"expected_revision": 1, "label": "Teil 2"})
    cycle = client.patch(f"/api/v1/assessments/{exam['id']}", headers=owner,
                         json={"expected_revision": 1, "parent_id": part["id"]})  # fmt: skip

    assert edited.status_code == 200, edited.text
    assert (edited.json()["label"], edited.json()["targets"], edited.json()["revision"]) == ("Teil 1", [], 2)
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_revision")
    assert stale.json()["details"]["current"]["revision"] == 2
    assert (cycle.status_code, cycle.json()["details"]) == (422, {"field": "parent_id", "problem": "cycle"})

    taken = client.delete(f"/api/v1/assessments/{exam['id']}?expected_revision=1", headers=editor)

    assert (taken.status_code, taken.json()) == (200, {"assessments": 2})
    assert client.get(f"/api/v1/documents/{document}/assessments", headers=owner).json()["assessments"] == []
    audited = "SELECT action, details FROM audit_log WHERE action LIKE 'assessment.%%' ORDER BY id"
    assert rows(url, audited) == [
        ("assessment.add", {"document": document, "targets": 0}),
        ("assessment.add", {"document": document, "targets": 2}),
        ("assessment.edit", {"document": document, "revision": 2, "fields": ["label", "targets"]}),
        ("assessment.drop", {"document": document, "assessments": 2}),
    ]


def test_a_grade_is_set_at_an_assessment_where_one_at_a_node_is_refused(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    held = holders(url, document)
    exam = added(client, document, owner, parent_id=held["node"], assessment_kind=EXAM)

    graded = client.put(f"/api/v1/assessments/{exam['id']}/values", headers=owner, json=values(1, GRADE))
    at_node = client.put(f"/api/v1/nodes/{held['node']}/values", headers=owner, json=values(1, GRADE))
    spans = client.put(f"/api/v1/assessments/{exam['id']}/values", headers=owner, json=values(2) | {
        "time_spans": [{"time_kind": CV + "time_gradeLevel"}]})  # fmt: skip

    assert graded.status_code == 200, graded.text
    assert [level["level"] for level in graded.json()["values"]["level_assignments"]] == [GRADE["level"]]
    assert graded.json()["revision"] == 2
    assert (at_node.status_code, at_node.json()["details"]) == (
        422, {"field": "level_assignments[0].level", "problem": "not_offered"},
    )  # fmt: skip
    assert (spans.status_code, spans.json()["details"]) == (
        422,
        {"field": "time_spans", "problem": "not_held"},
    )
    audited = "SELECT details FROM audit_log WHERE action = 'assessment.values'"
    assert [found["level_assignments"] for (found,) in rows(url, audited)] == [1]


def test_an_assessment_the_store_does_not_take_is_refused_at_its_field(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    held = holders(url, document)
    other, other_owner = a_document(client, url, name="Zweite", digest=b"\x02" * 32)
    foreign = holders(url, other)
    path = f"/api/v1/documents/{document}/assessments"

    refused = [
        client.post(path, headers=owner, json={"parent_id": held["node"], "assessment_kind": CV + "form_x"}),
        client.post(path, headers=owner, json={"parent_id": foreign["node"], "assessment_kind": EXAM}),
        client.post(path, headers=owner, json={"parent_id": held["node"], "assessment_kind": EXAM,
                                               "targets": [foreign["statement"]]}),
    ]  # fmt: skip
    out_of_range = client.post(path, headers=owner, json={"parent_id": held["node"], "assessment_kind": EXAM,
                                                          "weight_percent": 100.5})  # fmt: skip

    assert [(answer.status_code, answer.json()["details"]) for answer in refused] == [
        (422, {"field": "assessment_kind", "problem": "not_offered"}),
        (422, {"field": "parent_id", "problem": "not_offered"}),
        (422, {"field": "targets[0]", "problem": "not_offered"}),
    ]
    assert out_of_range.status_code == 422
    assert "100.5" not in out_of_range.text  # a refusal names no input
    assert rows(url, "SELECT count(*) FROM assessment") == [(0,)]
    assert other_owner != owner


def test_an_assessment_is_none_to_a_stranger_and_hidden_content_is_refused(
    client: TestClient, url: str
) -> None:
    document, owner = a_document(client, url)
    held = holders(url, document)
    exam = added(client, document, owner, parent_id=held["node"], assessment_kind=EXAM)
    _, stranger = an_account(url, "Fremd")
    path = f"/api/v1/assessments/{exam['id']}"

    answers = [
        client.patch(path, headers=stranger, json={"expected_revision": 1, "label": "Fremd"}),
        client.delete(f"{path}?expected_revision=1", headers=stranger),
        client.put(f"{path}/values", headers=stranger, json=values(1)),
        client.patch(f"/api/v1/assessments/{uuid.uuid4()}", headers=owner, json={"expected_revision": 1}),
    ]
    listed = client.get(f"/api/v1/documents/{document}/assessments", headers=stranger)
    made = client.post(f"/api/v1/documents/{document}/assessments", headers=stranger,
                       json={"parent_id": held["node"], "assessment_kind": EXAM})  # fmt: skip
    hidden_from_its_owner(url, document)
    hidden = [
        client.get(f"/api/v1/documents/{document}/assessments", headers=owner),
        client.patch(path, headers=owner, json={"expected_revision": 1}),
        client.delete(f"{path}?expected_revision=1", headers=owner),
        client.put(f"{path}/values", headers=owner, json=values(1)),
        client.post(f"/api/v1/documents/{document}/assessments", headers=owner,
                    json={"parent_id": held["node"], "assessment_kind": EXAM}),
    ]  # fmt: skip

    assert [(answer.status_code, answer.json()["code"]) for answer in answers] == [(404, "no_assessment")] * 4
    assert [(answer.status_code, answer.json()["code"]) for answer in (listed, made)] == [
        (404, "no_document")
    ] * 2
    assert [(answer.status_code, answer.json()["code"]) for answer in hidden] == [(403, "file_hidden")] * 5
    assert rows(url, "SELECT label, revision FROM assessment") == [(None, 1)]


def test_a_frozen_document_s_assessments_are_read_only(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    held = holders(url, document)
    exam = added(client, document, owner, parent_id=held["node"], assessment_kind=EXAM)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "UPDATE document SET iri = 'https://example.org/curriculum/1', frozen_at = now() WHERE id = %s",
            (document,),
        )

    listed = client.get(f"/api/v1/documents/{document}/assessments", headers=owner).json()
    refused = [
        client.patch(f"/api/v1/assessments/{exam['id']}", headers=owner, json={"expected_revision": 1,
                                                                             "label": "Neu"}),
        client.delete(f"/api/v1/assessments/{exam['id']}?expected_revision=1", headers=owner),
        client.put(f"/api/v1/assessments/{exam['id']}/values", headers=owner, json=values(1, GRADE)),
        client.post(f"/api/v1/documents/{document}/assessments", headers=owner,
                    json={"parent_id": held["node"], "assessment_kind": EXAM}),
    ]  # fmt: skip

    assert (listed["editable"], listed["closed"]) == (False, "frozen")
    assert [(answer.status_code, answer.json()["code"]) for answer in refused] == [(409, "frozen")] * 4
