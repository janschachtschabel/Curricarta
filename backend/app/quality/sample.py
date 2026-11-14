"""``python -m app.quality.sample <document> --kind statement|block|anchor --label <label> --account <name>
[--size N] [--seed TEXT]``: a document's sample for the gold standard (plan H-3 §3.2), drawn under the seed
and kept in the database; on stdout as JSON its id and, by stratum, the population and how many were drawn
- counts and names from fixed lists alone, never a wording.

- ``statement``: the statements the model wrote and no editor touched or rejected, by their kind; 40.
- ``block``: the blocks of the running text - no header or footer, none of the contents, none before the
  title pages end, no node's heading, 40 signs at least - by the third of the document they stand in and
  whether they are text or a table; 30. Where the contents were not found, the title pages are unknown:
  none are left out, and the output says so (``title_pages``).
- ``anchor``: the rows of an import still as imported, by how their anchor was found and whether it is a
  node's or a statement's; 40, five at least of each.

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
from app.db.conversions import all_blocks
from app.db.documents import Document, document_for_job
from app.db.gold import ItemDraft, SampleDraft, SampleKind, add_sample, items_of, sample_by_id, sample_drawn
from app.db.measures import imported_anchors, model_statements, title_blocks
from app.db.pool import CONNECTION_OPTIONS
from app.db.runs import Stage, done_stages
from app.domain.lexicon import active_cues
from app.pipeline.ground import ground_of
from app.pipeline.patterns import PatternSearch
from app.pipeline.skeleton import IN_CONTENTS
from app.pipeline.toc import OUTSIDE, find_contents
from app.quality.sampling import drawn

log = logging.getLogger(__name__)

SEED = "curricarta-h3"
SIZES: dict[SampleKind, int] = {"statement": 40, "block": 30, "anchor": 40}
LEASTS: dict[SampleKind, int] = {"statement": 2, "block": 2, "anchor": 5}
NEEDS: dict[SampleKind, Stage] = {"statement": "X4", "block": "X4", "anchor": "IM"}
SHORTEST_BLOCK = 40  # signs: a shorter block holds a statement seldom
LABEL = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")  # as migration gold checks it
SEED_TEXT = re.compile(r"[A-Za-z0-9._-]{1,100}")
_BY_NAME = "SELECT id FROM account WHERE name = %s"

TitlePages = Literal["left_out", "unknown"]
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
    title_pages: TitlePages | None  # a block sample drawn now: whether the title pages were left out


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
        return await _kept(connection, there, drawn_before=True, title_pages=None)
    title_pages: TitlePages | None = None
    if request.kind == "statement":
        population = await model_statements(connection, document.id)
    elif request.kind == "anchor":
        population = await imported_anchors(connection, document.id)
    else:
        population, title_pages = await _running_text(connection, document)
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
    )
    sample = await add_sample(connection, draft, picked)
    return await _kept(connection, sample, drawn_before=False, title_pages=title_pages)


def _key(item: ItemDraft) -> str:
    """What the seed orders an item by: a block by its id, else by its wording's hash and first block, so
    that the same statement at the same place keeps its place over a new run."""
    if item.block_id is not None:
        return item.block_id
    return f"{item.text_hash or 'none'}:{item.first_block or 'none'}"


async def _running_text(
    connection: psycopg.AsyncConnection, document: Document
) -> tuple[list[ItemDraft], TitlePages]:
    """The blocks of the document's running text, by third and kind; the contents found as the import
    finds them (app/sources/mem/import_job.py), by the document's cues as they stand now."""
    blocks = await all_blocks(connection, document.conversion_id)
    ground = await ground_of(connection, document)
    typed = active_cues(
        ground.cues, ground.regions, document.document_type_iri, None, wider_regions=ground.wider
    )
    toc = [found.cue for found in typed if IN_CONTENTS in found.cue.maps_to]
    contents = await asyncio.to_thread(find_contents, blocks, toc, PatternSearch())
    headings = await title_blocks(connection, document.id)
    pages = max((block.page for block in blocks), default=1)
    front = contents.front_end or 0
    population = [
        ItemDraft(stratum=f"t{1 + 3 * (block.page - 1) // pages}:{block.kind}", block_id=block.id)
        for position, block in enumerate(blocks)
        if block.kind not in OUTSIDE
        and position >= front
        and position not in contents.positions
        and block.id not in headings
        and len(block.text.strip()) >= SHORTEST_BLOCK
    ]
    return population, "unknown" if contents.front_end is None else "left_out"


async def _kept(
    connection: psycopg.AsyncConnection, sample_id: int, *, drawn_before: bool, title_pages: TitlePages | None
) -> Drawn:
    sample = await sample_by_id(connection, sample_id)
    if sample is None:  # taken away with its document since
        raise Refused("unknown_document", "the document went with its sample")
    picked = Counter(item.stratum for item in await items_of(connection, sample_id))
    strata = {stratum: (population, picked[stratum]) for stratum, population in sorted(sample.frame.items())}
    return Drawn(sample_id, drawn_before, strata, title_pages)


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
        "strata": {
            stratum: {"frame": frame, "drawn": count} for stratum, (frame, count) in made.strata.items()
        },
    }
    if made.title_pages is not None:
        printed["title_pages"] = made.title_pages
    sys.stdout.buffer.write((json.dumps(printed, indent=1) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
