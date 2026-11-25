"""A document's specifications through the API (plan M3a H1; app/api/specifications.py): read with their
variants, values and applicability contexts; a specification's title and field set on its revision, and its
values and contexts set as a whole - by the document's owner and the editors, audited by fields and counts
alone; refused with the field and why for a value or context the form does not take, with the
specification as it stands for a stale revision, and to a stranger as no specification at all."""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.api.test_document_tree import a_document
from tests.api.test_documents import an_account, client, hidden_from_its_owner, rows, url
from tests.db.l1 import CUR, CV, add_specification, add_variant

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents

LVL = "https://w3id.org/wlo/curriculum/level/"
HUMAN, PROPOSED = CV + "orig_human", CV + "rev_proposed"
GRADE = {"time_kind": CV + "time_gradeLevel", "span_from": 5, "span_to": 6}
CONTEXT = {
    "sector": CV + "sec_school", "formality": CV + "form_formal", "institution_text": "Gymnasium",
    "level_assignments": [{"level": LVL + "EQF-4"}], "time_spans": [GRADE],
}  # fmt: skip


def a_specification(url: str, document: str, key: str = "lp", **columns: Any) -> str:
    with psycopg.connect(url, autocommit=True) as connection:
        made = add_specification(connection, uuid.UUID(document), key=key, **{"title": "Physik"} | columns)
        add_variant(connection, made, "g8")
    return str(made)


def values(revision: int = 1, **kinds: list[dict[str, Any]]) -> dict[str, Any]:
    empty: dict[str, Any] = {"level_assignments": [], "time_spans": [], "workloads": [], "contexts": []}
    return {"expected_revision": revision} | empty | kinds


def test_a_document_s_specifications_are_read_with_their_variants_values_and_contexts(
    client: TestClient, url: str
) -> None:
    document, owner = a_document(client, url)
    made = a_specification(url, document)

    answer = client.get(f"/api/v1/documents/{document}/specifications", headers=owner)

    assert answer.status_code == 200, answer.text
    read = answer.json()
    assert (read["editable"], read["closed"]) == (True, None)
    [specification] = read["specifications"]
    assert {key: specification[key] for key in ("id", "key", "spec_kind", "type", "title", "revision")} == {
        "id": made, "key": "lp", "spec_kind": "curriculum", "type": CUR + "Curriculum", "title": "Physik",
        "revision": 1,
    }  # fmt: skip
    assert [(each["key"], each["variant_kind"]) for each in specification["variants"]] == [
        ("g8", CV + "var_track")
    ]
    assert specification["values"] == {"level_assignments": [], "time_spans": [], "workloads": []}
    assert specification["contexts"] == []


def test_a_specification_s_title_and_field_are_set_on_its_revision(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_specification(url, document)
    path = f"/api/v1/specifications/{made}"

    answer = client.patch(path, headers=owner, json={"expected_revision": 1, "field_text": "Physik"})
    stale = client.patch(path, headers=owner, json={"expected_revision": 1, "title": "Chemie"})
    blank = client.patch(path, headers=owner, json={"expected_revision": 2, "title": " "})

    assert answer.status_code == 200, answer.text
    assert (answer.json()["field_text"], answer.json()["revision"]) == ("Physik", 2)
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_revision")
    assert stale.json()["details"]["current"]["revision"] == 2
    assert (blank.status_code, blank.json()["details"]) == (422, {"field": "title", "problem": "required"})
    audited = "SELECT action, subject, details FROM audit_log WHERE action = 'specification.edit'"
    assert rows(url, audited) == [
        ("specification.edit", f"specification:{made}", {"document": document, "revision": 2,
                                                         "fields": ["field_text"]}),
    ]  # fmt: skip


def test_a_specification_s_values_and_contexts_are_set_as_a_whole(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_specification(url, document)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    path = f"/api/v1/specifications/{made}/values"

    answer = client.put(path, headers=editor, json=values(level_assignments=[{"level": LVL + "EQF-4"}],
                                                         contexts=[CONTEXT]))  # fmt: skip

    assert answer.status_code == 200, answer.text
    read = answer.json()
    assert read["revision"] == 2
    [context] = read["contexts"]
    assert (context["sector"], context["formality"], context["institution_text"]) == (
        CV + "sec_school", CV + "form_formal", "Gymnasium",
    )  # fmt: skip
    assert (context["origin"], context["review_status"], context["revision"]) == (HUMAN, PROPOSED, 1)
    assert [level["level"] for level in context["level_assignments"]] == [LVL + "EQF-4"]
    assert [span["span_from"] for span in context["time_spans"]] == [5]
    assert [level["level"] for level in read["values"]["level_assignments"]] == [LVL + "EQF-4"]
    listed = client.get(f"/api/v1/documents/{document}/specifications", headers=owner).json()
    assert listed["specifications"][0]["contexts"] == read["contexts"]

    # kept by its id, without its formality and time span, a blank institution none
    kept = CONTEXT | {"id": context["id"], "formality": None, "institution_text": " ", "time_spans": []}
    again = client.put(path, headers=owner, json=values(2, contexts=[kept]))

    assert again.status_code == 200, again.text
    [changed] = again.json()["contexts"]
    assert (changed["id"], changed["formality"], changed["institution_text"], changed["revision"]) == (
        context["id"], None, None, 2,
    )  # fmt: skip
    assert changed["time_spans"] == []
    audited = "SELECT details FROM audit_log WHERE action = 'specification.values' ORDER BY id"
    # every context taken away: the audit says so too
    emptied = client.put(path, headers=owner, json=values(3))
    assert (emptied.status_code, emptied.json()["contexts"]) == (200, [])
    assert [found["contexts"] for (found,) in rows(url, audited)] == [1, 1, 0]


def test_a_context_or_level_the_form_does_not_take_is_refused_at_its_field(
    client: TestClient, url: str
) -> None:
    document, owner = a_document(client, url)
    made = a_specification(url, document)
    assessment = a_specification(url, document, key="pr", spec_kind="assessmentSpecification")
    path = f"/api/v1/specifications/{made}/values"
    grade = [{"level": LVL + "grade-2"}]

    refused = [
        client.put(path, headers=owner, json=values(contexts=[CONTEXT | {"sector": CV + "form_formal"}])),
        client.put(path, headers=owner, json=values(contexts=[CONTEXT | {"level_assignments": grade}])),
        # a grade at a curriculum: an assessment specification's alone (LevelAssignmentShape)
        client.put(path, headers=owner, json=values(level_assignments=grade)),
    ]
    taken = client.put(f"/api/v1/specifications/{assessment}/values", headers=owner,
                       json=values(level_assignments=grade))  # fmt: skip

    assert [(answer.status_code, answer.json()["details"]) for answer in refused] == [
        (422, {"field": "contexts[0].sector", "problem": "not_offered"}),
        (422, {"field": "contexts[0].level_assignments[0].level", "problem": "not_offered"}),
        (422, {"field": "level_assignments[0].level", "problem": "not_offered"}),
    ]
    assert taken.status_code == 200, taken.text
    assert rows(url, "SELECT count(*) FROM applicability_context") == [(0,)]


def test_a_specification_is_none_to_a_stranger_and_hidden_content_is_refused(
    client: TestClient, url: str
) -> None:
    document, owner = a_document(client, url)
    made = a_specification(url, document)
    _, stranger = an_account(url, "Fremd")

    answers = [
        client.patch(f"/api/v1/specifications/{made}", headers=stranger, json={"expected_revision": 1}),
        client.put(f"/api/v1/specifications/{made}/values", headers=stranger, json=values()),
        client.patch(f"/api/v1/specifications/{uuid.uuid4()}", headers=owner, json={"expected_revision": 1}),
    ]
    listed = client.get(f"/api/v1/documents/{document}/specifications", headers=stranger)
    hidden_from_its_owner(url, document)
    hidden = client.get(f"/api/v1/documents/{document}/specifications", headers=owner)

    assert [(answer.status_code, answer.json()["code"]) for answer in answers] == [
        (404, "no_specification")
    ] * 3
    assert (listed.status_code, listed.json()["code"]) == (404, "no_document")
    assert (hidden.status_code, hidden.json()["code"]) == (403, "file_hidden")


def test_a_frozen_document_s_specifications_are_read_only(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_specification(url, document)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "UPDATE document SET iri = 'https://example.org/curriculum/1', frozen_at = now() WHERE id = %s",
            (document,),
        )

    listed = client.get(f"/api/v1/documents/{document}/specifications", headers=owner).json()
    edit = client.patch(
        f"/api/v1/specifications/{made}", headers=owner, json={"expected_revision": 1, "title": "Chemie"}
    )

    assert (listed["editable"], listed["closed"]) == (False, "frozen")
    assert (edit.status_code, edit.json()["code"]) == (409, "frozen")


def test_an_editor_sets_another_s_specification_and_a_stale_set_answers_it_as_it_stands(
    client: TestClient, url: str
) -> None:
    document, _ = a_document(client, url)
    made = a_specification(url, document)
    _, editor = an_account(url, "Redaktion", ("redaktion",))

    edit = {"expected_revision": 1, "title": "Chemie"}
    edited = client.patch(f"/api/v1/specifications/{made}", headers=editor, json=edit)
    stale = client.put(
        f"/api/v1/specifications/{made}/values", headers=editor, json=values(contexts=[CONTEXT])
    )

    assert edited.status_code == 200, edited.text
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_revision")
    current = stale.json()["details"]["current"]
    assert (current["id"], current["title"], current["revision"], current["contexts"]) == (
        made,
        "Chemie",
        2,
        [],
    )


def test_a_frozen_document_s_values_and_hidden_content_are_refused(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_specification(url, document)
    hidden_from_its_owner(url, document)

    patched = client.patch(f"/api/v1/specifications/{made}", headers=owner, json={"expected_revision": 1})
    put = client.put(f"/api/v1/specifications/{made}/values", headers=owner, json=values())
    frozen_document, frozen_owner = a_document(client, url, name="Zweite", digest=b"\x02" * 32)
    frozen = a_specification(url, frozen_document)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "UPDATE document SET iri = 'https://example.org/curriculum/2', frozen_at = now() WHERE id = %s",
            (frozen_document,),
        )
    refused = client.put(f"/api/v1/specifications/{frozen}/values", headers=frozen_owner, json=values(
        contexts=[CONTEXT]))  # fmt: skip

    assert [(answer.status_code, answer.json()["code"]) for answer in (patched, put)] == [
        (403, "file_hidden")
    ] * 2
    assert (refused.status_code, refused.json()["code"]) == (409, "frozen")
    assert rows(url, "SELECT count(*) FROM applicability_context") == [(0,)]
