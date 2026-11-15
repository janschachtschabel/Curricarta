"""What the retention needs of the schema (migration retention): an ended job may go, and what named it - a
conversion, a run - stays without it; a job holding a reservation stays; the pages a conversion booked outlive
it; the places the sweep empties of objects are noted under runs/, exports/ or sources/; the budget's sum and
the sweep's searches each read an index."""

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import errors

from app.core.storage import check_key, check_prefix
from app.db import retention
from app.db.migrate import MIGRATIONS, migrate
from app.usage import ledger
from tests.db.l1 import add_conversion, add_document, add_run, seed_vocabulary

pytestmark = pytest.mark.pg


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as opened:
        seed_vocabulary(opened)
        yield opened


def add_job(connection: psycopg.Connection, status: str = "done") -> uuid.UUID:
    job = uuid.uuid4()
    connection.execute("INSERT INTO job_lane (lane) VALUES ('system') ON CONFLICT DO NOTHING")
    connection.execute(
        "INSERT INTO job (id, kind, lane, status, finished_at)"
        " VALUES (%s, 'extract.run', 'system', %s, now())",
        (job, status),
    )
    return job


def named_by_job(connection: psycopg.Connection, job: uuid.UUID) -> dict[str, uuid.UUID]:
    """A conversion and a run, each naming ``job``."""
    made = add_conversion(connection)
    connection.execute("UPDATE conversion SET job_id = %s WHERE id = %s", (job, made["conversion"]))
    run = add_run(connection, add_document(connection, made))
    connection.execute("UPDATE extraction_run SET job_id = %s WHERE id = %s", (job, run))
    return {"conversion": made["conversion"], "run": run}


def job_of(connection: psycopg.Connection, table: str, row: uuid.UUID) -> object:
    found = connection.execute(
        f"SELECT job_id FROM {table} WHERE id = %s",  # noqa: S608 - the test's own names
        (row,),
    ).fetchone()
    assert found is not None, f"the {table} row went"
    return found[0]


def test_an_ended_job_goes_and_what_named_it_stays_without_it(connection: psycopg.Connection) -> None:
    job = add_job(connection)
    named = named_by_job(connection, job)

    connection.execute("DELETE FROM job WHERE id = %s", (job,))

    assert job_of(connection, "conversion", named["conversion"]) is None
    assert job_of(connection, "extraction_run", named["run"]) is None


def test_a_job_holding_a_reservation_stays(connection: psycopg.Connection) -> None:
    # an open reservation is booked as spent when its job ends (app/usage/ledger.py), never let go with it
    job = add_job(connection, status="failed")
    account = add_conversion(connection)["owner"]
    connection.execute(
        "INSERT INTO usage_reservation (account_id, job_id, purpose, model, input_tokens, output_tokens)"
        " VALUES (%s, %s, 'x4.unit', 'gpt-6-luna', 10, 10)",
        (account, job),
    )

    with pytest.raises(errors.ForeignKeyViolation):
        connection.execute("DELETE FROM job WHERE id = %s", (job,))


def test_the_pages_booked_outlive_their_conversion(connection: psycopg.Connection) -> None:
    # as llm_usage outlives its job: the page budget is the lifetime sum of the bookings
    made = add_conversion(connection)
    connection.execute(
        "INSERT INTO conversion_usage (conversion_id, account_id, engine, pages, billable)"
        " VALUES (%s, %s, 'docling', 2, true)",
        (made["conversion"], made["owner"]),
    )

    connection.execute("DELETE FROM conversion WHERE id = %s", (made["conversion"],))

    booked = connection.execute(
        "SELECT pages, billable FROM conversion_usage WHERE conversion_id = %s", (made["conversion"],)
    ).fetchall()
    assert booked == [(2, True)]


GARBAGE = "INSERT INTO storage_garbage (prefix) VALUES (%s)"


@pytest.mark.parametrize(
    "prefix",
    [
        f"runs/{uuid.uuid4()}/x4/",
        f"exports/{uuid.uuid4()}/",
        "sources/" + "ab" * 32,
        "runs/" + "a" * 239 + "/" + "b" * 239 + "/",  # 480 signs after the root, no segment over 255
        "runs/" + "a" * 255 + "/",
        "runs/a.b_c-d/",
    ],
    ids=["run", "export", "file", "longest", "longest-segment", "signs"],
)
def test_a_garbage_prefix_names_a_place_under_runs_exports_or_sources(
    connection: psycopg.Connection, prefix: str
) -> None:
    connection.execute(GARBAGE, (prefix,))

    noted = connection.execute("SELECT prefix, noted_at <= now() FROM storage_garbage").fetchall()
    assert noted == [(prefix, True)]
    # a place the database takes is one the store takes: a prefix to list, else an object's key
    if prefix.endswith("/"):
        check_prefix(prefix)
    else:
        check_key(prefix)


@pytest.mark.parametrize(
    "prefix",
    [
        "../x",
        "secrets/x",
        "",
        "runs/",
        "runs/../x/",
        "runs/a/./b/",
        "runs//a/",
        "runs/a b/",
        "runs/.a/",
        "runs/" + "a" * 240 + "/" + "b" * 240 + "/",
        "runs/" + "a" * 256 + "/",
        "runs/a./",
        "runs/a.",
    ],
    ids=[
        "parent",
        "elsewhere",
        "empty",
        "bare",
        "parent-inside",
        "dot",
        "empty-segment",
        "space",
        "hidden",
        "too-long",
        "segment-too-long",
        "dot-at-end",
        "key-dot-at-end",
    ],
)
def test_a_garbage_prefix_elsewhere_is_refused(connection: psycopg.Connection, prefix: str) -> None:
    # the sweep deletes every object under it: a place outside the app's three, or one that leaves the
    # root (the store refuses it as a key, app/core/storage.py check_key), is never noted. A device name
    # (runs/con/) passes the CHECK: the store refuses it, and the sweep passes such a place by
    with pytest.raises(errors.CheckViolation):
        connection.execute(GARBAGE, (prefix,))


def test_a_place_is_noted_once(connection: psycopg.Connection) -> None:
    connection.execute(GARBAGE, ("exports/a/",))

    with pytest.raises(errors.UniqueViolation):
        connection.execute(GARBAGE, ("exports/a/",))


def test_the_budget_s_sum_reads_its_index_alone(connection: psycopg.Connection) -> None:
    # the ledger sums an account's costs under its quota row's lock for every request it holds: from the
    # index, never the rows of a table that only grows
    account = add_conversion(connection)["owner"]
    for _ in range(3):
        connection.execute(
            "INSERT INTO llm_usage (account_id, purpose, model, input_tokens, cached_input_tokens,"
            " output_tokens, requests, unanswered_requests, estimated)"
            " VALUES (%s, 'x4.unit', 'gpt-6-luna', 9, 0, 3, 1, 0, false)",
            (account,),
        )
    connection.execute("VACUUM (ANALYZE) llm_usage")  # the visibility map an index-only scan reads
    connection.execute("SET enable_seqscan = off")

    with psycopg.ClientCursor(connection) as cursor:
        plan = "\n".join(row[0] for row in cursor.execute("EXPLAIN " + ledger._TAKEN, {"account": account}))

    assert "Index Only Scan using llm_usage_charged on llm_usage" in plan


@pytest.mark.parametrize(
    ("table", "index", "statement"),
    [("job", "job_ended", retention._CHOSEN), ("audit_log", "audit_log_at", retention._AUDIT)],
    ids=["job", "audit_log"],
)
def test_the_sweep_finds_what_is_past_its_time_by_an_index(
    connection: psycopg.Connection, table: str, index: str, statement: str
) -> None:
    # the sweep's own statements, explained (not run): an ended job and an old entry are found by an index
    connection.execute(f"ANALYZE {table}")
    connection.execute("SET enable_seqscan = off")

    with psycopg.ClientCursor(connection) as cursor:
        rows = cursor.execute("EXPLAIN " + statement, {"days": 90, "batch": 1000})
        plan = "\n".join(row[0] for row in rows)

    assert f"using {index} on {table}" in plan


def test_rows_written_before_keep_their_jobs_until_these_go(empty_database_url: str, tmp_path: Path) -> None:
    # the image before writes on through the rollout: what it wrote keeps its links as they were
    before = tmp_path / "migrations"
    before.mkdir()
    for migration in MIGRATIONS.iterdir():
        if migration.name.endswith(".sql") and migration.name < "0033":
            shutil.copyfile(str(migration), before / migration.name)
    migrate(empty_database_url, before)
    with psycopg.connect(empty_database_url, autocommit=True) as connection:
        seed_vocabulary(connection)
        job = add_job(connection)
        named = named_by_job(connection, job)

        migrate(empty_database_url)

        assert job_of(connection, "conversion", named["conversion"]) == job
        assert job_of(connection, "extraction_run", named["run"]) == job
        connection.execute("DELETE FROM job WHERE id = %s", (job,))
        assert job_of(connection, "conversion", named["conversion"]) is None
        assert job_of(connection, "extraction_run", named["run"]) is None
