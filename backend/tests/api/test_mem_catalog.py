"""The catalogue of MEM's plans over the API (app/api/mem.py, plan M2 E11): an admin starts its reading, one
at a time; the redaktion and the admin look it up by Land, subject and title, a page at a time."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.db.migrate import migrate
from app.sources.mem.catalog import KIND
from app.sources.mem.sparql import KMK_GRAPH
from app.vocab.store import load_vocabulary
from tests.support import make_settings, ontology_vocabulary, seed_account, selector_client

pytestmark = pytest.mark.pg

PUBLIC = "http://testserver:8000"
LP = "https://w3id.org/lehrplan/ontology/"
RLP, SAX = LP + "LP_3000046", LP + "LP_3000047"
RP_GRAPH = "https://w3id.org/lehrplan/rp"


@pytest.fixture
def migrated(database_url: str) -> str:
    migrate(database_url)
    return database_url


@pytest.fixture
def client(migrated: str, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=migrated, storage_dir=tmp_path))
    with selector_client(app, base_url=PUBLIC) as test_client:
        yield test_client


def header(url: str, role: str) -> dict[str, str]:
    return seed_account(url, f"Konto {role}", [role])[1]


def add_plans(url: str, *plans: tuple[str, str | None, str, list[str]], graph: str = RP_GRAPH) -> None:
    with psycopg.connect(url) as connection:
        for name, land, title, subjects in plans:
            connection.execute(
                "INSERT INTO mem_plan (iri, graph, land_iri, title, class_iri, subjects, attribution)"
                " VALUES (%s, %s, %s, %s, %s, %s, 'MEM-Schule')",
                (f"https://w3id.org/p/{name}", graph, land, title, LP + "LP_0000438", subjects),
            )


def test_an_admin_starts_the_catalogue_as_a_job_and_it_is_audited(client: TestClient, migrated: str) -> None:
    account, admin = seed_account(migrated, "Admin", ["admin"])

    answer = client.post("/api/v1/mem/catalog", headers=admin)

    assert answer.status_code == 202
    job_id = UUID(answer.json()["job_id"])
    with psycopg.connect(migrated) as connection:
        jobs = connection.execute("SELECT id, kind, status FROM job").fetchall()
        audited = connection.execute(
            "SELECT actor_id, action, subject FROM audit_log WHERE action = %s", (KIND,)
        ).fetchall()
    assert jobs == [(job_id, KIND, "queued")]
    assert audited == [(account, KIND, f"job:{job_id}")]


def test_a_second_start_while_one_waits_names_the_one_to_follow(client: TestClient, migrated: str) -> None:
    admin = header(migrated, "admin")
    first = client.post("/api/v1/mem/catalog", headers=admin).json()["job_id"]

    again = client.post("/api/v1/mem/catalog", headers=admin)

    assert again.status_code == 409
    assert (again.json()["code"], again.json()["details"]["job_id"]) == ("catalog_running", first)


@pytest.mark.parametrize("role", ["redaktion", "nutzer"])
def test_only_an_admin_starts_the_catalogue(client: TestClient, migrated: str, role: str) -> None:
    assert client.post("/api/v1/mem/catalog", headers=header(migrated, role)).status_code == 403


@pytest.mark.parametrize("role", ["admin", "redaktion"])
def test_the_redaktion_and_the_admin_look_the_catalogue_up(
    client: TestClient, migrated: str, role: str
) -> None:
    add_plans(migrated, ("a", RLP, "Deutsch 5-6", ["https://w3id.org/s/de"]))

    answer = client.get("/api/v1/mem/plans", headers=header(migrated, role))

    assert answer.status_code == 200
    body = answer.json()
    assert body["total"] == 1
    plan = body["plans"][0]
    assert (plan["iri"], plan["title"], plan["land_iri"], plan["subjects"]) == (
        "https://w3id.org/p/a",
        "Deutsch 5-6",
        RLP,
        ["https://w3id.org/s/de"],
    )
    assert plan["read_at"]  # how old the catalogue's word on the plan is


def test_a_user_does_not_look_the_catalogue_up(client: TestClient, migrated: str) -> None:
    assert client.get("/api/v1/mem/plans", headers=header(migrated, "nutzer")).status_code == 403


def test_an_empty_catalogue_is_an_empty_page(client: TestClient, migrated: str) -> None:
    answer = client.get("/api/v1/mem/plans", headers=header(migrated, "redaktion"))

    assert answer.json() == {"plans": [], "total": 0, "catalog_read_at": None}  # never read


@pytest.mark.parametrize(
    ("query", "titles", "total"),
    [
        ({"land": RLP}, ["Deutsch 5-6", "Mathematik"], 2),
        ({"subject": "https://w3id.org/s/de"}, ["Deutsch", "Deutsch 5-6"], 2),
        ({"title": "deutsch", "land": SAX}, ["Deutsch"], 1),
        ({"limit": 1, "offset": 1}, ["Deutsch 5-6"], 3),
    ],
    ids=["land", "subject", "title-and-land", "page"],
)
def test_the_catalogue_is_filtered_and_paged(
    client: TestClient, migrated: str, query: dict[str, Any], titles: list[str], total: int
) -> None:
    add_plans(
        migrated,
        ("a", RLP, "Deutsch 5-6", ["https://w3id.org/s/de"]),
        ("b", RLP, "Mathematik", ["https://w3id.org/s/ma"]),
        ("c", SAX, "Deutsch", ["https://w3id.org/s/de"]),
    )

    answer = client.get("/api/v1/mem/plans", params=query, headers=header(migrated, "redaktion"))

    assert [plan["title"] for plan in answer.json()["plans"]] == titles
    assert answer.json()["total"] == total


@pytest.mark.parametrize(
    "query",
    [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"title": "x" * 201}, {"land": "x" * 2001},
     # a NUL is no text the database keeps: refused at the door, not a 500 at the query (audit A)
     {"title": "a" + chr(0)}, {"land": "https://a" + chr(0)}, {"subject": "https://a" + chr(0)},
     {"region": "D" + chr(0)}, {"region": "de-sn"}],
    ids=["limit-zero", "limit-past", "offset", "title", "land", "nul-title", "nul-land", "nul-subject",
         "nul-region", "region-form"],
)  # fmt: skip
def test_a_lookup_out_of_bounds_is_refused(client: TestClient, migrated: str, query: dict[str, Any]) -> None:
    answer = client.get("/api/v1/mem/plans", params=query, headers=header(migrated, "redaktion"))

    assert answer.status_code == 422


@pytest.fixture
def vocabulary(migrated: str) -> str:
    load_vocabulary(migrated, ontology_vocabulary())
    return migrated


def a_catalogue(url: str) -> None:
    add_plans(
        url,
        ("a", RLP, "Deutsch 5-6", []),
        ("c", SAX, "Deutsch", []),
        ("x", LP + "LP_9999999", "Fremd", []),
        ("n", None, "Ohne Land", []),
    )
    add_plans(url, ("k", None, "Bildungsstandards Deutsch", []), graph=KMK_GRAPH)


def test_a_catalogue_says_when_it_was_last_read_whatever_the_filter_finds(
    client: TestClient, vocabulary: str
) -> None:
    a_catalogue(vocabulary)
    with psycopg.connect(vocabulary) as connection:
        connection.execute("UPDATE mem_plan SET read_at = '2026-11-01T10:00Z' WHERE iri LIKE '%%/a'")
        connection.execute("UPDATE mem_plan SET read_at = '2026-11-02T10:00Z' WHERE iri NOT LIKE '%%/a'")

    answer = client.get(
        "/api/v1/mem/plans", params={"title": "nichts"}, headers=header(vocabulary, "redaktion")
    )

    assert answer.json()["total"] == 0
    assert answer.json()["catalog_read_at"].startswith("2026-11-02T10:00")


def test_a_plan_names_its_land_s_region_the_kmk_s_all_of_germany(client: TestClient, vocabulary: str) -> None:
    a_catalogue(vocabulary)

    answer = client.get("/api/v1/mem/plans", headers=header(vocabulary, "redaktion"))

    assert {plan["title"]: plan["region"] for plan in answer.json()["plans"]} == {
        "Bildungsstandards Deutsch": "DE", "Deutsch": "DE-SN", "Deutsch 5-6": "DE-RP", "Fremd": None,
        "Ohne Land": None,
    }  # fmt: skip


@pytest.mark.parametrize(
    ("region", "titles"),
    [("DE-SN", ["Deutsch"]), ("DE-RP", ["Deutsch 5-6"]), ("DE", ["Bildungsstandards Deutsch"])],
)
def test_the_catalogue_is_filtered_by_region(
    client: TestClient, vocabulary: str, region: str, titles: list[str]
) -> None:
    a_catalogue(vocabulary)

    answer = client.get(
        "/api/v1/mem/plans", params={"region": region}, headers=header(vocabulary, "redaktion")
    )

    assert [plan["title"] for plan in answer.json()["plans"]] == titles


def test_a_region_the_vocabulary_does_not_know_is_refused(client: TestClient, vocabulary: str) -> None:
    answer = client.get(
        "/api/v1/mem/plans", params={"region": "DE-XX"}, headers=header(vocabulary, "redaktion")
    )

    assert (answer.status_code, answer.json()["code"]) == (422, "unknown_region")
