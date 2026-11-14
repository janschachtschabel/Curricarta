"""The reckoning core of a run's cost (plan M1 11.2): a request as the meter reckons it before it is
sent, the requests X3 and X4 still owe a document once X2 is done - exactly those the stages would ask,
chosen as they choose them -, and what they are expected to charge, in tokens weighed as the quota
counts them (app/llm/metering.py, ``Weights``). The estimate command (app/pipeline/estimate.py) prints
it, the watch after X2 (app/pipeline/watch.py) ends a run by it; neither is loaded here.

The expectation is not the most a run may cost (``Weights.held``, every answer at its cap): each
request is expected to read its shared part - the prefix before the cache breakpoint, with the margin
the meter counts on it (``MARGIN``) - from the cache, but the first ``uncached_first`` of each prefix,
which begin before the cache holds it, and to be answered at EXPECTED_ANSWER_TOKENS, about what the
acceptance's requests answered (some 1,050 each), at most its cap. A prefix is a stage's and a window's
(``Request.window``): X3's is not X4's, and a document read in windows has one a window. A run may charge
more: an answer out of form asks again, a cache the provider dropped is read whole.
"""

import asyncio
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import psycopg
from pydantic_ai.messages import ModelRequest, UserContent, UserPromptPart
from pydantic_ai.models import Model

from app.conversion.base import Block
from app.db.documents import Document
from app.db.runs import done_stages, stage_result
from app.llm.budget import count_tokens
from app.llm.calls import StageAgent, build_agent, output_cap
from app.llm.metering import MARGIN, Spent, Weights, estimate_input
from app.llm.schema import SCHEMA_DIR, load_schema
from app.llm.settings import LLMSettings
from app.pipeline.ground import Ground
from app.pipeline.prefix import PrefixPlan
from app.pipeline.prompts import x3, x4
from app.pipeline.unit_question import prefix_at, prefix_plan
from app.pipeline.x2_segments import WorkPackage
from app.pipeline.x3_stage import FrameQuestion, frame_question
from app.pipeline.x4_question import UnitQuestions, unit_questions
from app.pipeline.x4_statements import units_asked

EXPECTED_ANSWER_TOKENS = 1_100


@dataclass(frozen=True)
class Request:
    purpose: str  # as the ledger books it: "x1.profile", "x1.outline", "x3.frame", "x4.unit"
    input_tokens: int  # as the meter reckons it, its margin beside
    shared_tokens: int  # of it the text before the cache breakpoint, counted plainly; 0 without one
    output_tokens: int  # the cap the answer reserves
    window: str = ""  # the window of its prefix (app/pipeline/prefix.py, Prefix.window); "" where one serves


def stage_agent(model: Model, ontology_dir: Path, prompts: ModuleType) -> StageAgent:
    """A stage's agent as the stage builds it (app/pipeline/asking.py): what each request sends beside
    its prompt; ``prompts`` the stage's module of them (app/pipeline/prompts)."""
    schema = load_schema(ontology_dir / SCHEMA_DIR, prompts.SCHEMA)
    return build_agent(model, schema=schema, name=prompts.SCHEMA_NAME, instructions=prompts.INSTRUCTIONS)


def request_of(
    purpose: str,
    prompt: str | list[UserContent],
    stage: StageAgent,
    *,
    window: str = "",
    shared_counts: dict[str, int] | None = None,
) -> Request:
    """The first request of a stage's agent, as the meter reckons it (app/llm/calls.py, _attempt);
    ``window`` that of its prefix. ``shared_counts`` keeps the count of each shared text, so that
    the requests behind one prefix count it once."""
    request = ModelRequest(parts=[UserPromptPart(prompt)])
    reckoned = estimate_input([], request, instructions=stage.instructions, schema=stage.schema)
    shared = 0
    if not isinstance(prompt, str):
        text = str(prompt[0])
        known = None if shared_counts is None else shared_counts.get(text)
        shared = count_tokens(text) if known is None else known
        if shared_counts is not None:
            shared_counts[text] = shared
    return Request(purpose, reckoned, shared, stage.output_tokens, window)


def expected_charge(
    requests: Sequence[Request],
    weights: Weights,
    *,
    uncached_first: int,
    answer_tokens: int = EXPECTED_ANSWER_TOKENS,
) -> int:
    """What ``requests`` are expected to charge, weighed by ``weights`` (``expected_charges``)."""
    return sum(
        expected_charges(requests, weights, uncached_first=uncached_first, answer_tokens=answer_tokens)
    )


def expected_charges(
    requests: Sequence[Request],
    weights: Weights,
    *,
    uncached_first: int,
    answer_tokens: int = EXPECTED_ANSWER_TOKENS,
) -> list[int]:
    """What each of ``requests`` is expected to charge, weighed by ``weights``: its input, its shared
    part with its margin read from the cache but for the first ``uncached_first`` of each prefix (a
    stage's, a window's), and an answer of ``answer_tokens``, at most its cap - so never more than its
    reservation holds."""
    asked: Counter[tuple[str, str]] = Counter()
    charges = []
    for request in requests:
        prefix = (request.purpose, request.window)
        cached = 0 if asked[prefix] < uncached_first else math.ceil(request.shared_tokens * MARGIN)
        asked[prefix] += 1
        spent = Spent(
            input_tokens=request.input_tokens,
            cached_input_tokens=min(request.input_tokens, cached),
            output_tokens=min(answer_tokens, request.output_tokens),
        )
        charges.append(weights.charged(spent))
    return charges


def room_for(
    requests: Sequence[Request],
    weights: Weights,
    *,
    at_once: int,
    units: int,
    answer_tokens: int = EXPECTED_ANSWER_TOKENS,
) -> int:
    """What the requests asked at once hold beyond what they are expected to charge: a request reserves
    its input and its whole cap at the output weight (``Weights.held``) and books about a tenth of it,
    and X4 lets no unit begin once one reservation is refused. So a run needs this room beside its
    expectation: ``min(at_once, units or 1)`` times the most any of ``requests`` holds beyond its
    expected charge (``expected_charges``, the first ``at_once`` of each prefix whole)."""
    charges = expected_charges(requests, weights, uncached_first=at_once, answer_tokens=answer_tokens)
    beyond = (
        weights.held(request.input_tokens, request.output_tokens) - charge
        for request, charge in zip(requests, charges, strict=True)
    )
    return min(at_once, units or 1) * max(beyond, default=0)


async def statement_units(
    connection: psycopg.AsyncConnection, document: Document, model: Model
) -> list[WorkPackage]:
    """The units of X2's result a run of X4 asks under ``model``'s cap (``units_asked``)."""
    kept = await stage_result(connection, document.id, "X2")
    packages = [WorkPackage.from_result(item) for item in (kept or {}).get("packages", [])]
    units = [item for item in packages if item.job == "statements"]
    asked, _ = await units_asked(connection, document, units, output_cap(model))
    return asked


@dataclass(frozen=True)
class Owing:
    """What X3 and X4 still owe a document, read from the store (``owed_questions``); its requests are
    counted by ``requests`` without it - CPU work, in threads, as X4 counts its units' prefixes."""

    frame: FrameQuestion | None  # X3's question, where X3 is open
    questions: UnitQuestions | None  # X4's, where X4 is open
    units: list[WorkPackage]  # those X4 would ask (``statement_units``)
    x3_plan: PrefixPlan  # X3's prefix, for ``prefix_tokens``

    async def requests(self, model: Model, ontology_dir: Path) -> list[Request]:
        """X3's request first, then each unit's, counted as the meter counts them, one thread a
        request so that a cancel ends the count between two; PermanentError (prefix_too_long) where a
        unit's question fits no window."""
        prompts: list[tuple[str, str | list[UserContent], ModuleType, str]] = []
        if self.frame is not None:
            prompts.append(("x3.frame", self.frame.prompt, x3, ""))
        if self.questions is not None:
            for unit in self.units:
                asked = await self.questions.question(unit)
                prompts.append(("x4.unit", asked.prompt, x4, asked.window))
        agents = {
            module: stage_agent(model, ontology_dir, module) for module in {item[2] for item in prompts}
        }
        shared: dict[str, int] = {}  # by text, filled one thread after the other
        return [
            await asyncio.to_thread(
                request_of, purpose, prompt, agents[module], window=window, shared_counts=shared
            )
            for purpose, prompt, module, window in prompts
        ]

    async def prefix_tokens(self) -> int:
        """X3's prefix - the document as every request of the run sends it first -, counted plainly."""
        return await asyncio.to_thread(lambda: count_tokens(prefix_at(self.x3_plan, 0).text))


async def owed_questions(
    connection: psycopg.AsyncConnection,
    llm: LLMSettings,
    document: Document,
    blocks: Sequence[Block],
    printed: Sequence[str | None],
    ground: Ground,
    model: Model,
) -> Owing:
    """What ``document`` - X2 done on it - still owes X3 (where open) and X4 (each unit it would ask),
    read as the stages read it. X4's prefix lacks the choice lists X3 writes while X3 is open.
    PermanentError (prefix_too_long) where X3's question fits no window."""
    done = await done_stages(connection, document.id)
    units = await statement_units(connection, document, model)
    frame = None
    if "X3" not in done:
        frame = await frame_question(connection, llm, document, blocks, printed, ground, model)
    questions = None
    if "X4" not in done:
        questions = await unit_questions(connection, llm, document, blocks, printed, ground, model)
    plan = await prefix_plan(connection, llm, document.id, blocks, printed, lists="")
    return Owing(frame, questions, units, plan)


async def owed_requests(
    connection: psycopg.AsyncConnection,
    llm: LLMSettings,
    document: Document,
    blocks: Sequence[Block],
    printed: Sequence[str | None],
    ground: Ground,
    model: Model,
    ontology_dir: Path,
) -> tuple[list[Request], int]:
    """The requests ``document`` - X2 done on it - still owes X3 (where open) and X4 (each unit it
    would ask), counted as the stages send them, X3's first; and the number of those units.
    PermanentError (prefix_too_long) where a stage's question fits no window: the stage ends the job
    before it asks."""
    owing = await owed_questions(connection, llm, document, blocks, printed, ground, model)
    return await owing.requests(model, ontology_dir), len(owing.units)


async def prefix_tokens(
    connection: psycopg.AsyncConnection,
    llm: LLMSettings,
    document: Document,
    blocks: Sequence[Block],
    printed: Sequence[str | None],
) -> int:
    """X3's prefix - the document as every request of the run sends it first -, counted plainly;
    PermanentError (prefix_too_long) where no window of it fits."""
    plan = await prefix_plan(connection, llm, document.id, blocks, printed, lists="")
    return await asyncio.to_thread(lambda: count_tokens(prefix_at(plan, 0).text))
