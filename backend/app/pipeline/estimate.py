"""What an extraction run will ask of a document, counted before it asks (plan M1 11.2; the risk
"Kosten echter Läufe": a reckoning before every run): each request the stages still owe the
document, its input as the meter reckons it before sending (app/llm/metering.py), the share of it
before a cache breakpoint - the prefix the stage's requests send alike, which the provider reads
from its cache after the first - and the cap its answer reserves. Nothing is asked, nothing
written; the prices are the provider's, the app keeps none.

Before X1, the profile's question is counted as X1 asks it; the outline's are the questions of the
skeleton by the type the editors set - by none where they set none: X1 reads the headings by the
type it found, which may leave more of them to ask or fewer -, without the specifications X1 finds,
which its questions name. The units are not known before X2 - once X1 alone is done, they are
counted (X2 cuts them without the model) -; before X1 they are guessed (``guessed_units``): the
skeleton X1 reads cut as X2 cuts a tree, each heading a node of its type's depth - X1 may make
another tree of it, and give a heading a function that skips it: of the acceptance documents' guesses
X2 cut 0.5 to 1.0 (plan M1, Nachtrag 11b-4). The prefix of X3 is counted
(without the profile and the tree).
Once X2 is done, X3's question and every open unit's of X4 are counted as the stages ask them - a
unit held back after its answer was cut at the cap is not asked, nor counted; X4's
prefix without the choice lists X3 writes, while X3 is open, so lower than X4 will send. A stage the
reckoning cannot count is named with why (``unreckoned``): ``before_x2``; ``prefix_too_long`` where
no window fits, ``document_has_tree`` where a tree set up by hand stands - the stage ends the job
before it asks. An answer out of form asks again: a request beside these, and the job's attempts
each ask anew. A document imported from MEM-Schule owes its import's stages (IM, X5), which ask the
model nothing (app/sources/mem/import_job.py).

    docker compose -f deploy/docker-compose.yml exec -T worker python -m app.pipeline.estimate <document>

The requests are reckoned for the model the settings name, as the worker builds it - its cap, whether
it takes a cache breakpoint, the weights its tokens are charged by (``charged_at_most``: what the
budget must hold, every answer at its cap; ``charged_expected``: what the run is expected to charge,
app/pipeline/reckoned.py) -, without its key: it is never asked. JSON on stdout;
exit code 1 for a document that is not there, 2 for a call amiss.
"""

import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from pydantic import SecretStr
from pydantic_ai.messages import UserContent
from pydantic_ai.models import Model

from app.conversion.base import Block
from app.core.ids import new_id
from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db.conversions import all_blocks, printed_pages
from app.db.documents import Document, document_for_job
from app.db.pool import CONNECTION_OPTIONS
from app.db.profile import x1_state
from app.db.runs import done_stages
from app.domain.lexicon import active_cues
from app.jobs.outcome import PermanentError
from app.llm.client import build_model, cost_weights
from app.llm.metering import Weights
from app.llm.settings import LLMSettings
from app.pipeline.ground import Ground, ground_of
from app.pipeline.prompts import x1_outline, x1_profile
from app.pipeline.reckoned import (
    Request,
    expected_charge,
    owed_requests,
    prefix_tokens,
    request_of,
    room_for,
    stage_agent,
    statement_units,
)
from app.pipeline.run import STAGES
from app.pipeline.side_by_side import at_once
from app.pipeline.skeleton import Skeleton, build_skeleton
from app.pipeline.x1_question import outline_questions, profile_question
from app.pipeline.x2_segments import SegmentNode, depth_of, segments, work_packages
from app.sources.mem.import_kind import STAGES as IMPORT_STAGES
from app.vocab.lookup import concept_texts

log = logging.getLogger("app.pipeline.estimate")  # also when run as __main__
_NEVER_SENT = "reckoning-only"


@dataclass(frozen=True)
class Reckoning:
    owed: tuple[str, ...]  # the stages not done on the document
    units: int | None  # X4's units a run would ask - open, none held back by a cut; None before X1
    guessed_units: int | None  # before X1, X4's units as the skeleton would be cut; else None
    prefix_tokens: int | None  # X3's prefix, counted plainly; None where no window of it fits yet
    requests: tuple[Request, ...]
    unreckoned: dict[str, str]  # the stages owed but not counted, each with why ("X3": "before_x2")


async def reckon(
    connection: psycopg.AsyncConnection,
    llm: LLMSettings,
    document: Document,
    model: Model,
    ontology_dir: Path,
) -> Reckoning:
    """The requests the stages still owe ``document``, counted as the module says."""
    done = await done_stages(connection, document.id)
    if document.mem_iri is not None:
        imported = tuple(stage for stage in IMPORT_STAGES if stage not in done)
        return Reckoning(imported, None, None, None, (), {})
    owed = tuple(stage for stage in STAGES if stage not in done)
    blocks = await all_blocks(connection, document.conversion_id)
    printed = await printed_pages(connection, document.conversion_id)
    ground = await ground_of(connection, document)
    prompts: list[tuple[str, str | list[UserContent]]] = []
    unreckoned: dict[str, str] = {}
    guessed: int | None = None
    if "X1" in owed:
        if await x1_state(connection, document.id) == "tree":  # X1 ends the job before it asks
            unreckoned["X1"] = "document_has_tree"
        else:
            asked_x1, skeleton = await _x1(connection, document, blocks, printed, ground)
            prompts += asked_x1
            guessed = await _guessed_units(connection, blocks, skeleton)
    units: int | None = None
    owing: list[Request] = []
    if "X2" in done:
        try:
            owing, units = await owed_requests(
                connection, llm, document, blocks, printed, ground, model, ontology_dir
            )
        except PermanentError as stopped:  # prefix_too_long: the stage ends the job before it asks
            units = len(await statement_units(connection, document, model))
            unreckoned |= {stage: stopped.code for stage in ("X3", "X4") if stage in owed}
    else:
        if "X1" in done:  # X2 cuts the units with the next job, without the model
            found = await work_packages(connection, document.id, blocks)
            units = sum(item.job == "statements" for item in found)
        unreckoned |= {stage: "before_x2" for stage in ("X3", "X4") if stage in owed}
    try:
        prefix: int | None = await prefix_tokens(connection, llm, document, blocks, printed)
    except PermanentError:  # prefix_too_long: before X1 the document has no sections to cut windows by
        prefix = None
    stages = {"x1.profile": stage_agent(model, ontology_dir, x1_profile)}
    stages["x1.outline"] = stage_agent(model, ontology_dir, x1_outline)
    counted = await asyncio.to_thread(
        lambda: tuple(request_of(purpose, prompt, stages[purpose]) for purpose, prompt in prompts)
    )
    return Reckoning(owed, units, guessed, prefix, (*counted, *owing), unreckoned)


async def _x1(
    connection: psycopg.AsyncConnection,
    document: Document,
    blocks: Sequence[Block],
    printed: Sequence[str | None],
    ground: Ground,
) -> tuple[list[tuple[str, str | list[UserContent]]], Skeleton]:
    # as X1 asks them (app/pipeline/x1_stage.py), the outline by the editors' type where they set one;
    # the skeleton it reads beside them
    found = active_cues(ground.cues, ground.regions, None, None, wider_regions=ground.wider)
    skeleton = await asyncio.to_thread(build_skeleton, blocks, found, ground.node_types)
    profile = await profile_question(connection, document, blocks, printed, skeleton.contents, found)
    if document.document_type_iri is not None:
        typed = active_cues(
            ground.cues, ground.regions, document.document_type_iri, None, wider_regions=ground.wider
        )
        skeleton = await asyncio.to_thread(build_skeleton, blocks, typed, ground.node_types)
    outline = await outline_questions(connection, document, skeleton, blocks, [])
    asked: list[tuple[str, str | list[UserContent]]] = [
        ("x1.profile", profile.prompt),
        *(("x1.outline", prompt) for prompt in outline.prompts),
    ]
    return asked, skeleton


async def _guessed_units(
    connection: psycopg.AsyncConnection, blocks: Sequence[Block], skeleton: Skeleton
) -> int:
    """X4's units of the skeleton cut as X2 cuts a tree: each heading a node, of its type's depth
    (X1 has given none a function yet)."""
    types = sorted({heading.node_type for heading in skeleton.headings if heading.node_type})
    texts = await concept_texts(connection, types)
    ids = {heading.key: new_id() for heading in skeleton.headings}
    nodes = [
        SegmentNode(
            ids[heading.key],
            None if heading.parent is None else ids[heading.parent],
            heading.position,
            depth_of(texts[heading.node_type].depth if heading.node_type in texts else None, ""),
            heading.title,
        )
        for heading in skeleton.headings
    ]
    return sum(package.job == "statements" for package in segments(blocks, nodes))


def summary(
    document_id: UUID, reckoning: Reckoning, weights: Weights, *, uncached_first: int
) -> dict[str, Any]:
    """The reckoning as the command prints it: the requests summed by purpose and over all, the stages
    left unreckoned; ``reserved`` is what the meter reserves for these requests, every answer at its
    cap, ``charged_at_most`` what the budget must hold for them, weighed by ``weights`` - for the run,
    only where the reckoning is exact (the module says where it is not) and nothing is unreckoned;
    ``charged_expected`` what they are expected to charge, the first ``uncached_first`` of each prefix whole
    (app/pipeline/reckoned.py, expected_charge), ``room`` what the ``uncached_first`` asked at once hold
    beyond it (room_for) - both None while X3 or X4 is unreckoned: the watch after X2 lets a run pass
    where their sum is left."""
    unreckoned = bool({"X3", "X4"} & set(reckoning.unreckoned))
    requests, units = reckoning.requests, reckoning.units or 0
    by_purpose: dict[str, dict[str, int]] = {}
    for request in reckoning.requests:
        sums = by_purpose.setdefault(
            request.purpose, {"requests": 0, "input_tokens": 0, "shared_tokens": 0, "output_tokens": 0}
        )
        sums["requests"] += 1
        for name in ("input_tokens", "shared_tokens", "output_tokens"):
            sums[name] += getattr(request, name)
    total = {
        name: sum(sums[name] for sums in by_purpose.values())
        for name in ("requests", "input_tokens", "shared_tokens", "output_tokens")
    }
    return {
        "document_id": str(document_id),
        "owed": list(reckoning.owed),
        "units": reckoning.units,
        "guessed_units": reckoning.guessed_units,
        "prefix_tokens": reckoning.prefix_tokens,
        "unreckoned": reckoning.unreckoned,
        "by_purpose": by_purpose,
        "total": total,
        "reserved": total["input_tokens"] + total["output_tokens"],
        "weights": {"cached_input": str(weights.cached_input), "output": str(weights.output)},
        "charged_at_most": sum(
            weights.held(request.input_tokens, request.output_tokens) for request in reckoning.requests
        ),
        "charged_expected": None
        if unreckoned
        else expected_charge(requests, weights, uncached_first=uncached_first),
        "room": None if unreckoned else room_for(requests, weights, at_once=uncached_first, units=units),
        "requests": [asdict(request) for request in reckoning.requests],
    }


async def _reckoned(settings: Settings, llm: LLMSettings, document_id: UUID) -> dict[str, Any] | None:
    # the worker's model, built as the worker builds it; a key it never sends stands in for its own
    model = build_model(llm.model_copy(update={"openai_api_key": SecretStr(_NEVER_SENT)}))
    try:
        url = settings.database_url.get_secret_value()
        async with await psycopg.AsyncConnection.connect(url, **CONNECTION_OPTIONS) as connection:
            document = await document_for_job(connection, document_id)
            if document is None:
                return None
            reckoning = await reckon(connection, llm, document, model, settings.ontology_dir)
            # the units that begin beside each other before the cache holds their prefix
            first = at_once(settings)
            return summary(document_id, reckoning, cost_weights(llm), uncached_first=first)
    finally:
        await model.client.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        document_id = UUID(args[0]) if len(args) == 1 else None
    except ValueError:
        document_id = None
    if document_id is None:
        log.error("usage: python -m app.pipeline.estimate <document id>")
        return 2
    made = asyncio.run(
        _reckoned(settings, LLMSettings(), document_id), loop_factory=asyncio.SelectorEventLoop
    )
    if made is None:
        log.error("no document %s", document_id)
        return 1
    sys.stdout.buffer.write((json.dumps(made, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
