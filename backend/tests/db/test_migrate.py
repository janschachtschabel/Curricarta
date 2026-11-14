"""Versioned SQL files, each applied exactly once, under an advisory lock."""

import re
import threading
from pathlib import Path

import psycopg
import pytest

from app.db.migrate import MIGRATIONS, MigrationError, load_migrations, migrate

pytestmark = pytest.mark.pg


def write(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir(exist_ok=True)
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")
    return directory


def applied_rows(url: str) -> list[tuple[int, str]]:
    with psycopg.connect(url) as connection:
        rows = connection.execute("SELECT version, name FROM schema_migration ORDER BY version").fetchall()
    return [(int(version), str(name)) for version, name in rows]


def table_exists(url: str, name: str) -> bool:
    with psycopg.connect(url) as connection:
        row = connection.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()
    return bool(row and row[0])


TWO = {
    "0001_first.sql": "CREATE TABLE first (id integer PRIMARY KEY);",
    "0002_second.sql": "CREATE TABLE second (id integer PRIMARY KEY REFERENCES first (id));",
}


def test_a_fresh_database_gets_every_file_in_order(database_url: str, tmp_path: Path) -> None:
    applied = migrate(database_url, write(tmp_path / "m", TWO))

    assert applied == [1, 2]
    assert applied_rows(database_url) == [(1, "0001_first.sql"), (2, "0002_second.sql")]
    assert table_exists(database_url, "second")


def test_a_second_run_applies_nothing(database_url: str, tmp_path: Path) -> None:
    directory = write(tmp_path / "m", TWO)
    migrate(database_url, directory)

    assert migrate(database_url, directory) == []
    assert len(applied_rows(database_url)) == 2


def test_two_runs_at_once_apply_each_file_exactly_once(database_url: str, tmp_path: Path) -> None:
    directory = write(
        tmp_path / "m",
        {
            "0001_hits.sql": "CREATE TABLE hits (n integer); INSERT INTO hits VALUES (1);",
            # holds the lock long enough for the second run to wait on it
            "0002_slow.sql": "SELECT pg_sleep(0.3); INSERT INTO hits VALUES (2);",
        },
    )
    start = threading.Barrier(2)
    results: list[list[int]] = []
    errors: list[BaseException] = []

    def run() -> None:
        start.wait()
        try:
            results.append(migrate(database_url, directory))
        except BaseException as error:  # reported below, not lost in the thread
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert sorted(version for result in results for version in result) == [1, 2]
    with psycopg.connect(database_url) as connection:
        assert connection.execute("SELECT n FROM hits ORDER BY n").fetchall() == [(1,), (2,)]


def test_a_database_newer_than_the_code_is_refused(database_url: str, tmp_path: Path) -> None:
    migrate(database_url, write(tmp_path / "new", TWO))
    older = write(tmp_path / "old", {"0001_first.sql": TWO["0001_first.sql"]})

    with pytest.raises(MigrationError, match="newer"):
        migrate(database_url, older)


def test_a_file_changed_after_it_was_applied_is_refused(database_url: str, tmp_path: Path) -> None:
    directory = write(tmp_path / "m", TWO)
    migrate(database_url, directory)
    (directory / "0001_first.sql").write_text("CREATE TABLE first (id bigint PRIMARY KEY);", encoding="utf-8")

    with pytest.raises(MigrationError, match=re.escape("0001_first.sql")):
        migrate(database_url, directory)


def test_a_failing_file_keeps_the_earlier_ones_and_nothing_of_itself(
    database_url: str, tmp_path: Path
) -> None:
    directory = write(
        tmp_path / "m",
        {
            "0001_first.sql": TWO["0001_first.sql"],
            "0002_broken.sql": "CREATE TABLE half (id integer); SELECT 1 / 0;",
        },
    )

    with pytest.raises(MigrationError, match=re.escape("0002_broken.sql")):
        migrate(database_url, directory)

    assert applied_rows(database_url) == [(1, "0001_first.sql")]
    assert not table_exists(database_url, "half")


@pytest.mark.parametrize(
    ("files", "fault"),
    [
        ({"0001_a.sql": "", "0003_c.sql": ""}, "gap"),
        ({"0001_a.sql": "", "0001_b.sql": ""}, "twice"),
        ({"0002_b.sql": ""}, "gap"),
        ({"1_a.sql": ""}, "1_a.sql"),
        ({"0001-a.sql": ""}, "0001-a.sql"),
        ({"0001_A.sql": ""}, "0001_A.sql"),
    ],
    ids=["gap", "duplicate", "not-from-one", "short-number", "dash", "upper-case"],
)
def test_a_malformed_set_of_files_is_refused(tmp_path: Path, files: dict[str, str], fault: str) -> None:
    with pytest.raises(MigrationError, match=re.escape(fault)):
        load_migrations(write(tmp_path / "m", files))


def test_files_other_than_sql_are_not_migrations(tmp_path: Path) -> None:
    directory = write(tmp_path / "m", {"0001_first.sql": "SELECT 1;", "README.md": "notes"})

    assert [migration.filename for migration in load_migrations(directory)] == ["0001_first.sql"]


# audit 2026-11-14 (B, H-09): a migration's checksum named its raw bytes, so one checked out with CRLF
# (git's autocrlf, an editor) was another migration than the one the CI's image applied


def test_a_file_s_checksum_is_the_same_whatever_its_line_endings(tmp_path: Path) -> None:
    unix, windows = tmp_path / "unix", tmp_path / "windows"
    unix.mkdir()
    windows.mkdir()
    (unix / "0001_first.sql").write_bytes(b"CREATE TABLE first (\n    id integer PRIMARY KEY\n);\n")
    (windows / "0001_first.sql").write_bytes(b"CREATE TABLE first (\r\n    id integer PRIMARY KEY\r\n);\r\n")

    assert load_migrations(unix)[0].checksum == load_migrations(windows)[0].checksum


def test_a_database_migrated_from_one_checkout_takes_the_other(database_url: str, tmp_path: Path) -> None:
    directory = tmp_path / "m"
    directory.mkdir()
    (directory / "0001_first.sql").write_bytes(b"CREATE TABLE first (\n    id integer PRIMARY KEY\n);\n")
    migrate(database_url, directory)
    (directory / "0001_first.sql").write_bytes(
        b"CREATE TABLE first (\r\n    id integer PRIMARY KEY\r\n);\r\n"
    )

    assert migrate(database_url, directory) == []


def test_no_shipped_migration_changed_after_it_was_released() -> None:
    # CHECKSUMS names every migration as it was first shipped: a database that applied one refuses a
    # changed file (above), which a CI that always migrates an empty database never sees. A new
    # migration adds its line; a line changed is a migration changed.
    listed = dict(
        line.split() for line in (MIGRATIONS / "CHECKSUMS").read_text(encoding="utf-8").splitlines() if line
    )

    assert listed == {each.filename: each.checksum for each in load_migrations(MIGRATIONS)}
