"""The editor's form through the API (plan M1 9.1): every account reads a sector's form - the fields of a
node and of a statement, each list with its active values and their texts; a sector without a profile
has none."""

import pytest
from fastapi.testclient import TestClient

from tests.api.test_documents import an_account, client, url

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents

CV = "https://w3id.org/wlo/curriculum/vocab#"
SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"
LVL = "https://w3id.org/wlo/curriculum/level/"


def test_an_account_reads_a_sector_s_form_with_its_values(client: TestClient, url: str) -> None:
    _, header = an_account(url)

    answer = client.get("/api/v1/profiles/school/form", headers=header)

    assert answer.status_code == 200, answer.text
    form = answer.json()
    assert (form["sector"], form["profile"]) == ("school", SCHOOL + "Terminology")
    node = {field["key"]: field for field in form["node"]}
    assert list(node) == ["original_title", "function", "node_type", "code", "obligation"]
    assert {key: (field["kind"], field["required"], field["many"]) for key, field in node.items()} == {
        "original_title": ("text", True, False),
        "function": ("concept", True, False),
        "node_type": ("concept", False, False),
        "code": ("text", False, False),
        "obligation": ("concept", False, False),
    }
    assert (node["original_title"]["most"], node["original_title"]["values"]) == (2000, None)
    staged = next(
        value for value in node["node_type"]["values"] if value["iri"] == SCHOOL + "Stufenabschnitt"
    )
    assert staged["label"] == "Stufenabschnitt" and staged["broader"] == [CV + "fn_grouping"]
    assert staged["examples"] and staged["definition"] and staged["delimitation"]
    assert set(staged) == {
        "iri", "notation", "label", "alt_labels", "definition", "note", "delimitation", "examples", "broader",
        "group", "dimension",
    }  # fmt: skip
    assert staged["group"] is None  # a profile's node type is of no level system's
    statement = {field["key"]: field for field in form["statement"]}
    assert statement["addressees"]["many"] and len(statement["addressees"]["values"]) == 6
    assert statement["verbatim"]["most"] == 20_000


def test_the_form_names_each_kind_of_value_its_holders_and_fields(client: TestClient, url: str) -> None:
    _, header = an_account(url)

    form = client.get("/api/v1/profiles/school/form", headers=header).json()

    values = form["values"]
    assert {kind: entry["holders"] for kind, entry in values.items()} == {
        "level_assignments": ["node", "statement", "specification"],
        "time_spans": ["node", "specification"],
        "workloads": ["node", "specification"],
    }
    assert {kind: entry["periods"] for kind, entry in values.items()} == {
        "level_assignments": None, "time_spans": None, "workloads": "time_spans",
    }  # fmt: skip
    workload = {field["key"]: field for field in values["workloads"]["fields"]}
    assert {key: (field["kind"], field["required"]) for key, field in workload.items()} == {
        "amount": ("number", True), "amount_to": ("number", False), "unit": ("concept", True),
        "workload_kind": ("concept", False), "is_recommendation": ("boolean", False),
        "minutes_per_unit": ("number", False), "total": ("boolean", False),
    }  # fmt: skip
    assert CV + "unit_lesson" in {value["iri"] for value in workload["unit"]["values"]}
    assert all(value["group"] is None for value in workload["unit"]["values"])
    level = next(field for field in values["level_assignments"]["fields"] if field["key"] == "level")
    eqf = next(value for value in level["values"] if value["iri"] == LVL + "EQF-4")
    assert (
        eqf["group"] == LVL + "EQF"
        and form["groups"][LVL + "EQF"] == "Europäischer Qualifikationsrahmen (EQR)"
    )
    assert {value["group"] for value in level["values"]} <= set(form["groups"])
    assert eqf["dimension"] == CV + "dim_qualification" and workload["unit"]["values"][0]["dimension"] is None
    rules = values["level_assignments"]["rules"]
    assert {"holder": "statement", "dimensions": [CV + "dim_qualification"], "unless": None} in rules
    assert {"holder": "statement", "dimensions": [CV + "dim_conduct", CV + "dim_grading"],
            "unless": CV + "kind_standard"} in rules  # fmt: skip
    assert values["workloads"]["rules"] == []


def test_a_sector_without_a_profile_has_no_form(client: TestClient, url: str) -> None:
    _, header = an_account(url)

    answer = client.get("/api/v1/profiles/kindergarten/form", headers=header)

    assert (answer.status_code, answer.json()["code"]) == (404, "unknown_sector")
    assert client.get("/api/v1/profiles/school/form").status_code == 401
