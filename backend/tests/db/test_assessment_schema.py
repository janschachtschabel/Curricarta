"""A document's assessments (migration assessment; plan M3a J, cur:Assessment): each a part of one other
assessment, specification or node of its document, of a kind of the core's, with a weight between 0 and 100,
and never a part of itself however it is written; what it assesses are nodes and statements of its document,
each once; it holds levels and anchors of its own, and all of it goes with what it is a part of. What the
core's shapes say beside (the weights of one assessment's parts over 100 %) X5 checks."""

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import errors

from app.db.migrate import migrate
from tests.db.l1 import (
    CV,
    add_conversion,
    add_document,
    add_entity,
    add_node,
    add_specification,
    add_statement,
)
from tests.db.l2 import add_value, seed_l2_vocabulary

pytestmark = pytest.mark.pg
KIND_KEY = "assessment_assessment_kind_scheme_assessment_kind_iri_fkey"


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_l2_vocabulary(opened)
        yield opened


@pytest.fixture
def made(connection: psycopg.Connection) -> dict[str, Any]:
    made: dict[str, Any] = add_conversion(connection)
    document = made["document"] = add_document(connection, made)
    made["specification"] = add_specification(connection, document)
    made["node"] = add_node(connection, document)
    made["statement"] = add_statement(connection, document, made["node"])
    return made


def assessment(connection: psycopg.Connection, made: dict[str, Any], **columns: Any) -> uuid.UUID:
    """An assessment of the document, at its specification unless ``columns`` name another parent."""
    parents = ("parent_assessment_id", "node_id", "specification_id")
    holder = next((key for key in parents if key in columns), "specification_id")
    parent = columns.pop(holder, made["specification"])
    return add_value(connection, "assessment", made["document"], holder, parent, **columns)


def violated(connection: psycopg.Connection, query: str, *params: Any) -> str:
    with pytest.raises(errors.IntegrityError) as broken:
        connection.execute(query, params)
    assert broken.value.diag.constraint_name is not None, broken.value
    return broken.value.diag.constraint_name


def target(connection: psycopg.Connection, made: dict[str, Any], of: uuid.UUID, **columns: Any) -> None:
    values = {"document_id": made["document"], "assessment_id": of, "position": 1} | columns
    connection.execute(
        f"INSERT INTO assessment_target ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))})",  # noqa: S608
        tuple(values.values()),
    )


def test_an_assessment_states_kind_name_duration_weight_and_grading_at_its_parent(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    exam = assessment(connection, made, label="Abschlussprüfung", duration_minutes=120, graded=True)
    part = assessment(
        connection, made, parent_assessment_id=exam, assessment_kind_iri=CV + "ak_examPart",
        weight_percent=Decimal("37.5"),
    )  # fmt: skip
    at_node = assessment(connection, made, node_id=made["node"])

    found = connection.execute(
        "SELECT id, parent_assessment_id, specification_id, node_id, assessment_kind_iri, label,"
        " duration_minutes, weight_percent, graded, revision FROM assessment ORDER BY created_at, id"
    ).fetchall()
    assert set(found) == {
        (exam, None, made["specification"], None, CV + "ak_exam", "Abschlussprüfung", 120, None, True, 1),
        (part, exam, None, None, CV + "ak_examPart", None, None, Decimal("37.5"), None, 1),
        (at_node, None, None, made["node"], CV + "ak_exam", None, None, None, None, 1),
    }


@pytest.mark.parametrize(
    ("columns", "check"),
    [
        ({"weight_percent": Decimal("100.5")}, "assessment_weight_percent_check"),
        ({"weight_percent": Decimal(-1)}, "assessment_weight_percent_check"),
        ({"weight_percent": Decimal("NaN")}, "assessment_weight_percent_check"),
        ({"weight_percent": Decimal("Infinity")}, "assessment_weight_percent_check"),
        ({"duration_minutes": -1}, "assessment_duration_minutes_check"),
        ({"label": " "}, "assessment_label_check"),
        ({"label": "x" * 1001}, "assessment_label_check"),
        ({"assessment_kind_iri": CV + "form_formal"}, KIND_KEY),
        ({"specification_id": None}, "assessment_one_parent"),
    ],
    ids=["weight-over", "weight-under", "weight-nan", "weight-endless", "duration", "blank-label",
         "long-label", "kind-of-another-list", "no-parent"],
)  # fmt: skip
def test_what_an_assessment_may_not_say_is_refused_by_its_check(
    connection: psycopg.Connection, made: dict[str, Any], columns: dict[str, Any], check: str
) -> None:
    with pytest.raises(errors.IntegrityError) as broken:
        assessment(connection, made, **({"specification_id": made["specification"]} | columns))

    assert broken.value.diag.constraint_name == check


def test_an_assessment_has_one_parent_of_its_document(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    other = add_document(connection, made)
    foreign_node = add_node(connection, other)
    entity = add_entity(connection, "assessment")
    insert = (
        "INSERT INTO assessment (id, document_id, specification_id, node_id, position,"
        " assessment_kind_scheme, assessment_kind_iri, origin_scheme, origin_iri, review_status_scheme,"
        " review_status_iri)"
        " VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s)"
    )
    stated = (CV + "AssessmentKinds", CV + "ak_exam", CV + "Origins", CV + "orig_human",
              CV + "ReviewStatuses", CV + "rev_proposed")  # fmt: skip

    two = violated(connection, insert, entity, made["document"], made["specification"], made["node"], *stated)
    foreign = violated(connection, insert, entity, made["document"], None, foreign_node, *stated)

    assert (two, foreign) == ("assessment_one_parent", "assessment_document_id_node_id_fkey")


def test_an_assessment_is_never_a_part_of_itself(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    exam = assessment(connection, made)
    part = assessment(connection, made, parent_assessment_id=exam)
    area = assessment(connection, made, parent_assessment_id=part)
    move = "UPDATE assessment SET parent_assessment_id = %s, specification_id = NULL WHERE id = %s"

    itself = violated(connection, move, exam, exam)
    under_its_part = violated(connection, move, area, exam)

    assert (itself, under_its_part) == ("assessment_not_its_own_part", "assessment_without_cycle")
    assert connection.execute(
        "SELECT parent_assessment_id FROM assessment WHERE id = %s", (exam,)
    ).fetchone() == (None,)


def test_an_assessment_assesses_nodes_and_statements_of_its_document_each_once(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    exam = assessment(connection, made)
    other = add_document(connection, made)
    foreign = add_node(connection, other)
    target(connection, made, exam, node_id=made["node"])
    target(connection, made, exam, statement_id=made["statement"], position=2)
    insert = (
        "INSERT INTO assessment_target (document_id, assessment_id, node_id, statement_id, position)"
        " VALUES (%s, %s, %s, %s, %s)"
    )

    refused = [
        violated(connection, insert, made["document"], exam, made["node"], None, 3),
        violated(connection, insert, made["document"], exam, foreign, None, 3),
        violated(connection, insert, made["document"], exam, made["node"], made["statement"], 3),
        violated(connection, insert, made["document"], exam, None, None, 3),
    ]

    assert refused == [
        "assessment_target_once", "assessment_target_document_id_node_id_fkey", "assessment_target_one",
        "assessment_target_one",
    ]  # fmt: skip


def test_an_assessment_holds_levels_and_anchors_and_goes_with_its_parent(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    exam = assessment(connection, made, node_id=made["node"])
    part = assessment(connection, made, parent_assessment_id=exam)
    add_value(connection, "level_assignment", made["document"], "assessment_id", part)
    target(connection, made, part, statement_id=made["statement"])
    anchor = add_entity(connection, "anchor")
    connection.execute(
        "INSERT INTO anchor (id, document_id, conversion_id, assessment_id, page_start)"
        " VALUES (%s, %s, %s, %s, 1)",
        (anchor, made["document"], made["conversion"], part),
    )
    two_owners = violated(connection, "UPDATE anchor SET node_id = %s WHERE id = %s", made["node"], anchor)

    connection.execute("DELETE FROM node WHERE id = %s", (made["node"],))

    assert two_owners == "anchor_one_owner"
    left = connection.execute(
        "SELECT (SELECT count(*) FROM assessment), (SELECT count(*) FROM assessment_target),"
        " (SELECT count(*) FROM level_assignment), (SELECT count(*) FROM anchor)"
    ).fetchone()
    assert left == (0, 0, 0, 0)


def test_an_anchor_s_one_owner_check_names_the_assessment_and_its_page_checks_stay(
    connection: psycopg.Connection,
) -> None:
    # migration assessment drops the unnamed one-owner check of l1_anchors, names one with the assessment
    checks: dict[str, str] = dict(
        connection.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conrelid = 'anchor'::regclass AND contype = 'c'"
        ).fetchall()
    )

    assert "anchor_check" not in checks
    assert (
        "num_nonnulls(node_id, statement_id, frame_part_id, specification_id, assessment_id) <= 1"
        in checks["anchor_one_owner"]
    )
    assert [name for name, check in checks.items() if "num_nonnulls" in check] == ["anchor_one_owner"]
    page_checks = [check for check in checks.values() if "page_start" in check or "page_end" in check]
    assert (
        len(page_checks) == 4
    )  # a page or a printed one, an end after its start, an end of a range it begins, from 1
