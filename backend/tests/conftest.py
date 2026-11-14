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
from app.vocab.store import load_vocabulary
from tests.support import kept_logging, ontology_vocabulary


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


@pytest.fixture(scope="session")
def vocabulary_template(migrated_template: str) -> Iterator[str]:
    """The migrated template with the repository's vocabulary loaded, for the tests that load it
    first thing: writing its concepts and cues took about a second per test."""
    admin = _admin_url()
    with _database(admin, migrated_template, prefix="curricarta_tpl") as name:
        load_vocabulary(make_conninfo(admin, dbname=name), ontology_vocabulary())
        yield name


@pytest.fixture
def preloaded_vocabulary() -> None:
    """Asked for by a fixture whose first act on database_url is to load ontology_vocabulary(): the
    database then comes with it, and that load finds the release there and changes nothing. A fixture
    that writes anything before, loads another vocabulary first or reads the load's result must not
    ask for it. A marker by name, so that every fixture of the test shares the one database."""


@pytest.fixture
def database_url(request: pytest.FixtureRequest, migrated_template: str) -> Iterator[str]:
    """A fresh database with every migration applied: a test's own migrate() call finds nothing to do.
    A test of the migrations themselves takes empty_database_url."""
    template = migrated_template
    if "preloaded_vocabulary" in request.fixturenames:
        template = request.getfixturevalue("vocabulary_template")
    admin = _admin_url()
    with _database(admin, template) as name:
        yield make_conninfo(admin, dbname=name)


@pytest.fixture
def empty_database_url() -> Iterator[str]:
    """A fresh database without any migration, for the tests of the runner, of single migrations
    over older data, and of what an unmigrated database answers."""
    admin = _admin_url()
    with _database(admin, "template0") as name:
        yield make_conninfo(admin, dbname=name)


@pytest.fixture
def in_process_shacl(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SHACL check without its child at the names X5 (and with it the repair and the MEM import) and
    the MEM export call, the model and shapes read once per session (tests/shacl_in_process.py): for a
    test of what they do with its results. Each caller keeps a test of its own on the real child."""
    # imported here: every other test session would load the exporter, X5 and rdflib's SPARQL for nothing
    from app.exports import mem_export
    from app.pipeline import shacl_child, x5_stage
    from tests.shacl_in_process import parsed_once, shacl_in_process

    monkeypatch.setattr(shacl_child, "_parsed", parsed_once)
    monkeypatch.setattr(x5_stage, "shacl_check", shacl_in_process)
    monkeypatch.setattr(mem_export, "shacl_check", shacl_in_process)


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, object]]:
    """Async tests run on asyncio's selector loop: psycopg's async mode refuses Windows' proactor."""
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
