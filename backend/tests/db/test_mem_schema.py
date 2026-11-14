"""What an import from MEM-Schule keeps (migration 0030, plan M2): the catalogue of the plans the endpoint
holds, and at a document and its rows the MEM IRIs, classes and properties the export writes back."""

import shutil
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from app.db.migrate import MIGRATIONS, migrate
from tests.db.l1 import add_conversion, add_document, add_node, add_statement, seed_vocabulary

pytestmark = pytest.mark.pg

PLAN = "https://lp-sachsen.org/resource/lehrplan-141-1"
LP = "https://w3id.org/lehrplan/ontology/"


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_vocabulary(opened)
        yield opened


def a_plan(connection: psycopg.Connection, **columns: Any) -> None:
    values = {
        "iri": PLAN,
        "graph": "https://w3id.org/lehrplan/sn/data",
        "land_iri": LP + "LP_3000014",
        "title": "Lehrplan Deutsch Gymnasium",
        "class_iri": LP + "LP_0000438",
        "subjects": [LP + "LP_0000590"],
        "school_types": [],
        "licence": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": "FWU Lehrplan-Ontologie (MEM-Schule)",
    } | columns
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    connection.execute(
        f"INSERT INTO mem_plan ({names}) VALUES ({marks})",  # noqa: S608 - the test's own names
        tuple(values.values()),
    )


def test_the_catalogue_keeps_a_plan_once_with_when_it_was_read(connection: psycopg.Connection) -> None:
    a_plan(connection)

    read = connection.execute("SELECT read_at IS NOT NULL, subjects FROM mem_plan").fetchone()
    assert read == (True, [LP + "LP_0000590"])
    with pytest.raises(errors.UniqueViolation):
        a_plan(connection)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("iri", "ftp://lp-sachsen.org/x"),
        ("graph", "lp-sachsen"),
        ("title", ""),
        ("iri", "https://x/" + "a" * (2001 - len("https://x/"))),
    ],
    ids=["iri-scheme", "graph-scheme", "empty-title", "long-iri"],
)
def test_a_plan_s_iris_are_web_iris_and_its_title_says_something(
    connection: psycopg.Connection, column: str, value: str
) -> None:
    with pytest.raises(errors.CheckViolation):
        a_plan(connection, **{column: value})


# what Turtle's IRIREF refuses: the export writes <mem_iri> as it stands
@pytest.mark.parametrize("sign", [" ", "<", ">", '"', "{", "}", "|", "\\", "^", "`", "\x01", "\x1f", "\x7f"])
def test_an_iri_holds_no_sign_turtle_refuses_in_one(connection: psycopg.Connection, sign: str) -> None:
    with pytest.raises(errors.CheckViolation):
        a_plan(connection, iri=f"https://lp-sachsen.org/a{sign}b")


def test_every_mem_iri_column_refuses_what_the_plan_s_does(connection: psycopg.Connection) -> None:
    # one check, copied to five columns: the same expression at each
    checks = connection.execute(
        "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE contype = 'c' AND pg_get_constraintdef(oid) LIKE '%https?://%'"
        " AND (conrelid = 'mem_plan'::regclass OR pg_get_constraintdef(oid) LIKE '%mem_iri%')"
    ).fetchall()

    tables = sorted(table for table, _ in checks)
    assert tables == ["document", "mem_plan", "mem_plan", "node", "statement"]
    assert len({definition.split("~")[1].split(")")[0] for _, definition in checks}) == 1
    assert all("[:cntrl:]" in definition for _, definition in checks)


def test_an_iri_of_two_thousand_signs_is_taken(connection: psycopg.Connection) -> None:
    long = "https://lp-sachsen.org/"
    a_plan(connection, iri=long + "a" * (2000 - len(long)))


def test_a_conversion_takes_a_plan_once_but_its_draft_copies_carry_it_on(
    connection: psycopg.Connection,
) -> None:
    # two editors importing the same plan onto the same file at once: one wins (plan M2, E1)
    made = add_conversion(connection)
    first = add_document(connection, made, mem_iri=PLAN)

    with pytest.raises(errors.UniqueViolation):
        add_document(connection, made, mem_iri=PLAN)
    add_document(connection, made, mem_iri=PLAN, copy_of=first, iri="https://example.org/lp/1")  # its copy


def test_a_row_keeps_its_mem_iri_once_its_classes_and_properties(connection: psycopg.Connection) -> None:
    made = add_conversion(connection)
    document = add_document(connection, made)
    properties = {"description": "Die Lernenden …", "number": "1.2", "parents": [PLAN + "/teil-3"]}
    node = add_node(
        connection, document, mem_iri=PLAN + "/teil-1", mem_classes=[LP + "LP_0030050"],
        mem_properties=Jsonb(properties),
    )  # fmt: skip
    add_statement(connection, document, node, mem_iri=PLAN + "/teil-2")

    kept = connection.execute(
        "SELECT mem_classes, mem_properties FROM node WHERE id = %s", (node,)
    ).fetchone()
    assert kept == ([LP + "LP_0030050"], properties)
    plain = connection.execute("SELECT mem_classes, mem_properties FROM statement").fetchone()
    assert plain == ([], {})  # a row of no import holds nothing of MEM
    with pytest.raises(errors.UniqueViolation):
        add_node(connection, document, position=2, mem_iri=PLAN + "/teil-1")
    with pytest.raises(errors.UniqueViolation):
        add_statement(connection, document, node, position=2, mem_iri=PLAN + "/teil-2")


def test_a_document_keeps_what_the_import_named_it_by(connection: psycopg.Connection) -> None:
    made = add_conversion(connection)
    document = add_document(
        connection, made, mem_iri=PLAN, mem_subjects=[LP + "LP_0000590"],
        mem_licence="https://creativecommons.org/licenses/by-sa/4.0/", mem_attribution="FWU",
    )  # fmt: skip

    kept = connection.execute(
        "SELECT mem_subjects, mem_school_types, mem_licence, mem_attribution FROM document WHERE id = %s",
        (document,),
    ).fetchone()
    assert kept == ([LP + "LP_0000590"], [], "https://creativecommons.org/licenses/by-sa/4.0/", "FWU")
    unrelated = add_document(connection, add_conversion(connection, digest=bytes([2]) * 32))
    assert connection.execute(
        "SELECT mem_iri, mem_subjects FROM document WHERE id = %s", (unrelated,)
    ).fetchone() == (None, [])


def test_a_mem_iri_at_a_row_is_a_web_iri(connection: psycopg.Connection) -> None:
    made = add_conversion(connection)
    document = add_document(connection, made)

    with pytest.raises(errors.CheckViolation):
        add_node(connection, document, mem_iri="urn:uuid:" + str(uuid.uuid4()))


def test_rows_written_before_the_migration_hold_nothing_of_mem(database_url: str, tmp_path: Path) -> None:
    before = tmp_path / "migrations"
    before.mkdir()
    for migration in MIGRATIONS.iterdir():
        if migration.name.endswith(".sql") and migration.name < "0030":
            shutil.copyfile(str(migration), before / migration.name)
    migrate(database_url, before)
    with psycopg.connect(database_url, autocommit=True) as connection:
        seed_vocabulary(connection)
        made = add_conversion(connection)
        documents = [add_document(connection, made), add_document(connection, made)]  # one conversion
        node = add_node(connection, documents[0])
        add_statement(connection, documents[0], node)

        migrate(database_url)

        kept = connection.execute(
            "SELECT count(*) FILTER (WHERE mem_iri IS NULL AND mem_subjects = '{}') FROM document"
        ).fetchone()
        assert kept == (2,)
        assert connection.execute("SELECT mem_iri, mem_classes, mem_properties FROM node").fetchone() == (
            None, [], {},
        )  # fmt: skip
        statement = connection.execute("SELECT mem_iri, mem_classes, mem_properties FROM statement")
        assert statement.fetchone() == (None, [], {})


# Migration 0031 (plan M2-6): the plan's Land and class kept at the document, as the export states them;
# a frozen import takes the licence checked after it was made


FROZEN = {"iri": "https://example.org/lp/1", "frozen_at": datetime(2026, 11, 1, tzinfo=UTC)}
DOC_2 = "https://example.org/lp/2"


def test_a_document_keeps_its_plan_s_land_and_class_as_web_iris(connection: psycopg.Connection) -> None:
    made = add_conversion(connection)
    document = add_document(
        connection, made, mem_iri=PLAN, mem_land_iri=LP + "LP_3000014", mem_class_iri=LP + "LP_0000438"
    )

    kept = connection.execute(
        "SELECT mem_land_iri, mem_class_iri FROM document WHERE id = %s", (document,)
    ).fetchone()
    assert kept == (LP + "LP_3000014", LP + "LP_0000438")
    for column in ("mem_land_iri", "mem_class_iri"):
        with pytest.raises(errors.CheckViolation):
            connection.execute(
                f"UPDATE document SET {column} = 'https://w3id.org/a b' WHERE id = %s",  # noqa: S608 - a name
                (document,),
            )


def test_a_frozen_import_takes_a_new_licence_and_nothing_else(
    connection: psycopg.Connection,
) -> None:
    document = add_document(connection, add_conversion(connection), mem_iri=PLAN, **FROZEN)

    connection.execute(
        "UPDATE document SET mem_licence = 'https://creativecommons.org/licenses/by-sa/4.0/',"
        " updated_at = now() WHERE id = %s",
        (document,),
    )

    assert connection.execute("SELECT mem_licence FROM document WHERE id = %s", (document,)).fetchone() == (
        "https://creativecommons.org/licenses/by-sa/4.0/",
    )
    no_import = add_document(
        connection, add_conversion(connection, digest=bytes([2]) * 32), **FROZEN | {"iri": DOC_2}
    )
    with pytest.raises(errors.ObjectNotInPrerequisiteState):  # a frozen document of no import: no licence
        connection.execute("UPDATE document SET mem_licence = 'CC0' WHERE id = %s", (no_import,))
    for change in ("mem_land_iri = 'https://w3id.org/x'", "title = 'Anders'", "mem_attribution = 'FWU'"):
        with pytest.raises(errors.ObjectNotInPrerequisiteState):
            connection.execute(
                f"UPDATE document SET {change} WHERE id = %s",  # noqa: S608 - the test's own change
                (document,),
            )


def test_documents_imported_before_the_migration_take_their_plan_s_land_and_class(
    database_url: str, tmp_path: Path
) -> None:
    before = tmp_path / "migrations"
    before.mkdir()
    for migration in MIGRATIONS.iterdir():
        if migration.name.endswith(".sql") and migration.name < "0031":
            shutil.copyfile(str(migration), before / migration.name)
    migrate(database_url, before)
    with psycopg.connect(database_url, autocommit=True) as connection:
        seed_vocabulary(connection)
        a_plan(connection)
        draft = add_document(connection, add_conversion(connection), mem_iri=PLAN)
        frozen = add_document(
            connection, add_conversion(connection, digest=bytes([2]) * 32), mem_iri=PLAN, **FROZEN
        )
        gone = add_document(
            connection, add_conversion(connection, digest=bytes([3]) * 32), mem_iri=PLAN + "-weg"
        )  # its plan is no longer in the catalogue
        a_plan(connection, iri=PLAN + "-alt", land_iri="Sachsen")  # a Land the column would refuse
        odd = add_document(
            connection, add_conversion(connection, digest=bytes([4]) * 32), mem_iri=PLAN + "-alt"
        )

        migrate(database_url)

        kept = connection.execute(
            "SELECT id, mem_land_iri, mem_class_iri FROM document ORDER BY id"
        ).fetchall()
        assert {row[0]: row[1:] for row in kept} == {
            draft: (LP + "LP_3000014", LP + "LP_0000438"),
            frozen: (LP + "LP_3000014", LP + "LP_0000438"),
            gone: (None, None),
            odd: (None, LP + "LP_0000438"),
        }
        with pytest.raises(errors.ObjectNotInPrerequisiteState):  # the frozen one stays frozen
            connection.execute("UPDATE document SET title = 'Anders' WHERE id = %s", (frozen,))
