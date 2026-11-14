"""The editors' review of the research cues through the API (plan M1 10.3, 10c C6, C7): the sample stratum by
stratum and every cue decided, by the editors alone; a decision made again over the last, audited, raising a
cue only with where it was found."""

import json
import math
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.test_documents import an_account, client, rows, url

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents

ROUTE = "/api/v1/lexicon/review"
OWN = "https://w3id.org/wlo/curriculum/profile/school#cue-dt-kernlehrplan"
CV = "https://w3id.org/wlo/curriculum/vocab#"
REGION = "https://w3id.org/wlo/curriculum/region/"
ROLES = {
    "Präferenzbezeichnung",
    "echtes Synonym",
    "Hinweis (kein Synonym)",
    "Abgrenzung",
    "Homonym mit Regel",
}


def an_editor(url: str) -> dict[str, str]:
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    return editor


def review(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    answer = client.get(ROUTE, headers=headers)
    assert answer.status_code == 200, answer.text
    found: dict[str, Any] = answer.json()
    return found


def confirm(cue: str, **changes: Any) -> dict[str, Any]:
    return {"cue": cue, "decision": "confirmed", "strength": "0.9", "evidence": "KLP S. 14"} | changes


def test_the_editors_see_a_tenth_of_each_stratum_rounded_up(client: TestClient, url: str) -> None:
    found = review(client, an_editor(url))

    strata = found["strata"]
    assert sum(stratum["cues"] for stratum in strata) == 1491
    assert all(stratum["sampled"] == math.ceil(stratum["cues"] / 10) for stratum in strata)
    assert all(stratum["decided"] == 0 for stratum in strata)
    assert len(found["items"]) == sum(stratum["sampled"] for stratum in strata)
    assert found["retired"] == []
    item = found["items"][0]
    assert set(item) == {
        "iri",
        "sector",
        "regions",
        "surface_form",
        "pattern",
        "role",
        "kind",
        "maps_to",
        "strength",
        "verified",
        "sources",
        "notes",
        "recognition_hints",
        "examples",
        "sampled",
        "decision",
    }
    assert (item["sampled"], item["decision"], item["verified"]) == (True, None, False)
    assert [(stratum["sector"], stratum["regions"]) for stratum in strata] == sorted(
        (stratum["sector"], stratum["regions"]) for stratum in strata
    )


def test_the_sample_is_the_same_each_time(client: TestClient, url: str) -> None:
    editor = an_editor(url)

    assert review(client, editor)["items"] == review(client, editor)["items"]


def test_a_confirmation_raises_with_evidence_and_is_audited(client: TestClient, url: str) -> None:
    editor = an_editor(url)
    cue = review(client, editor)["items"][0]["iri"]

    answer = client.post(ROUTE, headers=editor, json=confirm(cue, evidence="  KLP S. 14 ", note="passt"))

    assert answer.status_code == 200, answer.text
    made = answer.json()
    assert {key: made[key] for key in ("cue", "decision", "strength", "evidence", "note", "applied")} == {
        "cue": cue,
        "decision": "confirmed",
        "strength": "0.90",
        "evidence": "KLP S. 14",
        "note": "passt",
        "applied": False,
    }
    assert made["decided_by"] == "Redaktion"
    assert rows(url, "SELECT action, subject, details FROM audit_log WHERE action = 'lexicon.review'") == [
        ("lexicon.review", f"cue:{cue}", {"decision": "confirmed", "strength": "0.90"})
    ]
    after = review(client, editor)
    (decided,) = [item for item in after["items"] if item["decision"] is not None]
    assert decided["iri"] == cue
    assert decided["decision"] == made
    assert sum(stratum["decided"] for stratum in after["strata"]) == 1


def test_a_cue_outside_the_sample_decided_is_listed_beside_it(client: TestClient, url: str) -> None:
    editor = an_editor(url)
    sampled = {item["iri"] for item in review(client, editor)["items"]}
    (other,) = rows(
        url,
        "SELECT iri FROM lexical_cue WHERE iri LIKE %s AND NOT iri = ANY (%s) ORDER BY iri LIMIT 1",
        "%#re-%",
        list(sampled),
    )

    answer = client.post(ROUTE, headers=editor, json={"cue": other[0], "decision": "rejected"})

    assert answer.status_code == 200, answer.text
    (listed,) = [item for item in review(client, editor)["items"] if item["iri"] == other[0]]
    assert (listed["sampled"], listed["decision"]["decision"]) == (False, "rejected")


def test_a_cue_decided_again_has_the_last_decision(client: TestClient, url: str) -> None:
    editor = an_editor(url)
    cue = review(client, editor)["items"][0]["iri"]
    client.post(ROUTE, headers=editor, json=confirm(cue))

    answer = client.post(ROUTE, headers=editor, json={"cue": cue, "decision": "rejected", "note": "falsch"})
    blank = client.post(ROUTE, headers=editor, json={"cue": cue, "decision": "rejected", "note": "   "})

    assert (answer.status_code, blank.status_code) == (200, 200), answer.text + blank.text
    assert answer.json()["note"] == "falsch"
    assert rows(url, "SELECT decision, strength, evidence, note FROM cue_review") == [
        ("rejected", None, None, None)  # a blank note is none
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "confirmed", "strength": "0.9"},
        {"decision": "confirmed", "strength": "0.9", "evidence": "   "},
        {"decision": "confirmed", "evidence": "S. 1"},
        {"decision": "confirmed", "strength": "0.95", "evidence": "S. 1"},
        {"decision": "confirmed", "strength": "0.45", "evidence": "S. 1"},
        {"decision": "confirmed", "strength": "0.855", "evidence": "S. 1"},
        {"decision": "confirmed", "strength": "0.9", "evidence": "x" * 501},
        {"decision": "rejected", "strength": "0.9"},
        {"decision": "deferred"},
        {"decision": "rejected", "note": "x" * 2001},
        {"decision": "rejected", "verified": True},
        {"decision": "confirmed", "strength": "0.9", "evidence": "S." + chr(0) + " 1"},
        {"decision": "rejected", "note": "a" + chr(0) + "b"},
        {"decision": "rejected", "cue": "https://w3id.org/x" + chr(0)},
    ],
    ids=[
        "no-evidence",
        "blank-evidence",
        "no-strength",
        "above-0.9",
        "below-0.5",
        "three-places",
        "evidence-too-long",
        "rejected-with-strength",
        "unknown-decision",
        "note-too-long",
        "unknown-field",
        "nul-evidence",
        "nul-note",
        "nul-cue",
    ],
)
def test_a_decision_outside_the_rules_is_refused(client: TestClient, url: str, body: dict[str, Any]) -> None:
    editor = an_editor(url)
    cue = review(client, editor)["items"][0]["iri"]

    answer = client.post(ROUTE, headers=editor, json={"cue": cue} | body)

    assert answer.status_code == 422, answer.text
    assert rows(url, "SELECT count(*) FROM cue_review") == [(0,)]


def test_a_lone_surrogate_is_refused_before_it_reaches_the_database(client: TestClient, url: str) -> None:
    editor = an_editor(url)
    cue = review(client, editor)["items"][0]["iri"]
    # JSON may write it as an escape, which no UTF-8 can carry; pydantic refuses it already (string_unicode),
    # the route's own check stands behind that
    body = json.dumps({"cue": cue, "decision": "rejected", "note": "a" + chr(0xD800)})

    answer = client.post(ROUTE, headers=editor | {"content-type": "application/json"}, content=body.encode())

    assert answer.status_code == 422, answer.text
    assert rows(url, "SELECT count(*) FROM cue_review") == [(0,)]


def test_only_an_active_research_cue_is_decided_on(client: TestClient, url: str) -> None:
    editor = an_editor(url)
    retired = review(client, editor)["items"][0]["iri"]
    rows(url, "UPDATE lexical_cue SET retired_in = 1 WHERE iri = %s RETURNING iri", retired)

    for cue in (OWN, OWN + "-unknown", retired):
        answer = client.post(ROUTE, headers=editor, json={"cue": cue, "decision": "rejected"})
        assert (answer.status_code, answer.json()["code"]) == (404, "no_cue"), cue
    assert rows(url, "SELECT count(*) FROM cue_review") == [(0,)]


def test_a_decision_on_a_retired_cue_stays_beside_the_list(client: TestClient, url: str) -> None:
    editor = an_editor(url)
    cue = review(client, editor)["items"][0]["iri"]
    client.post(ROUTE, headers=editor, json={"cue": cue, "decision": "rejected"})
    rows(url, "UPDATE lexical_cue SET retired_in = 1 WHERE iri = %s RETURNING iri", cue)

    after = review(client, editor)

    assert cue not in {item["iri"] for item in after["items"]}
    (retired,) = after["retired"]
    assert (retired["cue"], retired["decision"], retired["retired"], retired["applied"]) == (
        cue,
        "rejected",
        True,
        True,
    )
    assert retired["content"]["maps_to"]


def test_every_concept_the_list_names_comes_with_its_label(client: TestClient, url: str) -> None:
    found = review(client, an_editor(url))

    named = {region for stratum in found["strata"] for region in stratum["regions"]} | {
        iri
        for item in found["items"]
        for iri in [*item["maps_to"], item["role"], item["kind"], *item["regions"]]
    }
    concepts = {iri for (iri,) in rows(url, "SELECT iri FROM vocab_concept WHERE iri = ANY(%s)", list(named))}
    assert set(found["labels"]) == concepts  # a class or property of the core has none
    assert found["labels"][REGION + "DE-NW"] == "Nordrhein-Westfalen"
    assert {found["labels"][item["role"]] for item in found["items"]} <= ROLES


def test_a_retired_cue_s_concepts_come_with_their_labels(client: TestClient, url: str) -> None:
    # its target one no listed cue names: the label comes from what was judged
    editor = an_editor(url)
    cue = review(client, editor)["items"][0]["iri"]
    rows(url, "UPDATE lexical_cue SET maps_to = %s WHERE iri = %s RETURNING iri", [CV + "sec_adult"], cue)
    client.post(ROUTE, headers=editor, json={"cue": cue, "decision": "rejected"})
    rows(url, "UPDATE lexical_cue SET retired_in = 1 WHERE iri = %s RETURNING iri", cue)

    after = review(client, editor)

    (retired,) = after["retired"]
    content = retired["content"]
    assert content["maps_to"] == [CV + "sec_adult"]
    judged = {CV + "sec_adult", content["role"], content["kind"], *content["scope_regions"]}
    assert judged <= set(after["labels"])


def test_the_editors_alone_see_and_decide(client: TestClient, url: str) -> None:
    _, teacher = an_account(url, "Lehrkraft")
    _, admin = an_account(url, "Verwaltung", ("admin",))
    cue = review(client, admin)["items"][0]["iri"]

    seen = client.get(ROUTE, headers=teacher)
    decided = client.post(ROUTE, headers=teacher, json={"cue": cue, "decision": "rejected"})
    unknown = client.post(ROUTE, headers=teacher, json={"cue": OWN + "-unknown", "decision": "rejected"})

    assert (seen.status_code, seen.json()["code"]) == (403, "not_editor")
    assert (decided.status_code, decided.json()["code"]) == (403, "not_editor")
    assert (unknown.status_code, unknown.json()["code"]) == (403, "not_editor")  # nothing learnt of a cue
    assert client.get(ROUTE).status_code == 401
    assert client.post(ROUTE, json={"cue": cue, "decision": "rejected"}).status_code == 401
    assert rows(url, "SELECT count(*) FROM cue_review") == [(0,)]
    by_admin = client.post(ROUTE, headers=admin, json={"cue": cue, "decision": "rejected"})
    assert (by_admin.status_code, by_admin.json()["decided_by"]) == (200, "Verwaltung")


def test_a_rejection_the_files_carry_is_taken_back_by_deciding_again(client: TestClient, url: str) -> None:
    editor = an_editor(url)
    cue = review(client, editor)["items"][0]["iri"]
    client.post(ROUTE, headers=editor, json={"cue": cue, "decision": "rejected"})
    rows(url, "UPDATE lexical_cue SET retired_in = 1 WHERE iri = %s RETURNING iri", cue)  # the next release

    answer = client.post(ROUTE, headers=editor, json=confirm(cue))

    assert answer.status_code == 200, answer.text
    (retired,) = review(client, editor)["retired"]
    assert (retired["cue"], retired["decision"], retired["applied"]) == (cue, "confirmed", False)
