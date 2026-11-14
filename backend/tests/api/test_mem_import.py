"""A MEM-Schule plan imported into a document of a finished conversion (app/api/mem.py, Teilplan M2-5c): the
redaktion and the admins import a plan of the catalogue into a new document of an entry's finished
conversion - in the school sector, the plan's Land its region, typed and with its specification - and its
job waits; a plan the catalogue does not hold, a conversion not finished or of another file, a plan the
conversion took already are refused. The document an import made is not extracted or repaired, its tree is
the plan's."""

import threading
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import mem as mem_route
from app.api.app import create_app
from app.pipeline.extraction import unique_key
from tests.api.test_document_tree import a_document
from tests.api.test_document_units import a_run
from tests.api.test_documents import PUBLIC, a_conversion, an_account, asked, client, end_job, rows, url
from tests.api.test_node_editing import a_node
from tests.api.test_sources_edit import until_waiting
from tests.api.test_statement_editing import a_statement
from tests.db.l1 import add_entity
from tests.support import lock_held, make_settings, selector_client

pytestmark = pytest.mark.pg

__all__ = ["client", "url"]  # the fixtures, shared with test_documents

LP = "https://w3id.org/lehrplan/ontology/"
SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"
PLAN_IRI = "https://w3id.org/lehrplan/instances/rp/resource/lehrplan-134-1"
KMK_IRI = "https://w3id.org/lehrplan/instances/bista/resource/bildungsstandard-1"
RP_GRAPH, KMK_GRAPH = "https://w3id.org/lehrplan/rp", "https://w3id.org/lehrplan/graph/bista"


def imported(url: str, document: str) -> None:
    """The document as one an import made: it names its plan."""
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("UPDATE document SET mem_iri = %s WHERE id = %s", (PLAN_IRI, document))


def add_plan(
    url: str,
    iri: str = PLAN_IRI,
    *,
    graph: str = RP_GRAPH,
    land: str | None = LP + "LP_3000046",
    title: str = "Informatik 5-6",
    klass: str = LP + "LP_0000438",
) -> None:
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO mem_plan (iri, graph, land_iri, title, class_iri, subjects, licence, attribution)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'CC BY-SA 4.0', 'MEM-Schule')",
            (iri, graph, land, title, klass, ["https://w3id.org/schulfach/RP_1"]),
        )


def an_entry(url: str, name: str = "Lehrkraft", digest: bytes = b"\x01" * 32) -> dict[str, UUID]:
    """An account's entry with its file's finished conversion: what an editor imports into."""
    owner, _ = an_account(url, name)
    return a_conversion(url, owner, digest)


def ask(client: TestClient, header: dict[str, str], made: dict[str, UUID], plan: str = PLAN_IRI) -> Any:
    return client.post(
        f"/api/v1/sources/{made['source']}/mem-import",
        headers=header,
        json={"plan_iri": plan, "conversion_id": str(made["conversion"])},
    )


def counts(url: str) -> tuple[Any, ...]:
    return rows(url, "SELECT (SELECT count(*) FROM document), (SELECT count(*) FROM job)")[0]


@pytest.mark.parametrize("role", ["redaktion", "admin"])
def test_the_redaktion_imports_a_plan_into_a_new_document_and_its_job_waits(
    client: TestClient, url: str, role: str
) -> None:
    add_plan(url)
    made = an_entry(url)
    editor, header = an_account(url, "Redaktion", (role,))

    answer = ask(client, header, made)

    assert answer.status_code == 202, answer.text
    document, job = answer.json()["document"], answer.json()["job"]
    assert (document["title"], document["sector"], document["regions"], document["document_type_iri"]) == (
        "Informatik 5-6", "school", ["DE-RP"], SCHOOL + "dt-Lehrplan",
    )  # fmt: skip
    # where it came from, as the page names it (plan M2-8, A1)
    origin = {"plan_iri": PLAN_IRI, "attribution": "MEM-Schule", "licence": "CC BY-SA 4.0"}
    assert document["mem"] == origin
    assert client.get(f"/api/v1/documents/{document['id']}", headers=header).json()["mem"] == origin
    listed = client.get("/api/v1/documents", params={"source_id": str(made["source"])}, headers=header).json()
    assert [each["mem"] for each in listed] == [origin]
    assert (document["own"], document["source_id"], document["conversion_id"]) == (
        True, str(made["source"]), str(made["conversion"]),
    )  # fmt: skip
    assert (job["kind"], job["status"]) == ("extract.mem_import", "queued")
    assert rows(url, "SELECT lane, payload, unique_key FROM job WHERE id = %s", job["id"]) == [
        (str(editor), {"document_id": document["id"]}, unique_key(UUID(document["id"])))
    ]
    assert rows(url, "SELECT mem_iri, mem_attribution FROM document WHERE id = %s", document["id"]) == [
        (PLAN_IRI, "MEM-Schule")
    ]
    assert rows(
        url, "SELECT key, spec_kind, title FROM specification WHERE document_id = %s", document["id"]
    ) == [("S1", "curriculum", "Informatik 5-6")]
    [(action, subject, details)] = rows(
        url, "SELECT action, subject, details FROM audit_log WHERE action = 'document.mem_import'"
    )
    assert (action, subject) == ("document.mem_import", f"document:{document['id']}")
    assert details == {
        "source": str(made["source"]), "conversion": str(made["conversion"]), "plan": PLAN_IRI,
        "job": job["id"], "restart": False, "regions": ["DE-RP"],
    }  # fmt: skip


def test_a_plan_of_the_standards_is_a_framework_for_all_of_germany(client: TestClient, url: str) -> None:
    # land:DE is the KMK's: a cue scoped to it applies to the document (plan M2-7)
    add_plan(
        url,
        KMK_IRI,
        graph=KMK_GRAPH,
        land=None,
        title="Bildungsstandards Mathematik",
        klass=LP + "LP_0000571",
    )
    _, header = an_account(url, "Redaktion", ("redaktion",))

    answer = ask(client, header, an_entry(url), KMK_IRI)

    assert answer.status_code == 202, answer.text
    document = answer.json()["document"]
    assert (document["regions"], document["document_type_iri"]) == (["DE"], SCHOOL + "dt-Bildungsstandards")
    assert rows(url, "SELECT spec_kind FROM specification WHERE document_id = %s", document["id"]) == [
        ("competencyFramework",)
    ]
    [(details,)] = rows(url, "SELECT details FROM audit_log WHERE action = 'document.mem_import'")
    assert details["regions"] == ["DE"]


def test_a_title_longer_than_a_document_s_is_cut_to_it(client: TestClient, url: str) -> None:
    add_plan(url, title="T" * 1500)
    _, header = an_account(url, "Redaktion", ("redaktion",))

    answer = ask(client, header, an_entry(url))

    assert answer.status_code == 202, answer.text
    assert answer.json()["document"]["title"] == "T" * 1000
    assert rows(url, "SELECT length(title) FROM specification") == [(1000,)]


def test_a_user_imports_nothing(client: TestClient, url: str) -> None:
    add_plan(url)
    made = an_entry(url)
    _, header = an_account(url, "Nutzer")
    before = counts(url)

    answer = ask(client, header, made)

    assert answer.status_code == 403
    assert counts(url) == before


def test_a_plan_the_catalogue_does_not_hold_is_refused(client: TestClient, url: str) -> None:
    made = an_entry(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    before = counts(url)

    answer = ask(client, header, made)

    assert (answer.status_code, answer.json()["code"]) == (422, "mem_unknown_plan")
    assert counts(url) == before


@pytest.mark.parametrize("case", ["no-entry", "another-file", "not-finished"])
def test_an_import_without_a_finished_conversion_of_the_entry_is_refused(
    client: TestClient, url: str, case: str
) -> None:
    add_plan(url)
    made, other = an_entry(url), an_entry(url, "Andere", b"\x02" * 32)
    if case == "no-entry":
        made = {**made, "source": UUID(int=1)}
    elif case == "another-file":
        made = {**made, "conversion": other["conversion"]}
    else:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(
                "UPDATE conversion SET status = 'pending', finished_at = NULL, pages = NULL WHERE id = %s",
                (made["conversion"],),
            )
    _, header = an_account(url, "Redaktion", ("redaktion",))
    before = counts(url)

    answer = ask(client, header, made)

    assert (answer.status_code, answer.json()["code"]) == (404, "mem_no_conversion")
    assert counts(url) == before


@pytest.mark.parametrize(
    "body",
    [{"plan_iri": PLAN_IRI}, {"plan_iri": "h" * 2001, "conversion_id": str(UUID(int=1))},
     {"plan_iri": PLAN_IRI, "conversion_id": str(UUID(int=1)), "sector": "school"},
     {"plan_iri": PLAN_IRI + chr(0), "conversion_id": str(UUID(int=1))}],
    ids=["no-conversion", "long-iri", "extra-key", "nul-iri"],
)  # fmt: skip
def test_a_body_out_of_form_is_refused(client: TestClient, url: str, body: dict[str, str]) -> None:
    _, header = an_account(url, "Redaktion", ("redaktion",))

    answer = client.post(f"/api/v1/sources/{UUID(int=1)}/mem-import", headers=header, json=body)

    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")


def test_a_second_import_beside_its_waiting_job_is_taken(client: TestClient, url: str) -> None:
    add_plan(url)
    made = an_entry(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    first = ask(client, header, made).json()

    again = ask(client, header, made)

    assert (again.status_code, again.json()["code"], again.json()["details"]) == (
        409, "mem_plan_taken", {"document_id": first["document"]["id"]},
    )  # fmt: skip
    assert counts(url) == (1, 1)


def test_an_import_whose_job_failed_before_im_is_started_again_on_its_document(
    client: TestClient, url: str
) -> None:
    add_plan(url)
    made = an_entry(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    first = ask(client, header, made).json()
    end_job(url, first["job"]["id"], "failed")

    again = ask(client, header, made)

    assert again.status_code == 202, again.text
    document, job = again.json()["document"], again.json()["job"]
    assert document["id"] == first["document"]["id"] and job["id"] != first["job"]["id"]
    assert (job["kind"], job["status"]) == ("extract.mem_import", "queued")
    assert rows(url, "SELECT unique_key FROM job WHERE id = %s", job["id"]) == [
        (unique_key(UUID(document["id"])),)
    ]
    assert counts(url) == (1, 2)
    assert rows(url, "SELECT count(*) FROM specification") == [(1,)]
    assert [(details["restart"], details["regions"]) for (details,) in rows(
        url, "SELECT details FROM audit_log WHERE action = 'document.mem_import' ORDER BY id"
    )] == [(False, ["DE-RP"]), (True, ["DE-RP"])]  # fmt: skip


def test_another_editor_s_restart_goes_in_the_owner_s_lane(client: TestClient, url: str) -> None:
    add_plan(url)
    made = an_entry(url)
    owner, header = an_account(url, "Redaktion", ("redaktion",))
    _, other = an_account(url, "Admin", ("admin",))
    first = ask(client, header, made).json()
    end_job(url, first["job"]["id"], "failed")

    again = ask(client, other, made)

    assert again.status_code == 202, again.text
    assert again.json()["document"]["own"] is False
    assert rows(url, "SELECT lane FROM job WHERE id = %s", again.json()["job"]["id"]) == [(str(owner),)]


def test_an_import_done_is_taken(client: TestClient, url: str) -> None:
    add_plan(url)
    made = an_entry(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    first = ask(client, header, made).json()
    end_job(url, first["job"]["id"], "failed")  # its X5 failed, its tree is written
    a_run(url, first["document"]["id"], "IM")

    again = ask(client, header, made)

    assert (again.status_code, again.json()["code"], again.json()["details"]) == (
        409, "mem_plan_taken", {"document_id": first["document"]["id"]},
    )  # fmt: skip
    assert counts(url) == (1, 1)


def test_a_plan_another_entry_of_the_file_took_is_taken_not_started_again(
    client: TestClient, url: str
) -> None:
    # the index holds one import of a plan per conversion: an entry of the same file shares it
    add_plan(url)
    made = an_entry(url)
    with psycopg.connect(url, autocommit=True) as connection:
        source = add_entity(connection, "source")
        connection.execute(
            "INSERT INTO source (id, owner_id, provenance, register_status, file_id, file_name, mime)"
            " SELECT %s, owner_id, 'upload', 'acquired', file_id, 'kopie.pdf', mime FROM source"
            " WHERE id = %s",
            (source, made["source"]),
        )
    _, header = an_account(url, "Redaktion", ("redaktion",))
    first = ask(client, header, made).json()
    end_job(url, first["job"]["id"], "failed")

    again = ask(client, header, {**made, "source": source})

    assert (again.status_code, again.json()["code"], again.json()["details"]) == (
        409, "mem_plan_taken", {"document_id": first["document"]["id"]},
    )  # fmt: skip
    assert counts(url) == (1, 1)


def test_an_import_waiting_leaves_its_editor_s_extraction_of_the_entry_to_be_made(
    client: TestClient, url: str
) -> None:
    # an import is no extraction being run: a document asked of the same conversion is made beside it
    add_plan(url)
    made = an_entry(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    imported_one = ask(client, header, made).json()["document"]["id"]

    answer = client.post("/api/v1/documents", headers=header, json=asked(made))

    assert answer.status_code == 202, answer.text
    assert answer.json()["made"] is True and answer.json()["document"]["id"] != imported_one
    assert answer.json()["job"]["kind"] == "extract.run"


def send_at_once(url: str, store: Path, lock: str, requests: int, send: Any) -> list[Any]:
    """``send(client)`` from ``requests`` threads, each with an app of its own, while another session holds
    ``lock``: all of them come to wait for it, then go."""
    answers: list[Any] = []

    def sending() -> None:
        app = create_app(make_settings(database_url=url, storage_dir=store))
        with selector_client(app, base_url=PUBLIC) as client:
            answers.append(send(client))

    threads = [threading.Thread(target=sending) for _ in range(requests)]
    with lock_held(url, lock, at_most_s=30):
        for thread in threads:
            thread.start()
        until_waiting(url, requests)
    for thread in threads:
        thread.join(30)
    return sorted(answers, key=lambda answer: answer.status_code)


def test_two_restarts_at_once_start_one_job(client: TestClient, url: str, tmp_path: Path) -> None:
    add_plan(url)
    made = an_entry(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    first = ask(client, header, made).json()
    document = first["document"]["id"]
    end_job(url, first["job"]["id"], "failed")

    # both find the document and wait for its tree, as every start of a job of it does
    answers = send_at_once(
        url, tmp_path, f"SELECT lock_node_tree('{UUID(document)}')", 2, lambda sent: ask(sent, header, made)
    )

    assert [answer.status_code for answer in answers] == [202, 409]
    assert (answers[1].json()["code"], answers[1].json()["details"]) == (
        "mem_plan_taken",
        {"document_id": document},
    )
    assert rows(url, "SELECT status, count(*) FROM job GROUP BY status ORDER BY status") == [
        ("failed", 1), ("queued", 1),
    ]  # fmt: skip


def test_two_imports_at_once_make_one_document(url: str, tmp_path: Path) -> None:
    add_plan(url)
    made = an_entry(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))

    # both come to wait for the entry, as making a document reads it (app/db/documents.py)
    entry = f"SELECT 1 FROM source WHERE id = '{UUID(str(made['source']))}' FOR UPDATE"  # noqa: S608 - a UUID
    by_status = send_at_once(url, tmp_path, entry, 2, lambda sent: ask(sent, header, made))

    assert [answer.status_code for answer in by_status] == [202, 409]
    assert (by_status[1].json()["code"], by_status[1].json()["details"]) == (
        "mem_plan_taken", {"document_id": by_status[0].json()["document"]["id"]},
    )  # fmt: skip
    assert counts(url) == (1, 1)
    assert rows(url, "SELECT count(*) FROM specification") == [(1,)]


def tree_of(client: TestClient, document: str, header: dict[str, str]) -> Any:
    answer = client.get(f"/api/v1/documents/{document}/tree", headers=header)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_an_import_is_closed_while_its_job_runs_and_edited_once_im_and_x5_are_done(
    client: TestClient, url: str
) -> None:
    add_plan(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    started = ask(client, header, an_entry(url)).json()
    document = started["document"]["id"]
    node = a_node(url, document)  # as the job's run IM writes it
    change = {"expected_revision": 1, "fields": {"code": "2"}}

    waiting = tree_of(client, document, header)
    refused = client.patch(f"/api/v1/nodes/{node}", headers=header, json=change)
    end_job(url, started["job"]["id"], "failed")  # before its run IM was done
    unwritten = tree_of(client, document, header)
    for stage in ("IM", "X5"):
        a_run(url, document, stage)
    written = tree_of(client, document, header)
    edited = client.patch(f"/api/v1/nodes/{node}", headers=header, json=change)

    assert (waiting["closed"], waiting["editable"]) == ("job_open", False)
    assert (refused.status_code, refused.json()["code"]) == (409, "job_open")
    assert unwritten["closed"] == "not_extracted"
    assert (written["closed"], written["editable"], written["reviewable"]) == (None, True, True)
    assert edited.status_code == 200, edited.text


def test_an_import_is_frozen_with_its_work_issuer_and_edition(url: str, tmp_path: Path) -> None:
    app = create_app(
        make_settings(database_url=url, storage_dir=tmp_path, iri_base="https://example.org/kk/")
    )
    add_plan(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    with selector_client(app, base_url=PUBLIC) as client:
        started = ask(client, header, an_entry(url)).json()
        document = started["document"]["id"]
        end_job(url, started["job"]["id"], "done")
        a_statement(url, document, a_node(url, document, code="1"))
        for stage in ("IM", "X5"):
            a_run(url, document, stage)
        work = {"title": "Lehrplan Informatik", "region": "DE-RP", "short_title": "lp-informatik"}
        assert (
            client.patch(f"/api/v1/documents/{document}/work", headers=header, json=work).status_code == 200
        )
        metadata = {"issuer": "Ministerium", "edition": "2024"}
        assert client.patch(f"/api/v1/documents/{document}", headers=header, json=metadata).status_code == 200
        a_run(url, document, "X5")  # checked after the edits, as a freeze asks

        answer = client.post(f"/api/v1/documents/{document}/freeze", headers=header, json={})

    assert answer.status_code == 200, answer.text
    assert rows(url, "SELECT frozen_at IS NOT NULL, mem_iri FROM document WHERE id = %s", document) == [
        (True, PLAN_IRI)
    ]


def test_an_imported_document_is_neither_extracted_nor_repaired(client: TestClient, url: str) -> None:
    document, header = a_document(client, url, extracted=False)
    imported(url, document)
    jobs = rows(url, "SELECT count(*) FROM job")

    starts = {kind: client.post(f"/api/v1/documents/{document}/{kind}", headers=header) for kind in
              ("extraction", "repair")}  # fmt: skip

    assert {kind: (answer.status_code, answer.json()["code"]) for kind, answer in starts.items()} == {
        "extraction": (409, "not_extractable"),
        "repair": (409, "not_extractable"),
    }
    assert rows(url, "SELECT count(*) FROM job") == jobs


def test_the_import_s_refusals_are_in_the_spec(client: TestClient) -> None:
    responses = client.get("/openapi.json").json()["paths"]["/api/v1/sources/{source_id}/mem-import"]["post"][
        "responses"
    ]

    assert {"202", "404", "409", "422", "503"} <= set(responses)
    assert "mem_unknown_plan" in responses["422"]["description"]
    assert "validation_failed" in responses["422"]["description"]


def test_a_plan_taken_by_a_document_gone_meanwhile_is_tried_again(
    client: TestClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_plan(url)
    made = an_entry(url)
    _, header = an_account(url, "Redaktion", ("redaktion",))
    assert ask(client, header, made).status_code == 202

    async def gone(*_: Any) -> None:
        return None

    monkeypatch.setattr(mem_route, "imported_document", gone)
    again = ask(client, header, made)

    assert (again.status_code, again.json()["code"]) == (503, "service_unavailable")
    assert again.headers["retry-after"]
