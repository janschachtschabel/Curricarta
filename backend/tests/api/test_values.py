"""A holder's values through the API (plan M3a E2; app/api/values.py): a node's levels, time spans and
workloads, a statement's levels, set as a whole on the holder's revision and read with the tree - by the
document's owner and the editors, audited by counts alone; refused with the field and why for a value the
form does not take, with the holder as it stands for a stale revision, beside an open job, once frozen,
before the extraction read every package, and to a stranger as no holder at all."""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.api.test_document_tree import a_document, tree
from tests.api.test_documents import an_account, client, hidden_from_its_owner, rows, url
from tests.api.test_node_editing import a_node
from tests.api.test_statement_editing import a_statement
from tests.db.l1 import CV

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents

LVL = "https://w3id.org/wlo/curriculum/level/"
HUMAN, PROPOSED = CV + "orig_human", CV + "rev_proposed"
GRADE = {"time_kind": CV + "time_gradeLevel", "span_from": 5, "span_to": 6}
LESSONS = {"amount": 40, "amount_to": 50, "unit": CV + "unit_lesson", "periods": [GRADE]}


def values(revision: int = 1, **kinds: list[dict[str, Any]]) -> dict[str, Any]:
    return {"expected_revision": revision, "level_assignments": [], "time_spans": [], "workloads": []} | kinds


def test_a_node_s_values_are_set_and_read_with_the_tree(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_node(url, document)
    body = values(level_assignments=[{"level": LVL + "EQF-4"}], time_spans=[GRADE], workloads=[LESSONS])

    answer = client.put(f"/api/v1/nodes/{made}/values", headers=owner, json=body)

    assert answer.status_code == 200, answer.text
    row = answer.json()
    # the node's revision counts the set; its own origin stays, as its fields do (plan M3a D2)
    assert (row["revision"], row["origin"], row["review_status"]) == (2, CV + "orig_source", PROPOSED)
    held = row["values"]
    [level], [span], [workload] = held["level_assignments"], held["time_spans"], held["workloads"]
    stated = (level["origin"], level["review_status"], level["revision"])
    assert (level["level"], level["level_to"], *stated) == (
        LVL + "EQF-4", None, HUMAN, PROPOSED, 1,
    )  # fmt: skip
    assert (span["time_kind"], span["span_from"], span["span_to"]) == (CV + "time_gradeLevel", 5, 6)
    assert (workload["amount"], workload["amount_to"], workload["unit"], workload["total"]) == (
        40, 50, CV + "unit_lesson", False,
    )  # fmt: skip
    assert [period["span_from"] for period in workload["periods"]] == [5]
    [top] = tree(client, document, owner)["nodes"]
    assert top["values"] == held

    # kept by its id, the others left out: they go
    again = values(2, level_assignments=[{"id": level["id"], "level": LVL + "EQF-5"}])
    second = client.put(f"/api/v1/nodes/{made}/values", headers=owner, json=again)

    assert second.status_code == 200, second.text
    assert [
        (each["id"], each["level"], each["revision"]) for each in second.json()["values"]["level_assignments"]
    ] == [(level["id"], LVL + "EQF-5", 2)]
    assert second.json()["values"]["workloads"] == second.json()["values"]["time_spans"] == []


def test_a_statement_s_levels_are_set_and_read_with_the_tree(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url)
    node = a_node(url, document)
    said = a_statement(url, document, node)
    _, editor = an_account(url, "Redaktion", ("redaktion",))

    answer = client.put(
        f"/api/v1/statements/{said}/values",
        headers=editor,
        json=values(level_assignments=[{"level": LVL + "cefr-B1"}]),
    )

    assert answer.status_code == 200, answer.text
    assert (answer.json()["id"], answer.json()["revision"]) == (said, 2)
    [top] = tree(client, document, editor)["nodes"]
    [statement] = top["statements"]
    assert [level["level"] for level in statement["values"]["level_assignments"]] == [LVL + "cefr-B1"]
    assert top["values"] == {"level_assignments": [], "time_spans": [], "workloads": []}


def test_a_value_of_a_kind_the_holder_may_not_hold_is_refused(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    said = a_statement(url, document, a_node(url, document))

    answer = client.put(f"/api/v1/statements/{said}/values", headers=owner, json=values(time_spans=[GRADE]))

    assert (answer.status_code, answer.json()["code"]) == (422, "invalid_field")
    assert answer.json()["details"] == {"field": "time_spans", "problem": "not_held"}
    assert rows(url, "SELECT count(*) FROM time_span") == [(0,)]


def test_a_level_the_shapes_never_let_the_holder_hold_is_refused(client: TestClient, url: str) -> None:
    # a qualification level at a statement, a grade but at a standard (LevelAssignmentShape)
    document, owner = a_document(client, url)
    node = a_node(url, document)
    said = a_statement(url, document, node)
    standard = a_statement(url, document, node, statement_kind_iri=CV + "kind_standard", position=2)
    grade = values(level_assignments=[{"level": LVL + "grade-2"}])

    answers = [
        client.put(f"/api/v1/statements/{said}/values", headers=owner, json=values(
            level_assignments=[{"level": LVL + "cefr-B1"}, {"level": LVL + "EQF-4"}])),
        client.put(f"/api/v1/statements/{said}/values", headers=owner, json=grade),
        client.put(f"/api/v1/nodes/{node}/values", headers=owner, json=grade),
        client.put(f"/api/v1/nodes/{node}/values", headers=owner, json=values(
            level_assignments=[{"level": LVL + "DQR-4", "level_to": LVL + "EQF-5"}])),
    ]  # fmt: skip
    taken = client.put(f"/api/v1/statements/{standard}/values", headers=owner, json=grade)

    assert [(answer.status_code, answer.json()["details"]) for answer in answers] == [
        (422, {"field": "level_assignments[1].level", "problem": "not_offered"}),
        (422, {"field": "level_assignments[0].level", "problem": "not_offered"}),
        (422, {"field": "level_assignments[0].level", "problem": "not_offered"}),
        (422, {"field": "level_assignments[0].level_to", "problem": "not_offered"}),
    ]
    assert taken.status_code == 200, taken.text
    assert rows(url, "SELECT count(*) FROM level_assignment") == [(1,)]


def test_an_unknown_unit_names_its_field(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_node(url, document)
    wrong = {**LESSONS, "unit": CV + "unit_furlong"}
    reversed_ = {**LESSONS, "amount": 60}
    phase = {"time_kind": CV + "time_phase"}
    path = f"/api/v1/nodes/{made}/values"

    answers = [
        client.put(path, headers=owner, json=values(workloads=[LESSONS, wrong])),
        client.put(path, headers=owner, json=values(workloads=[reversed_])),
        client.put(path, headers=owner, json=values(workloads=[{**LESSONS, "periods": [phase]}])),
        client.put(path, headers=owner, json=values(level_assignments=[{"level": CV + "unit_lesson"}])),
        client.put(
            path,
            headers=owner,
            json=values(level_assignments=[{"level": LVL + "EQF-4", "id": str(uuid.uuid4())}]),
        ),
    ]

    assert [(answer.status_code, answer.json()["code"]) for answer in answers] == [(422, "invalid_field")] * 5
    assert [answer.json()["details"] for answer in answers] == [
        {"field": "workloads[1].unit", "problem": "not_offered"},
        {"field": "workloads[0].amount_to", "problem": "out_of_order"},
        {"field": "workloads[0].periods[0].time_kind", "problem": "not_offered"},
        {"field": "level_assignments[0].level", "problem": "not_offered"},
        {"field": "level_assignments[0].id", "problem": "unknown_value"},
    ]
    assert rows(url, "SELECT revision FROM node") == [(1,)]


def test_a_retired_concept_is_set_no_more_but_a_value_keeps_it(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_node(url, document)
    path = f"/api/v1/nodes/{made}/values"
    set_ = client.put(path, headers=owner, json=values(workloads=[LESSONS]))
    [workload] = set_.json()["values"]["workloads"]
    [period] = [each["id"] for each in workload["periods"]]
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("UPDATE vocab_concept SET retired_in = 1 WHERE iri = %s", (CV + "unit_lesson",))

    new = client.put(
        path, headers=owner, json=values(2, workloads=[{**LESSONS, "id": workload["id"]}, LESSONS])
    )
    kept = client.put(path, headers=owner, json=values(2, workloads=[
        {**LESSONS, "id": workload["id"], "amount": 30, "periods": [{**GRADE, "id": period}]},
    ]))  # fmt: skip

    assert (new.status_code, new.json()["details"]) == (
        422,
        {"field": "workloads[1].unit", "problem": "not_offered"},
    )
    assert kept.status_code == 200, kept.text
    assert [(each["unit"], each["amount"]) for each in kept.json()["values"]["workloads"]] == [
        (CV + "unit_lesson", 30)
    ]


def test_a_stale_revision_is_refused_with_the_holder_as_it_stands(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_node(url, document)
    path = f"/api/v1/nodes/{made}/values"
    client.put(path, headers=owner, json=values(level_assignments=[{"level": LVL + "EQF-4"}]))

    answer = client.put(path, headers=owner, json=values(time_spans=[GRADE]))

    assert (answer.status_code, answer.json()["code"]) == (409, "stale_revision")
    current = answer.json()["details"]["current"]
    assert (current["revision"], [each["level"] for each in current["values"]["level_assignments"]]) == (
        2, [LVL + "EQF-4"],
    )  # fmt: skip


@pytest.mark.parametrize("closed", ["frozen", "job_open", "not_extracted"])
def test_a_document_closed_to_change_refuses_values(client: TestClient, url: str, closed: str) -> None:
    document, owner = a_document(client, url, ended=closed != "job_open", extracted=closed != "not_extracted")
    made = a_node(url, document)
    if closed == "frozen":
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(
                "UPDATE document SET iri = 'https://example.org/curriculum/1', frozen_at = now()"
                " WHERE id = %s",
                (document,),
            )

    answer = client.put(f"/api/v1/nodes/{made}/values", headers=owner, json=values(time_spans=[GRADE]))

    assert (answer.status_code, answer.json()["code"]) == (409, closed)
    assert rows(url, "SELECT count(*) FROM time_span") == [(0,)]


def test_a_stranger_gets_404(client: TestClient, url: str) -> None:
    document, _ = a_document(client, url)
    made = a_node(url, document)
    said = a_statement(url, document, made)
    _, stranger = an_account(url, "Fremde")
    body = values(level_assignments=[{"level": LVL + "EQF-4"}])

    by_node = client.put(f"/api/v1/nodes/{made}/values", headers=stranger, json=body)
    by_statement = client.put(f"/api/v1/statements/{said}/values", headers=stranger, json=body)
    none = client.put(f"/api/v1/nodes/{uuid.uuid4()}/values", headers=stranger, json=body)

    assert [(answer.status_code, answer.json()["code"]) for answer in (by_node, by_statement, none)] == [
        (404, "no_node"), (404, "no_statement"), (404, "no_node"),
    ]  # fmt: skip
    assert client.put(f"/api/v1/nodes/{made}/values", json=body).status_code == 401
    assert rows(url, "SELECT count(*) FROM level_assignment") == [(0,)]


def test_a_holder_whose_entry_is_hidden_from_its_owner_is_set_by_the_editors_alone(
    client: TestClient, url: str
) -> None:
    document, owner = a_document(client, url)
    made = a_node(url, document)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    hidden_from_its_owner(url, document)
    body = values(level_assignments=[{"level": LVL + "EQF-4"}])

    hidden = client.put(f"/api/v1/nodes/{made}/values", headers=owner, json=body)
    edited = client.put(f"/api/v1/nodes/{made}/values", headers=editor, json=body)

    assert (hidden.status_code, hidden.json()["code"]) == (403, "file_hidden")
    assert edited.status_code == 200, edited.text


def test_a_body_out_of_bounds_is_refused_as_the_request_s(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_node(url, document)
    path = f"/api/v1/nodes/{made}/values"

    for body in (
        values(level_assignments=[{"level": LVL + "EQF-4"}] * 21),  # at most 20 of a kind
        {"expected_revision": 1, "level_assignments": []},  # a set names every kind
        values(workloads=[{**LESSONS, "amount": "NaN"}]),
        values(workloads=[{**LESSONS, "amount": -1}]),
        values(workloads=[{**LESSONS, "minutes_per_unit": 2**31}]),
        values(level_assignments=[{"level": LVL + "EQF-4", "origin": HUMAN}]),
    ):
        answer = client.put(path, headers=owner, json=body)
        assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed"), body
    assert rows(url, "SELECT revision FROM node") == [(1,)]


def test_the_audit_names_counts_and_no_content(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_node(url, document)
    said = a_statement(url, document, made)
    body = values(level_assignments=[{"level": LVL + "EQF-4"}], workloads=[LESSONS])

    client.put(f"/api/v1/nodes/{made}/values", headers=owner, json=body)
    client.put(f"/api/v1/statements/{said}/values", headers=owner, json=values())

    audited = "SELECT action, subject, details FROM audit_log WHERE action LIKE '%%.values' ORDER BY id"
    assert rows(url, audited) == [
        ("node.values", f"node:{made}", {
            "document": document, "revision": 2, "level_assignments": 1, "time_spans": 0, "workloads": 1,
            "periods": 1,
        }),
        ("statement.values", f"statement:{said}", {
            "document": document, "revision": 1, "level_assignments": 0, "time_spans": 0, "workloads": 0,
            "periods": 0,
        }),
    ]  # fmt: skip
