"""A rule's links and name (migration rule_link; plan M3a I, E10): a rules frame part is the rule, its IRI
given when the document is frozen, ``by_hand`` where an editor made it; what it applies to, its options and
what it requires are links to a node, a statement, a specification or a variant of its own document, each in
its place, each target once a role. A link goes with its rule and with its target."""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from app.db.migrate import migrate
from tests.db.l1 import (
    add_conversion,
    add_document,
    add_node,
    add_specification,
    add_statement,
    add_variant,
    seed_vocabulary,
)
from tests.db.test_l1_anchors import add_frame_part

pytestmark = pytest.mark.pg

RULE = {"verbatim": "Zwei aus vier.", "ruleKind": "selection"}


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_vocabulary(opened)
        yield opened


@pytest.fixture
def made(connection: psycopg.Connection) -> dict[str, Any]:
    made: dict[str, Any] = add_conversion(connection)
    document = made["document"] = add_document(connection, made)
    made["node"] = add_node(connection, document)
    made["statement"] = add_statement(connection, document, made["node"])
    made["specification"] = add_specification(connection, document)
    made["variant"] = add_variant(connection, made["specification"])
    made["rule"] = add_frame_part(connection, made, part_kind="rules", content=Jsonb(RULE))
    return made


def link(connection: psycopg.Connection, made: dict[str, Any], **columns: Any) -> None:
    values = {
        "frame_part_id": made["rule"], "document_id": made["document"], "role": "option", "position": 1,
    } | columns  # fmt: skip
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    connection.execute(
        f"INSERT INTO rule_link ({names}) VALUES ({marks})",  # noqa: S608 - the tests' own names
        tuple(values.values()),
    )


def violated(connection: psycopg.Connection, made: dict[str, Any], **columns: Any) -> str:
    with pytest.raises(errors.IntegrityError) as broken:
        link(connection, made, **columns)
    assert broken.value.diag.constraint_name is not None, broken.value
    return broken.value.diag.constraint_name


def test_a_rule_links_a_node_a_statement_a_specification_and_a_variant(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    link(connection, made, role="applies_to", specification_id=made["specification"])
    link(connection, made, role="option", node_id=made["node"])
    link(connection, made, role="option", position=2, variant_id=made["variant"],
         variant_specification_id=made["specification"])  # fmt: skip
    link(connection, made, role="requires", statement_id=made["statement"])

    found = connection.execute(
        "SELECT role, position, coalesce(node_id, statement_id, specification_id, variant_id) FROM rule_link"
        " ORDER BY role, position"
    ).fetchall()
    assert found == [
        ("applies_to", 1, made["specification"]), ("option", 1, made["node"]), ("option", 2, made["variant"]),
        ("requires", 1, made["statement"]),
    ]  # fmt: skip


# each a link breaking one constraint: its columns, the constraint's name
BROKEN: dict[str, tuple[dict[str, Any], str]] = {
    "a role the core has no property for": ({"role": "excludes", "node_id": "node"}, "rule_link_role_check"),
    "no target": ({}, "rule_link_one_target"),
    "a position below one": ({"position": 0, "node_id": "node"}, "rule_link_position_check"),
    "two targets": ({"node_id": "node", "statement_id": "statement"}, "rule_link_one_target"),
    "a variant without its specification": ({"variant_id": "variant"}, "rule_link_variant_named"),
}


@pytest.mark.parametrize("name", list(BROKEN))
def test_the_store_holds_what_a_link_is(
    connection: psycopg.Connection, made: dict[str, Any], name: str
) -> None:
    columns, constraint = BROKEN[name]
    # a target named by its kind stands for the fixture's row of that kind
    given = {key: made[value] if key.endswith("_id") else value for key, value in columns.items()}

    assert violated(connection, made, **given) == constraint


def test_a_role_takes_a_place_once_and_a_target_once(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    other = add_node(connection, made["document"], position=2)
    link(connection, made, node_id=made["node"])

    assert violated(connection, made, node_id=other) == "rule_link_pkey"
    assert violated(connection, made, position=2, node_id=made["node"]) == "rule_link_target"
    link(connection, made, role="applies_to", node_id=made["node"])  # the same target in another role


def test_a_link_s_target_is_of_its_rule_s_document(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    other_document = add_document(connection, add_conversion(connection, b"\x02" * 32))
    node = add_node(connection, other_document)
    specification = add_specification(connection, other_document)
    variant = add_variant(connection, specification)
    statement = add_statement(connection, other_document, node)

    assert violated(connection, made, node_id=node) == "rule_link_document_id_node_id_fkey"
    assert violated(connection, made, statement_id=statement) == "rule_link_document_id_statement_id_fkey"
    assert (
        violated(connection, made, specification_id=specification)
        == "rule_link_document_id_specification_id_fkey"
    )
    assert (
        violated(connection, made, variant_id=variant, variant_specification_id=specification)
        == "rule_link_document_id_variant_specification_id_fkey"
    )
    # a variant named with another specification of the document than its own
    assert (
        violated(connection, made, variant_id=variant, variant_specification_id=made["specification"])
        == "rule_link_variant_specification_id_variant_id_fkey"
    )


def test_a_link_goes_with_its_rule_and_with_its_target(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    link(connection, made, node_id=made["node"])
    link(connection, made, position=2, statement_id=made["statement"])
    link(connection, made, role="applies_to", specification_id=made["specification"])

    connection.execute("DELETE FROM statement WHERE id = %s", (made["statement"],))
    assert connection.execute("SELECT count(*) FROM rule_link").fetchone() == (2,)
    connection.execute("DELETE FROM node WHERE id = %s", (made["node"],))
    assert connection.execute("SELECT count(*) FROM rule_link").fetchone() == (1,)
    connection.execute("DELETE FROM frame_part WHERE id = %s", (made["rule"],))
    assert connection.execute("SELECT count(*) FROM rule_link").fetchone() == (0,)


def test_a_rule_s_iri_is_one_of_its_document_s(connection: psycopg.Connection, made: dict[str, Any]) -> None:
    iri = "https://example.org/doc/rule-1"
    connection.execute("UPDATE frame_part SET iri = %s WHERE id = %s", (iri, made["rule"]))
    second = add_frame_part(connection, made, part_kind="rules", content=Jsonb(RULE))

    with pytest.raises(errors.UniqueViolation) as taken:
        connection.execute("UPDATE frame_part SET iri = %s WHERE id = %s", (iri, second))
    with pytest.raises(errors.CheckViolation) as relative:
        connection.execute("UPDATE frame_part SET iri = 'rule-1' WHERE id = %s", (second,))
    assert taken.value.diag.constraint_name == "frame_part_document_id_iri_key"
    assert relative.value.diag.constraint_name == "frame_part_iri_check"


def test_a_frame_part_is_a_run_s_until_an_editor_makes_one(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    by_hand = add_frame_part(connection, made, part_kind="rules", content=Jsonb(RULE), by_hand=True)

    found = connection.execute(
        "SELECT id, by_hand FROM frame_part WHERE id = ANY(%s) ORDER BY position",
        ([made["rule"], by_hand],),
    ).fetchall()
    assert found == [(made["rule"], False), (by_hand, True)]


def test_an_unknown_target_is_refused(connection: psycopg.Connection, made: dict[str, Any]) -> None:
    assert violated(connection, made, node_id=uuid.uuid4()) == "rule_link_document_id_node_id_fkey"
