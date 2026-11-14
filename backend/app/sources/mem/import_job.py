"""The job extract.mem_import: a MEM-Schule plan imported into the document made for it (plan M2, E1/E2/E5;
Teilplan M2-5).

The route made the document of a finished conversion and named its plan (``document.mem_iri``). The job:

1. asks the endpoint whether its graph still holds the plan - a plan gone since the catalogue was read is
   ``mem_unknown_plan``, as is one the catalogue no longer names;
2. reads the plan's closure and references in pages and keeps them raw under the run (``runs/<run>/im/``);
3. builds the tree (app/sources/mem/tree.py), types it by the rules ``mem-rules/2`` as the lexicon and
   vocabulary in the database hold them (app/sources/mem/rules_db.py), a plan of the KMK's graph by its table;
4. looks for every wording in the conversion's text, without page edges and contents, in the document's
   order and within MEM_SEARCH_BUDGET_S (app/sources/mem/anchoring.py);
5. writes the tree as imported, proposed rows with their anchors and MEM traces, and the run IM, in one
   transaction under the lease - another run of IM done meanwhile passes this one over; a tree the
   document's profile does not take (a node type of the school's lexicon in another sector) ends the job
   (``mem_unwritable``), as another attempt would end alike;
6. checks the document as X5 does after an extraction.

A run of IM done before is not run again; X5 runs where it is owed. An answer the client cannot take ends
the job (``mem_refused``); an endpoint away for now leaves it to another attempt, at the last one it ends
``mem_unavailable``. The job reports reading the plan (``mem_read``) and looking for its wordings
(``mem_anchor``).
"""

import asyncio
import json
from collections import Counter
from collections.abc import Sequence
from functools import partial
from typing import Any

from app.conversion.base import Block
from app.db.conversions import all_blocks
from app.db.documents import Document, DocumentError, document_for_job
from app.db.mem_plans import MemPlan, plan_by_iri
from app.db.nodes import write_subtree
from app.db.runs import RunStart, done_stages, finish_run, lock_for_stage, start_run, x5_owed
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from app.jobs.queue import Job, check_lease, hold_lease
from app.llm.raw import RawResponses
from app.pipeline.anchor_search import search_text
from app.pipeline.asking import Superseded, ended
from app.pipeline.extraction import document_in
from app.pipeline.ground import contents_of, ground_of
from app.pipeline.progress import report
from app.pipeline.toc import title_page_blocks
from app.pipeline.x5_stage import run_x5
from app.sources.mem.anchoring import Anchored, anchor_rows
from app.sources.mem.classes import RULES
from app.sources.mem.drafts import Row, drafts_from, rows_in_order, rule_counts
from app.sources.mem.import_kind import KIND as KIND
from app.sources.mem.import_kind import STAGES as STAGES
from app.sources.mem.queries import closure_count, closure_page, plan_count, reference_count, reference_page
from app.sources.mem.rules_db import load_rules
from app.sources.mem.sparql import KMK_GRAPH, MemEndpoint, MemRefused, MemSparql, MemUnavailable
from app.sources.mem.tree import build_tree, storable_iri


async def import_document(context: JobContext, job: Job, *, transport: Any = None) -> dict[str, Any]:
    """The import of the job's document; ``transport`` is the network (tests)."""
    document_id = document_in(job.payload)
    async with context.pool.connection() as connection:
        document = None if document_id is None else await document_for_job(connection, document_id)
        if document is None:
            raise PermanentError("document_gone", "the document to import into is gone")
        plan = None if document.mem_iri is None else await plan_by_iri(connection, document.mem_iri)
        done = await done_stages(connection, document.id)
        owed = await x5_owed(connection, document.id)
    if "IM" not in done:
        if plan is None:
            raise PermanentError("mem_unknown_plan", "the catalogue names the document's plan no more")
        await _run_im(context, job, document, plan, transport)
    if "X5" not in done:
        await run_x5(context, job, document)
    elif owed:
        await run_x5(context, job, document, again=True)
    return {"document_id": str(document.id), "stages": STAGES}


async def _run_im(context: JobContext, job: Job, document: Document, plan: MemPlan, transport: Any) -> None:
    async with context.pool.connection() as connection:
        ground = await ground_of(connection, document)
        rules = await load_rules(connection, context.settings.ontology_dir, kmk=plan.graph == KMK_GRAPH)
        start = RunStart(document.id, job.id, job.attempts, "IM", None, RULES, ground.profile, ground.release)
        # an attempt that lost its lease starts no run that would never end - check_lease reads its
        # expiry too, which a progress report does not
        await check_lease(connection, job)
        run_id = await start_run(connection, start)
    raw = RawResponses(context.storage.sync, run_id, "im")
    sparql = MemSparql(MemEndpoint(context.settings.mem_sparql_url), transport)

    async def work() -> dict[str, Any]:
        async with context.pool.connection() as connection:
            await report(connection, job, "mem_read")
        try:
            closure, references = await _read(sparql, plan)
            await raw.keep(
                json.dumps({"plan": plan.iri, "closure": closure, "references": references}).encode()
            )
            tree = build_tree(closure, references)
        except MemRefused as refused:
            raise PermanentError(
                "mem_refused", f"the endpoint's answer for the plan was refused: {refused}"
            ) from None
        except MemUnavailable as away:
            if job.attempts < job.max_attempts:
                raise  # another attempt asks again
            raise PermanentError("mem_unavailable", f"the endpoint stayed out of reach: {away}") from None
        async with context.pool.connection() as connection:
            await report(connection, job, "mem_anchor")
            blocks = await all_blocks(connection, document.conversion_id)
        contents = await asyncio.to_thread(contents_of, ground, blocks, document.document_type_iri)
        searched = search_text(blocks, contents.positions)
        rows = rows_in_order(tree, rules, plan.iri, plan.title)
        anchored = await anchor_rows(rows, searched, context.settings.mem_search_budget_s)
        result = {
            "rules": RULES,
            "parts": len(closure),
            "references": sum(part.reference for part in tree.parts.values()),
            "typed": dict(rule_counts(tree, rules)),
            "stages": {kind: dict(counted) for kind, counted in anchored.stages.items()},
            "unsearched": anchored.unsearched,
            # found on the title pages, before the contents end them (E15 counts them apart)
            "front": _front(rows, anchored, blocks, contents.front_end),
            # rows the tables take no MEM IRI of: no MEM subject in the export
            "untraced": sum(not storable_iri(iri) for iri in tree.parts),
        }
        try:
            drafts = drafts_from(tree, rules, plan.iri, plan.title, anchored.anchors)
            async with context.pool.connection() as connection, connection.transaction():
                await hold_lease(connection, job)
                if await lock_for_stage(connection, document.id, "IM"):
                    raise Superseded
                for root in drafts:
                    await write_subtree(connection, document.id, root, run_id=run_id)
                await finish_run(connection, run_id, "done", result)
        except (ValueError, DocumentError) as refused:  # a draft's, and ProfileValueError is one
            raise PermanentError(
                "mem_unwritable", f"the document does not take the plan's tree: {refused}"
            ) from None
        return result

    await ended(context, run_id, "IM", work())


def _front(
    rows: Sequence[Row], anchored: Anchored, blocks: Sequence[Block], front_end: int | None
) -> dict[str, dict[str, int]] | None:
    """How many rows of nodes and of statements were found on the title pages, by stage; None where the
    document's contents were not found, so that no title pages are known."""
    before = title_page_blocks(blocks, front_end)
    if before is None:
        return None
    counted: dict[str, Counter[str]] = {}
    for row in rows:
        first = anchored.anchors[row.key].block_ids[:1]
        if first and first[0] in before:
            kind = counted.setdefault("node" if row.node else "statement", Counter())
            kind[anchored.stage_of[row.key]] += 1
    return {kind: dict(stages) for kind, stages in counted.items()}


async def _read(sparql: MemSparql, plan: MemPlan) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The plan's closure and references; PermanentError where the graph holds the plan no more."""
    counted = await sparql.select(plan_count(sparql, plan.graph, plan.iri))
    if not counted or counted[0].get("count") in (None, "0"):
        raise PermanentError("mem_unknown_plan", "the endpoint holds the document's plan no more")
    closure = await sparql.select_pages(
        partial(closure_page, sparql, plan.graph, plan.iri), closure_count(sparql, plan.graph, plan.iri)
    )
    references = await sparql.select_pages(
        partial(reference_page, sparql, plan.graph, plan.iri), reference_count(sparql, plan.graph, plan.iri)
    )
    return closure, references
