"""``python -m app.quality.sample <document> --kind statement|block|anchor --label <label> --account <name>
[--size N] [--seed TEXT]``: a document's sample for the gold standard (plan H-3 §3.2), drawn under the seed
and kept in the database; on stdout as JSON its id and, by stratum, the population and how many were drawn
- counts and names from fixed lists alone, never a wording. What each kind is drawn from, app/quality/
populations.py says: 40 statements, 30 blocks, 40 anchors with five at least of each stratum.

Statements and blocks need X4 done, anchors the import (IM). A second draw under the same seed finds the
sample there and draws nothing: whatever the arguments besides, it is that one that is printed."""

import argparse
import asyncio
import json
import logging
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, get_args
from uuid import UUID

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db.documents import document_for_job
from app.db.gold import (
    ItemDraft,
    SampleDraft,
    SampleKind,
    TitlePages,
    add_sample,
    items_of,
    sample_by_id,
    sample_drawn,
)
from app.db.pool import CONNECTION_OPTIONS
from app.db.runs import Stage, done_stages
from app.quality.populations import population_of
from app.quality.sampling import drawn

log = logging.getLogger(__name__)

SEED = "curricarta-h3"
SIZES: dict[SampleKind, int] = {"statement": 40, "block": 30, "anchor": 40}
LEASTS: dict[SampleKind, int] = {"statement": 2, "block": 2, "anchor": 5}
NEEDS: dict[SampleKind, Stage] = {"statement": "X4", "block": "X4", "anchor": "IM"}
LABEL = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")  # as migration gold checks it
SEED_TEXT = re.compile(r"[A-Za-z0-9._-]{1,100}")
_BY_NAME = "SELECT id FROM account WHERE name = %s"
_OF_DOCUMENT = "gold_sample_document_id_fkey"  # the foreign key a document taken away violates

Call = Literal["same", "differs"]
RefusalCode = Literal["unknown_document", "unknown_account", "extraction_not_done", "nothing_to_draw"]


class Refused(Exception):
    def __init__(self, code: RefusalCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Request:
    document_id: UUID
    kind: SampleKind
    label: str
    account: str  # its name
    size: int | None = None  # the kind's own where None
    seed: str = SEED


@dataclass(frozen=True)
class Drawn:
    sample: int
    drawn_before: bool
    strata: dict[str, tuple[int, int]]  # by stratum, in their order: the population and how many were drawn
    title_pages: TitlePages | None  # a block's or anchor's sample: whether its title pages were found
    label: str  # the sample's, as kept
    size: int  # asked for when drawn
    call: Call  # whether this call asked for the label and size kept, or for others


async def draw(connection: psycopg.AsyncConnection, request: Request) -> Drawn:
    """The document's sample of the request's kind under its seed: the one there, else drawn now and kept;
    Refused where the document or the account is not there, the stage it needs is not done, or nothing is
    there to draw."""
    document = await document_for_job(connection, request.document_id)
    if document is None:
        raise Refused("unknown_document", f"no document {request.document_id}")
    cursor = await connection.execute(_BY_NAME, (request.account,))
    account = await cursor.fetchone()
    if account is None:
        raise Refused("unknown_account", "no account of that name")
    if NEEDS[request.kind] not in await done_stages(connection, document.id):
        raise Refused("extraction_not_done", f"a {request.kind} sample needs {NEEDS[request.kind]} done")
    if (there := await sample_drawn(connection, document.id, request.kind, request.seed)) is not None:
        return await _kept(connection, there, request, drawn_before=True)
    found = await population_of(connection, document, request.kind)
    population = found.items
    if not population:
        raise Refused("nothing_to_draw", f"the document has no {request.kind} to draw")
    picked = drawn(
        population,
        seed=request.seed,
        size=request.size or SIZES[request.kind],
        stratum=lambda item: item.stratum,
        key=_key,
        least=LEASTS[request.kind],
    )
    frame = dict(sorted(Counter(item.stratum for item in population).items()))
    draft = SampleDraft(
        kind=request.kind,
        document_id=document.id,
        label=request.label,
        seed=request.seed,
        size=request.size or SIZES[request.kind],
        frame=frame,
        drawn_by=account[0],
        title_pages=found.title_pages,
    )
    gone = Refused("unknown_document", f"no document {request.document_id}")
    try:
        sample = await add_sample(connection, draft, picked)
    except psycopg.errors.ForeignKeyViolation as violated:  # the document taken away meanwhile, else as it is
        if violated.diag.constraint_name != _OF_DOCUMENT:
            raise
        raise gone from None
    except LookupError:  # taken away with the sample another draw had written
        raise gone from None
    return await _kept(connection, sample, request, drawn_before=False)


def _key(item: ItemDraft) -> str:
    """What the seed orders an item by: a block by its id, else by its wording's hash and first block, so
    that the same statement at the same place keeps its place over a new run."""
    if item.block_id is not None:
        return item.block_id
    return f"{item.text_hash or 'none'}:{item.first_block or 'none'}"


async def _kept(
    connection: psycopg.AsyncConnection, sample_id: int, request: Request, *, drawn_before: bool
) -> Drawn:
    sample = await sample_by_id(connection, sample_id)
    if sample is None:  # taken away with its document since
        raise Refused("unknown_document", "the document went with its sample")
    picked = Counter(item.stratum for item in await items_of(connection, sample_id))
    strata = {stratum: (population, picked[stratum]) for stratum, population in sorted(sample.frame.items())}
    asked = (request.label, request.size or SIZES[request.kind])
    call: Call = "same" if asked == (sample.label, sample.size) else "differs"
    return Drawn(sample_id, drawn_before, strata, sample.title_pages, sample.label, sample.size, call)


def _matching(pattern: re.Pattern[str], what: str) -> Callable[[str], str]:
    def check(value: str) -> str:
        if pattern.fullmatch(value) is None:
            raise argparse.ArgumentTypeError(f"{what} must match {pattern.pattern}")
        return value

    return check


def _size(value: str) -> int:
    if not value.isdigit() or not 1 <= int(value) <= 2000:
        raise argparse.ArgumentTypeError("the size lies between 1 and 2000")
    return int(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.quality.sample", description=__doc__.splitlines()[0])
    parser.add_argument("document", type=UUID)
    parser.add_argument("--kind", required=True, choices=get_args(SampleKind))
    parser.add_argument("--label", required=True, type=_matching(LABEL, "a label"))
    parser.add_argument("--account", required=True)
    parser.add_argument("--size", type=_size)
    parser.add_argument("--seed", default=SEED, type=_matching(SEED_TEXT, "a seed"))
    return parser


async def _drawn(settings: Settings, request: Request) -> Drawn:
    url = settings.database_url.get_secret_value()
    async with await psycopg.AsyncConnection.connect(
        url, autocommit=True, **CONNECTION_OPTIONS
    ) as connection:
        return await draw(connection, request)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))  # a call amiss exits with 2
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    request = Request(args.document, args.kind, args.label, args.account, args.size, args.seed)
    try:
        made = asyncio.run(_drawn(settings, request), loop_factory=asyncio.SelectorEventLoop)
    except Refused as refused:
        log.error("%s", refused)
        return 1
    printed: dict[str, object] = {
        "sample": made.sample,
        "kind": request.kind,
        "seed": request.seed,
        "drawn_before": made.drawn_before,
        "title_pages": made.title_pages,
        "label": made.label,
        "size": made.size,
        "call": made.call,
        "strata": {
            stratum: {"frame": frame, "drawn": count} for stratum, (frame, count) in made.strata.items()
        },
    }
    sys.stdout.buffer.write((json.dumps(printed, indent=1) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
