"""A document's rules through the API (plan M3a I; app/api/rules.py): read with what they may name and the
units and kinds of requirement to choose from; a rule's values and links set on its revision, a rule added
on blocks chosen, a rule taken away - by the document's owner and the editors, audited by fields alone;
refused with the field and why, with the rule as it stands for a stale revision, as anchor_missing for a rule
added nowhere, to a stranger as no rule at all, and as file_hidden where the entry's content is hidden."""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from tests.api.test_document_tree import a_document
from tests.api.test_documents import an_account, client, hidden_from_its_owner, rows, url
from tests.db.l1 import CV, add_entity, add_node, add_specification, add_variant

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents

MODEL, HUMAN, PROPOSED = CV + "orig_model", CV + "orig_human", CV + "rev_proposed"
RULE: dict[str, Any] = {
    "verbatim": "Zwei aus vier.", "ruleKind": "selection", "minCount": 2, "maxCount": 2, "minAmount": None,
    "maxAmount": None, "amountUnit": "ectsCredit", "requirementKind": None, "maxShare": None,
    "optionTexts": ["A", "B"],
}  # fmt: skip


def a_rule(url: str, document: str) -> str:
    """A rule X3 read, on block p1-b1."""
    with psycopg.connect(url, autocommit=True) as connection:
        part = add_entity(connection, "frame_part")
        connection.execute(
            "INSERT INTO frame_part (id, document_id, part_kind, content, origin_scheme, origin_iri,"
            " review_status_scheme, review_status_iri, position)"
            " VALUES (%s, %s, 'rules', %s, %s, %s, %s, %s, 1)",
            (part, document, Jsonb(RULE), CV + "Origins", MODEL, CV + "ReviewStatuses", PROPOSED),
        )
        anchor = add_entity(connection, "anchor")
        connection.execute(
            "INSERT INTO anchor (id, document_id, conversion_id, frame_part_id, page_start)"
            " SELECT %s, id, conversion_id, %s, 1 FROM document WHERE id = %s",
            (anchor, part, document),
        )
    return str(part)


def targets(url: str, document: str) -> dict[str, str]:
    with psycopg.connect(url, autocommit=True) as connection:
        top = add_node(connection, uuid.UUID(document), code="LF 1", original_title="Optik")
        specification = add_specification(connection, uuid.UUID(document), key="lp", title="Physik")
        variant = add_variant(connection, specification, "g8")
    return {"node": str(top), "specification": str(specification), "variant": str(variant)}


def test_a_document_s_rules_are_read_with_their_targets_and_choices(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_rule(url, document)
    named = targets(url, document)

    answer = client.get(f"/api/v1/documents/{document}/rules", headers=owner)

    assert answer.status_code == 200, answer.text
    read = answer.json()
    assert (read["editable"], read["closed"]) == (True, None)
    [rule] = read["rules"]
    shown = ("id", "kind", "verbatim", "min_count", "amount_unit", "option_texts")
    assert {key: rule[key] for key in shown} == {
        "id": made, "kind": "selection", "verbatim": "Zwei aus vier.", "min_count": 2,
        "amount_unit": CV + "unit_ectsCredit", "option_texts": ["A", "B"],
    }  # fmt: skip
    assert (rule["origin"], rule["review_status"], rule["revision"], rule["by_hand"]) == (
        MODEL,
        PROPOSED,
        1,
        False,
    )
    assert rule["anchors"] == [{"page_start": 1, "page_end": None, "blocks": []}]
    assert [(each["id"], each["kind"], each["label"]) for each in read["targets"]] == [
        (named["specification"], "specification", "Physik"),
        (named["variant"], "variant", "Physik: Gymnasium"),
        (named["node"], "node", "LF 1 Optik"),
    ]  # fmt: skip
    assert CV + "unit_ectsCredit" in [choice["iri"] for choice in read["units"]]
    assert {choice["iri"] for choice in read["requirement_kinds"]} == {
        CV + "req_formal",
        CV + "req_recommended",
        CV + "req_none",
    }


def test_a_rule_s_values_and_links_are_set_on_its_revision(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_rule(url, document)
    named = targets(url, document)
    path = f"/api/v1/rules/{made}"
    edit = {"expected_revision": 1, "max_count": 3, "min_amount": 7.5, "amount_unit": CV + "unit_hour",
            "options": [named["node"], named["variant"]], "applies_to": [named["specification"]],
            "option_texts": []}  # fmt: skip

    answer = client.patch(path, headers=owner, json=edit)
    stale = client.patch(path, headers=owner, json={"expected_revision": 1, "max_count": 4})
    refused = client.patch(path, headers=owner, json={"expected_revision": 2, "requires": [named["node"]]})
    over = client.patch(path, headers=owner, json={"expected_revision": 2, "max_share": 1.5})

    assert answer.status_code == 200, answer.text
    rule = answer.json()
    assert (rule["max_count"], rule["min_amount"], rule["amount_unit"], rule["revision"]) == (
        3, 7.5, CV + "unit_hour", 2,
    )  # fmt: skip
    assert (rule["origin"], rule["option_texts"]) == (HUMAN, [])
    assert [(each["id"], each["label"]) for each in rule["options"]] == [
        (named["node"], "LF 1 Optik"), (named["variant"], "Physik: Gymnasium"),
    ]  # fmt: skip
    assert [each["kind"] for each in rule["applies_to"]] == ["specification"]
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_revision")
    assert stale.json()["details"]["current"]["revision"] == 2
    assert (refused.status_code, refused.json()["details"]) == (
        422,
        {"field": "requires", "problem": "not_held"},
    )
    assert over.status_code == 422
    audited = "SELECT action, subject, details FROM audit_log WHERE action LIKE 'rule.%%'"
    assert rows(url, audited) == [
        ("rule.edit", f"rule:{made}", {"document": document, "revision": 2, "fields": sorted(
            ["max_count", "min_amount", "amount_unit", "options", "applies_to", "option_texts"])}),
    ]  # fmt: skip


def test_a_rule_is_added_on_blocks_chosen_and_taken_away(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    body = {
        "kind": "completion",
        "verbatim": "Bestanden ist, wer alles besteht.",
        "anchors": [{"blocks": ["p1-b1"]}],
    }

    added = client.post(f"/api/v1/documents/{document}/rules", headers=editor, json=body)
    nowhere = client.post(f"/api/v1/documents/{document}/rules", headers=owner, json=body | {"anchors": []})
    unknown = client.post(f"/api/v1/documents/{document}/rules", headers=owner, json=body | {"kind": "other"})

    assert added.status_code == 201, added.text
    rule = added.json()
    assert (rule["kind"], rule["origin"], rule["by_hand"]) == ("completion", HUMAN, True)
    assert rule["anchors"] == [{"page_start": 1, "page_end": None, "blocks": ["p1-b1"]}]
    assert (nowhere.status_code, nowhere.json()["code"]) == (422, "anchor_missing")
    assert unknown.status_code == 422

    taken = client.delete(f"/api/v1/rules/{rule['id']}?expected_revision=1", headers=owner)

    assert (taken.status_code, taken.json()) == (200, {"outcome": "deleted", "revision": None})
    assert client.get(f"/api/v1/documents/{document}/rules", headers=owner).json()["rules"] == []
    audited = "SELECT action, details FROM audit_log WHERE action LIKE 'rule.%%' ORDER BY id"
    assert rows(url, audited) == [
        ("rule.add", {"document": document, "kind": "completion", "anchors": 1}),
        ("rule.delete", {"document": document}),
    ]


def test_a_run_s_rule_taken_away_is_rejected_and_stays(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_rule(url, document)

    taken = client.delete(f"/api/v1/rules/{made}?expected_revision=1", headers=owner)
    stale = client.delete(f"/api/v1/rules/{made}?expected_revision=1", headers=owner)

    assert (taken.status_code, taken.json()) == (200, {"outcome": "rejected", "revision": 2})
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_revision")
    [rule] = client.get(f"/api/v1/documents/{document}/rules", headers=owner).json()["rules"]
    assert rule["review_status"] == CV + "rev_rejected"


def test_a_rule_is_none_to_a_stranger_and_hidden_content_is_refused(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_rule(url, document)
    _, stranger = an_account(url, "Fremd")
    new = {"kind": "completion", "verbatim": "Alles.", "anchors": [{"page": 1}]}

    answers = [
        client.patch(f"/api/v1/rules/{made}", headers=stranger, json={"expected_revision": 1}),
        client.delete(f"/api/v1/rules/{made}?expected_revision=1", headers=stranger),
        client.patch(f"/api/v1/rules/{uuid.uuid4()}", headers=owner, json={"expected_revision": 1}),
    ]
    added = client.post(f"/api/v1/documents/{document}/rules", headers=stranger, json=new)
    listed = client.get(f"/api/v1/documents/{document}/rules", headers=stranger)
    hidden_from_its_owner(url, document)
    hidden = [
        client.get(f"/api/v1/documents/{document}/rules", headers=owner),
        client.patch(f"/api/v1/rules/{made}", headers=owner, json={"expected_revision": 1}),
        client.post(f"/api/v1/documents/{document}/rules", headers=owner, json=new),
        client.delete(f"/api/v1/rules/{made}?expected_revision=1", headers=owner),
    ]

    assert [(answer.status_code, answer.json()["code"]) for answer in answers] == [(404, "no_rule")] * 3
    assert (added.status_code, added.json()["code"]) == (404, "no_document")
    assert (listed.status_code, listed.json()["code"]) == (404, "no_document")
    assert [(answer.status_code, answer.json()["code"]) for answer in hidden] == [(403, "file_hidden")] * 4
    assert rows(url, "SELECT revision FROM frame_part") == [(1,)]


def test_a_frozen_document_s_rules_are_read_only(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    made = a_rule(url, document)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "UPDATE document SET iri = 'https://example.org/curriculum/1', frozen_at = now() WHERE id = %s",
            (document,),
        )

    listed = client.get(f"/api/v1/documents/{document}/rules", headers=owner).json()
    edit = client.patch(f"/api/v1/rules/{made}", headers=owner, json={"expected_revision": 1, "max_count": 3})

    assert (listed["editable"], listed["closed"]) == (False, "frozen")
    assert (edit.status_code, edit.json()["code"]) == (409, "frozen")
