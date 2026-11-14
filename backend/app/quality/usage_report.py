"""``python -m app.quality.usage_report <document> --label <label> [--raw]``: what the runs of a document cost
(plan H-3, A3), as one line of JSON - counts alone, the document named by the label, never by its title:

- ``by_purpose`` and ``total``: the ledger's requests (app/db/usage_measures.py) - the tokens the answers
  reported, the bookings at what was held for a request (``estimated_*``: sent and never answered, or an
  answer that reported nothing) apart, what the budget was charged, the largest answer against ``cap``
  (LLM_MAX_OUTPUT_TOKENS) and the answers cut there, the reservations left;
- ``runs``: the runs by stage, how many ended how and how long they took; ``conversion``: its pages;
- with ``--raw``: the usage the kept answers report (``runs/<run>/<stage>/<n>.json``, as many as the
  ledger booked answers for), the reasoning tokens where an answer names them (null where none does: the
  ledger keeps them in the output), and whether the reported tokens are the ledger's (``ledger_equals_raw``).
  An answer gone or unreadable is counted and ends nothing.

An answer cut at the cap is told by its reported output reaching the cap; how the pipeline finds and books
cut answers may change - this count then needs a second look. Exit code 1 for a document that is not
there, 2 for a call amiss (a label other than a plain one among them)."""

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

import psycopg
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.core.storage import Storage, open_storage
from app.db.documents import document_for_job
from app.db.pool import CONNECTION_OPTIONS
from app.db.usage_measures import answered_runs, conversion_usage_of, runs_summary, usage_by_purpose
from app.llm.raw import kept_answers
from app.llm.settings import LLMSettings
from app.quality.sample import LABEL, matching

log = logging.getLogger("app.quality.usage_report")  # also when run as __main__

TOKENS = ("input_tokens", "cached_input_tokens", "output_tokens")


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class RawUsage:
    answers: int = 0  # read and reporting their usage
    gone: int = 0  # booked, not in the store
    unreadable: int = 0  # in the store, no answer
    unreported: int = 0  # an answer that reported no input: the ledger booked an estimate for it
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int | None = None


def _read(raw: RawUsage, data: bytes | None) -> None:
    if data is None:
        raw.gone += 1
        return
    try:
        answers = [
            message
            for message in ModelMessagesTypeAdapter.validate_json(data)
            if isinstance(message, ModelResponse)
        ]
    except ValidationError:
        answers = []
    if not answers:
        raw.unreadable += 1
        return
    for answer in answers:
        usage = answer.usage
        if usage.input_tokens == 0:  # booked at what was held for it (app/llm/calls.py _answered)
            raw.unreported += 1
            continue
        raw.answers += 1
        raw.input_tokens += usage.input_tokens
        raw.cached_input_tokens += usage.cache_read_tokens
        raw.output_tokens += usage.output_tokens
        if (reasoning := usage.details.get("reasoning_tokens")) is not None:
            raw.reasoning_tokens = (raw.reasoning_tokens or 0) + reasoning


async def _raw_usage(connection: psycopg.AsyncConnection, storage: Storage, document_id: UUID) -> RawUsage:
    raw = RawUsage()
    for run in await answered_runs(connection, document_id):
        for data in await kept_answers(storage, run.run_id, run.stage.lower(), run.answers):
            _read(raw, data)
    return raw


async def usage_report(
    connection: psycopg.AsyncConnection,
    storage: Storage | None,
    document_id: UUID,
    label: str,
    *,
    cap: int,
    raw: bool = False,
) -> dict[str, Any]:
    """The report as the module says; ``storage`` read with ``raw`` alone. Refused where the document is
    not there."""
    if await document_for_job(connection, document_id) is None:
        raise Refused("unknown_document", f"no document {document_id}")
    by_purpose = {
        usage.purpose: {name: value for name, value in asdict(usage).items() if name != "purpose"}
        for usage in await usage_by_purpose(connection, document_id, cap=cap)
    }
    sums = (
        "requests",
        "unanswered_requests",
        *TOKENS,
        "charged_tokens",
        "estimated_rows",
        "estimated_charged_tokens",
    )
    made: dict[str, Any] = {
        "label": label,
        "cap": cap,
        "by_purpose": by_purpose,
        "total": {name: sum(usage[name] for usage in by_purpose.values()) for name in sums},
        "runs": {
            stage: asdict(runs) for stage, runs in (await runs_summary(connection, document_id)).items()
        },
        "conversion": await conversion_usage_of(connection, document_id),
    }
    if raw:
        assert storage is not None  # noqa: S101 - the command opens it for --raw
        found = await _raw_usage(connection, storage, document_id)
        equal = all(getattr(found, name) == made["total"][name] for name in TOKENS)
        made["raw"] = asdict(found) | {"ledger_equals_raw": equal}
    return made


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.quality.usage_report", description=__doc__.splitlines()[0]
    )
    parser.add_argument("document", type=UUID)
    parser.add_argument("--label", required=True, type=matching(LABEL, "a label"))
    parser.add_argument("--raw", action="store_true")
    return parser


async def _report(settings: Settings, cap: int, args: argparse.Namespace) -> dict[str, Any]:
    storage = open_storage(settings) if args.raw else None
    url = settings.database_url.get_secret_value()
    async with await psycopg.AsyncConnection.connect(
        url, autocommit=True, **CONNECTION_OPTIONS
    ) as connection:
        return await usage_report(connection, storage, args.document, args.label, cap=cap, raw=args.raw)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))  # a call amiss exits with 2
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    cap = LLMSettings().llm_max_output_tokens
    try:
        made = asyncio.run(_report(settings, cap, args), loop_factory=asyncio.SelectorEventLoop)
    except Refused as refused:
        log.error("%s", refused)
        return 1
    sys.stdout.buffer.write((json.dumps(made) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
