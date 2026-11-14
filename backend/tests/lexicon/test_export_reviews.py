"""``python -m app.lexicon.export_reviews``: the editors' decisions as the research's importer reads them
back into the files (plan M1 10.3, 10.4; 10c C8, 10d D7) - every decision on a research cue, a retired cue's
too, by its cue, with what was judged; every new cue taken from a document's terms, without the document;
never who or when; the same decisions give the same bytes."""

import json
import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app.db.cue_review import decide, research_cues
from app.db.term_review import Choice, Judged, decide_term
from tests.db.test_nodes import url
from tests.support import without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["url"]  # the database with the vocabularies of the ontology, shared with test_nodes

BACKEND = Path(__file__).resolve().parents[2]
CV = "https://w3id.org/wlo/curriculum/vocab#"
SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"


def export(database_url: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "app.lexicon.export_reviews"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


async def two_decisions(url: str) -> tuple[str, str]:
    """A confirmed cue and a rejected one whose cue a release retired since."""
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
        account = uuid.uuid4()
        await connection.execute("INSERT INTO account (id, name) VALUES (%s, 'Redaktion Geheim')", (account,))
        first, second = (await research_cues(connection))[:2]
        await decide(connection, account, second.iri, "rejected", None, None, "steht nicht im Plan")
        await decide(connection, account, first.iri, "confirmed", Decimal("0.9"), "KLP S. 14", None)
        await connection.execute("UPDATE lexical_cue SET retired_in = 1 WHERE iri = %s", (second.iri,))
    return first.iri, second.iri


async def three_terms(url: str) -> None:
    """Two new cues, in other regions, and a term misread."""
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
        account = uuid.uuid4()
        await connection.execute(
            "INSERT INTO account (id, name) VALUES (%s, 'Redaktion Geheim B')", (account,)
        )
        for regions, key, choice in (
            (("DE-NW",), "lernbereich", Choice("cue", SCHOOL + "Inhaltsbereich", CV + "role_alt", "wie HE")),
            (("DE-BY", "DE-NW"), "lernbereich", Choice("cue", SCHOOL + "Kompetenzbereich", CV + "role_pref")),
            (("DE",), "fehler", Choice("error", note="kein Begriff")),
        ):
            judged = Judged(
                CV + "sec_school", regions, key, key.capitalize(), SCHOOL + "Terminology", {"documents": 3}
            )
            await decide_term(connection, account, judged, choice)


async def test_the_decisions_come_out_by_cue_with_what_was_judged(url: str) -> None:
    confirmed, rejected = await two_decisions(url)

    done = export(url)

    assert done.returncode == 0, done.stderr.decode()
    found = json.loads(done.stdout.decode("utf-8"))
    assert found["format"] == 2
    assert [decision["cue"] for decision in found["decisions"]] == sorted([confirmed, rejected])
    by_cue = {decision["cue"]: decision for decision in found["decisions"]}
    assert {key: value for key, value in by_cue[confirmed].items() if key != "content"} == {
        "cue": confirmed,
        "decision": "confirmed",
        "strength": "0.90",
        "evidence": "KLP S. 14",
        "note": None,
    }
    assert by_cue[rejected]["decision"] == "rejected"
    assert by_cue[rejected]["note"] == "steht nicht im Plan"
    assert set(by_cue[rejected]["content"]) == {
        "surface_form",
        "pattern",
        "maps_to",
        "scope_regions",
        "role",
        "kind",
        "profile",
    }
    assert b"Geheim" not in done.stdout  # who decided stays in the database and its audit log
    assert b"decided" not in done.stdout
    assert b"2 decisions: 1 confirmed, 1 rejected; 1 on a retired cue; 0 new cues" in done.stderr


async def test_the_new_cues_come_out_by_profile_and_regions_without_their_documents(url: str) -> None:
    await three_terms(url)

    done = export(url)

    assert done.returncode == 0, done.stderr.decode()
    found = json.loads(done.stdout.decode("utf-8"))
    assert found["new_terms"] == [
        {
            "profile": SCHOOL + "Terminology",
            "regions": ["DE-BY", "DE-NW"],
            "surface_form": "Lernbereich",
            "maps_to": SCHOOL + "Kompetenzbereich",
            "role": "pref",
            "note": None,
        },
        {
            "profile": SCHOOL + "Terminology",
            "regions": ["DE-NW"],
            "surface_form": "Lernbereich",
            "maps_to": SCHOOL + "Inhaltsbereich",
            "role": "alt",
            "note": "wie HE",
        },
    ]  # a term misread changes no file
    assert b"Geheim" not in done.stdout
    assert b"documents" not in done.stdout  # nor what was judged beside the cue
    assert b"0 decisions: 0 confirmed, 0 rejected; 0 on a retired cue; 2 new cues" in done.stderr


async def test_the_same_decisions_give_the_same_bytes(url: str) -> None:
    await two_decisions(url)
    await three_terms(url)

    once, again = export(url), export(url)

    assert once.stdout == again.stdout
    written = json.dumps(json.loads(once.stdout), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    assert once.stdout.decode("utf-8") == written  # as git shows it best: keys in order, signs as they read


def test_no_decisions_are_an_empty_list(url: str) -> None:
    done = export(url)

    assert done.returncode == 0, done.stderr.decode()
    assert json.loads(done.stdout) == {"format": 2, "decisions": [], "new_terms": []}


def test_a_database_that_refuses_says_so_in_one_line(url: str) -> None:
    done = export(make_conninfo(url, dbname="curricarta_t_none"))  # a database that is not

    assert done.returncode == 1
    assert done.stdout == b""
    assert len(done.stderr.decode().strip().splitlines()) == 1
    assert b"no decisions exported" in done.stderr
