"""X4 of an extraction run (plan M1 7b, F3, F4, F11, F12): the statements of each unit - an X2 package
read in full - asked of the model, a request a unit, behind the prefix the units share
(app/pipeline/x4_question.py), and each unit written whole on its own as soon as it is answered
(app/pipeline/x4_unit.py).

Units are asked side by side, at most EXTRACT_CONCURRENCY of them, and never more than the
database's pool leaves beside the worker's own work: each holds one connection at a time. A job
asks only the units still open - an earlier job's done stay done (extraction_unit) -, and none where
no window of the document fits one of them (``prefix_too_long``, before the run). A budget spent
lets no further unit begin: those asked are answered and written, then the run ends as
``budget_exhausted`` and the job with it, and a job with budget goes on with the rest. So does a
provider's error, once its waits are spent (app/pipeline/side_by_side.py): the run ends by it, a
request refused for good as ``model_refused``, any other for the job's next attempt. A unit whose
answer never took its form, or answered for another unit, stays open while the others go on; the
run then ends as failed (``model_unanswered``) and the next job asks it again. So does a unit whose
answer was cut at the output cap, but the run ends as ``answer_cut`` - before ``model_unanswered`` -
and its finding (``x4.answer_cut``) names the cap: no job asks the unit again under a cap no higher,
whose answer would be cut and paid for again, and each ends as ``answer_cut``. Any other error - a
lease lost, the database - ends every unit still asking; what was written stays. The run ends done
once every unit is, under the lease and the document's lock: a run of X4 done meanwhile passes it
over. Progress is reported as each unit is written.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import psycopg

from app.conversion.base import Block
from app.db.documents import Document
from app.db.findings import Finding, add_findings, drop_rule_findings, rule_details
from app.db.runs import RunStart, done_stages, finish_run, lock_for_stage, stage_result, start_run
from app.db.units import UnitTaken, done_units
from app.jobs.context import JobContext
from app.jobs.queue import Job, hold_lease
from app.llm.calls import StageAgent, output_cap
from app.llm.metering import BudgetExhausted
from app.llm.raw import RawResponses
from app.pipeline.asking import AnswerCut, Asking, Superseded, Unanswered, ended, model_of
from app.pipeline.ground import ground_of
from app.pipeline.progress import report
from app.pipeline.prompts import x4
from app.pipeline.side_by_side import PROVIDER_ERRORS, ask_side_by_side, fail_by_provider
from app.pipeline.x2_segments import WorkPackage
from app.pipeline.x4_question import UnitQuestions, unit_questions
from app.pipeline.x4_read import WrongUnit, read_unit
from app.pipeline.x4_unit import first_position, write_unit

PROMPT_VERSION = x4.PROMPT_VERSION


async def run_x4(
    context: JobContext, job: Job, document: Document, blocks: Sequence[Block], printed: Sequence[str | None]
) -> dict[str, Any]:
    """X4 of the document of these blocks (all of its conversion's, in order) - as the store holds
    it after X3 -; the run's result."""
    model, model_name = model_of(context)
    assert context.llm is not None  # noqa: S101 - the stage has its model (model_of)
    async with context.pool.connection() as connection:
        if "X4" in await done_stages(connection, document.id):  # another job's since this one looked
            return {"done_before": True}
        kept = await stage_result(connection, document.id, "X2")
        packages = [WorkPackage.from_result(item) for item in (kept or {}).get("packages", [])]
        units = [item for item in packages if item.job == "statements"]
        done = len(units) - len(open_units := await units_to_ask(connection, document, units))
        cut = await units_cut(connection, document, cap := output_cap(model))
        held = [unit.key for unit in open_units if unit.key in cut]
        open_units = [unit for unit in open_units if unit.key not in cut]
        # the lease first; in a block of its own, which ends the hold on the job's row
        await report(connection, job, "extract_statements", done=done, total=len(units))
    async with context.pool.connection() as connection:
        ground = await ground_of(connection, document)
        questions = await unit_questions(connection, context.llm, document, blocks, printed, ground, model)
    # every open unit's window, before any is asked: one that fits none ends the job at once,
    # rather than a run later with the units asked beside it cut off and paid for
    await questions.check(open_units)
    async with context.pool.connection() as connection:
        start = RunStart(
            document.id,
            job.id,
            job.attempts,
            "X4",
            model_name,
            PROMPT_VERSION,
            ground.profile,
            ground.release,
        )
        run_id = await start_run(connection, start)
    keeper = RawResponses(context.storage.sync, run_id, "x4")
    asking = Asking(context, job, document, run_id, model, model_name, keeper)
    work = _Units(asking, questions, packages, len(units), done, cap, held)
    return await ended(context, run_id, "X4", work.run(open_units))


async def units_to_ask(
    connection: psycopg.AsyncConnection, document: Document, units: Sequence[WorkPackage]
) -> list[WorkPackage]:
    """The units no job has done yet."""
    done = await done_units(connection, document.id)
    return [unit for unit in units if unit.key not in done]


async def units_cut(connection: psycopg.AsyncConnection, document: Document, cap: int | None) -> set[str]:
    """The units whose answer an earlier run found cut at a cap no lower than ``cap``."""
    found = await rule_details(connection, document.id, "x4.answer_cut")
    return {
        key
        for details in found
        if cap is not None and details.get("cap", 0) >= cap
        for key in details.get("units", [])
    }


@dataclass
class _Units:
    """One run's units being asked and written."""

    asking: Asking
    questions: UnitQuestions
    packages: Sequence[WorkPackage]  # all of X2's, for the parts of a node
    total: int
    done: int
    cap: int | None  # on an answer, as the model sends it
    held: list[str]  # open, and cut before under a cap no lower: not asked
    spent: BudgetExhausted | None = None  # once set, no further unit begins
    broken: Exception | None = None  # the provider's first error (PROVIDER_ERRORS); as spent
    unanswered: list[str] = field(default_factory=list)
    cut: list[str] = field(default_factory=list)
    taken: int = 0

    async def run(self, units: Sequence[WorkPackage]) -> dict[str, Any]:
        stage = self.asking.agent(x4.SCHEMA, x4.SCHEMA_NAME, x4.INSTRUCTIONS)
        await ask_side_by_side(self.asking.context.settings, units, lambda unit: self._unit(unit, stage))
        return await self._end()

    async def _unit(self, unit: WorkPackage, stage: StageAgent) -> None:
        if self.spent is not None or self.broken is not None:
            return
        question = await self.questions.question(unit)
        try:
            answer = await self.asking.answer(stage, "x4.unit", question.prompt)
            read = read_unit(answer, self.questions.statements, unit)
        except BudgetExhausted as spent:
            self.spent = spent
            return
        except PROVIDER_ERRORS as error:
            self.broken = self.broken or error
            return
        except AnswerCut:
            self.cut.append(unit.key)
            return
        except (Unanswered, WrongUnit):
            self.unanswered.append(unit.key)
            return
        # a unit's findings name it: one answer's paths are no document's (X6 repairs by unit)
        named = [replace(found, details={**found.details, "unit": unit.key}) for found in read.findings]
        read = replace(read, findings=[*question.findings, *named])
        context, job, document = self.asking.context, self.asking.job, self.asking.document
        async with context.pool.connection() as connection:
            first = first_position(unit, self.packages)
            try:
                await write_unit(
                    connection, job, document, unit, read, first=first, run_id=self.asking.run_id
                )
            except UnitTaken:  # by a job beside this one: done all the same
                self.taken += 1
            self.done += 1
            await report(connection, job, "extract_statements", done=self.done, total=self.total)

    async def _end(self) -> dict[str, Any]:
        context, job, document, run_id = (
            self.asking.context, self.asking.job, self.asking.document, self.asking.run_id,
        )  # fmt: skip
        keys = sorted(self.unanswered, key=_by_number)
        cut = sorted(self.cut, key=_by_number)
        findings = []
        if keys:
            message = "units the model's answers never took the form of, or answered for another"
            findings.append(Finding("x4.unanswered", "warning", document.id, message, None, {"units": keys}))
        if cut:  # named once, by the run that met the cap: a run that held them back adds nothing
            message = "units whose answer was cut at the output cap: not read"
            details = {"units": cut, "cap": self.cap}
            findings.append(Finding("x4.answer_cut", "warning", document.id, message, None, details))
        if findings:  # committed before the run ends: they go with the run, however that ends
            async with context.pool.connection() as connection, connection.transaction():
                await hold_lease(connection, job)
                await add_findings(connection, document.id, run_id, findings)
        if self.spent is not None:
            raise self.spent
        if self.broken is not None:
            fail_by_provider(self.broken)
        if cut or self.held:
            named = ", ".join(sorted([*cut, *self.held], key=_by_number))
            raise AnswerCut(f"units {named} were cut at the output cap of {self.cap} tokens")
        if keys:
            raise Unanswered(f"units {', '.join(keys)} were never answered in form")
        async with context.pool.connection() as connection, connection.transaction():
            await hold_lease(connection, job)
            if await lock_for_stage(connection, document.id, "X4"):
                raise Superseded
            # every unit answered now: an earlier run's word that some were not is no longer true
            await drop_rule_findings(connection, document.id, "x4.unanswered")
            await drop_rule_findings(connection, document.id, "x4.answer_cut")
            done = await done_units(connection, document.id)
            result = {
                "units": self.total,
                "statements": sum(unit.statements for unit in done.values()),
                "taken": self.taken,
            }
            await finish_run(connection, run_id, "done", result)
        return result


def _by_number(key: str) -> int:
    return int(key[1:])  # "E12" after "E2"
