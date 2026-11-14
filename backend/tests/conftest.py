"""Fixtures shared by the backend tests."""

import asyncio
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.db.migrate import migrate
from tests.support import kept_logging


@pytest.fixture(autouse=True)
def without_aws_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """boto3 reads AWS_* and ~/.aws besides the settings: a developer's profile, endpoint or keys
    would steer a test, or sign its requests. Nor does it ask the cloud's metadata address."""
    for key in [key for key in os.environ if key.upper().startswith("AWS_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("AWS_CONFIG_FILE", os.devnull)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", os.devnull)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Undo what configure_logging does to the process-wide loggers."""
    with kept_logging():
        yield


# A fresh PostgreSQL database per test, in the server CURRICARTA_TEST_DATABASE_URL names: an account
# that may create databases, on a server for tests only (locally the container curricarta-test-pg, in
# CI a service). Without it the database tests are skipped - unless CURRICARTA_REQUIRE_PG or CI is set:
# a CI job that lost the variable would otherwise pass with no database test run.
ADMIN_URL_VARIABLE = "CURRICARTA_TEST_DATABASE_URL"


def _admin_url() -> str:
    admin = os.environ.get(ADMIN_URL_VARIABLE)
    if not admin:
        if os.environ.get("CURRICARTA_REQUIRE_PG") or os.environ.get("CI"):
            pytest.fail(f"{ADMIN_URL_VARIABLE} is not set, but the database tests are required")
        pytest.skip(f"{ADMIN_URL_VARIABLE} is not set")
    return admin


@contextmanager
def _database(admin: str, template: str, prefix: str = "curricarta_t") -> Iterator[str]:
    """A new database copied from ``template``, dropped afterwards - also when its user left
    connections open. The name is random: test runs of other developers or CI jobs may share the server."""
    name = f"{prefix}_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(name), sql.Identifier(template))
        )
    try:
        yield name
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def migrated_template() -> Iterator[str]:
    """One database per test session with every migration applied, the template of database_url:
    running all migrations for each of thousands of tests took most of the suite's time. Copying needs
    the template without sessions, so it is migrated and closed before the first copy, and no test
    connects to it."""
    admin = _admin_url()
    with _database(admin, "template0", prefix="curricarta_tpl") as name:
        migrate(make_conninfo(admin, dbname=name))
        yield name


@pytest.fixture
def database_url(migrated_template: str) -> Iterator[str]:
    """A fresh database with every migration applied: a test's own migrate() call finds nothing to do.
    A test of the migrations themselves takes empty_database_url."""
    admin = _admin_url()
    with _database(admin, migrated_template) as name:
        yield make_conninfo(admin, dbname=name)


@pytest.fixture
def empty_database_url() -> Iterator[str]:
    """A fresh database without any migration, for the tests of the runner, of single migrations
    over older data, and of what an unmigrated database answers."""
    admin = _admin_url()
    with _database(admin, "template0") as name:
        yield make_conninfo(admin, dbname=name)


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, object]]:
    """Async tests run on asyncio's selector loop: psycopg's async mode refuses Windows' proactor."""
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
