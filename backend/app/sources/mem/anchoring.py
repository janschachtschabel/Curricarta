"""The anchors of an import's rows (plan M2, E3/E4; Teilplan M2-5, Nachtrag M2-4).

Each row's wording is looked for in the document's order (``drafts.rows_in_order``), after the place of the
last one found, one wording at a time beside the event loop (``asyncio.to_thread``) - so that a job asked to
stop stops between two. A wording found is anchored at its blocks and their pages; its match kind, quote and
span X5 reckons, as for every anchor. A wording not found is ``notFound`` with no block, on the page of the
row found before it, else the text's first - only estimated. The search has a time budget: past it, the
rows left are not looked for and are anchored as not found (``unsearched``), so that a plan of many long
wordings the document does not hold ends in time.
"""

import asyncio
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.domain.l1 import MATCH_NOT_FOUND, AnchorDraft
from app.pipeline.anchor_search import Found, SearchText, estimated_page, find
from app.sources.mem.drafts import Row


@dataclass(frozen=True)
class Anchored:
    anchors: dict[str, AnchorDraft]  # by the row's key
    stages: dict[str, Counter[str]] = field(default_factory=dict)  # by node and statement: stage, notFound …
    unsearched: int = 0  # rows past the search's time
    stage_of: dict[str, str] = field(default_factory=dict)  # by the row's key: stage, notFound, unsearched


async def anchor_rows(
    rows: Sequence[Row], searched: SearchText, budget_s: float, *, clock: Callable[[], float] = time.monotonic
) -> Anchored:
    """The anchor of each row, the search ending after ``budget_s`` seconds."""
    started = clock()
    page_of = dict(zip(searched.ids, searched.pages, strict=True))
    anchors: dict[str, AnchorDraft] = {}
    stages: dict[str, Counter[str]] = {}
    stage_of: dict[str, str] = {}
    before: Found | None = None
    unsearched = 0
    for row in rows:
        counted = stages.setdefault("node" if row.node else "statement", Counter())
        if clock() - started > budget_s:
            unsearched += 1
            counted["unsearched"] += 1
            stage_of[row.key] = "unsearched"
            anchors[row.key] = _not_found(searched, before)
            continue
        found = await asyncio.to_thread(find, row.wording, searched, before)
        if found is None:
            counted["notFound"] += 1
            stage_of[row.key] = "notFound"
            anchors[row.key] = _not_found(searched, before)
            continue
        counted[found.stage] += 1
        stage_of[row.key] = found.stage
        last = max(page_of[block] for block in found.block_ids)
        anchors[row.key] = AnchorDraft(
            found.block_ids, page_start=found.page, page_end=last if last > found.page else None
        )
        before = found
    return Anchored(anchors, stages, unsearched, stage_of)


def _not_found(searched: SearchText, before: Found | None) -> AnchorDraft:
    return AnchorDraft((), page_start=estimated_page(searched, before), match_kind=MATCH_NOT_FOUND)
