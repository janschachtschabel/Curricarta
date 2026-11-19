"""The second layer's values (migration l2_values; plan M3a D1): a level, a time span, a workload, each at
one holder of its document - a node, a specification, a statement or a rule's frame part for a level, a
workload for the time span it is given in. The database holds what is asked, the order of the numbers,
which vocabulary each column takes and that the holder is of the same document; what the core's shapes
say of the values beside (cur-shapes.ttl) X5 checks. With its holder a value goes."""

import uuid
from collections.abc import Iterator
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
from tests.db.l2 import FKF, LVL, ValueTable, add_value, seed_l2_vocabulary

pytestmark = pytest.mark.pg

# The holders each table takes now: those of later packages come with their own migrations
HOLDERS: dict[ValueTable, tuple[str, ...]] = {
    "time_span": ("node_id", "specification_id", "workload_id"),
    "workload": ("node_id", "specification_id"),
    "level_assignment": ("node_id", "statement_id", "specification_id", "frame_part_id"),
}
PAIRS = [(table, holder) for table, holders in HOLDERS.items() for holder in holders]


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_l2_vocabulary(opened)
        yield opened


def holders(connection: psycopg.Connection, made: dict[str, Any]) -> dict[str, uuid.UUID]:
    """A new document of ``made``'s conversion, and one row of each kind that holds values in it."""
    document = add_document(connection, made)
    node = add_node(connection, document)
    frame_part = add_entity(connection, "frame_part")
    connection.execute(
        "INSERT INTO frame_part (id, document_id, part_kind, content, origin_scheme, origin_iri,"
        " review_status_scheme, review_status_iri, position)"
        " VALUES (%s, %s, 'rules', '{}', %s, %s, %s, %s, 1)",
        (
            frame_part,
            document,
            CV + "Origins",
            CV + "orig_source",
            CV + "ReviewStatuses",
            CV + "rev_proposed",
        ),
    )
    specification = add_specification(connection, document)
    return {
        "document_id": document,
        "node_id": node,
        "statement_id": add_statement(connection, document, node),
        "specification_id": specification,
        "frame_part_id": frame_part,
        "workload_id": add_value(connection, "workload", document, "specification_id", specification),
    }


@pytest.fixture
def held(connection: psycopg.Connection) -> dict[str, uuid.UUID]:
    return holders(connection, add_conversion(connection))


def violated(
    connection: psycopg.Connection, table: ValueTable, held: dict[str, uuid.UUID], **columns: Any
) -> str:
    """The name of the constraint a row of ``table`` at the held node (or specification) with ``columns``
    breaks."""
    holder = "node_id" if "node_id" in HOLDERS[table] else "specification_id"
    with pytest.raises(errors.IntegrityError) as broken:
        add_value(connection, table, held["document_id"], holder, held[holder], **columns)
    assert broken.value.diag.constraint_name is not None, broken.value
    return broken.value.diag.constraint_name


@pytest.mark.parametrize(("table", "holder"), PAIRS, ids=[f"{t}-{h}" for t, h in PAIRS])
def test_a_value_stands_at_each_holder_its_table_takes(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], table: ValueTable, holder: str
) -> None:
    value = add_value(connection, table, held["document_id"], holder, held[holder], position=2)

    found = connection.execute(f"SELECT {holder} FROM {table} WHERE id = %s", (value,)).fetchone()  # noqa: S608
    assert found == (held[holder],)


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("time_span", "time_kind_iri"),
        ("time_span", "time_kind_scheme"),
        ("workload", "amount"),
        ("workload", "unit_iri"),
        ("workload", "unit_scheme"),
        ("level_assignment", "level_iri"),
    ],
)
def test_a_value_has_what_its_table_asks(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], table: ValueTable, column: str
) -> None:
    holder = "node_id"
    with pytest.raises(errors.NotNullViolation) as missing:
        add_value(connection, table, held["document_id"], holder, held[holder], **{column: None})

    assert missing.value.diag.column_name == column


# each a row breaking one constraint: its table, its columns, the constraint's name
VOCABULARY: dict[str, tuple[ValueTable, dict[str, Any], str]] = {
    "a time kind of the units": (
        "time_span", {"time_kind_iri": CV + "unit_lesson"}, "time_span_time_kind_scheme_time_kind_iri_fkey"
    ),
    "a time relation of the level relations": (
        "time_span",
        {"time_relation_scheme": CV + "TimeRelations", "time_relation_iri": CV + "lrel_target"},
        "time_span_time_relation_scheme_time_relation_iri_fkey",
    ),
    "a time relation without its scheme": (
        "time_span", {"time_relation_iri": CV + "trel_during"}, "time_span_time_relation_named"
    ),
    "a unit of the time kinds": (
        "workload", {"unit_iri": CV + "time_gradeLevel"}, "workload_unit_scheme_unit_iri_fkey"
    ),
    "a workload kind of the units": (
        "workload",
        {"workload_kind_scheme": CV + "WorkloadKinds", "workload_kind_iri": CV + "unit_lesson"},
        "workload_workload_kind_scheme_workload_kind_iri_fkey",
    ),
    "a level relation of the dimensions": (
        "level_assignment",
        {"relation_scheme": CV + "LevelRelations", "relation_iri": CV + "dim_stage"},
        "level_assignment_relation_scheme_relation_iri_fkey",
    ),
    "a level dimension of the relations": (
        "level_assignment",
        {"dimension_scheme": CV + "LevelDimensions", "dimension_iri": CV + "lrel_target"},
        "level_assignment_dimension_scheme_dimension_iri_fkey",
    ),
    "a level no vocabulary holds": (
        "level_assignment", {"level_iri": LVL + "EQF-9"}, "level_assignment_level_iri_fkey"
    ),
    "a level no level concept": (
        "level_assignment", {"level_iri": CV + "unit_lesson"}, "level_assignment_level_fits"
    ),
    "a level's end no level concept": (
        "level_assignment", {"level_to_iri": FKF + "fkf-kenntnisse"}, "level_assignment_level_to_fits"
    ),
    "a competence dimension no dimension": (
        "level_assignment",
        {"competence_dimension_iri": LVL + "EQF-5"},
        "level_assignment_competence_dimension_fits",
    ),
    # no phase vocabulary is one the profiles share (plan M3a D1): no time span is a named phase yet
    "a named phase": ("time_span", {"time_kind_iri": CV + "time_phase"}, "time_span_no_phase"),
}  # fmt: skip


@pytest.mark.parametrize("name", list(VOCABULARY))
def test_a_value_is_of_its_column_s_vocabulary(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], name: str
) -> None:
    table, columns, constraint = VOCABULARY[name]

    assert violated(connection, table, held, **columns) == constraint


def test_a_value_of_its_column_s_vocabulary_stands(
    connection: psycopg.Connection, held: dict[str, uuid.UUID]
) -> None:
    document, node = held["document_id"], held["node_id"]
    add_value(connection, "time_span", document, "node_id", node, time_relation_scheme=CV + "TimeRelations",
              time_relation_iri=CV + "trel_during")  # fmt: skip
    add_value(connection, "workload", document, "node_id", node, workload_kind_scheme=CV + "WorkloadKinds",
              workload_kind_iri=CV + "wl_guidanceValue", minutes_per_unit=45, is_recommendation=True,
              total=True)  # fmt: skip
    add_value(connection, "level_assignment", document, "node_id", node, level_to_iri=LVL + "EQF-5",
              relation_scheme=CV + "LevelRelations", relation_iri=CV + "lrel_target",
              dimension_scheme=CV + "LevelDimensions", dimension_iri=CV + "dim_stage",
              competence_dimension_iri=FKF + "fkf-kenntnisse")  # fmt: skip


@pytest.mark.parametrize(("table", "holder"), PAIRS, ids=[f"{t}-{h}" for t, h in PAIRS])
def test_a_value_s_holder_is_of_its_document(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], table: ValueTable, holder: str
) -> None:
    other = holders(connection, add_conversion(connection, b"\x02" * 32))

    with pytest.raises(errors.ForeignKeyViolation) as foreign:
        add_value(connection, table, held["document_id"], holder, other[holder])

    assert foreign.value.diag.constraint_name == f"{table}_document_id_{holder}_fkey"


@pytest.mark.parametrize("table", list(HOLDERS))
def test_a_value_has_one_holder(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], table: ValueTable
) -> None:
    with pytest.raises(errors.CheckViolation) as none:
        add_value(connection, table, held["document_id"], "node_id", None)
    with pytest.raises(errors.CheckViolation) as two:
        add_value(connection, table, held["document_id"], "node_id", held["node_id"],
                  specification_id=held["specification_id"])  # fmt: skip

    assert none.value.diag.constraint_name == two.value.diag.constraint_name == f"{table}_one_holder"


NUMBERS: dict[str, tuple[ValueTable, dict[str, Any], str]] = {
    "a span that ends before it begins": (
        "time_span",
        {"span_from": 7, "span_to": 6},
        "time_span_span_order",
    ),
    "a span from below zero": ("time_span", {"span_from": -1}, "time_span_span_from_check"),
    "a span to below zero": ("time_span", {"span_from": None, "span_to": -1}, "time_span_span_to_check"),
    "an amount whose end is below it": ("workload", {"amount": 51, "amount_to": 50}, "workload_amount_order"),
    "an amount below zero": ("workload", {"amount": -1, "amount_to": None}, "workload_amount_check"),
    "no minutes in a unit": ("workload", {"minutes_per_unit": 0}, "workload_minutes_per_unit_check"),
    # numeric takes NaN and Infinity, which every order above lets pass: no number of a document is either
    "an amount not a number": ("workload", {"amount": "NaN", "amount_to": None}, "workload_amount_finite"),
    "an endless amount": ("workload", {"amount": "Infinity", "amount_to": None}, "workload_amount_finite"),
    "an amount's end not a number": ("workload", {"amount_to": "NaN"}, "workload_amount_to_finite"),
    "a span from no number": (
        "time_span",
        {"span_from": "NaN", "span_to": None},
        "time_span_span_from_finite",
    ),
    "a span from the endless": (
        "time_span",
        {"span_from": "Infinity", "span_to": None},
        "time_span_span_from_finite",
    ),
    "a span to no number": ("time_span", {"span_to": "NaN"}, "time_span_span_to_finite"),
    "a span to the endless": ("time_span", {"span_to": "Infinity"}, "time_span_span_to_finite"),
    "a position below one": ("level_assignment", {"position": 0}, "level_assignment_position_check"),
}


@pytest.mark.parametrize("name", list(NUMBERS))
def test_a_value_s_numbers_keep_their_order(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], name: str
) -> None:
    table, columns, constraint = NUMBERS[name]

    assert violated(connection, table, held, **columns) == constraint


def test_open_ends_and_equal_ends_stand(connection: psycopg.Connection, held: dict[str, uuid.UUID]) -> None:
    document, node = held["document_id"], held["node_id"]
    add_value(connection, "time_span", document, "node_id", node, span_from=None, span_to=None)
    add_value(connection, "time_span", document, "node_id", node, position=2, span_from=3, span_to=3)
    add_value(connection, "workload", document, "node_id", node, amount=0, amount_to=None)


@pytest.mark.parametrize("table", list(HOLDERS))
def test_a_holder_s_values_of_a_kind_take_a_position_each(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], table: ValueTable
) -> None:
    document = held["document_id"]
    add_value(connection, table, document, "node_id", held["node_id"])
    add_value(connection, table, document, "specification_id", held["specification_id"], position=2)

    with pytest.raises(errors.UniqueViolation) as twice:
        add_value(connection, table, document, "node_id", held["node_id"])

    assert twice.value.diag.constraint_name == f"{table}_position"


def test_a_rule_s_value_names_the_rule(connection: psycopg.Connection, held: dict[str, uuid.UUID]) -> None:
    with pytest.raises(errors.CheckViolation):
        add_value(connection, "workload", held["document_id"], "node_id", held["node_id"],
                  origin_iri=CV + "orig_rule")  # fmt: skip
    add_value(connection, "workload", held["document_id"], "node_id", held["node_id"],
              origin_iri=CV + "orig_rule", rule_id="ue-45")  # fmt: skip


@pytest.mark.parametrize(("table", "holder"), PAIRS, ids=[f"{t}-{h}" for t, h in PAIRS])
def test_with_its_holder_the_value_goes(
    connection: psycopg.Connection, held: dict[str, uuid.UUID], table: ValueTable, holder: str
) -> None:
    value = add_value(connection, table, held["document_id"], holder, held[holder], position=2)
    kept = add_value(
        connection, "level_assignment", held["document_id"], "node_id", held["node_id"], position=3
    )
    holding = {"node_id": "node", "statement_id": "statement", "specification_id": "specification",
               "frame_part_id": "frame_part", "workload_id": "workload"}[holder]  # fmt: skip

    connection.execute(f"DELETE FROM {holding} WHERE id = %s", (held[holder],))  # noqa: S608 - the test's names

    gone = connection.execute(f"SELECT count(*) FROM {table} WHERE id = %s", (value,)).fetchone()  # noqa: S608
    assert gone == (0,)
    if holder != "node_id":
        assert connection.execute(
            "SELECT count(*) FROM level_assignment WHERE id = %s", (kept,)
        ).fetchone() == (1,)


def test_a_value_is_an_entity_of_its_own_kind(
    connection: psycopg.Connection, held: dict[str, uuid.UUID]
) -> None:
    wrong = add_entity(connection, "node")

    with pytest.raises(errors.ForeignKeyViolation):
        connection.execute(
            "INSERT INTO level_assignment (id, document_id, node_id, position, level_iri, origin_scheme,"
            " origin_iri, review_status_scheme, review_status_iri)"
            " VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s)",
            (wrong, held["document_id"], held["node_id"], LVL + "EQF-4", CV + "Origins", CV + "orig_human",
             CV + "ReviewStatuses", CV + "rev_proposed"),
        )  # fmt: skip
