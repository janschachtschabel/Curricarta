"""A MEM wording looked for in the whole document, in the plan's order (plan M2, E3/E4), after the old app's
``resolve_anchor_after``.

The import knows a part's wording, not where it stands. The text is the conversion's blocks in reading
order, one line end between two, without page headers and footers and without the blocks of the
contents: a wording there would anchor in the wrong place. A plan words parts alike at two places (a
Leistungskurs repeats the Grundkurs), so the search starts at the block where the part before it was
found: from there on, then before it - the window before reaching past that block's start by twice the
wording's length, to the next line end, for a wording that begins just before it. Before it, the first
place from the document's top is taken, as the old app took it. A word-for-word match anywhere still
beats a fuzzy one after the part before: stage by stage as anchor_check has them (exact and whitespace,
elided, normalized and fuzzy), each in both windows, before the next stage - and within the last stage a
normalized place before beats a fuzzy passage after. A place found is one of this text: the caller starts
each document's search with no part before.

A wording not found gets the page of the part found before it, else the first page of the text - only
estimated (E3). CPU work: a caller in the event loop runs this by ``asyncio.to_thread``.
"""

import bisect
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from app.conversion.base import Block
from app.pipeline.anchor_check import MAX_FUZZY
from app.pipeline.anchor_fuzzy import fuzzy
from app.pipeline.anchor_match import Hit, Kind, elided, needle, verbatim
from app.pipeline.toc import OUTSIDE

Stage = Callable[[str, str], Hit | None]


@dataclass(frozen=True)
class SearchText:
    """The text a wording is looked for in, and where each of its blocks begins in it."""

    text: str
    starts: tuple[int, ...]
    ids: tuple[str, ...]
    pages: tuple[int, ...]


@dataclass(frozen=True)
class Found:
    """Where a wording stands: its blocks, the page of the first, the stage that found it, its span in the
    text searched."""

    block_ids: tuple[str, ...]
    page: int
    stage: Kind
    start: int
    end: int


def search_text(blocks: Sequence[Block], contents: Collection[int]) -> SearchText:
    """The text of ``blocks`` (a conversion's, in order) without page headers and footers and without
    those at the positions ``contents`` names."""
    parts: list[str] = []
    starts: list[int] = []
    ids: list[str] = []
    pages: list[int] = []
    at = 0
    for position, block in enumerate(blocks):
        if block.kind in OUTSIDE or position in contents:
            continue
        starts.append(at)
        ids.append(block.id)
        pages.append(block.page)
        parts.append(block.text)
        at += len(block.text) + 1
    return SearchText("\n".join(parts), tuple(starts), tuple(ids), tuple(pages))


def find(wording: str, searched: SearchText, after: Found | None) -> Found | None:
    """Where ``wording`` stands, the part before it found at ``after`` - in this text: ValueError for a place
    past its end; None where no stage finds it."""
    target = needle(wording)
    text = searched.text
    if after is not None and after.end > len(text):
        raise ValueError("a place found in another text")
    if not target or not text:
        return None
    windows = [(0, text)]
    if after is not None:
        line = searched.starts[_block_at(searched, after.start)]
        if line:
            # the window before ends at a line end, which ends a word for every stage: cut inside one, a
            # match at its end would pass for whole ("Lernfeld 1" of "Lernfeld 12")
            cut = text.find("\n", line + 2 * len(target))
            windows = [(line, text[line:]), (0, text if cut == -1 else text[:cut])]
    stages: list[Stage] = [verbatim, elided]
    if len(target) <= MAX_FUZZY:
        stages.append(fuzzy)
    for stage in stages:
        # the windows in turn; a fuzzy passage after waits for a normalized place before, which the same
        # stage finds (a wording a line-end hyphen parts in the document)
        kept: tuple[int, Hit] | None = None
        for offset, window in windows:
            hit = stage(target, window)
            if hit is not None and hit.kind != "fuzzy":
                return _found(searched, hit, offset)
            if hit is not None and kept is None:
                kept = (offset, hit)
        if kept is not None:
            return _found(searched, kept[1], kept[0])
    return None


def estimated_page(searched: SearchText, before: Found | None) -> int:
    """The page a wording not found is put on: that of the part found before it, else the text's first."""
    if before is not None:
        return before.page
    return searched.pages[0] if searched.pages else 1


def _found(searched: SearchText, hit: Hit, offset: int) -> Found:
    start, end = hit.start + offset, hit.end + offset
    first, last = _block_at(searched, start), _block_at(searched, max(start, end - 1))
    return Found(searched.ids[first : last + 1], searched.pages[first], hit.kind, start, end)


def _block_at(searched: SearchText, offset: int) -> int:
    """The index of the block the text's ``offset`` falls in (the line end after a block counts to it)."""
    return max(bisect.bisect_right(searched.starts, offset) - 1, 0)
