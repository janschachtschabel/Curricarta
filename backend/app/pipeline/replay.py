"""``python -m app.pipeline.replay <document> [--stage x4]``: the answers the X4 runs of a document kept
(``runs/<run>/x4/<n>.json``, as many as the ledger booked answers for), read again by today's reader
without asking the model (plan H-3, A4) - so that a change to the reader is judged without paying for a
new run. Each answer goes through the stage's own agent - its schema's form checked (``schema_errors``),
its texts made storable -, a stand-in model handing it the kept answer and never asking a provider; then
``as_written`` and ``read_unit``, as X4 reads it (app/pipeline/asking.py, x4_statements.py). Of each unit
the last answer in form counts; one out of form, or for a unit X2 did not cut, is passed over.

Printed as one line of JSON, counts and codes alone: the answers read and gone, the units, the
statements read now against those the units wrote (``extraction_unit``), the findings of the reading
against those the runs wrote, by rule, the units whose count differs, the units X6 wrote anew since
(their statements are X6's, not X4's), and the lexicon's release then and now: the reader reads with X3's
choice lists and the lexicon as they stand, so a replay after a change of the vocabularies measures both.
The question's own findings (``x4.pattern_timeout``) and ``x4.unanswered`` are the run's, never the
reader's. Read only: nothing is written to the document, the store or a file. Exit code 1 for a document
that is not there or has no kept answer of X4, 2 for a call amiss."""

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from pydantic import ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.conversion.base import Block
from app.core.logging import configure_logging
from app.core.settings import Settings
from app.core.storage import Storage, open_storage
from app.db.conversions import all_blocks, printed_pages
from app.db.documents import Document, document_for_job
from app.db.findings import rules_of_runs
from app.db.gold_report import head_of
from app.db.pool import CONNECTION_OPTIONS
from app.db.runs import stage_result
from app.db.units import done_units
from app.db.usage_measures import answered_runs
from app.domain.wording import text_hash
from app.llm.calls import StageAgent, build_agent
from app.llm.raw import kept_answers
from app.llm.schema import SCHEMA_DIR, load_schema
from app.llm.settings import LLMSettings
from app.pipeline.ground import ground_of
from app.pipeline.prefix import as_written
from app.pipeline.prompts import x4
from app.pipeline.x2_segments import WorkPackage
from app.pipeline.x4_question import unit_questions
from app.pipeline.x4_read import read_unit

log = logging.getLogger("app.pipeline.replay")  # also when run as __main__

Key = tuple[str, str]  # a statement's wording hash and first block: what a gold judgement follows


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Replayed:
    answers: int  # kept answers read
    gone: int  # booked as answered, not in the store
    units: int  # X2's units of statements
    statements_now: int  # as today's reader reads the answers
    statements_stored: int  # as the units wrote them (extraction_unit)
    findings_now: dict[str, int]  # of the reading, by rule
    findings_stored: dict[str, int]  # the X4 runs wrote and are kept, by rule
    out_of_form: int  # answers that never took the schema's form, or no answer at all
    wrong_unit: int  # answers for a unit X2 did not cut
    missing: int  # units without an answer in form
    repaired: int  # units X6 wrote anew since: what they hold is X6's
    units_differing: tuple[str, ...]  # whose statements now and stored differ in number
    lexicon_release_then: int | None  # of the last X4 run done
    lexicon_release_now: int | None
    keys: tuple[Key, ...]  # each statement read now: its wording's hash and first block; never printed


class _AskedAgain(Exception):
    """The agent asked again: the kept answer did not take the form, and no other one comes."""


class _KeptAnswers:
    """A stand-in model that hands the agent the kept answer it is given, once: nothing is ever sent."""

    def __init__(self, llm: LLMSettings) -> None:
        self.answer: ModelResponse | None = None
        self.model = FunctionModel(self._hand, settings={"max_tokens": llm.llm_max_output_tokens})

    def _hand(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if self.answer is None:
            raise _AskedAgain
        answer, self.answer = self.answer, None
        return answer

    async def output(self, stage: StageAgent, data: bytes) -> dict[str, Any] | None:
        """The kept answer as the stage's agent takes it, None where it took no form."""
        try:
            [answer] = [
                m for m in ModelMessagesTypeAdapter.validate_json(data) if isinstance(m, ModelResponse)
            ]
        except (ValidationError, ValueError):
            return None
        self.answer = answer
        try:
            return (await stage.agent.run("")).output
        except (_AskedAgain, UnexpectedModelBehavior):
            return None
        finally:
            self.answer = None


async def replay_x4(
    connection: psycopg.AsyncConnection,
    storage: Storage,
    llm: LLMSettings,
    document: Document,
    blocks: Sequence[Block],
    printed: Sequence[str | None],
    ontology_dir: Path,
) -> Replayed:
    """The X4 answers of ``document`` (of these blocks, all of its conversion's, in order) read again, as
    the module says; Refused where no X4 run was booked an answer. Writes nothing."""
    runs = [run for run in await answered_runs(connection, document.id) if run.stage == "X4" and run.answers]
    if not runs:
        raise Refused("no_raw_answers", "no run of X4 kept an answer")
    kept = await stage_result(connection, document.id, "X2")
    packages = [WorkPackage.from_result(item) for item in (kept or {}).get("packages", [])]
    units = {item.key: item for item in packages if item.job == "statements"}
    ground = await ground_of(connection, document)
    hands = _KeptAnswers(llm)
    questions = await unit_questions(connection, llm, document, blocks, printed, ground, hands.model)
    schema = load_schema(ontology_dir / SCHEMA_DIR, x4.SCHEMA)
    stage = build_agent(hands.model, schema=schema, name=x4.SCHEMA_NAME, instructions=x4.INSTRUCTIONS)
    answers = gone = out_of_form = wrong_unit = 0
    latest: dict[str, dict[str, Any]] = {}  # each unit's last answer in form
    for run in runs:
        for data in await kept_answers(storage, run.run_id, "x4", run.answers):
            if data is None:
                gone += 1
                continue
            answers += 1
            output = await hands.output(stage, data)
            if output is None:
                out_of_form += 1
                continue
            answer = as_written(output)
            if (unit := answer["unitKey"].strip()) not in units:
                wrong_unit += 1
            else:
                latest[unit] = answer
    findings: Counter[str] = Counter()
    read_now: dict[str, int] = {}
    keys: list[Key] = []
    for key, answer in latest.items():
        read = read_unit(answer, questions.statements, units[key])
        findings.update(found.rule for found in read.findings)
        read_now[key] = len(read.statements)
        keys += [(text_hash(item.draft.verbatim), blocks[item.first].id) for item in read.statements]
    done = await done_units(connection, document.id)
    then = (await head_of(connection, document.id)).runs.get("X4")
    return Replayed(
        answers=answers,
        gone=gone,
        units=len(units),
        statements_now=sum(read_now.values()),
        statements_stored=sum(unit.statements for unit in done.values()),
        findings_now=dict(sorted(findings.items())),
        findings_stored=await rules_of_runs(connection, [run.run_id for run in runs]),
        out_of_form=out_of_form,
        wrong_unit=wrong_unit,
        missing=sum(1 for key in units if key not in latest),
        repaired=sum(1 for unit in done.values() if unit.repairs),
        units_differing=tuple(
            key
            for key in sorted(units, key=lambda key: int(key[1:]))
            if read_now.get(key, 0) != (done[key].statements if key in done else 0)
        ),
        lexicon_release_then=None if then is None else then.lexicon_release,
        lexicon_release_now=ground.release,
        keys=tuple(keys),
    )


async def replay_document(
    connection: psycopg.AsyncConnection,
    storage: Storage,
    llm: LLMSettings,
    document_id: UUID,
    ontology_dir: Path,
) -> Replayed:
    """``replay_x4`` of the document by its id; Refused where it is not there or kept no X4 answer."""
    document = await document_for_job(connection, document_id)
    if document is None:
        raise Refused("unknown_document", f"no document {document_id}")
    blocks = await all_blocks(connection, document.conversion_id)
    printed = await printed_pages(connection, document.conversion_id)
    return await replay_x4(connection, storage, llm, document, blocks, printed, ontology_dir)


def printed(replayed: Replayed) -> dict[str, Any]:
    """What the command prints: the counts and codes, not the keys."""
    return {name: value for name, value in asdict(replayed).items() if name != "keys"} | {
        "units_differing": list(replayed.units_differing)
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline.replay", description=__doc__.splitlines()[0]
    )
    parser.add_argument("document", type=UUID)
    parser.add_argument("--stage", choices=["x4"], default="x4")
    return parser


async def _replayed(settings: Settings, llm: LLMSettings, document_id: UUID) -> Replayed:
    storage = open_storage(settings)
    url = settings.database_url.get_secret_value()
    async with await psycopg.AsyncConnection.connect(
        url, autocommit=True, **CONNECTION_OPTIONS
    ) as connection:
        await connection.execute("SET default_transaction_read_only = on")  # a replay writes nothing
        return await replay_document(connection, storage, llm, document_id, settings.ontology_dir)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))  # a call amiss exits with 2
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        found = asyncio.run(
            _replayed(settings, LLMSettings(), args.document), loop_factory=asyncio.SelectorEventLoop
        )
    except Refused as refused:
        log.error("%s", refused)
        return 1
    sys.stdout.buffer.write((json.dumps(printed(found)) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
