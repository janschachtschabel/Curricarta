"""``app.pipeline.replay`` after the retention took a run's raw answers (python -m app.retention, past
RETENTION_RAW_ANSWERS_DAYS): their run is not read and its answers are counted apart (``swept``), never as
answers gone from the store; where it took every X4 run's, the replay says so."""

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart
from pydantic_ai.usage import RequestUsage

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.db.runs import RunStart, finish_run, start_run
from app.llm.raw import answer_key
from app.pipeline.replay import Refused
from app.retention import Policy, sweep
from tests.pipeline.test_replay import extracted, replayed
from tests.pipeline.test_run import Model, setup

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, from test_run

RAW_ANSWERS_ONLY = Policy(jobs_days=0, audit_days=0, raw_answers_days=30)
# ended 40 days ago, past the raw answers' 30
AGED = (
    "UPDATE extraction_run SET started_at = now() - interval '41 days',"
    " finished_at = now() - interval '40 days'"
)


async def test_answers_the_retention_took_are_counted_apart_and_the_kept_run_is_read(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    before = await replayed(connection, tmp_path, document)
    store = FileSystemStorage(tmp_path / "store")
    older = await start_run(connection, RunStart(document.id, None, 1, "X4", "m", "x", None, None))
    await finish_run(connection, older, "done", {})
    for number in (1, 2):  # an earlier run's two answers, booked and kept
        await connection.execute(
            "INSERT INTO llm_usage (account_id, run_id, purpose, model, input_tokens, cached_input_tokens,"
            " output_tokens, requests, unanswered_requests, estimated)"
            " VALUES (%s, %s, 'x4.unit', 'm', 9, 0, 9, 1, 0, false)",
            (document.owner_id, older),
        )
        response = ModelResponse(
            parts=[ToolCallPart("final_result", "{}")], usage=RequestUsage(input_tokens=9)
        )
        store.put(answer_key(older, "x4", number), ModelMessagesTypeAdapter.dump_json([response]))
    await connection.execute(AGED + " WHERE id = %s", (older,))

    taken = await sweep(connection, AsyncStorage(store), RAW_ANSWERS_ONLY, dry_run=False)
    found = await replayed(connection, tmp_path, document)

    assert (taken.runs, taken.objects) == (1, 2)
    assert (found.runs, found.answers, found.swept, found.gone) == (before.runs, before.answers, 2, 0)
    assert (found.statements_now, found.missing) == (before.statements_now, before.missing)


async def test_a_document_whose_x4_answers_the_retention_took_says_so(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    await connection.execute(AGED + " WHERE document_id = %s", (document.id,))
    await sweep(
        connection, AsyncStorage(FileSystemStorage(tmp_path / "store")), RAW_ANSWERS_ONLY, dry_run=False
    )

    with pytest.raises(Refused, match="raw_answers_swept"):
        await replayed(connection, tmp_path, document)
