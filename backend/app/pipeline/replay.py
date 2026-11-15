"""``python -m app.pipeline.replay <document> [--stage x4]``: the answers the X4 runs of a document kept
(``runs/<run>/x4/<n>.json``: as many as the ledger booked answers for, and any kept beyond them,
``beyond_ledger``), read again by today's reader without asking the model (plan H-3, A4) - so that a change
to the reader is judged without paying for a new run. Each answer goes through the stage's own agent - its
schema's form checked (``schema_errors``), its texts made storable -, a stand-in model handing it over and
never asking a provider; each unit's own answer is chosen as the pipeline chose it
(app/pipeline/replay_answers.py); then ``as_written`` and ``read_unit``, as X4 reads it
(app/pipeline/asking.py, x4_statements.py).

Printed as one line of JSON, counts and codes alone: the X4 runs read, the answers read, gone from the
store, taken by the retention (``swept``: past RETENTION_RAW_ANSWERS_DAYS, their run's key cleared, the
run not read), unreadable, out of form, naming no unit of X2 (``unknown_unit``); the units, those without an
answer (``missing``), those whose run kept more than one answer naming them (``ambiguous``), those X6
wrote anew since (``repaired_units``: what they hold is X6's, not X4's); the statements read now against
those the units wrote (``extraction_unit``), the units whose count differs; the findings of the reading
against those the X4 runs wrote, by rule; and the lexicon's release then - of the last X4 run that ended
done, while the answers of every answered X4 run are read - and now: the reader reads with X3's choice
lists and the lexicon as they stand, so a replay after a change of the vocabularies measures both. The
question's own
findings (``x4.pattern_timeout``), ``x4.unanswered`` and ``x4.answer_cut`` are the run's, never the
reader's: they may stand in ``findings_stored``, never in ``findings_now``.

Two limits to read the counts by. The database is one snapshot (app/db/snapshot.py), the store is not: a
job writing meanwhile can keep answers the snapshot's ledger has not booked yet (``beyond_ledger``, read all
the same) and write units the snapshot does not show - replay a document no job is working on. And the
choice of a unit's answer rests on what is kept today: where its own answer is gone, unreadable or out of
form today, a single stray naming it in the run that wrote it - another unit's answer, thrown away by the
run - is taken for its own; only two are told apart (``ambiguous``).

Read only, in one snapshot of the database: nothing is written to the document, the store or a file. An
output that is not counts and codes alone is refused (``report_not_closed``). Exit code 1 for a document
that is not there or has no kept answer of X4 (``no_raw_answers``; ``raw_answers_swept`` where the retention
took them all), or a refused output; 2 for a call amiss."""

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

from app.conversion.base import Block
from app.core.logging import configure_logging
from app.core.settings import Settings
from app.core.storage import Storage, open_storage
from app.db.conversions import all_blocks, printed_pages
from app.db.documents import Document, document_for_job
from app.db.findings import rules_of_runs
from app.db.gold_report import head_of
from app.db.runs import stage_result
from app.db.snapshot import snapshot
from app.db.units import done_units
from app.db.usage_measures import answered_runs
from app.domain.wording import text_hash
from app.llm.calls import build_agent
from app.llm.schema import SCHEMA_DIR, load_schema
from app.llm.settings import LLMSettings
from app.pipeline.ground import ground_of
from app.pipeline.prompts import x4
from app.pipeline.replay_answers import KeptAnswers, chosen, gather
from app.pipeline.x2_segments import WorkPackage
from app.pipeline.x4_question import unit_questions
from app.pipeline.x4_read import read_unit
from app.quality.closed import NOT_CLOSED, closed

log = logging.getLogger("app.pipeline.replay")  # also when run as __main__

Key = tuple[str, str]  # a statement's wording hash and first block: what a gold judgement follows


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Replayed:
    runs: int  # X4 runs read
    answers: int  # kept answers read
    gone: int  # booked as answered, not in the store
    unreadable: int  # kept, no model answer
    beyond_ledger: int  # kept beyond the answers the ledger booked
    swept: int  # booked as answered, taken by the retention with their run's key: that run is not read
    units: int  # X2's units of statements
    statements_now: int  # as today's reader reads the units' answers
    statements_stored: int  # as the units wrote them (extraction_unit)
    findings_now: dict[str, int]  # of the reading, by rule
    findings_stored: dict[str, int]  # the X4 runs wrote and are kept, by rule
    out_of_form: int  # answers that never took the schema's form
    unknown_unit: int  # answers naming no unit of X2
    missing: int  # units without an answer of their own
    ambiguous: int  # units whose run kept more than one answer naming them: not guessed
    repaired_units: tuple[str, ...]  # units X6 wrote anew since: what they hold is X6's
    units_differing: tuple[str, ...]  # whose statements now and stored differ in number
    lexicon_release_then: int | None  # of the last X4 run that ended done
    lexicon_release_now: int | None
    keys: tuple[Key, ...]  # each statement read now: its wording's hash and first block; never printed


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
    answered = [
        run for run in await answered_runs(connection, document.id) if run.stage == "X4" and run.answers
    ]
    if not answered:
        raise Refused("no_raw_answers", "no run of X4 kept an answer")
    runs = [run for run in answered if not run.swept]
    if not runs:
        raise Refused("raw_answers_swept", "the retention took the answers of every run of X4")
    kept = await stage_result(connection, document.id, "X2")
    packages = [WorkPackage.from_result(item) for item in (kept or {}).get("packages", [])]
    units = {item.key: item for item in packages if item.job == "statements"}
    order = sorted(units, key=lambda key: int(key[1:]))
    ground = await ground_of(connection, document)
    hands = KeptAnswers(llm)
    questions = await unit_questions(connection, llm, document, blocks, printed, ground, hands.model)
    schema = load_schema(ontology_dir / SCHEMA_DIR, x4.SCHEMA)
    stage = build_agent(hands.model, schema=schema, name=x4.SCHEMA_NAME, instructions=x4.INSTRUCTIONS)
    gathered = await gather(storage, stage, hands, runs, units)
    done = await done_units(connection, document.id)
    # every answered X4 run is one, its answers swept or not: a unit a swept run wrote has no answer of its
    # own now (missing), and is never taken for X6's work nor given another run's answer naming it
    picked = chosen(order, done, {run.run_id for run in answered}, gathered)
    findings: Counter[str] = Counter()
    read_now: dict[str, int] = {}
    keys: list[Key] = []
    for key, answer in picked.answers.items():
        read = read_unit(answer, questions.statements, units[key])
        findings.update(found.rule for found in read.findings)
        read_now[key] = len(read.statements)
        keys += [(text_hash(item.draft.verbatim), blocks[item.first].id) for item in read.statements]
    then = (await head_of(connection, document.id)).runs.get("X4")
    return Replayed(
        runs=gathered.runs,
        answers=gathered.answers,
        gone=gathered.gone,
        unreadable=gathered.unreadable,
        beyond_ledger=gathered.beyond_ledger,
        swept=sum(run.answers for run in answered if run.swept),
        units=len(units),
        statements_now=sum(read_now.values()),
        statements_stored=sum(unit.statements for unit in done.values()),
        findings_now=dict(sorted(findings.items())),
        findings_stored=await rules_of_runs(connection, [run.run_id for run in runs]),
        out_of_form=gathered.out_of_form,
        unknown_unit=gathered.unknown_unit,
        missing=sum(1 for key in units if key not in picked.answers and key not in picked.ambiguous),
        ambiguous=len(picked.ambiguous),
        repaired_units=picked.repaired,
        units_differing=tuple(
            key for key in order if read_now.get(key, 0) != (done[key].statements if key in done else 0)
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
    """What the command prints: the counts and codes - the number of units repaired beside their keys -,
    not the keys of the statements."""
    shown = {name: value for name, value in asdict(replayed).items() if name != "keys"}
    return shown | {
        "repaired": len(replayed.repaired_units),
        "repaired_units": list(replayed.repaired_units),
        "units_differing": list(replayed.units_differing),
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
    async with snapshot(settings.database_url.get_secret_value()) as connection:
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
    made = printed(found)
    try:
        closed(made)
    except ValueError:  # a rule's name a leaf cannot hold, say
        log.error("%s: a key or leaf is no count or code", NOT_CLOSED)
        return 1
    sys.stdout.buffer.write((json.dumps(made) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
