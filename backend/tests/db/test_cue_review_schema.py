"""The editors' decisions on research cues (migration cue_review, plan M1 10.3, 10c C5): one for each cue,
confirmed - with a strength up to 0.9 and where they found it - or rejected, by an account."""

from typing import Any, get_args
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from app.db.cue_review import CueDecision
from tests.db.l1 import listed_values
from tests.db.test_lexicon_schema import SCHOOL, add_cue, add_profile, connection

pytestmark = pytest.mark.pg
__all__ = ["connection"]

CUE = SCHOOL + "cue-1"


@pytest.fixture(autouse=True)
def _a_cue(connection: psycopg.Connection) -> None:
    add_profile(connection)
    add_cue(connection)


def an_account(connection: psycopg.Connection) -> UUID:
    account = uuid4()
    connection.execute("INSERT INTO account (id, name) VALUES (%s, %s)", (account, f"Redaktion {account}"))
    return account


def decide(connection: psycopg.Connection, **columns: Any) -> None:
    values: dict[str, Any] = {
        "cue_iri": CUE,
        "decision": "confirmed",
        "strength": "0.9",
        "evidence": "KLP Physik S. 14",
        "content": Jsonb({"surface_form": "Kernlehrplan"}),
        "decided_by": an_account(connection),
    }
    values |= columns
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    connection.execute(f"INSERT INTO cue_review ({names}) VALUES ({marks})", tuple(values.values()))  # noqa: S608


def test_a_confirmed_cue_keeps_its_strength_evidence_and_the_hour_of_the_decision(
    connection: psycopg.Connection,
) -> None:
    decide(connection)

    row = connection.execute(
        "SELECT strength::text, evidence, note, decided_at <= now() FROM cue_review"
    ).fetchone()

    assert row == ("0.90", "KLP Physik S. 14", None, True)


def test_the_decisions_are_the_listed_ones(connection: psycopg.Connection) -> None:
    assert listed_values(connection, "cue_review", "decision") == set(get_args(CueDecision))


def test_a_rejected_cue_needs_no_evidence(connection: psycopg.Connection) -> None:
    decide(connection, decision="rejected", strength=None, evidence=None, note="steht so nicht im Lehrplan")

    assert connection.execute("SELECT decision FROM cue_review").fetchone() == ("rejected",)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"evidence": None}, "cue_review_confirmed_with_evidence"),
        ({"strength": None}, "cue_review_confirmed_with_evidence"),
        ({"decision": "rejected"}, "cue_review_strength_only_confirmed"),
        ({"strength": "0.95"}, "cue_review_strength_check"),
        ({"strength": "0.45"}, "cue_review_strength_check"),
        ({"evidence": ""}, "cue_review_evidence_check"),
        ({"evidence": "x" * 501}, "cue_review_evidence_check"),
        ({"note": ""}, "cue_review_note_check"),
        ({"note": "x" * 2001}, "cue_review_note_check"),
        ({"decision": "deferred"}, "cue_review_decision_check"),
        ({"content": Jsonb([])}, "cue_review_content_check"),
    ],
    ids=[
        "confirmed-without-evidence",
        "confirmed-without-strength",
        "rejected-with-strength",
        "strength-above-0.9",
        "strength-below-0.5",
        "evidence-empty",
        "evidence-too-long",
        "note-empty",
        "note-too-long",
        "decision-unknown",
        "content-no-object",
    ],
)
def test_a_decision_outside_the_rules_is_refused(
    connection: psycopg.Connection, columns: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(errors.CheckViolation) as refused:
        decide(connection, **columns)

    assert refused.value.diag.constraint_name == constraint


def test_the_bounds_hold(connection: psycopg.Connection) -> None:
    decide(connection, strength="0.5", evidence="x" * 500, note="x" * 2000)

    assert connection.execute("SELECT strength::text FROM cue_review").fetchone() == ("0.50",)


def test_a_cue_has_one_decision_and_it_names_a_cue_and_an_account(connection: psycopg.Connection) -> None:
    decide(connection)

    add_cue(connection, SCHOOL + "cue-2")

    with pytest.raises(errors.UniqueViolation):
        decide(connection)
    with pytest.raises(errors.ForeignKeyViolation) as no_cue:
        decide(connection, cue_iri=SCHOOL + "cue-unknown")
    with pytest.raises(errors.ForeignKeyViolation) as no_account:
        decide(connection, cue_iri=SCHOOL + "cue-2", decided_by=uuid4())

    assert no_cue.value.diag.constraint_name == "cue_review_cue_iri_fkey"
    assert no_account.value.diag.constraint_name == "cue_review_decided_by_fkey"
