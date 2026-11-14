"""The editors' decisions on the terms X1 found no type for, through the API (plan M1 10.4, 10d D5, D6):
every term the documents' profiles name, once for its sector, regions and word, and a decision on it by the
editors alone - a new cue to a node type of the sector's profile with its role, a term peculiar to its
document, or one misread -, made again over the last and audited."""

import json
import threading
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.api import lexicon_terms
from app.lexicon import held as held_module
from app.vocab import lookup
from tests.api.test_documents import a_conversion, an_account, asked, client, rows, url

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents

ROUTE = "/api/v1/lexicon/terms"
CV = "https://w3id.org/wlo/curriculum/vocab#"
SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"
AREA = SCHOOL + "Inhaltsbereich"
REGION = "https://w3id.org/wlo/curriculum/region/"
SOURCE = "http://purl.org/dc/terms/source"


def an_editor(url: str) -> dict[str, str]:
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    return editor


def a_document(
    client: TestClient, url: str, terms: list[dict[str, Any]], title: str | None = None, **asking: Any
) -> UUID:
    made_by = uuid4()
    owner, header = an_account(url, f"Eigentum {made_by}")
    made = a_conversion(url, owner, made_by.bytes * 2)
    answer = client.post("/api/v1/documents", headers=header, json=asked(made, **asking))
    assert answer.status_code == 202, answer.text
    document = UUID(answer.json()["document"]["id"])
    rows(
        url,
        "UPDATE document_profile SET new_terms = %s WHERE document_id = %s RETURNING document_id",
        Jsonb(terms),
        document,
    )
    rows(url, "UPDATE document SET title = %s WHERE id = %s RETURNING id", title, document)
    return document


def term(text: str, function: str | None = CV + "fn_area", block: str | None = "p1-b1") -> dict[str, Any]:
    return {"documentTerm": text, "suggestedFunction": function, "evidenceBlockId": block}


def listed(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    answer = client.get(ROUTE, headers=headers)
    assert answer.status_code == 200, answer.text
    found: dict[str, Any] = answer.json()
    return found


def a_cue(text: str = "Inhaltsfeld", **changes: Any) -> dict[str, Any]:
    asked = {"sector": "school", "regions": ["DE-NW"], "term": text, "decision": "cue"}
    return asked | {"maps_to": AREA, "role": "alt"} | changes


def test_the_editors_see_each_term_once_with_its_first_places(client: TestClient, url: str) -> None:
    first = a_document(
        client, url, [term("Inhaltsfeld"), term("Lernbereich", CV + "fn_unit", None)], "Kernlehrplan Physik"
    )
    second = a_document(client, url, [term(" inhaltsfeld: ", None)])
    a_document(client, url, [term("Inhaltsfeld")], regions=["DE-BY"])
    a_document(client, url, [term("Leitidee")], regions=[])

    found = listed(client, an_editor(url))

    assert [
        (item["sector"], item["regions"], item["term"], item["documents"]) for item in found["terms"]
    ] == [
        ("school", ["DE"], "Leitidee", 1),
        ("school", ["DE-BY"], "Inhaltsfeld", 1),
        ("school", ["DE-NW"], "Inhaltsfeld", 2),
        ("school", ["DE-NW"], "Lernbereich", 1),
    ]
    field = found["terms"][2]
    assert field["functions"] == [CV + "fn_area"]
    assert field["occurrences"] == [
        {
            "document": str(first),
            "title": "Kernlehrplan Physik",
            "block": "p1-b1",
            "function": CV + "fn_area",
        },
        {"document": str(second), "title": None, "block": "p1-b1", "function": None},
    ]
    assert field["decision"] is None
    assert found["gone"] == []


def test_a_new_cue_is_decided_with_its_target_and_role_and_audited(client: TestClient, url: str) -> None:
    a_document(client, url, [term("Inhaltsfeld"), term("Inhaltsfeld", block="p2-b1")])
    editor = an_editor(url)

    answer = client.post(ROUTE, headers=editor, json=a_cue("INHALTSFELD", note="  wie in HE "))

    assert answer.status_code == 200, answer.text
    made = answer.json()
    assert {key: value for key, value in made.items() if key != "decided_at"} == {
        "sector": "school",
        "regions": ["DE-NW"],
        "term": "Inhaltsfeld",  # as the documents write it
        "decision": "cue",
        "maps_to": AREA,
        "role": "alt",
        "note": "wie in HE",
        "content": {"functions": [CV + "fn_area"], "documents": 1},
        "decided_by": "Redaktion",
        "applied": False,
    }
    assert rows(url, "SELECT action, subject, details FROM audit_log WHERE action = 'lexicon.term'") == [
        ("lexicon.term", "term:school:DE-NW:inhaltsfeld", {"decision": "cue", "maps_to": AREA, "role": "alt"})
    ]
    assert rows(url, "SELECT profile_iri, role_iri FROM term_review") == [
        (SCHOOL + "Terminology", CV + "role_alt")
    ]
    after = listed(client, editor)
    (decided,) = after["terms"]
    assert decided["decision"] == made
    assert after["gone"] == []  # a decided term the documents still name stands with them


def test_a_term_decided_again_has_the_last_decision(client: TestClient, url: str) -> None:
    a_document(client, url, [term("Inhaltsfeld")])
    editor = an_editor(url)
    client.post(ROUTE, headers=editor, json=a_cue())

    answer = client.post(
        ROUTE, headers=editor, json=a_cue(decision="error", maps_to=None, role=None, note="   ")
    )

    assert answer.status_code == 200, answer.text
    assert rows(url, "SELECT decision, maps_to, role_iri, note FROM term_review") == [
        ("error", None, None, None)
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"maps_to": None},
        {"role": None},
        {"decision": "document", "role": None},
        {"decision": "error", "maps_to": None},
        {"role": "negative"},
        {"decision": "deferred"},
        {"term": "x" * 501},
        {"term": "\u00df" * 251},  # its key twice as long
        {"regions": ["DE-NW"] * 18},
        {"maps_to": "x" * 501},
        {"sector": "x" * 65},
        {"sector": "school" + chr(0)},
        {"term": "   "},
        {"regions": []},
        {"regions": ["de-nw"]},
        {"sector": ""},
        {"note": "x" * 2001},
        {"verified": True},
        {"term": "Inhalts" + chr(0) + "feld"},
        {"note": "a" + chr(0)},
        {"maps_to": AREA + chr(0)},
    ],
    ids=[
        "cue-without-target",
        "cue-without-role",
        "document-with-target",
        "error-with-role",
        "role-negative",
        "decision-unknown",
        "term-too-long",
        "key-too-long",
        "too-many-regions",
        "target-too-long",
        "sector-too-long",
        "nul-sector",
        "term-blank",
        "no-regions",
        "region-unwritten",
        "no-sector",
        "note-too-long",
        "unknown-field",
        "nul-term",
        "nul-note",
        "nul-target",
    ],
)
def test_a_decision_outside_the_rules_is_refused(
    client: TestClient, url: str, changes: dict[str, Any]
) -> None:
    a_document(client, url, [term("Inhaltsfeld"), term("LF"), term("\u00df" * 251)])

    answer = client.post(ROUTE, headers=an_editor(url), json=a_cue() | changes)

    # refused by the rules of the body, not by a later check (a target too long is no node type either)
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed"), answer.text
    assert rows(url, "SELECT count(*) FROM term_review") == [(0,)]


def test_a_word_shorter_than_a_cue_as_the_documents_write_it_gives_none(client: TestClient, url: str) -> None:
    a_document(client, url, [term("Ma\u00df")])  # its key "mass" has four signs, the word three

    answer = client.post(ROUTE, headers=an_editor(url), json=a_cue("MASS"))

    assert (answer.status_code, answer.json()["code"]) == (422, "too_short"), answer.text
    assert rows(url, "SELECT count(*) FROM term_review") == [(0,)]


def test_the_longest_key_is_decided_on(client: TestClient, url: str) -> None:
    a_document(client, url, [term("\u00df" * 250)])

    answer = client.post(
        ROUTE, headers=an_editor(url), json=a_cue("\u00df" * 250, decision="error", maps_to=None, role=None)
    )

    assert answer.status_code == 200, answer.text


@pytest.mark.parametrize("role", ["pref", "cue"])
def test_a_new_cue_has_the_role_asked(client: TestClient, url: str, role: str) -> None:
    a_document(client, url, [term("Inhaltsfeld")])

    answer = client.post(ROUTE, headers=an_editor(url), json=a_cue(role=role))

    assert (answer.status_code, answer.json()["role"]) == (200, role), answer.text
    assert rows(url, "SELECT role_iri FROM term_review") == [(CV + "role_" + role,)]


def test_a_term_of_a_document_without_regions_is_decided_for_the_whole_country(
    client: TestClient, url: str
) -> None:
    a_document(client, url, [term("Leitidee")], regions=[])

    answer = client.post(ROUTE, headers=an_editor(url), json=a_cue("Leitidee", regions=["DE"]))

    assert (answer.status_code, answer.json()["regions"]) == (200, ["DE"]), answer.text


def test_a_short_term_is_decided_on_where_it_gives_no_cue(client: TestClient, url: str) -> None:
    a_document(client, url, [term("LF")])

    answer = client.post(
        ROUTE, headers=an_editor(url), json=a_cue("LF", decision="error", maps_to=None, role=None)
    )

    assert answer.status_code == 200, answer.text


@pytest.mark.parametrize("field", ["note", "term", "maps_to", "sector"])
def test_a_lone_surrogate_is_refused_before_it_reaches_the_database(
    client: TestClient, url: str, field: str
) -> None:
    a_document(client, url, [term("Inhaltsfeld")])
    asked = a_cue(note="passt")
    body = json.dumps(asked | {field: asked[field] + chr(0xD800)})  # an escape no UTF-8 carries

    answer = client.post(ROUTE, headers=an_editor(url) | {"content-type": "application/json"}, content=body)

    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed"), answer.text
    assert rows(url, "SELECT count(*) FROM term_review") == [(0,)]


def test_a_term_no_document_names_is_no_term(client: TestClient, url: str) -> None:
    a_document(client, url, [term("Inhaltsfeld")])
    editor = an_editor(url)

    for changes in (
        {"term": "Leitidee"},
        {"regions": ["DE-BY"]},
        {"regions": ["DE-NW", "DE-BY"]},
        {"sector": "vocational"},
        {"sector": "unknown"},
    ):
        answer = client.post(ROUTE, headers=editor, json=a_cue(**changes))
        assert (answer.status_code, answer.json()["code"]) == (404, "no_term"), changes
    assert rows(url, "SELECT count(*) FROM term_review") == [(0,)]


def test_the_regions_are_one_however_they_are_asked(client: TestClient, url: str) -> None:
    a_document(client, url, [term("Inhaltsfeld")], regions=["DE-NW", "DE-BY"])

    answer = client.post(ROUTE, headers=an_editor(url), json=a_cue(regions=["DE-NW", "DE-BY", "DE-NW"]))

    assert (answer.status_code, answer.json()["regions"]) == (200, ["DE-BY", "DE-NW"])


def test_a_new_cue_points_to_a_node_type_of_the_sector_s_profile(client: TestClient, url: str) -> None:
    a_document(client, url, [term("Inhaltsfeld")])
    editor = an_editor(url)

    for target in (
        SCHOOL + "Kompetenzerwartung",  # a statement subkind
        "https://w3id.org/wlo/curriculum/profile/vocational#Ausbildungsberufsbild",
        SCHOOL + "Unbekannt",
    ):
        answer = client.post(ROUTE, headers=editor, json=a_cue(maps_to=target))
        assert (answer.status_code, answer.json()["code"]) == (422, "not_a_node_type"), target
    assert rows(url, "SELECT count(*) FROM term_review") == [(0,)]


def test_a_decision_on_a_term_no_document_names_any_more_stays_beside_the_list(
    client: TestClient, url: str
) -> None:
    document = a_document(client, url, [term("Inhaltsfeld")])
    editor = an_editor(url)
    client.post(ROUTE, headers=editor, json=a_cue())
    rows(url, "UPDATE document_profile SET new_terms = '[]' WHERE document_id = %s RETURNING 1", document)

    after = listed(client, editor)
    again = client.post(
        ROUTE, headers=editor, json=a_cue("inhaltsfeld", decision="document", maps_to=None, role=None)
    )

    assert after["terms"] == []
    assert [(made["term"], made["decision"]) for made in after["gone"]] == [("Inhaltsfeld", "cue")]
    assert (again.status_code, again.json()["term"], again.json()["decision"]) == (
        200,
        "Inhaltsfeld",
        "document",
    )
    assert again.json()["content"] == {"functions": [CV + "fn_area"], "documents": 1}  # as it was judged


def test_the_editors_alone_see_and_decide(client: TestClient, url: str) -> None:
    a_document(client, url, [term("Inhaltsfeld")])
    _, teacher = an_account(url, "Lehrkraft")
    _, admin = an_account(url, "Verwaltung", ("admin",))

    seen = client.get(ROUTE, headers=teacher)
    decided = client.post(ROUTE, headers=teacher, json=a_cue())
    unknown = client.post(ROUTE, headers=teacher, json=a_cue("Leitidee"))

    assert (seen.status_code, seen.json()["code"]) == (403, "not_editor")
    assert (decided.status_code, decided.json()["code"]) == (403, "not_editor")
    assert (unknown.status_code, unknown.json()["code"]) == (403, "not_editor")  # nothing learnt of a term
    assert client.get(ROUTE).status_code == 401
    assert client.post(ROUTE, json=a_cue()).status_code == 401
    assert rows(url, "SELECT count(*) FROM term_review") == [(0,)]
    by_admin = client.post(ROUTE, headers=admin, json=a_cue())
    assert (by_admin.status_code, by_admin.json()["decided_by"]) == (200, "Verwaltung")


def a_research_cue(url: str, word: str | None, region: str, pattern: str | None = None) -> str:
    iri = SCHOOL + f"re-{region}-probe"
    rows(
        url,
        "INSERT INTO lexical_cue (iri, profile_iri, surface_form, pattern, role_scheme, role_iri,"
        " kind_scheme, kind_iri, maps_to, scope_regions, properties)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING iri",
        iri,
        SCHOOL + "Terminology",
        word,
        pattern,
        CV + "CueRoles",
        CV + "role_alt",
        CV + "CueKinds",
        CV + ("ck_term" if pattern is None else "ck_headingPattern"),
        [AREA],
        [REGION + region],
        Jsonb({SOURCE: [{"value": "recherche-ergebnisse/probe.md"}]}),
    )
    return iri


def test_a_term_comes_with_the_active_cues_that_hold_it_already(client: TestClient, url: str) -> None:
    # the own lexicon's first; a research cue of another land holds it too
    research = a_research_cue(url, "Inhaltsfeld", "DE-BY")
    numbered = a_research_cue(url, None, "DE-HE", r"^Inhaltsfeld\s+[0-9]+")
    ((pattern, maps_to, regions),) = rows(
        url,
        "SELECT pattern, maps_to, scope_regions FROM lexical_cue WHERE iri = %s",
        SCHOOL + "cue-ib-inhaltsfeld",
    )
    a_document(client, url, [term("Inhaltsfeld"), term("Probebereich")])

    field, probe = listed(client, an_editor(url))["terms"]

    assert probe["held"] == []
    assert field["held"][0] == {
        "iri": SCHOOL + "cue-ib-inhaltsfeld",
        "own": True,
        "by_word": True,
        "surface_form": "Inhaltsfeld",
        "pattern": pattern,
        "maps_to": maps_to,
        "role": CV + "role_cue",
        "regions": sorted(regions),
    }
    owned = [held["own"] for held in field["held"]]
    assert owned == sorted(owned, reverse=True)
    (researched,) = [held for held in field["held"] if held["iri"] == research]
    assert (researched["own"], researched["by_word"]) == (False, True)
    assert researched["regions"] == [REGION + "DE-BY"]
    (by_pattern,) = [held for held in field["held"] if held["iri"] == numbered]
    assert (by_pattern["by_word"], by_pattern["surface_form"]) == (False, None)


def test_every_concept_the_list_names_comes_with_its_label(client: TestClient, url: str) -> None:
    a_document(client, url, [term("Inhaltsfeld"), term("Lernbereich", CV + "fn_unit")])

    found = listed(client, an_editor(url))

    named = {
        iri
        for item in found["terms"]
        for iri in [
            *item["functions"],
            *(place["function"] for place in item["occurrences"] if place["function"]),
            *(iri for held in item["held"] for iri in [*held["maps_to"], held["role"], *held["regions"]]),
        ]
    }
    concepts = {iri for (iri,) in rows(url, "SELECT iri FROM vocab_concept WHERE iri = ANY(%s)", list(named))}
    assert set(found["labels"]) == concepts
    assert found["labels"][CV + "role_cue"] == "Hinweis (kein Synonym)"
    assert CV + "fn_unit" in found["labels"]


def test_a_decision_on_a_term_gone_comes_with_the_labels_of_what_was_judged(
    client: TestClient, url: str
) -> None:
    document = a_document(client, url, [term("Probebereich", CV + "fn_unit")])
    editor = an_editor(url)
    unit = SCHOOL + "Unterrichtseinheit"
    assert client.post(ROUTE, headers=editor, json=a_cue("Probebereich", maps_to=unit)).status_code == 200
    rows(url, "UPDATE document_profile SET new_terms = '[]' WHERE document_id = %s RETURNING 1", document)

    found = listed(client, editor)

    assert (found["terms"], len(found["gone"])) == ([], 1)
    assert set(found["labels"]) == {unit, CV + "fn_unit"}  # its target, and the functions suggested then


def test_the_terms_are_gathered_and_held_off_the_event_loop(
    client: TestClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the patterns may take their time limit: the loop that answers other requests does not wait for them
    seen: dict[str, int] = {}
    real_holding, real_labels = held_module.holding, lookup.labels

    def holding(*args: Any) -> Any:
        seen["holding"] = threading.get_ident()
        return real_holding(*args)

    async def labels(*args: Any) -> Any:
        seen["loop"] = threading.get_ident()
        return await real_labels(*args)

    monkeypatch.setattr(lexicon_terms, "holding", holding)
    monkeypatch.setattr(lexicon_terms, "labels", labels)
    a_document(client, url, [term("Inhaltsfeld")])

    listed(client, an_editor(url))

    assert set(seen) == {"holding", "loop"}
    assert seen["holding"] != seen["loop"]
