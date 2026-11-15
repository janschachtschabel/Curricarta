"""The gold report's ``--replayed`` (plan H-3 §3.4, A8): what a replay of a document's kept answers
(app/pipeline/replay.py) would keep and lose of a statement sample's judgements, counted by
``app.quality.rates.replayed``, and what the replay rests on.

Every judged item counts (``judged``: ``kept_*`` and ``gone_*`` add up to it), also one whose row changed or
went since the draw: a judgement follows its wording at its first block, which is what a replay reads
again. A statement read now is new where neither the model's statements the document holds nor the sample's
items hold its key that often - a drawn item an editor reworded since is no new statement.

``gone_*`` means "today's reader no longer reads it" only where the replay read every answer: answers gone
from the store, unreadable or out of form, units missing or ambiguous, units X6 wrote anew since (it reads
X4's answers alone) all raise it too, and the vocabularies' release may have moved. The block tells those
counts (``replay``); the measure of a change to the reader is the DIFFERENCE between a ``--replayed`` before
and one after it, never its absolute numbers."""

from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from app.core.storage import Storage
from app.db.gold import Item, Judgement
from app.db.measures import model_statements
from app.llm.settings import LLMSettings
from app.pipeline.replay import Replayed, replay_document
from app.quality.rates import Key, replayed

Replay = Callable[[UUID], Awaitable[Replayed]]  # the replay of a document by its id
RESTS_ON = (
    "runs", "answers", "gone", "swept", "unreadable", "beyond_ledger", "out_of_form", "missing", "ambiguous",
    "lexicon_release_then", "lexicon_release_now",
)  # fmt: skip


async def replayed_counts(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    items: Sequence[Item],
    judgements: Mapping[int, Judgement],
    replay: Replay,
) -> dict[str, Any]:
    """The judged items kept and gone by verdict, the statements read now that nobody judged, and what the
    replay rests on."""
    found = await replay(document_id)
    stored = Counter(
        (item.text_hash, item.first_block)
        for item in await model_statements(connection, document_id)
        if item.text_hash is not None
    )
    drawn = Counter((item.text_hash, item.first_block) for item in items if item.text_hash is not None)
    judged: list[tuple[Key, str]] = [
        ((item.text_hash, item.first_block), verdict)
        for item in items
        if item.text_hash is not None
        and item.id in judgements
        and (verdict := judgements[item.id].verdict) is not None
    ]
    counts = replayed(judged, stored=list((stored | drawn).elements()), read_now=found.keys)
    rests_on = {name: getattr(found, name) for name in RESTS_ON} | {"repaired": len(found.repaired_units)}
    return {"judged": len(judged)} | counts | {"replay": rests_on}


def replay_of(
    connection: psycopg.AsyncConnection, storage: Storage, llm: LLMSettings, ontology_dir: Path
) -> Replay:
    """The replay the command runs: app.pipeline.replay's, over this connection, which it only reads."""

    async def replay(document_id: UUID) -> Replayed:
        return await replay_document(connection, storage, llm, document_id, ontology_dir)

    return replay
