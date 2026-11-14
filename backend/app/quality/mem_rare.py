"""The MEM import's not-found wordings held against the fuzzy stage's limit on places (plan H-3, A10; the
open point of M2-4): how many it may have hidden - a wording's rarest word (of three letters and more)
standing in the searched text more often than the stage tries places (``FUZZY_PLACES``), so that its place
may lie past them (``rare_word_hidden``).

Only wordings the fuzzy stage looked for are held against it:

- one longer than the stage takes (``MAX_FUZZY``) was never looked for by it; such wordings are counted
  apart (``too_long_for_fuzzy``);
- a row past the search's time (``import.unsearched``) was not looked for at all: the rows the search left
  are the last ones in its order (app/sources/mem/anchoring.py stops for good once the time is past), read
  from the plan's kept answers in the order the import searched them (``rows_in_order``). Neither count
  holds one of them: the two and ``unsearched`` are disjoint. Where the search left rows and they cannot
  be told by their MEM IRI (one of no storable IRI, every row left, or the kept answers or the plan gone),
  both counts are null.

The count is an estimate (``rare_word_hidden_by: whole_text_estimate``), mostly from above: the words are
counted in the whole searched text, while the search looks in windows - after the place of the row found
before, then before it (app/pipeline/anchor_search.py) -, each of which may hold a word fewer times; and in
an edge case a window's rarest word is another. The searched text is built as the import built it, by the
document's cues as they stand now; the rows are the import's rows still as imported now (a statement
rejected since is out), while ``hits`` is the run's result as the import left it."""

import asyncio
import re
from collections.abc import Collection, Sequence

import psycopg

from app.db.conversions import all_blocks
from app.db.documents import Document
from app.db.mem_measures import not_found_wordings
from app.pipeline.anchor_check import MAX_FUZZY
from app.pipeline.anchor_fuzzy import FUZZY_PLACES, FUZZY_QUOTE
from app.pipeline.anchor_match import needle
from app.pipeline.anchor_search import search_text
from app.pipeline.ground import contents_of, ground_of
from app.sources.mem.drafts import Row
from app.sources.mem.tree import storable_iri

ESTIMATE = "whole_text_estimate"
_WORD = re.compile(r"\w{3,}")  # a word as the fuzzy stage picks its places by (app/pipeline/anchor_fuzzy.py)


def rarest_too_often(wording: str, text: str) -> bool:
    """Whether the rarest of the words the fuzzy stage looks for the wording's places by stands in ``text``
    more often than it tries places; a wording none of whose words stand there is not."""
    counts = [text.count(word) for word in set(_WORD.findall(needle(wording)[:FUZZY_QUOTE]))]
    held = [count for count in counts if count]
    return bool(held) and min(held) > FUZZY_PLACES


def rows_left(rows: Sequence[Row] | None, unsearched: int) -> frozenset[str] | None:
    """The MEM IRIs of the rows past the search's time - the last ``unsearched`` of ``rows``, in the
    search's order -; None where one of them has none the rows keep (or the rows are not known)."""
    if not unsearched:
        return frozenset()
    if rows is None:
        return None
    left = [row.key for row in rows[-unsearched:]]
    if unsearched < len(rows) and all(storable_iri(key) for key in left):
        return frozenset(left)
    return None


async def rare_words(
    connection: psycopg.AsyncConnection, document: Document, left: Collection[str] | None
) -> dict[str, object]:
    """``rare_word_hidden``, how it is reckoned, and ``too_long_for_fuzzy``, ``left`` the rows past the
    search's time (``rows_left``)."""
    made: dict[str, object] = {"rare_word_hidden": None, "rare_word_hidden_by": ESTIMATE}
    if left is None:
        return made | {"too_long_for_fuzzy": None}
    wordings = [w for iri, w in await not_found_wordings(connection, document.id) if iri not in left]
    blocks = await all_blocks(connection, document.conversion_id)
    ground = await ground_of(connection, document)
    contents = await asyncio.to_thread(contents_of, ground, blocks, document.document_type_iri)
    text = search_text(blocks, contents.positions).text
    fuzzy = [wording for wording in wordings if len(needle(wording)) <= MAX_FUZZY]
    made["rare_word_hidden"] = sum(rarest_too_often(wording, text) for wording in fuzzy)
    return made | {"too_long_for_fuzzy": len(wordings) - len(fuzzy)}
