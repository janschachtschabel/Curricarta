"""``app.pipeline.replay``: the answers the X4 runs kept, read again by today's reader without asking the
model - each unit's own answer chosen as the pipeline chose it, read as the stage reads it -, counted
beside what the runs wrote. Read only. A model stands in for the extraction (FunctionModel,
tests/pipeline/test_run.py), never a provider; the command's own tests: test_replay_command.py."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.usage import RequestUsage

from app.core.storage import FileSystemStorage
from app.db.conversions import all_blocks, printed_pages
from app.db.documents import Document
from app.db.measures import model_statements
from app.db.runs import RunStart, start_run
from app.llm.raw import answer_key
from app.pipeline import statement_read
from app.pipeline.replay import Replayed, replay_x4
from app.pipeline.run import extract_document
from tests.llm.test_client import llm_settings
from tests.pipeline.test_run import Model, a_document, a_job, a_statement, context_of, rows, setup
from tests.support import make_settings

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, from test_run


class OnceOutOfForm(Model):
    """The model of test_run, whose first answer for unit E1 lacks what the schema asks for."""

    def __init__(self, **given: Any) -> None:
        super().__init__(**given)
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


async def x4_run(connection: psycopg.AsyncConnection, document: Document) -> UUID:
    [(run,)] = await rows(
        connection,
        "SELECT id FROM extraction_run WHERE document_id = %s AND stage_iri LIKE '%%X4'",
        document.id,
    )
    return UUID(str(run))


async def kept_later(
    connection: psycopg.AsyncConnection, tmp_path: Path, document: Document, given: list[dict[str, Any]]
) -> None:
    """Answers in form kept after the run's own, in its run, each booked as an answered request."""
    run = await x4_run(connection, document)
    [(booked,)] = await rows(
        connection, "SELECT count(*) FROM llm_usage WHERE run_id = %s AND requests > 0", run
    )
    for number, answer in enumerate(given, start=booked + 1):
        await connection.execute(
            "INSERT INTO llm_usage (account_id, run_id, purpose, model, input_tokens, cached_input_tokens,"
            " output_tokens, requests, unanswered_requests, estimated)"
            " VALUES (%s, %s, 'x4.unit', 'm', 9, 0, 9, 1, 0, false)",
            (document.owner_id, run),
        )
        response = ModelResponse(
            parts=[ToolCallPart("final_result", json.dumps(answer))], usage=RequestUsage(input_tokens=9)
        )
        FileSystemStorage(tmp_path / "store").put(
            answer_key(run, "x4", number), ModelMessagesTypeAdapter.dump_json([response])
        )


def unit(key: str, *statements: dict[str, Any]) -> dict[str, Any]:
    return {"unitKey": key, "statements": list(statements), "checkedAbsent": []}


async def test_a_replay_reads_what_the_run_read(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    # E1 answered with a statement and one more in a block the conversion does not hold: a finding
    stray = unit("E1", a_statement("p2-b2", "Aussage E1"), a_statement("p9-b9", "Aussage E1 zwei"))
    document = await extracted(pool, connection, tmp_path, database_url, Model(units={"E1": stray}))

    found = await replayed(connection, tmp_path, document)

    assert (found.runs, found.answers, found.gone, found.unreadable, found.beyond_ledger) == (1, 2, 0, 0, 0)
    assert (found.units, found.statements_now, found.statements_stored) == (2, 2, 2)
    assert (found.out_of_form, found.unknown_unit, found.missing, found.ambiguous) == (0, 0, 0, 0)
    # what the run's reading found ...
    assert found.findings_stored == {"x4.statement_without_block": 1, "x4.unknown_block": 1}
    assert found.findings_now == found.findings_stored  # ... today's finds again
    stored = [(item.text_hash, item.first_block) for item in await model_statements(connection, document.id)]
    assert sorted(found.keys) == sorted(stored)  # the same wordings at the same blocks
    assert found.lexicon_release_then == found.lexicon_release_now is not None
    assert (found.units_differing, found.repaired_units) == ((), ())


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
    await kept_later(connection, tmp_path, document, [unit("E9", a_statement("p2-b2", "Aussage E9"))])

    found = await replayed(connection, tmp_path, document)

    # E1 spoilt, E1 in form, E2 in form, and an answer for a unit X2 did not cut
    assert (found.answers, found.out_of_form, found.unknown_unit, found.missing) == (4, 1, 1, 0)
    assert (found.statements_now, found.statements_stored, found.units_differing) == (2, 2, ())


async def test_a_unit_s_answer_is_its_run_s_and_a_second_naming_it_is_not_guessed(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    # an answer naming E2, kept after E2's own in the same run - another unit's, which the run threw away
    two = [a_statement("p2-b4", "Aussage E2 eins"), a_statement("p2-b4", "Aussage E2 zwei")]
    await kept_later(connection, tmp_path, document, [unit(" E2 ", *two)])

    ambiguous = await replayed(connection, tmp_path, document)
    await connection.execute("UPDATE extraction_unit SET run_id = NULL WHERE unit_key = 'E2'")  # run gone
    last = await replayed(connection, tmp_path, document)

    assert (ambiguous.ambiguous, ambiguous.missing, ambiguous.statements_now) == (1, 0, 1)  # E1 alone
    assert ambiguous.units_differing == ("E2",)
    # no X4 run wrote it: the last answer in form naming it
    assert (last.ambiguous, last.statements_now, last.units_differing) == (0, 3, ("E2",))


async def test_answers_gone_unreadable_or_beyond_the_ledger_are_told_and_the_rest_is_read(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    run = await x4_run(connection, document)
    store = FileSystemStorage(tmp_path / "store")
    first = store.get(answer_key(run, "x4", 1))
    store.delete(answer_key(run, "x4", 1))
    store.put(answer_key(run, "x4", 2), b"not an answer")
    store.put(answer_key(run, "x4", 3), first)  # kept, never booked

    found = await replayed(connection, tmp_path, document)

    assert (found.answers, found.gone, found.unreadable, found.beyond_ledger) == (2, 1, 1, 1)
    assert (found.statements_now, found.missing) == (1, 1)  # the first answer read from 3; the other lost


async def test_a_unit_written_anew_by_a_repair_is_told_and_no_run_done_leaves_the_release_unsaid(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    repair = await start_run(connection, RunStart(document.id, None, None, "X6", None, None, None, None))
    await connection.execute(
        "UPDATE extraction_unit SET run_id = %s, repairs = 1 WHERE unit_key = 'E2'", (repair,)
    )
    await connection.execute("UPDATE extraction_unit SET repairs = 1 WHERE unit_key = 'E1'")  # wrote nothing
    await connection.execute(
        "UPDATE extraction_run SET outcome = 'failed' WHERE id = %s", (await x4_run(connection, document),)
    )

    found = await replayed(connection, tmp_path, document)

    assert found.repaired_units == ("E2",)  # E1's repair wrote nothing: X4's still
    assert (found.statements_now, found.missing) == (2, 0)  # E2 by its last answer in form
    assert found.lexicon_release_then is None  # no X4 run ended done
