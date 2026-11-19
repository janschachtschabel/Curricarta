"""The anchors of an import's rows (plan M2, E3/E4; Teilplan M2-5, Nachtrag M2-4).

Each row's wording is looked for in the document's order (``drafts.rows_in_order``), after the place of the
last one found, one wording at a time beside the event loop (``asyncio.to_thread``) - so that a job asked to
stop stops between two; a statement's without the lead-in MEM gives each (``looked_for``). A wording found
is anchored at its blocks and their pages; its match kind, quote and span X5 reckons, as for every anchor -
a statement's with the wordings ``looked_for`` gives, in the same turn (app/pipeline/x5_stage.py).
A wording not found is ``notFound`` with no block, on the page of the row found before it, else the text's
first - only estimated. The search has a time budget: past it, the rows left are not looked for and are
anchored as not found (``unsearched``), so that a plan of many long wordings the document does not hold
ends in time.
"""

import asyncio
import re
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.domain.l1 import MATCH_NOT_FOUND, AnchorDraft
from app.pipeline.anchor_search import Found, SearchText, estimated_page, find
from app.sources.mem.drafts import Row

# The lead-in MEM words every statement after, as MEM writes it; "SuS" stands in no document.
_LEAD_IN = re.compile(r"\s*(?:Die SuS|Die Schülerinnen und Schüler|Schülerinnen und Schüler)\s+")
# What a wording must keep after it to be looked for so: two words of three letters and more, the words
# the fuzzy stage finds its places by - one ("lesen.") stands in many sentences.
_WORD = re.compile(r"\w{3,}")
_LEAST_WORDS = 2


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
        found = await asyncio.to_thread(_find, row, searched, before)
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


def looked_for(wording: str, *, statement: bool) -> tuple[str, ...]:
    """What the search looks for of a row's wording, in turn until one is found: a statement's without the
    lead-in MEM puts before each ("Die SuS wenden ... an") where the document has one before its list, or
    none, and then whole - a document that words the statement after the same lead-in shares it, and a rest
    alone may be too little alike for the fuzzy stage; whole alone where too little is left to be found in
    one place, and a node's title. The row's wording, kept and exported, stays MEM's. X5 checks an imported
    statement's anchor with the same wordings in the same turn, so its match kind follows the search."""
    lead_in = _LEAD_IN.match(wording) if statement else None
    if lead_in is None:
        return (wording,)
    rest = wording[lead_in.end() :]
    return (rest, wording) if len(_WORD.findall(rest)) >= _LEAST_WORDS else (wording,)


def _find(row: Row, searched: SearchText, before: Found | None) -> Found | None:
    """Where the row's wording stands: the first of ``looked_for`` found."""
    for wording in looked_for(row.wording, statement=not row.node):
        found = find(wording, searched, before)
        if found is not None:
            return found
    return None


def _not_found(searched: SearchText, before: Found | None) -> AnchorDraft:
    return AnchorDraft((), page_start=estimated_page(searched, before), match_kind=MATCH_NOT_FOUND)
