"""``python -m app.quality.sample`` as the operator calls it: the sample's id and its counts by stratum as
JSON on stdout, a refusal in one line with exit code 1, a call amiss with 2."""

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from app.quality.sample import SEED
from tests.quality.test_sample_command import a_document, connection, done, owner
from tests.support import without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the database with the ontology's vocabularies, shared with test_sample_command

BACKEND = Path(__file__).resolve().parents[2]


def sample_command(database_url: str, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.quality.sample", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


async def test_the_command_prints_the_sample_and_its_strata(
    connection: psycopg.AsyncConnection, database_url: str
) -> None:
    document = await a_document(connection)
    await done(connection, document, "X4")
    arguments = (str(document.id), "--kind", "statement", "--label", "pilot-1", "--account")
    account = await owner(connection, document)

    first = sample_command(database_url, *arguments, account, "--size", "2")
    refused = sample_command(database_url, *arguments, "niemand")

    assert first.returncode == 0, first.stderr
    printed = json.loads(first.stdout)
    assert printed == {
        "sample": printed["sample"], "kind": "statement", "seed": SEED, "drawn_before": False,
        "strata": {"content": {"frame": 1, "drawn": 1}, "learningOutcome": {"frame": 1, "drawn": 1}},
    }  # fmt: skip
    assert isinstance(printed["sample"], int)
    assert (refused.returncode, refused.stdout) == (1, b"")
    [line] = refused.stderr.splitlines()
    assert b"unknown_account" in line


@pytest.mark.parametrize(
    "arguments",
    [
        (),
        ("no-id", "--kind", "statement", "--label", "pilot-1", "--account", "a"),
        ("01a1951f-692d-7a7c-9470-8b70074d6685", "--kind", "node", "--label", "pilot-1", "--account", "a"),
        ("01a1951f-692d-7a7c-9470-8b70074d6685", "--kind", "block", "--label", "Pilot 1", "--account", "a"),
        (
            "01a1951f-692d-7a7c-9470-8b70074d6685",
            "--kind",
            "block",
            "--label",
            "p",
            "--account",
            "a",
            "--size",
            "0",
        ),
        (
            "01a1951f-692d-7a7c-9470-8b70074d6685",
            "--kind",
            "block",
            "--label",
            "p",
            "--account",
            "a",
            "--seed",
            "a b",
        ),
    ],
    ids=["nothing", "no-id", "no-kind", "label-with-space", "size-0", "seed-with-space"],
)
def test_a_call_amiss_is_told_by_its_exit_code(database_url: str, arguments: tuple[str, ...]) -> None:
    done = sample_command(database_url, *arguments)

    assert done.returncode == 2
    assert b"usage: python -m app.quality.sample" in done.stderr
