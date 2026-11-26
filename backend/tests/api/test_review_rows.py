"""The editors' review of assessments and placements through the API (plan M3a L; app/api/review.py): rows
as nodes are, by the editors alone, audited by counts; a placement's review counts its node's revision too, so
a set of the node's placements read before it is stale; a row of another document is none of this one."""

import pytest
from fastapi.testclient import TestClient

from tests.api.test_assessments import EXAM, added, holders
from tests.api.test_document_tree import a_document
from tests.api.test_documents import an_account, client, rows, url
from tests.api.test_placements import BINDING, made, placements
from tests.db.l1 import CV

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents


def a_placement(client: TestClient, url: str, document: str, owner: dict[str, str]) -> dict[str, str]:
    """The module of ``made`` placed in its specification: the placement's id and the module's."""
    held = made(url, document)
    entry = {"specification_id": held["specification"], "obligation": BINDING}
    answer = client.put(
        f"/api/v1/nodes/{held['module']}/placements", headers=owner, json=placements(1, entry)
    )
    assert answer.status_code == 200, answer.text
    return {"placement": answer.json()["placements"][0]["id"], "module": held["module"], **held}


def test_the_editors_review_an_assessment_and_a_placement_at_once(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    placed = a_placement(client, url, document, owner)
    exam = added(client, document, owner, parent_id=placed["specification"], assessment_kind=EXAM)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    items = [
        {"kind": "assessment", "id": exam["id"], "revision": 1},
        {"kind": "placement", "id": placed["placement"], "revision": 1},
    ]

    answer = client.post(
        f"/api/v1/documents/{document}/review", headers=editor, json={"status": "confirmed", "items": items}
    )
    # the node's set of its placements on the revision before the review
    stale = client.put(
        f"/api/v1/nodes/{placed['module']}/placements",
        headers=owner,
        json=placements(2, {"id": placed["placement"], "specification_id": placed["specification"],
                            "obligation": BINDING}),
    )  # fmt: skip

    assert answer.status_code == 200, answer.text
    assert answer.json()["revisions"] == [
        {"id": exam["id"], "revision": 2}, {"id": placed["placement"], "revision": 2},
    ]  # fmt: skip
    # the node whose revision the placement's review moved, so that the node's set can go on from it
    assert answer.json()["nodes"] == [{"id": placed["module"], "revision": 3}]
    assert rows(
        url, "SELECT review_status_iri, origin_iri FROM assessment UNION ALL"
        " SELECT review_status_iri, origin_iri FROM placement",
    ) == [(CV + "rev_confirmed", CV + "orig_human")] * 2  # fmt: skip
    assert rows(url, "SELECT action, subject, details FROM audit_log WHERE action = 'review.set'") == [
        ("review.set", f"document:{document}", {"status": "confirmed", "items": 2})
    ]
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_revision")
    assert stale.json()["details"]["current"]["revision"] == 3


def test_an_assessment_or_placement_reviewed_by_none_but_the_editors_and_of_this_document_alone(
    client: TestClient, url: str
) -> None:
    document, owner = a_document(client, url)
    exam = added(
        client, document, owner, parent_id=holders(url, document)["specification"], assessment_kind=EXAM
    )
    other, other_owner = a_document(client, url, name="Andere", digest=b"\x02" * 32)
    elsewhere = a_placement(client, url, other, other_owner)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    _, stranger = an_account(url, "Fremde")
    path = f"/api/v1/documents/{document}/review"
    review = {"status": "rejected", "items": [{"kind": "assessment", "id": exam["id"], "revision": 1}]}

    by_owner = client.post(path, headers=owner, json=review)
    by_stranger = client.post(path, headers=stranger, json=review)
    stale = client.post(path, headers=editor, json={"status": "rejected", "items": [
        {"kind": "assessment", "id": exam["id"], "revision": 2},
        {"kind": "placement", "id": elsewhere["placement"], "revision": 1},
    ]})  # fmt: skip

    assert (by_owner.status_code, by_owner.json()["code"]) == (403, "not_editor")
    assert (by_stranger.status_code, by_stranger.json()["code"]) == (404, "no_document")
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_revision")
    assert stale.json()["details"] == {
        "stale": [
            {"kind": "assessment", "id": exam["id"], "current": 1},
            {"kind": "placement", "id": elsewhere["placement"], "current": None},
        ]
    }
    proposed = [(CV + "rev_proposed", 1)] * 2
    assert rows(url, "SELECT review_status_iri, revision FROM assessment UNION ALL"
                " SELECT review_status_iri, revision FROM placement") == proposed  # fmt: skip
    assert rows(url, "SELECT count(*) FROM audit_log WHERE action = 'review.set'") == [(0,)]
