"""``python -m app.pipeline.replay`` and ``python -m app.quality.report --replayed`` as the operator calls
them: one line of counts and codes, nothing written, a refusal in one line; the gold report's ``replayed``
block telling what the replay rests on."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.core.ids import new_id
from app.core.storage import FileSystemStorage
from app.db.gold import Judgement, items_of, judge
from app.db.nodes import write_subtree
from app.domain.l1 import NodeDraft
from app.llm.raw import answer_key
from app.quality.closed import closed
from app.quality.sample import Request, draw
from tests.pipeline.test_replay import extracted, replayed, x4_run
from tests.pipeline.test_run import BODY, CV, Model, a_document, rows, setup
from tests.quality.gold_documents import MODEL, PROPOSED, done, statement
from tests.support import without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, from test_run

BACKEND = Path(__file__).resolve().parents[2]


def command(
    module: str, database_url: str, store: Path, *arguments: str
) -> subprocess.CompletedProcess[bytes]:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url, "STORAGE_DIR": str(store)}
    return subprocess.run(  # noqa: S603 - the interpreter running the tests, the tests' own arguments
        [sys.executable, "-m", module, *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        timeout=180,
        check=False,
    )


async def test_nothing_is_written(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())
    before = await _counts(connection), _keys(tmp_path / "store")

    await replayed(connection, tmp_path, document)
    done_ = command("app.pipeline.replay", database_url, tmp_path / "store", str(document.id))

    assert done_.returncode == 0, done_.stderr
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


async def test_the_counts_name_no_wording(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(pool, connection, tmp_path, database_url, Model())

    made = command("app.pipeline.replay", database_url, tmp_path / "store", str(document.id), "--stage", "x4")

    assert made.returncode == 0, made.stderr
    [line] = made.stdout.splitlines()  # one line of JSON
    printed = json.loads(line)
    assert printed["statements_now"] == printed["statements_stored"] == 2
    assert (printed["runs"], printed["repaired"], printed["repaired_units"]) == (1, 0, [])
    assert "keys" not in printed
    text = line.decode("utf-8")
    assert "Aussage" not in text and all(word not in text for word in BODY.split() if len(word) > 4)
    closed(printed)  # counts and codes alone


async def test_a_document_without_raw_answers_says_so(setup: Any, tmp_path: Path, database_url: str) -> None:
    _, connection = setup
    document = await a_document(connection)  # never extracted
    store = tmp_path / "store"

    refused = command("app.pipeline.replay", database_url, store, str(document.id))
    nowhere = command("app.pipeline.replay", database_url, store, str(new_id()))
    amiss = command("app.pipeline.replay", database_url, store, str(document.id), "--stage", "x3")

    assert (refused.returncode, refused.stdout) == (1, b"")
    [line] = refused.stderr.splitlines()
    assert b"no_raw_answers" in line
    assert (nowhere.returncode, nowhere.stdout) == (1, b"")
    assert b"unknown_document" in nowhere.stderr
    assert amiss.returncode == 2  # x4 alone is replayed


async def test_the_gold_report_tells_what_the_replay_keeps_of_the_judgements_and_what_it_rests_on(
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
    store = tmp_path / "store"

    whole = command("app.quality.report", database_url, store, "--sample", str(sample), "--replayed")
    FileSystemStorage(store).delete(answer_key(await x4_run(connection, document), "x4", 1))
    short = command("app.quality.report", database_url, store, "--sample", str(sample), "--replayed")
    refused = command("app.quality.report", database_url, store, "--sample", str(elsewhere), "--replayed")

    assert whole.returncode == 0, whole.stderr
    assert json.loads(whole.stdout)["documents"][0]["statement"]["replayed"] == {
        "judged": 2,
        "kept_correct": 2, "kept_imprecise": 0, "kept_wrong": 0,
        "gone_correct": 0, "gone_imprecise": 0, "gone_wrong": 0,
        "new_unjudged": 0,
        "replay": {
            "runs": 1, "answers": 2, "gone": 0, "swept": 0, "unreadable": 0, "beyond_ledger": 0,
            "out_of_form": 0, "missing": 0, "ambiguous": 0, "repaired": 0,
            "lexicon_release_then": json.loads(whole.stdout)["documents"][0]["runs"]["X4"]["lexicon_release"],
            "lexicon_release_now": json.loads(whole.stdout)["documents"][0]["runs"]["X4"]["lexicon_release"],
        },
    }  # fmt: skip
    # one kept answer gone from the store: a judgement is lost, and the block says why
    lost = json.loads(short.stdout)["documents"][0]["statement"]["replayed"]
    assert (lost["kept_correct"], lost["gone_correct"]) == (1, 1)
    assert (lost["replay"]["gone"], lost["replay"]["missing"]) == (1, 1)
    assert (refused.returncode, refused.stdout) == (1, b"")
    assert b"no_raw_answers" in refused.stderr
