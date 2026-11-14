"""The reckoning core of a run's cost (plan M1 11.2): a request as the meter reckons it before it is
sent, the requests X3 and X4 still owe a document once X2 is done - exactly those the stages would ask,
chosen as they choose them -, and what they are expected to charge, in tokens weighed as the quota
counts them (app/llm/metering.py, ``Weights``). The estimate command (app/pipeline/estimate.py) prints
it, the watch after X2 (app/pipeline/watch.py) ends a run by it; neither is loaded here.

The expectation is not the most a run may cost (``Weights.held``, every answer at its cap): each
request is expected to read its shared part - the prefix before the cache breakpoint - from the cache,
but the first ``uncached_first`` of them, which begin before the cache holds it, and to be answered at
EXPECTED_ANSWER_TOKENS, about what the acceptance's requests answered (some 1,050 each), at most its
cap. A run may charge more: an answer out of form asks again, a cache the provider dropped is read
whole.
"""

import asyncio
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
from app.llm.metering import Spent, Weights, estimate_input
from app.llm.schema import SCHEMA_DIR, load_schema
from app.llm.settings import LLMSettings
from app.pipeline.ground import Ground
from app.pipeline.prompts import x3, x4
from app.pipeline.unit_question import prefix_at, prefix_plan
from app.pipeline.x2_segments import WorkPackage
from app.pipeline.x3_stage import frame_question
from app.pipeline.x4_question import unit_questions
from app.pipeline.x4_statements import units_asked

EXPECTED_ANSWER_TOKENS = 1_100


@dataclass(frozen=True)
class Request:
    purpose: str  # as the ledger books it: "x1.profile", "x1.outline", "x3.frame", "x4.unit"
    input_tokens: int  # as the meter reckons it, its margin beside
    shared_tokens: int  # of it the text before the cache breakpoint, counted plainly; 0 without one
    output_tokens: int  # the cap the answer reserves


def stage_agent(model: Model, ontology_dir: Path, prompts: ModuleType) -> StageAgent:
    """A stage's agent as the stage builds it (app/pipeline/asking.py): what each request sends beside
    its prompt; ``prompts`` the stage's module of them (app/pipeline/prompts)."""
    schema = load_schema(ontology_dir / SCHEMA_DIR, prompts.SCHEMA)
    return build_agent(model, schema=schema, name=prompts.SCHEMA_NAME, instructions=prompts.INSTRUCTIONS)


def request_of(purpose: str, prompt: str | list[UserContent], stage: StageAgent) -> Request:
    """The first request of a stage's agent, as the meter reckons it (app/llm/calls.py, _attempt)."""
    request = ModelRequest(parts=[UserPromptPart(prompt)])
    reckoned = estimate_input([], request, instructions=stage.instructions, schema=stage.schema)
    shared = 0 if isinstance(prompt, str) else count_tokens(str(prompt[0]))
    return Request(purpose, reckoned, shared, stage.output_tokens)


def expected_charge(
    requests: Sequence[Request],
    weights: Weights,
    *,
    uncached_first: int,
    answer_tokens: int = EXPECTED_ANSWER_TOKENS,
) -> int:
    """What ``requests`` are expected to charge, weighed by ``weights``: each its input, its shared
    part read from the cache but for the first ``uncached_first``, and an answer of ``answer_tokens``,
    at most its cap - so never more than their reservations hold."""
    return sum(
        weights.charged(
            Spent(
                input_tokens=request.input_tokens,
                cached_input_tokens=0 if at < uncached_first else request.shared_tokens,
                output_tokens=min(answer_tokens, request.output_tokens),
            )
        )
        for at, request in enumerate(requests)
    )


async def statement_units(
    connection: psycopg.AsyncConnection, document: Document, model: Model
) -> list[WorkPackage]:
    """The units of X2's result a run of X4 asks under ``model``'s cap (``units_asked``)."""
    kept = await stage_result(connection, document.id, "X2")
    packages = [WorkPackage.from_result(item) for item in (kept or {}).get("packages", [])]
    units = [item for item in packages if item.job == "statements"]
    asked, _ = await units_asked(connection, document, units, output_cap(model))
    return asked


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
    would ask), counted as the stages send them, X3's first; and the number of those units. X4's
    prefix lacks the choice lists X3 writes while X3 is open. PermanentError (prefix_too_long) where
    a stage's question fits no window: the stage ends the job before it asks."""
    done = await done_stages(connection, document.id)
    units = await statement_units(connection, document, model)
    prompts: list[tuple[str, str | list[UserContent], ModuleType]] = []
    if "X3" not in done:
        question = await frame_question(connection, llm, document, blocks, printed, ground, model)
        prompts.append(("x3.frame", question.prompt, x3))
    if "X4" not in done:
        questions = await unit_questions(connection, llm, document, blocks, printed, ground, model)
        prompts += [("x4.unit", (await questions.question(unit)).prompt, x4) for unit in units]
    agents = {module: stage_agent(model, ontology_dir, module) for module in {item[2] for item in prompts}}
    requests = await asyncio.to_thread(
        lambda: [request_of(purpose, prompt, agents[module]) for purpose, prompt, module in prompts]
    )
    return requests, len(units)


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
    return count_tokens((await asyncio.to_thread(prefix_at, plan, 0)).text)
