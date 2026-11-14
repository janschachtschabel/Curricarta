"""The kept answers a replay reads (app/pipeline/replay.py), and which of them is each unit's.

Each kept file is read as the one model answer it holds - one that is no such answer is ``unreadable`` -,
then taken by the stage's own agent: a stand-in model hands it the kept answer once, and where the agent
asks again (out of the schema's form, a cut or filtered answer) there is none (``out_of_form``). Nothing is
ever sent.

Which answer is a unit's, as the pipeline chose it: X4 reads an answer for the unit it ASKED and throws
away one naming another; the question is not kept, so for a unit an X4 run wrote (``extraction_unit
.run_id``) the replay takes the answers in form naming that unit in THAT run - a run asks a unit once and
an answer in form ends the call, so one of them is its own; more than one is ``ambiguous`` and not guessed.
A unit no X4 run wrote - not done, its run gone, or written anew by another stage since (X6: ``repaired``)
- takes the last answer in form naming it, over the runs in the order they began."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.core.storage import Storage
from app.db.units import UnitDone
from app.db.usage_measures import RunAnswers
from app.llm.calls import StageAgent
from app.llm.raw import kept_answers
from app.llm.settings import LLMSettings
from app.pipeline.prefix import as_written


class _AskedAgain(Exception):
    """The agent asked again: the kept answer did not take the form, and no other one comes."""


class KeptAnswers:
    """A stand-in model that hands the agent the kept answer it is given, once: nothing is ever sent."""

    def __init__(self, llm: LLMSettings) -> None:
        self.answer: ModelResponse | None = None
        self.model = FunctionModel(self._hand, settings={"max_tokens": llm.llm_max_output_tokens})

    def _hand(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if self.answer is None:
            raise _AskedAgain
        answer, self.answer = self.answer, None
        return answer

    async def output(self, stage: StageAgent, answer: ModelResponse) -> dict[str, Any] | None:
        """The kept answer as the stage's agent takes it, None where it took no form."""
        self.answer = answer
        try:
            return (await stage.agent.run("")).output
        except (_AskedAgain, UnexpectedModelBehavior):
            return None
        finally:
            self.answer = None


def parsed(data: bytes) -> ModelResponse | None:
    """The one model answer a kept file holds, None where it holds no such answer."""
    try:
        found = [m for m in ModelMessagesTypeAdapter.validate_json(data) if isinstance(m, ModelResponse)]
    except ValidationError:
        return None
    return found[0] if len(found) == 1 else None


@dataclass
class Gathered:
    runs: int = 0  # X4 runs read
    answers: int = 0  # kept files read
    gone: int = 0  # booked as answered, not in the store
    unreadable: int = 0  # in the store, no model answer
    beyond_ledger: int = 0  # kept beyond the answers the ledger booked: read all the same
    out_of_form: int = 0
    unknown_unit: int = 0  # naming no unit X2 cut
    # the answers in form, as written, in the order kept: (run, the unit named, the answer)
    in_form: list[tuple[UUID, str, dict[str, Any]]] = field(default_factory=list)


async def gather(
    storage: Storage,
    stage: StageAgent,
    hands: KeptAnswers,
    runs: Sequence[RunAnswers],
    units: Collection[str],
) -> Gathered:
    """Every kept answer of the X4 runs, read and taken as the module says."""
    found = Gathered(runs=len(runs))
    for run in runs:
        kept = await kept_answers(storage, run.run_id, "x4", run.answers)
        found.beyond_ledger += max(len(kept) - run.answers, 0)
        for data in kept:
            if data is None:
                found.gone += 1
                continue
            found.answers += 1
            answer = parsed(data)
            output = None if answer is None else await hands.output(stage, answer)
            if answer is None:
                found.unreadable += 1
            elif output is None:
                found.out_of_form += 1
            elif (unit := (written := as_written(output))["unitKey"].strip()) not in units:
                found.unknown_unit += 1
            else:
                found.in_form.append((run.run_id, unit, written))
    return found


@dataclass(frozen=True)
class Chosen:
    answers: dict[str, dict[str, Any]]  # each unit's own answer, by its key
    ambiguous: tuple[str, ...]  # units whose run kept more than one answer naming them
    repaired: tuple[str, ...]  # units another stage than X4 wrote anew since


def chosen(
    units: Sequence[str], done: Mapping[str, UnitDone], x4_runs: Collection[UUID], gathered: Gathered
) -> Chosen:
    """Each unit's answer, as the module says."""
    answers: dict[str, dict[str, Any]] = {}
    ambiguous: list[str] = []
    for key in units:
        written_by = done[key].run_id if key in done else None
        if written_by in x4_runs:
            own = [answer for run, unit, answer in gathered.in_form if run == written_by and unit == key]
            if len(own) == 1:
                answers[key] = own[0]
            elif own:
                ambiguous.append(key)
            continue
        last = [answer for _, unit, answer in gathered.in_form if unit == key]
        if last:
            answers[key] = last[-1]
    repaired = tuple(
        key
        for key in units
        if key in done and done[key].run_id is not None and done[key].run_id not in x4_runs
    )
    return Chosen(answers, tuple(ambiguous), repaired)
