"""The gold standard's tables (migration gold, plan H-3 §3.1): a sample of one document, drawn once per kind
and seed; its items, each pointing at one statement, node or block; and the judgements of an item, one
for each account - a verdict with its reasons from a fixed list, or a block's count alone."""

from collections.abc import Iterator
from typing import Any, get_args
from uuid import UUID

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from app.db.gold import Reason, SampleKind, Verdict
from app.db.migrate import migrate
from tests.db.l1 import add_conversion, add_document, listed_values, seed_vocabulary

pytestmark = pytest.mark.pg

HASH = "a" * 64


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_vocabulary(opened)
        yield opened


@pytest.fixture
def made(connection: psycopg.Connection) -> dict[str, Any]:
    made: dict[str, Any] = add_conversion(connection)
    made["document"] = add_document(connection, made)
    return made


def insert(connection: psycopg.Connection, table: str, values: dict[str, Any]) -> Any:
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    returning = " RETURNING id" if table != "gold_judgement" else ""
    found = connection.execute(
        f"INSERT INTO {table} ({names}) VALUES ({marks}){returning}",  # noqa: S608 - the tests' own names
        tuple(values.values()),
    )
    return found.fetchone()[0] if returning else None  # type: ignore[index]


def a_sample(connection: psycopg.Connection, made: dict[str, Any], **columns: Any) -> int:
    values = {
        "kind": "statement",
        "document_id": made["document"],
        "label": "pilot-1",
        "seed": "curricarta-h3",
        "size": 40,
        "frame": Jsonb({"learningOutcome": 3}),
        "drawn_by": made["owner"],
    } | columns
    return int(insert(connection, "gold_sample", values))


def an_item(connection: psycopg.Connection, sample: int, place: int = 1, **columns: Any) -> int:
    values = {
        "sample_id": sample,
        "stratum": "learningOutcome",
        "place": place,
        "statement_id": UUID(int=place),
        "text_hash": HASH,
        "first_block": "p1-b1",
    } | columns
    return int(insert(connection, "gold_item", values))


def a_judgement(connection: psycopg.Connection, item: int, account: UUID, **columns: Any) -> None:
    values = {"item_id": item, "judged_by": account, "verdict": "correct"} | columns
    insert(connection, "gold_judgement", values)


def test_the_kinds_verdicts_and_reasons_are_the_listed_ones(connection: psycopg.Connection) -> None:
    assert listed_values(connection, "gold_sample", "kind") == set(get_args(SampleKind))
    assert listed_values(connection, "gold_judgement", "verdict") == set(get_args(Verdict))
    assert listed_values(connection, "gold_judgement", "reasons") == set(get_args(Reason))


def test_a_sample_is_one_per_document_kind_and_seed(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    a_sample(connection, made)
    a_sample(connection, made, kind="block")  # another kind
    a_sample(connection, made, seed="another-seed")  # another seed

    with pytest.raises(errors.UniqueViolation) as refused:
        a_sample(connection, made, label="pilot-2", size=10)

    assert refused.value.diag.constraint_name == "gold_sample_document_id_kind_seed_key"


@pytest.mark.parametrize(
    "columns",
    [
        {"statement_id": None},
        {"node_id": UUID(int=9)},
        {"block_id": "p1-b2"},
        {"statement_id": None, "node_id": UUID(int=9), "block_id": "p1-b2"},
    ],
    ids=["none", "statement-and-node", "statement-and-block", "node-and-block"],
)
def test_an_item_points_at_exactly_one_thing(
    connection: psycopg.Connection, made: dict[str, Any], columns: dict[str, Any]
) -> None:
    sample = a_sample(connection, made)
    an_item(connection, sample, 1)
    an_item(connection, sample, 2, statement_id=None, node_id=UUID(int=2))
    an_item(connection, sample, 3, statement_id=None, block_id="p1-b3", text_hash=None, first_block=None)

    with pytest.raises(errors.CheckViolation) as refused:
        an_item(connection, sample, 4, **columns)

    assert refused.value.diag.constraint_name == "gold_item_one_thing"


def test_a_correct_verdict_has_no_reason(connection: psycopg.Connection, made: dict[str, Any]) -> None:
    item = an_item(connection, a_sample(connection, made))

    with pytest.raises(errors.CheckViolation) as refused:
        a_judgement(connection, item, made["owner"], reasons=["boundary"])
    a_judgement(connection, item, made["owner"])

    assert refused.value.diag.constraint_name == "gold_judgement_correct_without_reason"
    assert connection.execute("SELECT verdict, reasons FROM gold_judgement").fetchall() == [("correct", [])]


@pytest.mark.parametrize("verdict", ["imprecise", "wrong"])
def test_a_verdict_other_than_correct_names_a_reason(
    connection: psycopg.Connection, made: dict[str, Any], verdict: str
) -> None:
    item = an_item(connection, a_sample(connection, made))

    with pytest.raises(errors.CheckViolation) as refused:
        a_judgement(connection, item, made["owner"], verdict=verdict)
    a_judgement(connection, item, made["owner"], verdict=verdict, reasons=["boundary", "node"])

    assert refused.value.diag.constraint_name == "gold_judgement_others_with_reason"
    assert connection.execute("SELECT reasons FROM gold_judgement").fetchall() == [(["boundary", "node"],)]


def test_a_reason_outside_the_list_is_refused(connection: psycopg.Connection, made: dict[str, Any]) -> None:
    item = an_item(connection, a_sample(connection, made))

    with pytest.raises(errors.CheckViolation) as refused:
        a_judgement(connection, item, made["owner"], verdict="wrong", reasons=["missed", "typo"])

    assert refused.value.diag.constraint_name == "gold_judgement_reasons_check"


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"verdict": "correct", "expected": 2}, "gold_judgement_verdict_or_count"),
        ({"verdict": None}, "gold_judgement_verdict_or_count"),
        ({"verdict": None, "expected": -1}, "gold_judgement_expected_check"),
        ({"verdict": None, "expected": 501}, "gold_judgement_expected_check"),
    ],
    ids=["verdict-and-count", "neither", "count-below-0", "count-above-500"],
)
def test_a_block_is_judged_by_a_count_alone(
    connection: psycopg.Connection, made: dict[str, Any], columns: dict[str, Any], constraint: str
) -> None:
    sample = a_sample(connection, made, kind="block")
    item = an_item(connection, sample, statement_id=None, block_id="p1-b1", text_hash=None, first_block=None)

    with pytest.raises(errors.CheckViolation) as refused:
        a_judgement(connection, item, made["owner"], **columns)
    a_judgement(connection, item, made["owner"], verdict=None, expected=0)

    assert refused.value.diag.constraint_name == constraint
    assert connection.execute("SELECT verdict, expected FROM gold_judgement").fetchall() == [(None, 0)]


@pytest.mark.parametrize("label", ["pilot 1", " pilot", "Pilot-1", "-pilot", "p" * 41])
def test_a_label_with_a_space_is_refused(
    connection: psycopg.Connection, made: dict[str, Any], label: str
) -> None:
    # the report names a document by its label alone: no title, no wording, can pass through it
    a_sample(connection, made, label="p" * 40)

    with pytest.raises(errors.CheckViolation) as refused:
        a_sample(connection, made, label=label, seed="another")

    assert refused.value.diag.constraint_name == "gold_sample_label_check"


def test_a_document_taken_away_takes_its_samples_along(
    connection: psycopg.Connection, made: dict[str, Any]
) -> None:
    other = add_document(connection, made)
    kept = an_item(connection, a_sample(connection, made | {"document": other}))
    item = an_item(connection, a_sample(connection, made))
    a_judgement(connection, item, made["owner"])
    a_judgement(connection, kept, made["owner"])

    connection.execute("DELETE FROM document WHERE id = %s", (made["document"],))

    assert connection.execute("SELECT document_id FROM gold_sample").fetchall() == [(other,)]
    assert connection.execute("SELECT id FROM gold_item").fetchall() == [(kept,)]
    assert connection.execute("SELECT item_id FROM gold_judgement").fetchall() == [(kept,)]
