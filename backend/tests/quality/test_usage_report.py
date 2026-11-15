"""``python -m app.quality.usage_report <document> --label <label> [--raw]``: what the runs of a document
cost, as counts - the ledger summed by purpose, estimated bookings apart, the largest answer against the
cap, the reservations left, the runs by stage -, and with ``--raw`` the usage the kept answers report,
held against the ledger. Never a title or a wording."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from pydantic_ai.messages import FinishReason, ModelMessagesTypeAdapter, ModelResponse, ToolCallPart
from pydantic_ai.usage import RequestUsage

from app.core.ids import new_id
from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.db.documents import Document
from app.db.runs import RunStart, Stage, finish_run, start_run
from app.jobs.queue import enqueue
from app.llm.raw import answer_key
from app.quality.closed import closed
from app.quality.usage_report import usage_report
from app.retention import Policy, sweep
from tests.quality.gold_documents import WORDS, a_document, connection
from tests.support import without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection"]  # the fixture, from gold_documents

BACKEND = Path(__file__).resolve().parents[2]
CAP = 4_000
MARKER = "Kieselbachufer"  # in the title and in an answer's wording: never in the report


async def a_run(connection: psycopg.AsyncConnection, document: Document, stage: Stage) -> UUID:
    run = await start_run(connection, RunStart(document.id, None, 1, stage, "gpt-6-luna", "x", None, None))
    await finish_run(connection, run, "done", {})
    return run


async def booked(
    connection: psycopg.AsyncConnection,
    document: Document,
    run: UUID,
    purpose: str,
    spent: tuple[int, int, int],
    *,
    estimated: bool = False,
    unanswered: int = 0,
    requests: int = 1,
) -> None:
    """A request booked as the ledger books it: input, of it cached, output; weights 0.1 and 5. One sent
    and never answered is booked with no request and one unanswered (app/llm/calls.py _book_cut_off)."""
    await connection.execute(
        "INSERT INTO llm_usage (account_id, run_id, purpose, model, input_tokens, cached_input_tokens,"
        " output_tokens, requests, unanswered_requests, estimated, cached_input_weight, output_weight)"
        " VALUES (%s, %s, %s, 'gpt-6-luna', %s, %s, %s, %s, %s, %s, 0.1, 5)",
        (document.owner_id, run, purpose, *spent, requests, unanswered, estimated),
    )


def kept(
    store: Path,
    run: UUID,
    stage: str,
    number: int,
    spent: tuple[int, int, int],
    finish_reason: FinishReason | None = None,
    **details: int,
) -> None:
    """An answer kept as app/llm/calls.py keeps it, reporting its usage."""
    usage = RequestUsage(
        input_tokens=spent[0], cache_read_tokens=spent[1], output_tokens=spent[2], details=details
    )
    answer = ToolCallPart(
        "final_result", json.dumps({"statements": [{"verbatim": f"{MARKER} {WORDS['outcome']}"}]})
    )
    response = ModelResponse(parts=[answer], usage=usage, finish_reason=finish_reason)
    data = ModelMessagesTypeAdapter.dump_json([response])
    FileSystemStorage(store).put(answer_key(run, stage, number), data)


async def a_document_run(
    connection: psycopg.AsyncConnection, store: Path
) -> tuple[Document, dict[str, UUID]]:
    """A document whose X3 asked once and X4 twice, each answer booked and kept; X4's second answer names
    its reasoning tokens, the first not; the first says it was cut at the cap."""
    document = await a_document(connection)
    await connection.execute("UPDATE document SET title = %s WHERE id = %s", (MARKER, document.id))
    runs = {stage: await a_run(connection, document, stage) for stage in ("X3", "X4")}
    answers: list[tuple[str, str, int, tuple[int, int, int], dict[str, int]]] = [
        ("X3", "x3.frame", 1, (10_000, 0, 900), {}),
        ("X4", "x4.unit", 1, (12_000, 9_000, 1_200), {}),
        ("X4", "x4.unit", 2, (12_500, 9_000, 1_500), {"reasoning_tokens": 300}),
    ]
    for stage, purpose, number, spent, details in answers:
        await booked(connection, document, runs[stage], purpose, spent)
        cut: FinishReason | None = "length" if (stage, number) == ("X4", 1) else None
        kept(store, runs[stage], stage.lower(), number, spent, cut, **details)
    return document, runs


async def test_the_report_sums_the_ledger_by_purpose(
    connection: psycopg.AsyncConnection, tmp_path: Path
) -> None:
    document, runs = await a_document_run(connection, tmp_path)
    other = await a_document(connection)  # another document's request: not this one's
    await booked(connection, other, await a_run(connection, other, "X4"), "x4.unit", (99_000, 0, 9_000))
    job = await enqueue(connection, "extract.run", "test", {"document_id": str(document.id)})
    await connection.execute(
        "INSERT INTO usage_reservation (account_id, job_id, run_id, purpose, model, input_tokens,"
        " output_tokens) VALUES (%s, %s, %s, 'x4.unit', 'gpt-6-luna', 13000, %s)",
        (document.owner_id, job, runs["X4"], CAP),
    )  # held for a request whose booking never came

    made = await usage_report(connection, None, document.id, "pilot-1", cap=CAP)

    assert made["label"] == "pilot-1"
    assert made["cap"] == CAP
    # charged: uncached input + ceil(cached * 0.1 + output * 5)
    assert made["by_purpose"] == {
        "x3.frame": {
            "requests": 1, "unanswered_requests": 0, "input_tokens": 10_000, "cached_input_tokens": 0,
            "output_tokens": 900, "charged_tokens": 14_500, "estimated_rows": 0,
            "estimated_charged_tokens": 0, "max_output_tokens": 900, "cut_answers": 0, "reservations_left": 0,
        },
        "x4.unit": {
            "requests": 2, "unanswered_requests": 0, "input_tokens": 24_500, "cached_input_tokens": 18_000,
            "output_tokens": 2_700, "charged_tokens": 3_000 + 900 + 6_000 + 3_500 + 900 + 7_500,
            "estimated_rows": 0, "estimated_charged_tokens": 0, "max_output_tokens": 1_500, "cut_answers": 0,
            "reservations_left": 1,
        },
    }  # fmt: skip
    assert made["total"]["requests"] == 3
    assert made["total"]["charged_tokens"] == 14_500 + 21_800
    assert set(made["runs"]) == {"X3", "X4"}
    assert made["runs"]["X4"]["outcomes"] == {"done": 1}
    assert made["runs"]["X4"]["seconds"] >= 0
    assert made["conversion"] == {"engine": "pdfplumber", "pages": 1, "billable": False}
    assert "raw" not in made  # asked for with --raw alone


async def test_estimated_bookings_are_counted_apart(
    connection: psycopg.AsyncConnection, tmp_path: Path
) -> None:
    document, runs = await a_document_run(connection, tmp_path)
    # sent and never answered: booked at what was held for it; and an answer cut at the cap
    await booked(
        connection,
        document,
        runs["X4"],
        "x4.unit",
        (13_000, 0, CAP),
        estimated=True,
        unanswered=1,
        requests=0,
    )
    await booked(connection, document, runs["X4"], "x4.unit", (12_000, 9_000, CAP))

    made = await usage_report(connection, None, document.id, "pilot-1", cap=CAP)

    units = made["by_purpose"]["x4.unit"]
    assert (units["requests"], units["unanswered_requests"]) == (3, 1)
    assert (units["estimated_rows"], units["estimated_charged_tokens"]) == (1, 13_000 + 5 * CAP)
    assert units["input_tokens"] == 24_500 + 12_000  # the reported answers' alone
    assert units["output_tokens"] == 2_700 + CAP
    assert (units["max_output_tokens"], units["cut_answers"]) == (CAP, 1)  # the estimate is no answer
    assert units["charged_tokens"] == 21_800 + (3_000 + 900 + 5 * CAP) + (13_000 + 5 * CAP)


def usage_command(database_url: str, store: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url, "STORAGE_DIR": str(store)}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.quality.usage_report", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


async def test_the_raw_answers_usage_equals_the_ledger(
    connection: psycopg.AsyncConnection, database_url: str, tmp_path: Path
) -> None:
    document, runs = await a_document_run(connection, tmp_path)
    # refused by the provider: a request without tokens, and no answer kept
    await booked(connection, document, runs["X4"], "x4.unit", (0, 0, 0))

    done = usage_command(database_url, tmp_path, str(document.id), "--label", "pilot-1", "--raw")

    assert done.returncode == 0, done.stderr
    [line] = done.stdout.splitlines()  # one line of JSON
    sys.stdout.write(line.decode("utf-8") + "\n")  # the acceptance's sample output (pytest -s)
    made = json.loads(line)
    assert made["raw"] == {
        "answers": 3, "gone": 0, "swept": 0, "unreadable": 0, "unreported": 0, "beyond_ledger": 0,
        "input_tokens": 34_500, "cached_input_tokens": 18_000, "output_tokens": 3_600,
        "reasoning_tokens": 300, "cut_by_finish_reason": 1, "ledger_equals_raw": True,
    }  # fmt: skip
    assert made["cap"] == 16_000  # LLM_MAX_OUTPUT_TOKENS as the worker reads it, by default


async def test_a_raw_answer_gone_is_counted_and_ends_nothing(
    connection: psycopg.AsyncConnection, tmp_path: Path
) -> None:
    document, runs = await a_document_run(connection, tmp_path)
    store = FileSystemStorage(tmp_path)
    store.delete(answer_key(runs["X4"], "x4", 1))
    store.put(answer_key(runs["X3"], "x3", 1), b"not an answer")
    kept(tmp_path, runs["X3"], "x3", 2, (100, 0, 10))  # kept, never booked: read and told

    made = await usage_report(connection, store, document.id, "pilot-1", cap=CAP, raw=True)

    assert made["raw"] == {
        "answers": 2, "gone": 1, "swept": 0, "unreadable": 1, "unreported": 0, "beyond_ledger": 1,
        "input_tokens": 12_600, "cached_input_tokens": 9_000, "output_tokens": 1_510,
        "reasoning_tokens": 300, "cut_by_finish_reason": 0, "ledger_equals_raw": False,
    }  # fmt: skip
    assert made["by_purpose"]["x4.unit"]["requests"] == 2  # the ledger as it is


async def test_answers_the_retention_took_are_counted_apart_and_the_rest_still_equals_the_ledger(
    connection: psycopg.AsyncConnection, tmp_path: Path
) -> None:
    # past RETENTION_RAW_ANSWERS_DAYS the sweep takes a run's answers and clears its key: not lost, not a
    # booking amiss - the ledger is held against the answers still kept
    document, runs = await a_document_run(connection, tmp_path)
    await connection.execute(
        "UPDATE extraction_run SET started_at = now() - interval '41 days',"
        " finished_at = now() - interval '40 days' WHERE id = %s",
        (runs["X3"],),
    )
    taken = await sweep(
        connection, AsyncStorage(FileSystemStorage(tmp_path)), Policy(0, 0, 30), dry_run=False
    )
    assert (taken.runs, taken.objects) == (1, 1)

    made = await usage_report(
        connection, FileSystemStorage(tmp_path), document.id, "pilot-1", cap=CAP, raw=True
    )

    assert made["raw"] == {
        "answers": 2, "gone": 0, "swept": 1, "unreadable": 0, "unreported": 0, "beyond_ledger": 0,
        "input_tokens": 24_500, "cached_input_tokens": 18_000, "output_tokens": 2_700,
        "reasoning_tokens": 300, "cut_by_finish_reason": 1, "ledger_equals_raw": True,
    }  # fmt: skip
    assert made["total"]["input_tokens"] == 34_500  # the ledger as it is: nothing of it was swept


async def test_the_report_names_neither_title_nor_wording(
    connection: psycopg.AsyncConnection, tmp_path: Path
) -> None:
    document, _ = await a_document_run(connection, tmp_path)

    made = await usage_report(
        connection, FileSystemStorage(tmp_path), document.id, "pilot-1", cap=CAP, raw=True
    )

    printed = json.dumps(made, ensure_ascii=False)
    assert MARKER not in printed
    assert all(word not in printed for word in WORDS["outcome"].split() if len(word) > 3)
    closed(made)  # counts, rates and codes alone


async def test_a_document_that_is_not_there_is_said_in_one_line(database_url: str, tmp_path: Path) -> None:
    done = usage_command(database_url, tmp_path, str(new_id()), "--label", "pilot-1")

    assert (done.returncode, done.stdout) == (1, b"")
    [line] = done.stderr.splitlines()
    assert b"unknown_document" in line


@pytest.mark.parametrize(
    "arguments",
    [("--label", "Pilot 1"), ("--label", "pilot_1"), ("--label", ""), ()],
    ids=["space", "underscore", "empty", "none"],
)
def test_a_label_other_than_plain_is_refused(database_url: str, tmp_path: Path, arguments: Any) -> None:
    done = usage_command(database_url, tmp_path, "01a1951f-692d-7a7c-9470-8b70074d6685", *arguments)

    assert (done.returncode, done.stdout) == (2, b"")
    assert b"usage: python -m app.quality.usage_report" in done.stderr
