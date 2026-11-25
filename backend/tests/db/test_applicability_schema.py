"""A specification's applicability contexts (migration applicability; plan M3a H1, cur:ApplicabilityContext):
each of one specification of its document, in its order, with a sector and a formality of their
vocabularies, the institution and the target group as written, where it came from and how far it is
reviewed. It holds time spans and levels of its own (tests/db/test_l2_schema.py) and goes with its
specification; what the core's shapes say of a context beside (an OR context, plan M3a: none yet) X5
checks."""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import errors

from app.db.migrate import migrate
from tests.db.l1 import CV, add_conversion, add_document, add_entity, add_specification
from tests.db.l2 import add_value, seed_l2_vocabulary

pytestmark = pytest.mark.pg


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_l2_vocabulary(opened)
        yield opened


@pytest.fixture
def held(connection: psycopg.Connection) -> dict[str, uuid.UUID]:
    document = add_document(connection, add_conversion(connection))
    return {"document_id": document, "specification_id": add_specification(connection, document)}


def context(connection: psycopg.Connection, held: dict[str, uuid.UUID], **columns: Any) -> uuid.UUID:
    return add_value(
        connection, "applicability_context", held["document_id"], "specification_id",
        held["specification_id"], **columns,
    )  # fmt: skip


def violated(connection: psycopg.Connection, held: dict[str, uuid.UUID], **columns: Any) -> str:
    with pytest.raises(errors.IntegrityError) as broken:
        context(connection, held, **columns)
    assert broken.value.diag.constraint_name is not None, broken.value
    return broken.value.diag.constraint_name


def test_a_context_states_sector_formality_institution_and_target_group(
    connection: psycopg.Connection, held: dict[str, uuid.UUID]
) -> None:
    made = context(
        connection, held, formality_scheme=CV + "Formalities", formality_iri=CV + "form_formal",
        institution_text="Gymnasium", target_group_text="Erwachsene",
    )  # fmt: skip

    found = connection.execute(
        "SELECT specification_id, sector_iri, formality_iri, institution_text, target_group_text, revision"
        " FROM applicability_context WHERE id = %s",
        (made,),
    ).fetchone()
    assert found == (
        held["specification_id"], CV + "sec_school", CV + "form_formal", "Gymnasium", "Erwachsene", 1,
    )  # fmt: skip


def test_a_context_may_say_nothing_but_its_values(
    connection: psycopg.Connection, held: dict[str, uuid.UUID]
) -> None:
    # the shapes ask nothing of a context; its time span or level may be all it says
    made = context(connection, held, sector_scheme=None, sector_iri=None)
    add_value(connection, "level_assignment", held["document_id"], "applicability_context_id", made)


# each a row breaking one constraint: its columns, the constraint's name
BROKEN: dict[str, tuple[dict[str, Any], str]] = {
    "a sector of the formalities": (
        {"sector_iri": CV + "form_formal"}, "applicability_context_sector_scheme_sector_iri_fkey"
    ),
    "a sector's scheme of another list": (
        {"sector_scheme": CV + "Formalities"}, "applicability_context_sector_scheme_check"
    ),
    "a sector without its scheme": ({"sector_scheme": None}, "applicability_context_sector_named"),
    "a formality of the sectors": (
        {"formality_scheme": CV + "Formalities", "formality_iri": CV + "sec_school"},
        "applicability_context_formality_scheme_formality_iri_fkey",
    ),
    "a formality without its scheme": (
        {"formality_iri": CV + "form_formal"}, "applicability_context_formality_named"
    ),
    "a blank institution": ({"institution_text": " "}, "applicability_context_institution_text_check"),
    "an overlong target group": (
        {"target_group_text": "x" * 2001}, "applicability_context_target_group_text_check"
    ),
    "a position below one": ({"position": 0}, "applicability_context_position_check"),
    "a rule's context without its rule": (
        {"origin_iri": CV + "orig_rule"}, "applicability_context_check"
    ),
}  # fmt: skip


@pytest.mark.parametrize("name", list(BROKEN))
def test_the_store_holds_what_a_context_is(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], name: str
) -> None:
    columns, constraint = BROKEN[name]

    assert violated(connection, held, **columns) == constraint


def test_a_specification_s_contexts_take_a_position_each(
    connection: psycopg.Connection, held: dict[str, uuid.UUID]
) -> None:
    context(connection, held)
    context(connection, held, position=2)

    assert violated(connection, held, position=2) == "applicability_context_position"


def test_a_context_s_specification_is_of_its_document(
    connection: psycopg.Connection, held: dict[str, uuid.UUID]
) -> None:
    other = add_specification(connection, add_document(connection, add_conversion(connection, b"\x02" * 32)))

    assert (
        violated(connection, held, specification_id=other)
        == "applicability_context_document_id_specification_id_fkey"
    )


def test_with_its_specification_the_context_goes_with_what_it_holds(
    connection: psycopg.Connection, held: dict[str, uuid.UUID]
) -> None:
    made = context(connection, held)
    add_value(connection, "time_span", held["document_id"], "applicability_context_id", made)

    connection.execute("DELETE FROM specification WHERE id = %s", (held["specification_id"],))

    assert connection.execute(
        "SELECT (SELECT count(*) FROM applicability_context), (SELECT count(*) FROM time_span)"
    ).fetchone() == (0, 0)


def test_a_context_is_an_entity_of_its_own_kind(
    connection: psycopg.Connection, held: dict[str, uuid.UUID]
) -> None:
    wrong = add_entity(connection, "node")

    with pytest.raises(errors.ForeignKeyViolation):
        connection.execute(
            "INSERT INTO applicability_context (id, document_id, specification_id, position, origin_scheme,"
            " origin_iri, review_status_scheme, review_status_iri) VALUES (%s, %s, %s, 1, %s, %s, %s, %s)",
            (wrong, held["document_id"], held["specification_id"], CV + "Origins", CV + "orig_human",
             CV + "ReviewStatuses", CV + "rev_proposed"),
        )  # fmt: skip
