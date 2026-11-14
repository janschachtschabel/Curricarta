"""The accounting's tables (migration usage, plan M1 5.4, Festlegungen "Kosten"): what an account
may spend, what each model request cost, and what is held for the requests yet to be answered."""

import shutil
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import errors

from app.core.ids import new_id
from app.db.migrate import MIGRATIONS, migrate

pytestmark = pytest.mark.pg


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        yield opened


def add_account(connection: psycopg.Connection) -> UUID:
    account = new_id()
    connection.execute(
        "INSERT INTO account (id, name) VALUES (%s, %s)", (account, f"konto-{account.hex[-12:]}")
    )
    return account


def add_job(connection: psycopg.Connection, account: UUID) -> UUID:
    job = new_id()
    connection.execute("INSERT INTO job_lane (lane) VALUES (%s) ON CONFLICT DO NOTHING", (str(account),))
    connection.execute(
        "INSERT INTO job (id, kind, lane) VALUES (%s, 'extraction.x1', %s)", (job, str(account))
    )
    return job


def insert(connection: psycopg.Connection, table: str, values: dict[str, Any]) -> int:
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    row = connection.execute(
        f"INSERT INTO {table} ({names}) VALUES ({marks}) RETURNING id",  # noqa: S608 - the test's own names
        tuple(values.values()),
    ).fetchone()
    assert row is not None
    return int(row[0])


def add_usage(connection: psycopg.Connection, account: UUID, **columns: Any) -> int:
    values = {
        "account_id": account,
        "purpose": "x1",
        "model": "gpt-6-luna",
        "input_tokens": 1_200,
        "cached_input_tokens": 1_000,
        "output_tokens": 300,
        "requests": 1,
        "unanswered_requests": 0,
        "estimated": False,
        "cached_input_weight": 1,
        "output_weight": 1,
        **columns,
    }
    return insert(connection, "llm_usage", values)


def add_reservation(connection: psycopg.Connection, account: UUID, job: UUID, **columns: Any) -> int:
    values = {
        "account_id": account,
        "job_id": job,
        "purpose": "x1",
        "model": "gpt-6-luna",
        "input_tokens": 1_320,
        "output_tokens": 16_000,
        "cached_input_weight": 1,
        "output_weight": 1,
        **columns,
    }
    return insert(connection, "usage_reservation", values)


def test_an_account_s_limits_are_counts_or_none(connection: psycopg.Connection) -> None:
    # NULL: no limit; tokens beyond what an integer holds
    unlimited, limited = add_account(connection), add_account(connection)
    connection.execute("INSERT INTO quota (account_id) VALUES (%s)", (unlimited,))
    connection.execute(
        "INSERT INTO quota (account_id, token_limit, page_limit) VALUES (%s, %s, 0)", (limited, 5 * 10**9)
    )

    rows = connection.execute("SELECT account_id, token_limit, page_limit FROM quota").fetchall()

    # by account, not by id: two ids of one millisecond sort by chance
    assert {row[0]: row[1:] for row in rows} == {unlimited: (None, None), limited: (5 * 10**9, 0)}
    assert len(rows) == 2


@pytest.mark.parametrize("column", ["token_limit", "page_limit"])
def test_a_limit_below_nothing_is_refused(connection: psycopg.Connection, column: str) -> None:
    account = add_account(connection)

    with pytest.raises(errors.CheckViolation):
        connection.execute(
            f"INSERT INTO quota (account_id, {column}) VALUES (%s, -1)",  # noqa: S608 - the test's names
            (account,),
        )


def test_an_account_has_one_quota_and_takes_it_along(connection: psycopg.Connection) -> None:
    account = add_account(connection)
    connection.execute("INSERT INTO quota (account_id, token_limit) VALUES (%s, 10)", (account,))

    with pytest.raises(errors.UniqueViolation):
        connection.execute("INSERT INTO quota (account_id, token_limit) VALUES (%s, 20)", (account,))
    connection.execute("DELETE FROM account WHERE id = %s", (account,))

    assert connection.execute("SELECT count(*) FROM quota").fetchone() == (0,)


def test_a_request_s_cost_is_kept_with_its_job_run_and_purpose(connection: psycopg.Connection) -> None:
    account = add_account(connection)
    job, run = add_job(connection, account), new_id()

    usage = add_usage(connection, account, job_id=job, run_id=run)

    row = connection.execute(
        "SELECT account_id, job_id, run_id, purpose, model, input_tokens, cached_input_tokens, output_tokens,"
        " requests, unanswered_requests, estimated, booked_at IS NOT NULL FROM llm_usage WHERE id = %s",
        (usage,),
    ).fetchone()
    assert row == (account, job, run, "x1", "gpt-6-luna", 1_200, 1_000, 300, 1, 0, False, True)


@pytest.mark.parametrize(
    "column", ["input_tokens", "cached_input_tokens", "output_tokens", "requests", "unanswered_requests"]
)
def test_a_count_below_nothing_is_refused(connection: psycopg.Connection, column: str) -> None:
    account = add_account(connection)

    with pytest.raises(errors.CheckViolation):
        add_usage(connection, account, **{column: -1})


def test_more_input_from_the_cache_than_input_is_refused(connection: psycopg.Connection) -> None:
    account = add_account(connection)

    add_usage(connection, account, input_tokens=500, cached_input_tokens=500)
    with pytest.raises(errors.CheckViolation):
        add_usage(connection, account, input_tokens=500, cached_input_tokens=501)


def test_a_cost_says_whether_it_was_estimated(connection: psycopg.Connection) -> None:
    # the writer says it: a reservation booked for a request nobody answered is not a count
    account = add_account(connection)

    with pytest.raises(errors.NotNullViolation):
        connection.execute(
            "INSERT INTO llm_usage (account_id, purpose, model, input_tokens, cached_input_tokens,"
            " output_tokens, requests, unanswered_requests, cached_input_weight, output_weight)"
            " VALUES (%s, 'x1', 'gpt-6-luna', 1, 0, 1, 1, 0, 1, 1)",
            (account,),
        )
    estimated = add_usage(connection, account, requests=0, unanswered_requests=1, estimated=True)

    flag = connection.execute("SELECT estimated FROM llm_usage WHERE id = %s", (estimated,)).fetchone()
    assert flag == (True,)


@pytest.mark.parametrize(
    ("column", "value"),
    [("purpose", ""), ("purpose", "X1"), ("purpose", "x1 x2"), ("model", ""), ("model", "m" * 201)],
    ids=["empty-purpose", "upper-purpose", "spaced-purpose", "empty-model", "long-model"],
)
def test_a_cost_names_its_purpose_and_model_plainly(
    connection: psycopg.Connection, column: str, value: str
) -> None:
    account = add_account(connection)

    with pytest.raises(errors.CheckViolation):
        add_usage(connection, account, **{column: value})
    with pytest.raises(errors.CheckViolation):
        add_reservation(connection, account, add_job(connection, account), **{column: value})


def test_a_cost_is_charged_to_an_account_that_keeps_it(connection: psycopg.Connection) -> None:
    account = add_account(connection)
    add_usage(connection, account)

    with pytest.raises(errors.ForeignKeyViolation):
        add_usage(connection, new_id())
    with pytest.raises(errors.ForeignKeyViolation):  # what it spent stays on record
        connection.execute("DELETE FROM account WHERE id = %s", (account,))


def test_a_cost_outlives_its_job(connection: psycopg.Connection) -> None:
    # like the audit log: a record of what was spent, whatever becomes of the job and its run
    account = add_account(connection)
    job = add_job(connection, account)
    add_usage(connection, account, job_id=job, run_id=new_id())

    connection.execute("DELETE FROM job WHERE id = %s", (job,))

    assert connection.execute("SELECT job_id FROM llm_usage").fetchall() == [(job,)]


def test_a_reservation_holds_input_and_output_for_a_job_of_an_account(connection: psycopg.Connection) -> None:
    account = add_account(connection)
    job, run = add_job(connection, account), new_id()

    reservation = add_reservation(connection, account, job, run_id=run)

    row = connection.execute(
        "SELECT account_id, job_id, run_id, purpose, model, input_tokens, output_tokens,"
        " created_at IS NOT NULL FROM usage_reservation WHERE id = %s",
        (reservation,),
    ).fetchone()
    assert row == (account, job, run, "x1", "gpt-6-luna", 1_320, 16_000, True)


@pytest.mark.parametrize("column", ["input_tokens", "output_tokens"])
def test_a_reservation_holds_something(connection: psycopg.Connection, column: str) -> None:
    account = add_account(connection)
    job = add_job(connection, account)

    with pytest.raises(errors.CheckViolation):
        add_reservation(connection, account, job, **{column: 0})


@pytest.mark.parametrize("column", ["account_id", "job_id"])
def test_a_reservation_names_its_job_and_account(connection: psycopg.Connection, column: str) -> None:
    account = add_account(connection)
    job = add_job(connection, account)

    with pytest.raises(errors.NotNullViolation):
        add_reservation(connection, account, job, **{column: None})
    with pytest.raises(errors.ForeignKeyViolation):
        add_reservation(connection, account, job, **{column: new_id()})


def test_a_job_or_account_holding_a_reservation_stays_until_it_is_booked(
    connection: psycopg.Connection,
) -> None:
    # an open reservation is booked as spent (app/usage/ledger.py), never let go with its job
    account = add_account(connection)
    job = add_job(connection, account)
    add_reservation(connection, account, job)

    with pytest.raises(errors.ForeignKeyViolation):
        connection.execute("DELETE FROM job WHERE id = %s", (job,))
    with pytest.raises(errors.ForeignKeyViolation):
        connection.execute("DELETE FROM account WHERE id = %s", (account,))


# An index whose first key column is the column: the ledger sums an account's costs and
# reservations for each request it reserves, and books an abandoned job's reservations
_LEADING = """
SELECT EXISTS (
    SELECT FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
    WHERE i.indrelid = %s::regclass AND a.attname = %s
)
"""


@pytest.mark.parametrize(
    ("table", "column"),
    [("llm_usage", "account_id"), ("usage_reservation", "account_id"), ("usage_reservation", "job_id")],
)
def test_the_ledger_finds_its_rows_by_an_index(
    connection: psycopg.Connection, table: str, column: str
) -> None:
    assert connection.execute(_LEADING, (table, column)).fetchone() == (True,)


LUNA = {"cached_input_weight": Decimal("0.1"), "output_weight": Decimal("5")}


def charged(connection: psycopg.Connection, table: str, row: int) -> int:
    found = connection.execute(
        f"SELECT charged_tokens FROM {table} WHERE id = %s",  # noqa: S608 - the test's own names
        (row,),
    ).fetchone()
    assert found is not None
    return int(found[0])


def test_a_cost_is_charged_its_cached_input_and_output_by_their_weights(
    connection: psycopg.Connection,
) -> None:
    account = add_account(connection)

    weighed = add_usage(connection, account, **LUNA)  # 1 200 in, 1 000 of it cached, 300 out
    alike = add_usage(connection, account)
    part = add_usage(connection, account, input_tokens=3, cached_input_tokens=3, output_tokens=0, **LUNA)

    assert charged(connection, "llm_usage", weighed) == 200 + 100 + 1_500
    assert charged(connection, "llm_usage", alike) == 1_500
    assert charged(connection, "llm_usage", part) == 1  # a part of a token is a token (app/llm/metering.py)


def test_a_reservation_holds_its_input_whole_and_its_output_weighed(connection: psycopg.Connection) -> None:
    account = add_account(connection)

    held = add_reservation(connection, account, add_job(connection, account), **LUNA)

    assert charged(connection, "usage_reservation", held) == 1_320 + 80_000


@pytest.mark.parametrize("table", ["llm_usage", "usage_reservation"])
@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("cached_input_weight", "1.5"),
        ("cached_input_weight", "-0.1"),
        ("output_weight", "0"),
        ("output_weight", "101"),
    ],
    ids=["cached-above-input", "cached-negative", "output-free", "output-past-hundred"],
)
def test_a_weight_out_of_its_bounds_is_refused(
    connection: psycopg.Connection, table: str, column: str, value: str
) -> None:
    account = add_account(connection)

    with pytest.raises(errors.CheckViolation):
        if table == "llm_usage":
            add_usage(connection, account, **{column: Decimal(value)})
        else:
            add_reservation(connection, account, add_job(connection, account), **{column: Decimal(value)})


@pytest.mark.parametrize("table", ["llm_usage", "usage_reservation"])
def test_a_row_s_weights_are_never_none(connection: psycopg.Connection, table: str) -> None:
    account = add_account(connection)

    with pytest.raises(errors.NotNullViolation):
        if table == "llm_usage":
            add_usage(connection, account, cached_input_weight=None)
        else:
            add_reservation(connection, account, add_job(connection, account), output_weight=None)


def test_a_writer_of_the_release_before_writes_on_through_the_rollout(connection: psycopg.Connection) -> None:
    # the migration runs before the rollout (a Helm hook): a worker not yet replaced names no weights,
    # and its rows count every token alike, as it charged them
    account = add_account(connection)
    job = add_job(connection, account)

    held = connection.execute(
        "INSERT INTO usage_reservation (account_id, job_id, purpose, model, input_tokens, output_tokens)"
        " VALUES (%s, %s, 'x1', 'gpt-6-luna', 1320, 16000) RETURNING id",
        (account, job),
    ).fetchone()
    booked = connection.execute(
        "INSERT INTO llm_usage (account_id, purpose, model, input_tokens, cached_input_tokens, output_tokens,"
        " requests, unanswered_requests, estimated)"
        " VALUES (%s, 'x1', 'gpt-6-luna', 1200, 1000, 300, 1, 0, false) RETURNING id",
        (account,),
    ).fetchone()

    assert held is not None and booked is not None
    assert charged(connection, "usage_reservation", held[0]) == 17_320
    assert charged(connection, "llm_usage", booked[0]) == 1_500


def test_what_was_booked_before_weights_is_charged_as_it_was(empty_database_url: str, tmp_path: Path) -> None:
    before = tmp_path / "migrations"
    before.mkdir()
    for migration in MIGRATIONS.iterdir():
        if migration.name.endswith(".sql") and migration.name < "0029":
            shutil.copyfile(str(migration), before / migration.name)
    migrate(empty_database_url, before)
    with psycopg.connect(empty_database_url, autocommit=True) as connection:
        account = add_account(connection)
        booked = insert(connection, "llm_usage", {
            "account_id": account, "purpose": "x1", "model": "gpt-6-luna", "input_tokens": 1_200,
            "cached_input_tokens": 1_000, "output_tokens": 300, "requests": 1, "unanswered_requests": 0,
            "estimated": False,
        })  # fmt: skip
        held = insert(connection, "usage_reservation", {
            "account_id": account, "job_id": add_job(connection, account), "purpose": "x1",
            "model": "gpt-6-luna", "input_tokens": 1_320, "output_tokens": 16_000,
        })  # fmt: skip

        migrate(empty_database_url)

        assert charged(connection, "llm_usage", booked) == 1_500
        assert charged(connection, "usage_reservation", held) == 17_320


def test_a_reservation_s_column_holds_a_part_of_a_token_a_token(connection: psycopg.Connection) -> None:
    account = add_account(connection)

    held = add_reservation(
        connection, account, add_job(connection, account), output_tokens=7, output_weight=Decimal("0.3")
    )

    assert charged(connection, "usage_reservation", held) == 1_320 + 3  # as Weights.held reckons it


def test_the_weights_bounds_are_taken(connection: psycopg.Connection) -> None:
    account = add_account(connection)

    for cached, output in ((Decimal(0), Decimal("100")), (Decimal(1), Decimal("0.001"))):
        add_usage(connection, account, cached_input_weight=cached, output_weight=output)
