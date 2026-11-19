"""X5 of the job extract.run (plan M1 8.1-8.5; konzept §13.2 "Prüfen"): no model asked.

1. Each anchor of a statement or a node's heading that has no match kind yet is checked against the
   text of the blocks it names (app/pipeline/anchor_check.py) - a statement imported from MEM-Schule with
   the wording its import looked for (app/sources/mem/anchoring.py) - CPU work, beside the event loop - and
   its match kind, the document's text at the place and its span written under the attempt's lease and
   the tree's lock (who changes a tree's anchors takes it first, migration l1_nodes) - batch by batch,
   each written as it is done, within X5_ANCHOR_BUDGET_S (audit 2026-11-14): past it no further batch
   begins, the rest stays unchecked with ``x5.anchors_unchecked`` (violation), and the next check of the
   document goes on with it; freezing refuses a document with an anchor unchecked (app/db/freezing.py).
2. A wording its named blocks do not hold is ``x5.wording_not_found`` (violation) on its statement or
   node, read from the anchors as they stand, so a later run of X5 finds it again; the plausibility
   checks (app/pipeline/x5_checks.py) add theirs. A wording the MEM import found nowhere in the document
   (no block, an estimated page, the row not edited since) is ``x5.import_not_found`` (warning): a hint
   for the redaktion, not a false claim (plan M2, E3).
3. The document's Kern graph is validated against the shapes in a child process
   (app/pipeline/shacl.py) within SHACL_TIMEOUT_S; past it, ``x5.shacl_timeout`` (violation) keeps the
   gate shut, and X5 ends all the same.
4. The findings and the run's end are written in one transaction under the lease; another job's run of
   X5 done meanwhile passes this one over (app/pipeline/asking.py, Superseded).

After a repair (job extract.repair, plan M1 8b) X5 runs ``again``: a run done before does not stop it, and
its findings replace those of the stage's runs before - they describe the document before the repair.
One open extraction job per document (app/pipeline/extraction.py) keeps a second such run away.
"""

import asyncio
import logging
import threading
from collections import Counter
from collections.abc import Sequence
from time import monotonic
from typing import Any

from app.core.child import ChildLog
from app.db.anchors import (
    CheckedAnchor,
    UncheckedAnchor,
    import_not_found_anchors,
    match_kinds,
    not_found_anchors,
    set_matches,
    unchecked_anchors,
)
from app.db.documents import Document
from app.db.findings import Finding, add_findings, drop_stage_findings
from app.db.nodes import lock_tree
from app.db.runs import RunStart, done_stages, finish_run, lock_for_stage, start_run
from app.domain.l1 import Severity
from app.exports.kern_rdf import kern_graph
from app.exports.kern_rows import read_document
from app.jobs.context import JobContext
from app.jobs.queue import Job, hold_lease
from app.pipeline.anchor_check import NOT_FOUND, AnchorMatch, check_wording
from app.pipeline.asking import Superseded, ended
from app.pipeline.progress import report
from app.pipeline.shacl import ShaclTimeout, as_findings, shacl_check
from app.pipeline.x4_unit import UNIT_WITHOUT_NODE
from app.pipeline.x5_checks import plausibility
from app.sources.mem.anchoring import looked_for
from app.vocab.lookup import current_release

log = logging.getLogger(__name__)
PROMPT_VERSION = "x5-checks/3"  # the checks' version: a run says by which rules it found
ANCHOR_BATCH = 200  # the anchors matched, then written, at a time
_CV = "https://w3id.org/wlo/curriculum/vocab#"
_MOST_QUOTE = 20_000  # what the anchor's quote holds (0015)
_SEVERITIES: tuple[Severity, ...] = ("violation", "warning", "info")


async def run_x5(context: JobContext, job: Job, document: Document, *, again: bool = False) -> dict[str, Any]:
    """X5 of the document, ended by what it found or by what broke it; ``again`` after a repair."""
    async with context.pool.connection() as connection:
        if not again and "X5" in await done_stages(connection, document.id):
            return {"done_before": True}
        # the lease first: an attempt that lost it starts no run that would never end
        await report(connection, job, "check_document")
        start = RunStart(
            document.id,
            job.id,
            job.attempts,
            "X5",
            None,
            PROMPT_VERSION,
            None,
            await current_release(connection),
        )
        run_id = await start_run(connection, start)
    return await ended(context, run_id, "X5", _checked(context, job, document, run_id, again=again))


async def _checked(
    context: JobContext, job: Job, document: Document, run_id: Any, *, again: bool
) -> dict[str, Any]:
    left = await _anchors(context, job, document)
    # the findings and the graph of one state of the document: a node moved meanwhile is in both or in none
    async with context.pool.connection() as connection, connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        findings = [
            Finding(
                "x5.wording_not_found",
                "violation",
                owner,
                "the wording is not in the blocks its anchor names",
                details={"anchor": str(anchor)},
            )
            for anchor, owner in await not_found_anchors(connection, document.id)
        ]
        findings += [
            Finding(
                "x5.import_not_found",
                "warning",
                owner,
                "the import found the wording nowhere in the document; its page is estimated",
                details={"anchor": str(anchor)},
            )
            for anchor, owner in await import_not_found_anchors(connection, document.id)
        ]
        findings += await plausibility(connection, document.id)
        if left:
            message = f"{left} anchors were not checked within X5_ANCHOR_BUDGET_S: the next check goes on"
            findings.append(
                Finding(
                    "x5.anchors_unchecked", "violation", document.id, message, details={"unchecked": left}
                )
            )
        kinds = await match_kinds(connection, document.id)  # as they stand: an attempt before set some
        rows = await read_document(connection, document.id)
    graph = await asyncio.to_thread(kern_graph, rows)  # a second for a long document: beside the loop
    settings = context.settings
    told = ChildLog.of(settings)
    shacl = "done"
    try:
        results = await shacl_check(
            graph, ontology_dir=settings.ontology_dir, timeout_s=settings.shacl_timeout_s, told=told
        )
        findings += as_findings(results, document.id)
    except ShaclTimeout:
        shacl = "timeout"
        message = f"the SHACL validation took longer than {settings.shacl_timeout_s} s: the gate stays shut"
        findings.append(Finding("x5.shacl_timeout", "violation", document.id, message))
    counted = Counter(found.severity for found in findings)
    result = {
        "anchors": kinds,
        "anchors_left": left,
        "findings": {severity: counted[severity] for severity in _SEVERITIES},
        "shacl": shacl,
    }
    async with context.pool.connection() as connection, connection.transaction():
        await hold_lease(connection, job)
        if await lock_for_stage(connection, document.id, "X5") and not again:
            raise Superseded
        if again:
            # x5.anchors_unchecked of a run before goes here, with the run's end, not with the last
            # batch: a check again that wrote the last anchors and then failed (its SHACL child) leaves it
            # standing though none is unchecked - meant: it sends the editors to check again, which clears it
            await drop_stage_findings(connection, document.id, "X5", keep_run=run_id)
        await add_findings(connection, document.id, run_id, findings)
        await finish_run(connection, run_id, "done", result)
    return result


async def _anchors(context: JobContext, job: Job, document: Document) -> int:
    """Check the document's unchecked anchors batch by batch, each batch's matches written under the
    lease as it is done, until the budget is spent; how many were left unchecked."""
    async with context.pool.connection() as connection:
        # X4's node of a unit under no heading bears the document's title, no wording of its blocks
        unchecked = await unchecked_anchors(connection, document.id, rule_titles=(UNIT_WITHOUT_NODE,))
    budget = context.settings.x5_anchor_budget_s
    started = monotonic()
    stop = threading.Event()  # set by a cancel: the thread ends after the anchor in hand
    done = 0
    while done < len(unchecked) and monotonic() - started < budget:
        batch = unchecked[done : done + ANCHOR_BATCH]
        try:
            matches = await asyncio.to_thread(_matched, batch, stop)
        except BaseException:
            stop.set()
            raise
        # a lost lease writes nothing more; the batches before stay, matches of the anchors as they are
        async with context.pool.connection() as connection, connection.transaction():
            await hold_lease(connection, job)
            await lock_tree(connection, document.id)
            await set_matches(
                connection,
                [checked_anchor(anchor, match) for anchor, match in zip(batch, matches, strict=True)],
            )
        done += len(batch)
    log.info("x5 checked %d anchors in %.1f s", done, monotonic() - started)
    return len(unchecked) - done


def _matched(batch: Sequence[UncheckedAnchor], stop: threading.Event) -> list[AnchorMatch]:
    """The batch's matches, in a thread; fewer where ``stop`` is set - its caller is gone by then."""
    matches = []
    for anchor in batch:
        if stop.is_set():
            break
        matches.append(check_anchor(anchor))
    return matches


def check_anchor(anchor: UncheckedAnchor) -> AnchorMatch:
    """How the anchor's wording stands in its blocks; a MEM statement's as the import looked for it - the
    first of ``looked_for`` its blocks hold, so that its match kind and quote follow the search."""
    match = NOT_FOUND
    for wording in looked_for(anchor.wording, statement=anchor.mem_statement):
        match = check_wording(wording, anchor.texts)
        if match.kind != NOT_FOUND.kind:
            break
    return match


def checked_anchor(anchor: UncheckedAnchor, match: AnchorMatch) -> CheckedAnchor:
    """The match as the anchor keeps it; a quote longer than the store holds is left out, its span kept."""
    quote = match.quote if match.quote is None or len(match.quote) <= _MOST_QUOTE else None
    return CheckedAnchor(anchor.id, _CV + "match_" + match.kind, match.score, quote, match.start, match.end)
