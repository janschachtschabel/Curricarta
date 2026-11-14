"""The terms X1 found no type for and the editors' decisions on them (app/db/term_review.py, plan M1 10.4, 10d
D2-D5): each new term of each document's profile, and one decision for each term, made again over the last;
a new cue is applied once an active cue of the profile says it - its word, target, role and regions."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.conversion.base import Block
from app.db.term_review import Choice, Judged, decide_term, held_cues, occurrences, term_reviews
from tests.db.document_of import document_of
from tests.db.test_nodes import url

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["url"]  # the database with the vocabularies of the ontology, shared with test_nodes

CV = "https://w3id.org/wlo/curriculum/vocab#"
SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"
REGION = "https://w3id.org/wlo/curriculum/region/"
AREA = SCHOOL + "Inhaltsbereich"
BLOCKS = [
    Block(
        id="p1-b1",
        page=1,
        kind="text",
        text="Inhaltsfeld 1",
        bbox=(0, 0, 1, 1),
        font_size=10,
        bold=False,
        italic=False,
    )
]


@pytest.fixture
async def connection(url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as opened:
        yield opened


async def an_account(connection: psycopg.AsyncConnection, name: str = "Redaktion") -> uuid.UUID:
    account = uuid.uuid4()
    await connection.execute("INSERT INTO account (id, name) VALUES (%s, %s)", (account, name))
    return account


async def with_terms(
    connection: psycopg.AsyncConnection, terms: list[dict[str, Any]], **made: Any
) -> uuid.UUID:
    document = await document_of(connection, BLOCKS, **made)
    await connection.execute(
        "UPDATE document_profile SET new_terms = %s WHERE document_id = %s", (Jsonb(terms), document.id)
    )
    return document.id


def term(text: str, function: str | None = CV + "fn_area", block: str | None = "p1-b1") -> dict[str, Any]:
    return {"documentTerm": text, "suggestedFunction": function, "evidenceBlockId": block}


def judged(**changes: Any) -> Judged:
    values: dict[str, Any] = {
        "sector_iri": CV + "sec_school",
        "regions": ("DE-NW",),
        "key": "inhaltsfeld",
        "surface_form": "Inhaltsfeld",
        "profile": SCHOOL + "Terminology",
        "content": {"functions": [CV + "fn_area"], "documents": 1},
    }
    return Judged(**(values | changes))


async def test_each_new_term_of_each_document_is_an_occurrence(connection: psycopg.AsyncConnection) -> None:
    odd: list[dict[str, Any]] = [{"documentTerm": None}, {"documentTerm": 7}, {"suggestedFunction": None}]
    first = await with_terms(connection, [term("Inhaltsfeld"), term("Lernbereich", None, None), *odd])
    other = await with_terms(connection, [term("Inhaltsfeld")], sector="vocational", regions=())
    await with_terms(connection, [])
    await connection.execute("UPDATE document SET title = 'Kernlehrplan Physik' WHERE id = %s", (first,))

    found = await occurrences(connection)

    assert sorted((place.document, place.text, place.block, place.function) for place in found) == sorted(
        [
            (first, "Inhaltsfeld", "p1-b1", CV + "fn_area"),
            (first, "Lernbereich", None, None),
            (other, "Inhaltsfeld", "p1-b1", CV + "fn_area"),
        ]
    )
    by_document = {place.document: place for place in found}
    assert (by_document[first].sector, by_document[first].sector_iri, by_document[first].regions) == (
        "school",
        CV + "sec_school",
        ("DE-NW",),
    )
    assert (by_document[other].sector, by_document[other].regions) == ("vocational", ())
    assert (by_document[first].title, by_document[other].title) == ("Kernlehrplan Physik", None)
    assert by_document[first].created_at is not None


async def test_the_occurrences_are_of_active_sectors_and_where_asked_of_one(
    connection: psycopg.AsyncConnection,
) -> None:
    school = await with_terms(connection, [term("Inhaltsfeld")])
    vocational = await with_terms(connection, [term("Lernfeld")], sector="vocational")
    await with_terms(connection, [term("Handlungsfeld")], sector="higher")

    of_school = await occurrences(connection, CV + "sec_school")
    await connection.execute(
        "UPDATE vocab_concept SET retired_in = (SELECT max(id) FROM vocab_release) WHERE iri = %s",
        (CV + "sec_higher",),
    )
    active = await occurrences(connection)

    assert [place.document for place in of_school] == [school]
    assert sorted(place.text for place in active) == ["Inhaltsfeld", "Lernfeld"]
    assert vocational in {place.document for place in active}


async def test_a_decision_is_kept_and_made_again_over_the_last(connection: psycopg.AsyncConnection) -> None:
    editor = await an_account(connection, "Redaktion")

    made = await decide_term(
        connection, editor, judged(), Choice("cue", maps_to=AREA, role=CV + "role_alt", note="NW, HE")
    )
    await connection.execute("UPDATE term_review SET decided_at = '2026-01-01T00:00:00Z'")
    again = await decide_term(
        connection,
        await an_account(connection, "Verwaltung"),
        judged(surface_form="INHALTSFELD"),
        Choice("error"),
    )

    assert (made.sector, made.regions, made.key, made.decision, made.maps_to, made.role, made.note) == (
        "school",
        ("DE-NW",),
        "inhaltsfeld",
        "cue",
        AREA,
        CV + "role_alt",
        "NW, HE",
    )
    assert (made.decided_by, made.profile, made.content) == (
        "Redaktion",
        SCHOOL + "Terminology",
        {"functions": [CV + "fn_area"], "documents": 1},
    )
    assert (again.decision, again.maps_to, again.role, again.note, again.surface_form, again.decided_by) == (
        "error",
        None,
        None,
        None,
        "INHALTSFELD",
        "Verwaltung",
    )
    assert again.decided_at > datetime(2026, 1, 1, tzinfo=UTC)  # the hour of the last decision
    assert [review.decision for review in await term_reviews(connection)] == ["error"]


async def test_a_new_cue_is_applied_once_an_active_cue_of_the_profile_says_it(
    connection: psycopg.AsyncConnection,
) -> None:
    editor = await an_account(connection)
    await decide_term(connection, editor, judged(), Choice("cue", maps_to=AREA, role=CV + "role_alt"))
    await decide_term(connection, editor, judged(key="leitidee", surface_form="Leitidee"), Choice("document"))
    before = {review.key: review.applied for review in await term_reviews(connection)}

    async def a_cue(iri: str, **changes: Any) -> None:
        values: dict[str, Any] = {
            "surface_form": "Inhaltsfeld",
            "role_iri": CV + "role_alt",
            "maps_to": [AREA, SCHOOL + "Kompetenzbereich"],
            "scope_regions": [REGION + "DE-NW"],
        } | changes
        await connection.execute(
            "INSERT INTO lexical_cue (iri, profile_iri, surface_form, role_scheme, role_iri, kind_scheme,"
            " kind_iri, maps_to, scope_regions) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                SCHOOL + iri,
                SCHOOL + "Terminology",
                values["surface_form"],
                CV + "CueRoles",
                values["role_iri"],
                CV + "CueKinds",
                CV + "ck_term",
                values["maps_to"],
                values["scope_regions"],
            ),
        )

    await a_cue("other-form", surface_form="Inhaltsfelder")
    await a_cue("other-role", role_iri=CV + "role_pref")
    await a_cue("other-target", maps_to=[SCHOOL + "Kompetenzbereich"])
    await a_cue("more-regions", scope_regions=[REGION + "DE-NW", REGION + "DE-BY"])
    await a_cue("everywhere", scope_regions=[])  # holds in NW too, but says other regions than the term
    await a_cue("retired")
    await connection.execute(
        "UPDATE lexical_cue SET retired_in = (SELECT max(id) FROM vocab_release) WHERE iri = %s",
        (SCHOOL + "retired",),
    )
    vocational = "https://w3id.org/wlo/curriculum/profile/vocational#"
    await connection.execute(
        "INSERT INTO lexical_cue (iri, profile_iri, surface_form, role_scheme, role_iri, kind_scheme,"
        " kind_iri, maps_to, scope_regions) SELECT %s, %s, surface_form, role_scheme, role_iri, kind_scheme,"
        " kind_iri, maps_to, %s FROM lexical_cue WHERE iri = %s",
        (
            vocational + "of-another-profile",
            vocational + "Terminology",
            [REGION + "DE-NW"],
            SCHOOL + "everywhere",
        ),
    )
    unapplied = {review.key: review.applied for review in await term_reviews(connection)}
    await a_cue("re-DE-NW-000000000000")
    after = {review.key: review.applied for review in await term_reviews(connection)}

    assert before == unapplied == {"inhaltsfeld": False, "leitidee": None}
    # nothing to apply of a term peculiar to a document
    assert after == {"inhaltsfeld": True, "leitidee": None}


async def test_the_decisions_stand_in_the_order_of_their_terms(connection: psycopg.AsyncConnection) -> None:
    editor = await an_account(connection)
    for changes in (
        {"regions": ("DE-NW",), "key": "b"},
        {"regions": ("DE", "DE-NW"), "key": "c"},
        {"regions": ("DE",), "key": "z"},
        {"regions": ("DE-NW",), "key": "a"},
        {"sector_iri": CV + "sec_vocational", "regions": ("DE",), "key": "a"},
    ):
        await decide_term(connection, editor, judged(**changes, surface_form="Wort"), Choice("error"))

    found = [(review.sector, review.regions, review.key) for review in await term_reviews(connection)]

    assert found == sorted(found)
    assert len(found) == 5


async def test_the_cues_that_may_hold_a_term_are_the_active_ones_own_or_researched(
    connection: psycopg.AsyncConnection,
) -> None:
    await connection.execute(
        "UPDATE lexical_cue SET retired_in = (SELECT max(id) FROM vocab_release) WHERE iri = %s",
        (SCHOOL + "cue-dt-bildungsplan",),
    )
    await connection.execute(  # a research cue whose regions stand unsorted
        "INSERT INTO lexical_cue (iri, profile_iri, surface_form, role_scheme, role_iri, kind_scheme,"
        " kind_iri, maps_to, scope_regions, properties)"
        " VALUES (%s, %s, 'Probebereich', %s, %s, %s, %s, %s, %s, %s)",
        (
            SCHOOL + "re-probe",
            SCHOOL + "Terminology",
            CV + "CueRoles",
            CV + "role_alt",
            CV + "CueKinds",
            CV + "ck_term",
            [AREA],
            [REGION + "DE-NW", REGION + "DE-BY"],
            Jsonb({"http://purl.org/dc/terms/source": [{"value": "recherche-ergebnisse/probe.md"}]}),
        ),
    )
    (stored,) = await (
        await connection.execute(
            "SELECT surface_form, pattern, maps_to, role_iri FROM lexical_cue WHERE iri = %s",
            (SCHOOL + "cue-dt-kernlehrplan",),
        )
    ).fetchall()

    cues = {cue.iri: cue for cue in await held_cues(connection)}

    own = cues[SCHOOL + "cue-dt-kernlehrplan"]
    assert (own.own, own.sector_iri) == (True, CV + "sec_school")
    assert (own.surface_form, own.pattern, list(own.maps_to), own.role) == stored
    assert SCHOOL + "cue-dt-bildungsplan" not in cues
    researched = [cue for cue in cues.values() if not cue.own]
    assert (len(cues), len(researched)) == (2760, 1492)
    assert cues[SCHOOL + "re-probe"].regions == (REGION + "DE-BY", REGION + "DE-NW")
    assert all(cue.regions == tuple(sorted(cue.regions)) and cue.regions for cue in researched)
