"""A node's placements (migration placement; plan M3a K, cur:Placement): each places its node (cur:placedUnit)
in a specification or a variant of its document - one at least, a variant of the specification where both are
named -, at a node of its document (cur:inNode) or nowhere in particular, with an obligation of the core's
list and a grade weight; it holds time spans and workloads of its own and goes with what it names. What the
core's shapes say beside (the credits of a semester) X5 checks."""

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
    add_variant,
)
from tests.db.l2 import add_value, seed_l2_vocabulary

pytestmark = pytest.mark.pg
OBLIGATION_KEY = "placement_obligation_scheme_obligation_iri_fkey"


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
    made["variant"] = add_variant(connection, made["specification"])
    made["module"] = add_node(connection, document)
    made["area"] = add_node(connection, document, position=2)
    return made


def placement(connection: psycopg.Connection, made: dict[str, Any], **columns: Any) -> uuid.UUID:
    """A placement of the document's module, in its specification unless ``columns`` say otherwise."""
    values = {"specification_id": made["specification"]} | columns
    node = values.pop("node_id", made["module"])
    return add_value(connection, "placement", made["document"], "node_id", node, **values)


def violated(connection: psycopg.Connection, query: str, *params: Any) -> str:
    with pytest.raises(errors.IntegrityError) as broken:
        connection.execute(query, params)
    assert broken.value.diag.constraint_name is not None, broken.value
    return broken.value.diag.constraint_name


def test_a_placement_states_where_its_node_is_placed_how_binding_and_with_what_weight(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    in_specification = placement(connection, made, in_node_id=made["area"], grade_weight=Decimal("1.5"))
    in_variant = placement(
        connection, made, specification_id=None, variant_id=made["variant"],
        variant_specification_id=made["specification"], position=2,
    )  # fmt: skip
    both = placement(
        connection,
        made,
        variant_id=made["variant"],
        variant_specification_id=made["specification"],
        position=3,
    )

    found = connection.execute(
        "SELECT id, node_id, specification_id, variant_id, in_node_id, position, obligation_iri,"
        " grade_weight, iri, revision FROM placement ORDER BY position"
    ).fetchall()
    module, specification, variant = made["module"], made["specification"], made["variant"]
    assert found == [
        (in_specification, module, specification, None, made["area"], 1, CV + "obl_binding", Decimal("1.5"),
         None, 1),
        (in_variant, module, None, variant, None, 2, CV + "obl_binding", None, None, 1),
        (both, module, specification, variant, None, 3, CV + "obl_binding", None, None, 1),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("columns", "check"),
    [
        ({"specification_id": None}, "placement_in_context"),
        ({"grade_weight": Decimal(-1)}, "placement_grade_weight_check"),
        ({"grade_weight": Decimal("NaN")}, "placement_grade_weight_check"),
        ({"grade_weight": Decimal("Infinity")}, "placement_grade_weight_check"),
        ({"obligation_iri": CV + "form_formal"}, OBLIGATION_KEY),
        ({"iri": "urn:uuid:1"}, "placement_iri_check"),
        ({"variant_id": "variant"}, "placement_variant_named"),
    ],
    ids=["no-specification-nor-variant", "weight-under", "weight-nan", "weight-endless",
         "obligation-of-another-list", "iri-not-http", "variant-without-its-specification"],
)  # fmt: skip
def test_what_a_placement_may_not_say_is_refused_by_its_check(
    connection: psycopg.Connection, made: dict[str, Any], columns: dict[str, Any], check: str
) -> None:
    given = {key: made[value] if value == "variant" else value for key, value in columns.items()}
    with pytest.raises(errors.IntegrityError) as broken:
        placement(connection, made, **given)

    assert broken.value.diag.constraint_name == check


def test_a_placement_names_rows_of_its_document_and_a_variant_of_the_specification_it_names(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    other = add_document(connection, made)
    foreign_node = add_node(connection, other)
    foreign_specification = add_specification(connection, other)
    second = add_specification(connection, made["document"], key="s2")
    entity = add_entity(connection, "placement")
    insert = (
        "INSERT INTO placement (id, document_id, node_id, specification_id, variant_id,"
        " variant_specification_id, in_node_id, position, obligation_scheme, obligation_iri, origin_scheme,"
        " origin_iri, review_status_scheme, review_status_iri)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s)"
    )
    stated = (CV + "Obligations", CV + "obl_mandatory", CV + "Origins", CV + "orig_human",
              CV + "ReviewStatuses", CV + "rev_proposed")  # fmt: skip
    document, module, specification, variant = (
        made["document"],
        made["module"],
        made["specification"],
        made["variant"],
    )

    refused = [
        violated(
            connection, insert, entity, document, foreign_node, specification, None, None, None, *stated
        ),
        violated(
            connection, insert, entity, document, module, foreign_specification, None, None, None, *stated
        ),
        violated(
            connection, insert, entity, document, module, specification, None, None, foreign_node, *stated
        ),
        violated(connection, insert, entity, document, module, None, variant, second, None, *stated),
        violated(connection, insert, entity, document, module, second, variant, specification, None, *stated),
        violated(connection, insert, entity, document, module, specification, None, None, module, *stated),
    ]

    assert refused == [
        "placement_document_id_node_id_fkey", "placement_document_id_specification_id_fkey",
        "placement_document_id_in_node_id_fkey", "placement_variant_specification_id_variant_id_fkey",
        "placement_variant_of_its_specification", "placement_not_in_itself",
    ]  # fmt: skip


def test_the_placements_of_a_node_stand_in_their_order(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    placement(connection, made)

    twice = violated(
        connection,
        "INSERT INTO placement (id, document_id, node_id, specification_id, position, obligation_scheme,"
        " obligation_iri, origin_scheme, origin_iri, review_status_scheme, review_status_iri)"
        " VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s)",
        add_entity(connection, "placement"), made["document"], made["module"], made["specification"],
        CV + "Obligations", CV + "obl_mandatory", CV + "Origins", CV + "orig_human", CV + "ReviewStatuses",
        CV + "rev_proposed",
    )  # fmt: skip

    assert twice == "placement_position"


def test_a_placement_holds_time_spans_and_workloads_and_goes_with_what_it_names(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    document = made["document"]
    at_module = placement(connection, made)
    in_area = placement(connection, made, in_node_id=made["area"], position=2)
    in_variant = placement(
        connection, made, specification_id=None, variant_id=made["variant"],
        variant_specification_id=made["specification"], position=3,
    )  # fmt: skip
    semester = add_value(connection, "time_span", document, "placement_id", at_module)
    workload = add_value(connection, "workload", document, "placement_id", at_module)
    add_value(connection, "time_span", document, "workload_id", workload)
    two_holders = violated(
        connection, "UPDATE time_span SET node_id = %s WHERE id = %s", made["module"], semester
    )
    second_first = violated(
        connection,
        "INSERT INTO time_span (id, document_id, placement_id, position, time_kind_scheme, time_kind_iri,"
        " origin_scheme, origin_iri, review_status_scheme, review_status_iri)"
        " VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s)",
        add_entity(connection, "time_span"), document, at_module, CV + "TimeKinds", CV + "time_gradeLevel",
        CV + "Origins", CV + "orig_human", CV + "ReviewStatuses", CV + "rev_proposed",
    )  # fmt: skip

    connection.execute("DELETE FROM variant WHERE id = %s", (made["variant"],))
    connection.execute("DELETE FROM node WHERE id = %s", (made["area"],))
    left_after_variant_and_place = connection.execute("SELECT id FROM placement ORDER BY position").fetchall()
    connection.execute("DELETE FROM node WHERE id = %s", (made["module"],))

    assert (two_holders, second_first) == ("time_span_one_holder", "time_span_position")
    assert left_after_variant_and_place == [(at_module,)]
    assert in_area != in_variant
    left = connection.execute(
        "SELECT (SELECT count(*) FROM placement), (SELECT count(*) FROM time_span),"
        " (SELECT count(*) FROM workload)"
    ).fetchone()
    assert left == (0, 0, 0)


def test_a_workload_names_its_placement_among_its_one_holder(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    at_module = placement(connection, made)
    workload = add_value(connection, "workload", made["document"], "placement_id", at_module)

    two_holders = violated(
        connection, "UPDATE workload SET node_id = %s WHERE id = %s", made["module"], workload
    )

    assert two_holders == "workload_one_holder"
