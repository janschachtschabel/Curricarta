"""``python -m app.pipeline.estimate <document>``: the reckoning of a run before it asks (plan M1 11.2) as
JSON on stdout, by purpose and over all, with the stages it leaves unreckoned; without the model's key."""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.llm.metering import Weights
from app.pipeline.reckoned import Request, expected_charge
from tests.pipeline.test_estimate import after_x2
from tests.pipeline.test_run import a_document, setup
from tests.support import without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the database with the ontology's vocabularies and a pool, shared with test_run

BACKEND = Path(__file__).resolve().parents[2]


def estimate(database_url: str, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():  # no key among them: the command needs none
        # the model named: its weights are what the reckoning prints (app/llm/client.py)
        environment = {**os.environ, "DATABASE_URL": database_url, "OPENAI_MODEL": "gpt-6-luna"}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.pipeline.estimate", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


async def test_the_command_prints_the_reckoning_by_purpose(setup: Any, database_url: str) -> None:
    _, connection = setup
    document = await a_document(connection)

    done = estimate(database_url, str(document.id))

    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)
    assert printed["document_id"] == str(document.id)
    assert printed["owed"] == ["X1", "X2", "X3", "X4", "X5"]
    assert printed["units"] is None
    assert printed["unreckoned"] == {"X3": "before_x2", "X4": "before_x2"}
    assert list(printed["by_purpose"]) == ["x1.profile", "x1.outline"]
    total = printed["total"]
    assert total["requests"] == len(printed["requests"]) >= 2
    assert total["output_tokens"] == 16_000 * total["requests"]  # every answer at its cap
    assert printed["reserved"] == total["input_tokens"] + total["output_tokens"]
    # what the budget must hold, in tokens as charged: gpt-6-luna's output at five (app/llm/client.py)
    assert printed["weights"] == {"cached_input": "0.1", "output": "5"}
    assert printed["charged_at_most"] == total["input_tokens"] + 5 * total["output_tokens"]
    assert isinstance(printed["guessed_units"], int)  # before X1, from the skeleton
    assert total["input_tokens"] == sum(request["input_tokens"] for request in printed["requests"])


async def test_the_command_prints_what_the_run_is_expected_to_charge(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # before X2 the units are not counted: no expectation; after it X3 and each unit, the cache read
    # after the first requests of each prefix (EXTRACT_CONCURRENCY), each answer at the measured mean
    _, connection = setup
    before = json.loads(estimate(database_url, str((await a_document(connection)).id)).stdout)
    document, _ = await after_x2(setup, tmp_path, database_url)

    done = estimate(database_url, str(document.id))

    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)
    requests = [Request(**request) for request in printed["requests"]]
    weights = Weights(Decimal(printed["weights"]["cached_input"]), Decimal(printed["weights"]["output"]))
    assert before["charged_expected"] is None
    assert printed["unreckoned"] == {}
    assert printed["charged_expected"] == expected_charge(requests, weights, uncached_first=4)
    assert 0 < printed["charged_expected"] <= printed["charged_at_most"]


async def test_a_document_that_is_not_there_is_said_in_one_line(setup: Any, database_url: str) -> None:
    done = estimate(database_url, "01a1951f-692d-7a7c-9470-8b70074d6685")

    assert done.returncode == 1
    assert done.stdout == b""
    [line] = done.stderr.splitlines()
    assert b"no document 01a1951f-692d-7a7c-9470-8b70074d6685" in line


@pytest.mark.parametrize("arguments", [(), ("no-id",), ("01a1951f-692d-7a7c-9470-8b70074d6685", "more")])
def test_the_command_takes_one_document_id(database_url: str, arguments: tuple[str, ...]) -> None:
    # a call amiss, not a document missing: told apart by the exit code
    done = estimate(database_url, *arguments)

    assert done.returncode == 2
    assert b"usage: python -m app.pipeline.estimate" in done.stderr
