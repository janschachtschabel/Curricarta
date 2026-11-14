"""``python -m app.pipeline.replay <document> [--stage x4]``: the answers an X4 run kept, read again by
today's reader without asking the model - each unit's last answer in form, read as the stage reads it -,
counted beside what the run wrote. Read only: nothing in the database or the store changes. A model
stands in for the extraction (FunctionModel, tests/pipeline/test_run.py), never a provider."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.usage import RequestUsage

from app.core.ids import new_id
from app.core.storage import FileSystemStorage
from app.db.conversions import all_blocks, printed_pages
from app.db.documents import Document
from app.db.gold import Judgement, items_of, judge
from app.db.measures import model_statements
from app.db.nodes import write_subtree
from app.domain.l1 import NodeDraft
from app.llm.raw import answer_key
from app.pipeline import statement_read
from app.pipeline.replay import Replayed, replay_x4
from app.pipeline.run import extract_document
from app.quality.report import closed
from app.quality.sample import Request, draw
from tests.llm.test_client import llm_settings
from tests.pipeline.test_run import BODY, CV, Model, a_document, a_job, a_statement, context_of, rows, setup
from tests.quality.gold_documents import MODEL, PROPOSED, done, statement
from tests.support import make_settings, without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, from test_run

BACKEND = Path(__file__).resolve().parents[2]


class OnceOutOfForm(Model):
    """The model of test_run, whose first answer for unit E1 lacks what the schema asks for."""

    def __init__(self) -> None:
        super().__init__()
        self.spoilt = False

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        answered = super().__call__(messages, info)
        part = answered.parts[0]
        assert isinstance(part, ToolCallPart)
        if '"unitKey": "E1"' in str(part.args) and not self.spoilt:
            self.spoilt = True
            return ModelResponse(
                parts=[ToolCallPart(part.tool_name, '{"unitKey": "E1"}')], usage=answered.usage
            )
        return answered


async def extracted(
    pool: AsyncConnectionPool,
    connection: psycopg.AsyncConnection,
    tmp_path: Path,
    database_url: str,
    model: Any,
) -> Document:
    document = await a_document(connection)
    job = await a_job(connection, document.id, document.owner_id)
    await extract_document(context_of(pool, tmp_path, model, database_url), job)
    return document


async def replayed(connection: psycopg.AsyncConnection, tmp_path: Path, document: Document) -> Replayed:
    blocks = await all_blocks(connection, document.conversion_id)
    printed = await printed_pages(connection, document.conversion_id)
    storage = FileSystemStorage(tmp_path / "store")
    settings = make_settings()
    return await replay_x4(
        connection, storage, llm_settings(), document, blocks, printed, settings.ontology_dir
    )


async def test_a_replay_reads_what_the_run_read(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())

    found = await replayed(connection, tmp_path, document)

    assert (found.answers, found.gone, found.units) == (2, 0, 2)
    assert (found.statements_now, found.statements_stored) == (2, 2)
    assert (found.out_of_form, found.wrong_unit, found.missing, found.repaired) == (0, 0, 0, 0)
    assert found.findings_now == found.findings_stored
    stored = [(item.text_hash, item.first_block) for item in await model_statements(connection, document.id)]
    assert sorted(found.keys) == sorted(stored)  # the same wordings at the same blocks
    assert found.lexicon_release_then == found.lexicon_release_now is not None
    assert found.units_differing == ()


async def test_a_reader_changed_since_shows_in_the_counts(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    monkeypatch.setattr(statement_read, "MOST_STATEMENTS", 0)  # a reader that keeps no statement

    found = await replayed(connection, tmp_path, document)

    assert (found.statements_now, found.statements_stored) == (0, 2)
    assert found.findings_now == {"x4.too_many_statements": 2}
    assert "x4.too_many_statements" not in found.findings_stored
    assert found.keys == ()
    assert found.units_differing == ("E1", "E2")


async def test_an_answer_out_of_form_is_passed_over_for_the_one_after(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, OnceOutOfForm())
    # then an answer for a unit the document does not have, and a second answer for E1 in form - booked and
    # kept as the run would have
    [(run,)] = await rows(
        connection,
        "SELECT id FROM extraction_run WHERE document_id = %s AND stage_iri LIKE '%%X4'",
        document.id,
    )
    two = [a_statement("p2-b2", "Aussage E1 eins"), a_statement("p2-b2", "Aussage E1 zwei")]
    later = [
        {"unitKey": "E9", "statements": [a_statement("p2-b2", "Aussage E9")], "checkedAbsent": []},
        {"unitKey": " E1 ", "statements": two, "checkedAbsent": []},
    ]
    for number, given in enumerate(later, start=4):
        await connection.execute(
            "INSERT INTO llm_usage (account_id, run_id, purpose, model, input_tokens, cached_input_tokens,"
            " output_tokens, requests, unanswered_requests, estimated)"
            " VALUES (%s, %s, 'x4.unit', 'm', 9, 0, 9, 1, 0, false)",
            (document.owner_id, run),
        )
        answer = ModelResponse(
            parts=[ToolCallPart("final_result", json.dumps(given))], usage=RequestUsage(input_tokens=9)
        )
        FileSystemStorage(tmp_path / "store").put(
            answer_key(run, "x4", number), ModelMessagesTypeAdapter.dump_json([answer])
        )

    found = await replayed(connection, tmp_path, document)

    assert (found.answers, found.out_of_form, found.wrong_unit, found.missing) == (5, 1, 1, 0)
    # E1 by its last answer in form, two statements; E2 as written
    assert (found.statements_now, found.statements_stored, found.units_differing) == (3, 2, ("E1",))


async def test_nothing_is_written(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    before = await _counts(connection), _keys(tmp_path / "store")

    await replayed(connection, tmp_path, document)

    assert (await _counts(connection), _keys(tmp_path / "store")) == before


async def _counts(connection: psycopg.AsyncConnection) -> dict[str, int]:
    tables = await rows(
        connection,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        " AND table_type = 'BASE TABLE' ORDER BY 1",
    )
    counted: dict[str, int] = {}
    for (table,) in tables:
        [(found,)] = await rows(connection, f'SELECT count(*) FROM "{table}"')  # noqa: S608 - the catalogue's
        counted[table] = found
    assert counted["statement"] > 0
    return counted


def _keys(store: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(store)): path.read_bytes() for path in sorted(store.rglob("*")) if path.is_file()
    }


def replay_command(database_url: str, store: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url, "STORAGE_DIR": str(store)}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.pipeline.replay", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=180,
        check=False,
    )


async def test_the_counts_name_no_wording(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())

    done = replay_command(database_url, tmp_path / "store", str(document.id), "--stage", "x4")

    assert done.returncode == 0, done.stderr
    [line] = done.stdout.splitlines()  # one line of JSON
    printed = json.loads(line)
    assert printed["statements_now"] == printed["statements_stored"] == 2
    text = line.decode("utf-8")
    assert "Aussage" not in text and all(word not in text for word in BODY.split() if len(word) > 4)
    closed(printed)  # counts and codes alone


async def test_a_document_without_raw_answers_says_so(setup: Any, tmp_path: Path, database_url: str) -> None:
    _, connection = setup
    document = await a_document(connection)  # never extracted

    done = replay_command(database_url, tmp_path / "store", str(document.id))
    nowhere = replay_command(database_url, tmp_path / "store", str(new_id()))
    amiss = replay_command(database_url, tmp_path / "store", str(document.id), "--stage", "x3")

    assert (done.returncode, done.stdout) == (1, b"")
    [line] = done.stderr.splitlines()
    assert b"no_raw_answers" in line
    assert (nowhere.returncode, nowhere.stdout) == (1, b"")
    assert b"unknown_document" in nowhere.stderr
    assert amiss.returncode == 2  # x4 alone is replayed


def report_command(database_url: str, store: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url, "STORAGE_DIR": str(store)}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", "app.quality.report", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=180,
        check=False,
    )


async def test_the_gold_report_tells_what_the_replay_keeps_of_the_judgements(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    [(account,)] = await rows(connection, "SELECT name FROM account WHERE id = %s", document.owner_id)
    sample = (await draw(connection, Request(document.id, "statement", "pilot-1", account))).sample
    for item in await items_of(connection, sample):
        await judge(connection, item.id, document.owner_id, Judgement("correct", (), None, None))
    # a document whose statements no run of the model wrote: nothing kept to replay
    unextracted = await a_document(connection)
    root = NodeDraft(
        function=CV + "fn_area", origin=MODEL, review_status=PROPOSED, original_title="Kompetenzen",
        statements=(statement(BODY),),
    )  # fmt: skip
    await write_subtree(connection, unextracted.id, root)
    await done(connection, unextracted, "X4")
    [(other,)] = await rows(connection, "SELECT name FROM account WHERE id = %s", unextracted.owner_id)
    elsewhere = (await draw(connection, Request(unextracted.id, "statement", "pilot-2", other))).sample

    made = report_command(database_url, tmp_path / "store", "--sample", str(sample), "--replayed")
    refused = report_command(database_url, tmp_path / "store", "--sample", str(elsewhere), "--replayed")

    assert made.returncode == 0, made.stderr
    statements = json.loads(made.stdout)["documents"][0]["statement"]
    assert statements["replayed"] == {
        "kept_correct": 2, "kept_imprecise": 0, "kept_wrong": 0,
        "gone_correct": 0, "gone_imprecise": 0, "gone_wrong": 0,
        "new_unjudged": 0,
    }  # fmt: skip
    assert (refused.returncode, refused.stdout) == (1, b"")
    assert b"no_raw_answers" in refused.stderr
