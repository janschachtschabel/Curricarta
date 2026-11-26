"""A node's placements through the API (plan M3a K; app/api/placements.py): set as the node's whole on its
revision and read with the tree - beside the document's specifications and variants they may be in -, the time
spans and workloads of one set as a whole on its revision - by the document's owner and the editors, audited
by counts alone; refused with the placement's path and why, with the node as it stands for a stale revision,
and to a stranger as no node or placement at all."""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.api.test_document_tree import a_document, tree
from tests.api.test_documents import an_account, client, hidden_from_its_owner, rows, url
from tests.db.l1 import CV, add_node, add_specification, add_variant

pytestmark = pytest.mark.pg
__all__ = ["client", "url"]  # the fixtures, shared with test_documents

BINDING, ELECTIVE = CV + "obl_binding", CV + "obl_elective"
SEMESTER = {"time_kind": CV + "time_semester", "span_from": 3}
CREDITS = {"amount": 5, "unit": CV + "unit_ectsCredit"}
LEVEL = "https://w3id.org/wlo/curriculum/level/EQF-4"


def made(url: str, document: str) -> dict[str, str]:
    """A module and an area of the document, its specification and a variant of it."""
    with psycopg.connect(url, autocommit=True) as connection:
        specification = add_specification(connection, uuid.UUID(document), key="ba", title="Bachelor")
        variant = add_variant(connection, specification)
        module = add_node(connection, uuid.UUID(document), code="M 1", original_title="Analysis")
        area = add_node(
            connection, uuid.UUID(document), position=2, code="B", original_title="Pflichtbereich"
        )
    return {
        "specification": str(specification),
        "variant": str(variant),
        "module": str(module),
        "area": str(area),
    }


def placements(revision: int, *entries: dict[str, Any]) -> dict[str, Any]:
    return {"expected_revision": revision, "placements": list(entries)}


def values(revision: int, **kinds: list[dict[str, Any]]) -> dict[str, Any]:
    return {"expected_revision": revision, "level_assignments": [], "time_spans": [], "workloads": []} | kinds


def test_a_node_s_placements_are_set_read_with_the_tree_and_their_values_set(
    client: TestClient, url: str
) -> None:
    document, owner = a_document(client, url)
    held = made(url, document)
    _, editor = an_account(url, "Redaktion", ("redaktion",))
    path = f"/api/v1/nodes/{held['module']}/placements"

    set_ = client.put(path, headers=owner, json=placements(
        1,
        {"specification_id": held["specification"], "in_node_id": held["area"], "obligation": BINDING,
         "grade_weight": 1.5},
        {"variant_id": held["variant"], "obligation": ELECTIVE},
    ))  # fmt: skip
    assert set_.status_code == 200, set_.text
    first, second = set_.json()["placements"]
    stale = client.put(path, headers=owner, json=placements(1))
    with_values = client.put(f"/api/v1/placements/{first['id']}/values", headers=editor,
                             json=values(1, time_spans=[SEMESTER], workloads=[CREDITS]))  # fmt: skip
    kept_entry = {"id": second["id"], "variant_id": held["variant"], "obligation": ELECTIVE}
    on_old_view = client.put(path, headers=editor, json=placements(2, kept_entry))
    # the values' set counted the node's revision too, and says it: the node's set goes on from there
    kept = client.put(path, headers=editor, json=placements(with_values.json()["node_revision"], kept_entry))

    assert set_.json()["revision"] == 2
    assert (first["specification_id"], first["in_node_id"], first["obligation"], first["grade_weight"]) == (
        held["specification"], held["area"], BINDING, 1.5,
    )  # fmt: skip
    assert (second["variant_id"], second["specification_id"], second["position"]) == (
        held["variant"],
        None,
        2,
    )
    assert (first["origin"], first["review_status"], first["revision"], first["iri"]) == (
        CV + "orig_human", CV + "rev_proposed", 1, None,
    )  # fmt: skip
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_revision")
    assert stale.json()["details"]["current"]["revision"] == 2
    assert with_values.status_code == 200, with_values.text
    assert (with_values.json()["revision"], with_values.json()["node_revision"]) == (2, 3)
    assert (on_old_view.status_code, on_old_view.json()["code"]) == (409, "stale_revision")
    assert [span["time_kind"] for span in with_values.json()["values"]["time_spans"]] == [
        CV + "time_semester"
    ]
    assert kept.status_code == 200, kept.text
    read = tree(client, document, owner)
    nodes = {node["id"]: node for node in read["nodes"]}
    assert read["specifications"] == [
        {
            "id": held["specification"],
            "title": "Bachelor",
            "variants": [{"id": held["variant"], "label": "Gymnasium"}],
        }
    ]
    assert [(each["id"], each["position"]) for each in nodes[held["module"]]["placements"]] == [
        (second["id"], 1)
    ]
    assert nodes[held["area"]]["placements"] == []
    audited = "SELECT action, details FROM audit_log WHERE action LIKE '%%placement%%' ORDER BY id"
    assert rows(url, audited) == [
        ("node.placements", {"document": document, "revision": 2, "placements": 2}),
        ("placement.values", {"document": document, "revision": 2, "level_assignments": 0, "time_spans": 1,
                              "workloads": 1, "periods": 0}),
        ("node.placements", {"document": document, "revision": 4, "placements": 1}),
    ]  # fmt: skip


def test_a_placement_the_store_does_not_take_is_refused_at_its_path(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    held = made(url, document)
    path = f"/api/v1/nodes/{held['module']}/placements"
    entry = {"specification_id": held["specification"], "obligation": BINDING}
    module = client.put(path, headers=owner, json=placements(1, entry))
    placement = module.json()["placements"][0]["id"]

    refused = [
        client.put(path, headers=owner, json=placements(2, {"obligation": BINDING})),
        client.put(path, headers=owner, json=placements(2, {"specification_id": held["specification"],
                                                            "obligation": CV + "form_formal"})),
        client.put(path, headers=owner, json=placements(2, entry | {"in_node_id": held["module"]})),
        client.put(path, headers=owner, json=placements(2, {"id": str(uuid.uuid4()),
                                                            "specification_id": held["specification"],
                                                            "obligation": BINDING})),
        client.put(f"/api/v1/placements/{placement}/values", headers=owner,
                   json=values(1, level_assignments=[{"level": LEVEL}])),
    ]  # fmt: skip
    negative = client.put(path, headers=owner, json=placements(2, entry | {"grade_weight": -2.5}))

    assert [(answer.status_code, answer.json()["details"]) for answer in refused] == [
        (422, {"field": "placements[0].specification_id", "problem": "required"}),
        (422, {"field": "placements[0].obligation", "problem": "not_offered"}),
        (422, {"field": "placements[0].in_node_id", "problem": "not_offered"}),
        (422, {"field": "placements[0]", "problem": "unknown_value"}),
        (422, {"field": "level_assignments", "problem": "not_held"}),
    ]
    assert negative.status_code == 422
    assert "-2.5" not in negative.text  # a refusal names no input
    assert rows(url, "SELECT count(*), max(revision) FROM placement") == [(1, 1)]


def test_a_node_s_placements_are_none_to_a_stranger_and_hidden_content_is_refused(
    client: TestClient, url: str
) -> None:
    document, owner = a_document(client, url)
    held = made(url, document)
    path = f"/api/v1/nodes/{held['module']}/placements"
    entry = {"specification_id": held["specification"], "obligation": BINDING}
    placement = client.put(path, headers=owner, json=placements(1, entry)).json()["placements"][0]["id"]
    _, stranger = an_account(url, "Fremd")

    answers = [
        client.put(path, headers=stranger, json=placements(2)),
        client.put(f"/api/v1/placements/{placement}/values", headers=stranger, json=values(1)),
        client.put(f"/api/v1/placements/{uuid.uuid4()}/values", headers=owner, json=values(1)),
    ]
    hidden_from_its_owner(url, document)
    hidden = [
        client.put(path, headers=owner, json=placements(2)),
        client.put(f"/api/v1/placements/{placement}/values", headers=owner, json=values(1)),
    ]

    assert [(answer.status_code, answer.json()["code"]) for answer in answers] == [
        (404, "no_node"), (404, "no_placement"), (404, "no_placement"),
    ]  # fmt: skip
    assert [(answer.status_code, answer.json()["code"]) for answer in hidden] == [(403, "file_hidden")] * 2
    assert rows(url, "SELECT count(*), max(revision) FROM placement") == [(1, 1)]


def test_a_frozen_document_s_placements_are_read_only(client: TestClient, url: str) -> None:
    document, owner = a_document(client, url)
    held = made(url, document)
    path = f"/api/v1/nodes/{held['module']}/placements"
    entry = {"specification_id": held["specification"], "obligation": BINDING}
    placement = client.put(path, headers=owner, json=placements(1, entry)).json()["placements"][0]["id"]
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "UPDATE document SET iri = 'https://example.org/curriculum/1', frozen_at = now() WHERE id = %s",
            (document,),
        )

    refused = [
        client.put(path, headers=owner, json=placements(2)),
        client.put(
            f"/api/v1/placements/{placement}/values", headers=owner, json=values(1, time_spans=[SEMESTER])
        ),
    ]

    assert [(answer.status_code, answer.json()["code"]) for answer in refused] == [(409, "frozen")] * 2
