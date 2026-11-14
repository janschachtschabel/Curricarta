"""The gold report's ``--replayed`` (plan H-3 §3.4, A8): what a replay of a document's kept answers
(app/pipeline/replay.py) would keep and lose of a statement sample's judgements, counted by
``app.quality.rates.replayed`` against the model's statements the document holds now. Every judged item
counts, also one whose row is gone since the draw: a judgement follows its wording at its first block,
which is what a replay reads again."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from uuid import UUID

import psycopg

from app.core.storage import Storage
from app.db.gold import Item, Judgement
from app.db.measures import model_statements
from app.llm.settings import LLMSettings
from app.pipeline.replay import replay_document
from app.quality.rates import Key, replayed

# The keys (wording hash, first block) of the statements a replay of the document reads now
Replay = Callable[[UUID], Awaitable[Sequence[Key]]]


async def replayed_counts(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    items: Sequence[Item],
    judgements: Mapping[int, Judgement],
    replay: Replay,
) -> dict[str, int]:
    """The judged items kept and gone by verdict, and the statements read now that nobody judged."""
    read_now = await replay(document_id)
    stored = [
        (item.text_hash, item.first_block)
        for item in await model_statements(connection, document_id)
        if item.text_hash is not None
    ]
    judged = [
        ((item.text_hash, item.first_block), verdict)
        for item in items
        if item.text_hash is not None
        and item.id in judgements
        and (verdict := judgements[item.id].verdict) is not None
    ]
    return replayed(judged, stored=stored, read_now=read_now)


def replay_of(
    connection: psycopg.AsyncConnection, storage: Storage, llm: LLMSettings, ontology_dir: Path
) -> Replay:
    """The replay the command runs: app.pipeline.replay's, over this connection, which it only reads."""

    async def replay(document_id: UUID) -> Sequence[Key]:
        return (await replay_document(connection, storage, llm, document_id, ontology_dir)).keys

    return replay
