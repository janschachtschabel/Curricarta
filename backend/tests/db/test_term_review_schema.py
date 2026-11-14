"""The editors' decisions on the terms X1 found no type for (migration term_review, plan M1 10.4, 10d D4): one
for each term of a sector and its regions - a new cue, with its target and role, a term peculiar to its
document, or one misread -, by an account."""

from typing import Any, get_args
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from app.db.term_review import TermDecision
from tests.db.l1 import listed_values
from tests.db.test_lexicon_schema import CV, SCHOOL, add_profile, connection

pytestmark = pytest.mark.pg
__all__ = ["connection"]

NODE_TYPE = SCHOOL + "nt-Lernbereich"


@pytest.fixture(autouse=True)
def _a_profile(connection: psycopg.Connection) -> None:
    add_profile(connection)
    connection.execute(
        "INSERT INTO vocab_concept (iri, scheme_iri, types, pref_labels, alt_labels, definitions, broader,"
        " properties) VALUES (%s, %s, '{}', '{}', '{}', '{}', '{}', '{}')",
        (NODE_TYPE, CV + "Stages"),
    )


def an_account(connection: psycopg.Connection) -> UUID:
    account = uuid4()
    connection.execute("INSERT INTO account (id, name) VALUES (%s, %s)", (account, f"Redaktion {account}"))
    return account


def decide(connection: psycopg.Connection, **columns: Any) -> None:
    values: dict[str, Any] = {
        "sector_scheme": CV + "EducationSectors",
        "sector_iri": CV + "sec_school",
        "regions": ["DE-NW"],
        "term_key": "lernbereich",
        "surface_form": "Lernbereich",
        "decision": "cue",
        "profile_iri": SCHOOL + "Terminology",
        "maps_to": NODE_TYPE,
        "role_scheme": CV + "CueRoles",
        "role_iri": CV + "role_cue",
        "content": Jsonb({"functions": [CV + "fn_unit"], "documents": 2}),
        "decided_by": an_account(connection),
    }
    values |= columns
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    connection.execute(f"INSERT INTO term_review ({names}) VALUES ({marks})", tuple(values.values()))  # noqa: S608


def test_a_new_cue_keeps_its_target_role_and_the_hour_of_the_decision(connection: psycopg.Connection) -> None:
    decide(connection, note="eigene Ebene in SN")

    row = connection.execute(
        "SELECT surface_form, maps_to, role_iri, note, decided_at <= now() FROM term_review"
    ).fetchone()

    assert row == ("Lernbereich", NODE_TYPE, CV + "role_cue", "eigene Ebene in SN", True)


def test_the_decisions_are_the_listed_ones(connection: psycopg.Connection) -> None:
    assert listed_values(connection, "term_review", "decision") == set(get_args(TermDecision))


@pytest.mark.parametrize("decision", ["document", "error"])
def test_a_term_that_gives_no_cue_names_no_target(connection: psycopg.Connection, decision: str) -> None:
    decide(connection, decision=decision, profile_iri=None, maps_to=None, role_scheme=None, role_iri=None)

    assert connection.execute("SELECT decision FROM term_review").fetchone() == (decision,)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"maps_to": None}, "term_review_cue_complete"),
        ({"role_scheme": None, "role_iri": None}, "term_review_cue_complete"),
        ({"profile_iri": None}, "term_review_cue_complete"),
        ({"decision": "document", "role_scheme": None, "role_iri": None}, "term_review_only_cue_targets"),
        ({"decision": "error", "maps_to": None}, "term_review_only_cue_targets"),
        ({"decision": "document", "maps_to": None, "role_iri": None}, "term_review_role_in_scheme"),
        ({"role_scheme": CV + "CueKinds"}, "term_review_role_scheme_check"),
        ({"regions": []}, "term_review_regions_check"),
        ({"regions": ["de-nw"]}, "term_review_regions_check"),
        ({"regions": ["DE-NW", None]}, "term_review_regions_check"),
        ({"term_key": ""}, "term_review_term_key_check"),
        ({"term_key": "x" * 501}, "term_review_term_key_check"),
        ({"surface_form": " \u00a0"}, "term_review_surface_form_check"),
        ({"surface_form": "x" * 501}, "term_review_surface_form_check"),
        ({"note": ""}, "term_review_note_check"),
        ({"note": "x" * 2001}, "term_review_note_check"),
        ({"decision": "deferred"}, "term_review_decision_check"),
        ({"content": Jsonb([])}, "term_review_content_check"),
        ({"sector_scheme": CV + "Stages"}, "term_review_sector_scheme_check"),
    ],
    ids=[
        "cue-without-target",
        "cue-without-role",
        "cue-without-profile",
        "document-with-target",
        "error-with-role",
        "role-without-concept",
        "role-of-another-scheme",
        "no-regions",
        "region-unwritten",
        "region-null",
        "key-empty",
        "key-too-long",
        "form-blank",
        "form-too-long",
        "note-empty",
        "note-too-long",
        "decision-unknown",
        "content-no-object",
        "sector-of-another-scheme",
    ],
)
def test_a_decision_outside_the_rules_is_refused(
    connection: psycopg.Connection, columns: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(errors.CheckViolation) as refused:
        decide(connection, **columns)

    assert refused.value.diag.constraint_name == constraint


def test_the_bounds_hold(connection: psycopg.Connection) -> None:
    decide(connection, regions=["DE", "DE-BY"], term_key="x" * 500, surface_form="x" * 500, note="x" * 2000)

    assert connection.execute("SELECT regions FROM term_review").fetchone() == (["DE", "DE-BY"],)


def test_a_term_has_one_decision_and_its_names_are_known(connection: psycopg.Connection) -> None:
    decide(connection)
    decide(connection, regions=["DE-BY"])
    decide(connection, sector_iri=CV + "sec_vocational", profile_iri=SCHOOL + "Terminology")

    with pytest.raises(errors.UniqueViolation):
        decide(connection, decision="error", profile_iri=None, maps_to=None, role_scheme=None, role_iri=None)
    unknown: dict[str, dict[str, Any]] = {
        "sector": {"regions": ["DE-SN"], "sector_iri": CV + "sec_unknown"},
        "target": {"regions": ["DE-SN"], "maps_to": SCHOOL + "nt-unknown"},
        "profile": {"regions": ["DE-SN"], "profile_iri": SCHOOL + "Unknown"},
        "role": {"regions": ["DE-SN"], "role_iri": CV + "ck_term"},
        "account": {"regions": ["DE-SN"], "decided_by": uuid4()},
    }
    refused = {}
    for name, columns in unknown.items():
        with pytest.raises(errors.ForeignKeyViolation) as violation:
            decide(connection, **columns)
        refused[name] = violation.value.diag.constraint_name

    assert refused == {
        "sector": "term_review_sector_scheme_sector_iri_fkey",
        "target": "term_review_maps_to_fkey",
        "profile": "term_review_profile_iri_fkey",
        "role": "term_review_role_scheme_role_iri_fkey",
        "account": "term_review_decided_by_fkey",
    }
