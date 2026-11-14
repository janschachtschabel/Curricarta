"""X5 checks a document's anchors in batches within a time budget (audit 2026-11-14): each batch's
matches written under the lease and the tree's lock as it is done; past X5_ANCHOR_BUDGET_S no further
batch begins, the rest stays unchecked with the finding ``x5.anchors_unchecked``, and the next check goes
on with exactly the anchors not reached. A model stands in for X1 to X4; the clock is injected."""

import asyncio
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from app.db.anchors import UncheckedAnchor
from app.jobs.queue import LeaseLost, hold_lease
from app.pipeline import run, x5_stage
from app.pipeline.anchor_check import AnchorMatch
from app.pipeline.run import extract_document
from tests.pipeline.test_run import Model, a_document, a_job, context_of, rows, setup
from tests.pipeline.test_x5_stage import matched, skipped, x5_findings, x5_runs

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run


async def all_anchors(connection: Any, document: Any) -> int:
    """The anchors X5 checks in the stand-in's document: those of statements and of headings."""
    [(count,)] = await rows(
        connection,
        "SELECT count(*) FROM anchor a JOIN anchor_block ab ON ab.anchor_id = a.id"
        " WHERE a.document_id = %s AND (a.statement_id IS NOT NULL OR a.node_id IS NOT NULL)",
        document.id,
    )
    return int(count)


def ticking(step: float) -> Callable[[], float]:
    """A clock that goes on by ``step`` each time it is read."""
    ticks: Iterator[float] = (step * n for n in range(1_000_000))
    return lambda: next(ticks)


async def x4_done(pool: Any, connection: Any, tmp_path: Path, database_url: str) -> tuple[Any, Any, Any]:
    """A document X1 to X4 have read, and its job and context: X5 to come."""
    document = await a_document(connection)
    job = await a_job(connection, document.id, document.owner_id)
    context = context_of(pool, tmp_path, Model(), database_url)
    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(run, "run_x5", skipped)
        await extract_document(context, job)
    return document, job, context


async def test_x5_writes_the_matches_batch_by_batch(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document, job, context = await x4_done(pool, connection, tmp_path, database_url)
    total = await all_anchors(connection, document)
    assert total >= 3
    monkeypatch.setattr(x5_stage, "ANCHOR_BATCH", 2)
    seen_before: list[int] = []  # the matches committed as each batch's write begins

    async def counted(writing: Any, attempt: Any) -> None:
        seen_before.append(await matched(connection, document))
        await hold_lease(writing, attempt)

    monkeypatch.setattr(x5_stage, "hold_lease", counted)
    made = await x5_stage.run_x5(context, job, document)

    batches = -(-total // 2)
    # one write per batch, each after the ones before were committed; the run's end writes last
    assert seen_before[:batches] == [min(2 * n, total) for n in range(batches)]
    assert await matched(connection, document) == total
    assert made["anchors_left"] == 0
    assert "x5.anchors_unchecked" not in {rule for rule, _, _ in await x5_findings(connection, document)}


async def test_x5_past_its_time_leaves_the_rest_unchecked_says_so_and_ends(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    pool, connection = setup
    document, job, context = await x4_done(pool, connection, tmp_path, database_url)
    total = await all_anchors(connection, document)
    monkeypatch.setattr(x5_stage, "ANCHOR_BATCH", 1)
    # read at the start, before each batch, at the end: the first batch at 200 s, the second past 300 s
    monkeypatch.setattr(x5_stage, "monotonic", ticking(200.0))

    with caplog.at_level("INFO", logger="app.pipeline.x5_stage"):
        made = await x5_stage.run_x5(context, job, document)

    assert await matched(connection, document) == 1
    assert made["anchors_left"] == total - 1
    [(outcome, result)] = await x5_runs(connection, document)
    assert (outcome, result["anchors_left"]) == ("done", total - 1)
    [(severity, focus, details)] = await rows(
        connection,
        "SELECT severity, focus_id, details FROM validation_finding"
        " WHERE document_id = %s AND rule = 'x5.anchors_unchecked'",
        document.id,
    )
    assert (severity, focus, details) == ("violation", document.id, {"unchecked": total - 1})
    assert "x5 checked 1 anchors in 600.0 s" in caplog.messages


async def test_a_check_again_goes_on_where_the_time_ran_out(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document, job, context = await x4_done(pool, connection, tmp_path, database_url)
    total = await all_anchors(connection, document)
    monkeypatch.setattr(x5_stage, "ANCHOR_BATCH", 1)
    with monkeypatch.context() as patched:
        patched.setattr(x5_stage, "monotonic", ticking(200.0))
        await x5_stage.run_x5(context, job, document)
    left = {
        found
        for (found,) in await rows(
            connection,
            "SELECT a.id FROM anchor a JOIN anchor_block ab ON ab.anchor_id = a.id"
            " WHERE a.document_id = %s AND a.match_kind_iri IS NULL"
            " AND (a.statement_id IS NOT NULL OR a.node_id IS NOT NULL)",
            document.id,
        )
    }
    asked: list[Any] = []
    matching = x5_stage._matched

    def watched(batch: Sequence[UncheckedAnchor], stop: threading.Event) -> list[AnchorMatch]:
        asked.extend(anchor.id for anchor in batch)
        return matching(batch, stop)

    monkeypatch.setattr(x5_stage, "_matched", watched)
    made = await x5_stage.run_x5(context, job, document, again=True)  # as POST /documents/{id}/check does

    assert len(left) == total - 1
    assert sorted(asked) == sorted(left)
    assert (made["anchors_left"], await matched(connection, document)) == (0, total)
    assert "x5.anchors_unchecked" not in {rule for rule, _, _ in await x5_findings(connection, document)}


async def test_the_matches_of_the_batches_before_stay_where_the_lease_is_lost_between_two(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document, job, context = await x4_done(pool, connection, tmp_path, database_url)
    monkeypatch.setattr(x5_stage, "ANCHOR_BATCH", 1)
    writes = 0

    async def lost_before_the_second(writing: Any, attempt: Any) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:  # the first batch's write is committed: the lease runs out before the next
            await connection.execute(
                "UPDATE job SET lease_expires_at = now() - interval '1 second' WHERE id = %s", (job.id,)
            )
        await hold_lease(writing, attempt)

    monkeypatch.setattr(x5_stage, "hold_lease", lost_before_the_second)
    with pytest.raises(LeaseLost):
        await x5_stage.run_x5(context, job, document)

    assert await matched(connection, document) == 1
    assert [(outcome, made.get("failure")) for outcome, made in await x5_runs(connection, document)] == [
        ("failed", "LeaseLost")
    ]
    assert await x5_findings(connection, document) == []


async def test_a_cancel_stops_the_matching_after_the_anchor_in_hand(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document, job, context = await x4_done(pool, connection, tmp_path, database_url)
    assert await all_anchors(connection, document) >= 2  # one batch holds them all
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    compared: list[str] = []
    matching = x5_stage._matched

    def slow(wording: str, texts: Sequence[str]) -> AnchorMatch:
        compared.append(wording)
        entered.set()
        release.wait(10)
        return AnchorMatch("notFound", None, None, None, None)

    def watched(batch: Sequence[UncheckedAnchor], stop: threading.Event) -> list[AnchorMatch]:
        try:
            return matching(batch, stop)
        finally:
            finished.set()

    monkeypatch.setattr(x5_stage, "check_wording", slow)
    monkeypatch.setattr(x5_stage, "_matched", watched)
    checking = asyncio.create_task(x5_stage.run_x5(context, job, document))
    assert await asyncio.to_thread(entered.wait, 10)
    checking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await checking
    release.set()
    assert await asyncio.to_thread(finished.wait, 10)

    assert len(compared) == 1
    assert await matched(connection, document) == 0
