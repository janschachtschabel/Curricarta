"""What the measuring commands share - the usage report, the replay, the gold report, the MEM import's
report: each reads through one snapshot that refuses every write (app/db/snapshot.py), and each checks its
output before it prints, refusing what is not a count, rate or code (app/quality/closed.py)."""

import argparse
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.db.migrate import migrate
from app.db.snapshot import snapshot
from app.pipeline import replay
from app.quality import mem_report, report, usage_report
from tests.llm.test_client import llm_settings
from tests.support import kept_logging, make_settings, without_settings_variables

NOWHERE = UUID("01a1951f-692d-7a7c-9470-8b70074d6685")


def calls(module: Any, database_url: str, store: Path) -> Callable[[], Awaitable[object]]:
    """The command's own reading, as its main runs it, for a document or sample that is not there."""
    settings = make_settings(database_url=database_url, storage_dir=store)
    if module is replay:
        return lambda: replay._replayed(settings, llm_settings(), NOWHERE)
    if module is report:
        return lambda: report._report(settings, [999_999], True)
    if module is mem_report:
        found = argparse.Namespace(document=NOWHERE, label="pilot-1", endpoint_counts=False)
        return lambda: mem_report._report(settings, found)
    arguments = argparse.Namespace(document=NOWHERE, label="pilot-1", raw=True)
    return lambda: usage_report._report(settings, 16_000, arguments)


@pytest.mark.pg
@pytest.mark.anyio
@pytest.mark.parametrize(
    "module", [replay, report, usage_report, mem_report], ids=["replay", "report", "usage", "mem"]
)
async def test_each_command_reads_through_a_snapshot_that_refuses_writes(
    module: Any, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate(database_url)
    opened: list[str] = []

    @asynccontextmanager
    async def watched(url: str) -> AsyncIterator[psycopg.AsyncConnection]:
        async with snapshot(url) as connection:
            opened.append(url)
            yield connection

    monkeypatch.setattr(module, "snapshot", watched)

    with pytest.raises(Exception, match="unknown_"):  # nothing there: refused, after the snapshot was opened
        await calls(module, database_url, tmp_path)()

    assert opened == [database_url]


@pytest.mark.parametrize(
    ("module", "arguments"),
    [
        (replay, [str(NOWHERE)]),
        (usage_report, [str(NOWHERE), "--label", "pilot-1"]),
        (report, ["--sample", "1"]),
        (mem_report, [str(NOWHERE), "--label", "pilot-1"]),
    ],
    ids=["replay", "usage", "report", "mem"],
)
def test_an_output_that_is_not_closed_is_refused_not_printed(
    module: Any,
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def leaking(*_: object) -> Any:
        if module is replay:
            return replay.Replayed(**{**EMPTY, "findings_now": {"a wording with spaces": 1}})
        return {"label": "a wording with spaces"}

    monkeypatch.setattr(module, "_replayed" if module is replay else "_report", leaking)
    with without_settings_variables(), kept_logging():
        monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
        done = module.main(arguments)

    printed = capsys.readouterr()
    assert (done, printed.out) == (1, "")
    assert "report_not_closed" in printed.err


EMPTY: dict[str, Any] = {
    "runs": 0, "answers": 0, "gone": 0, "unreadable": 0, "beyond_ledger": 0, "units": 0,
    "statements_now": 0, "statements_stored": 0, "findings_now": {}, "findings_stored": {}, "out_of_form": 0,
    "unknown_unit": 0, "missing": 0, "ambiguous": 0, "repaired_units": (), "units_differing": (),
    "lexicon_release_then": None, "lexicon_release_now": None, "keys": (),
}  # fmt: skip
