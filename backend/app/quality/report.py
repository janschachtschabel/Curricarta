"""``python -m app.quality.report --sample <id> [--sample <id> ...] [--replayed]``: what the judgements of
gold samples measure (plan H-3 §3.4), as JSON on stdout - each document one entry, whatever samples of it
are named:

- ``statement``: by stratum the population when drawn (``frame``), drawn, judged, correct, imprecise,
  wrong, unjudged; the reasons; precision strict and lenient and the wrong rate weighted by each stratum's
  share of the frame kept when drawn (``by: frame_when_drawn``; null while a drawn item is still open, their
  count beside it), and the pooled rates over the judged items (``by: item``), each with the Wilson
  interval (95 %) of the pooled rate alone (``*_pooled_wilson95``): the weighted rate has none.
- ``block``: recall - Σ min(found, expected) / Σ expected over the judged blocks, ``found`` the model's
  statements whose anchors name the block now, however reviewed -, the blocks missed, those expected
  empty but holding statements (apart), the surplus.
- ``anchor``: the found anchors' precision as statements', over the strata that are not ``notFound:*`` -
  all of them, and again without the title pages' (``front:*``) -, beside ``title_pages`` as kept when
  drawn; apart, ``not_found``: the rows the import did not find - in the frame, drawn, judged, open - and
  how many of those judged hold a wording that is there after all (``missed``, ``missed_rate``).
- with ``--replayed``, in the statement section: what a replay of the document's kept answers
  (``python -m app.pipeline.replay``) would keep and lose of the judgements, by verdict, and how many
  statements it reads that nobody judged (``replayed``; app/quality/report_replay.py) - the precision after
  a change to the reader, without a new run and without writing.

A weighted rate is said once no drawn item is open in the strata that enter that measure: the anchors'
precision waits for the found strata alone, the figure without the title pages for those not ``front:*``.

An item no longer what was drawn (app/quality/stale.py: its row gone since the draw, or its wording, origin
or first block changed) and not judged is counted apart - ``stale: {gone, changed}`` in the statement and
anchor sections - and nowhere else: not among the drawn or the open, in no denominator. One judged while it
was as drawn stays among the judged and in every rate - a row changed afterwards does not undo what was
seen, and editors and repairs change what was wrong -; ``stale.judged_before`` counts those.

Each leaf is a number, a truth value, null or a code of ``LEAF``: no wording, quote or note can pass."""

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from typing import Any

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.core.storage import open_storage
from app.db.gold import Sample, items_of, judgements_of, judges_of, sample_by_id
from app.db.gold_report import head_of
from app.db.snapshot import snapshot
from app.llm.settings import LLMSettings
from app.pipeline.replay import Refused as ReplayRefused
from app.quality.closed import NOT_CLOSED, closed, token
from app.quality.report_replay import Replay, replay_of, replayed_counts
from app.quality.report_sections import (
    STATEMENT_REASONS,
    Section,
    anchors,
    blocks,
    verdicts,
)
from app.quality.stale import STALE, stale_items

log = logging.getLogger(__name__)


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


async def _entry(
    connection: psycopg.AsyncConnection, samples: Sequence[Sample], replay: Replay | None
) -> Section:
    head = await head_of(connection, samples[0].document_id)
    entry: Section = {
        "label": token(samples[0].label),
        "source_kind": "mem_import" if "IM" in head.runs else "extraction",
        "regions": [token(region) for region in head.regions],
        "sector": token(head.sector),
        "pages": head.pages,
        "runs": {
            stage: {
                "model": token(run.model),
                "prompt": token(run.prompt),
                "lexicon_release": run.lexicon_release,
            }
            for stage, run in sorted(head.runs.items())
            if token(stage)
        },
        "samples": [
            {"id": s.id, "kind": s.kind, "label": token(s.label), "seed": token(s.seed)} for s in samples
        ],
    }
    for sample in samples:
        items = await items_of(connection, sample.id)
        judgements = await judgements_of(connection, sample.id)
        if sample.kind == "block":  # a block is never stale
            section = await blocks(connection, sample, items, judgements)
        else:
            stale = await stale_items(connection, sample, items)
            open_stale = {key: state for key, state in stale.items() if key not in judgements}
            kept = [item for item in items if item.id not in open_stale]  # as drawn, or judged so
            counted = {state: list(open_stale.values()).count(state) for state in STALE}
            apart = {"stale": counted | {"judged_before": len(stale) - len(open_stale)}}
            if sample.kind == "anchor":
                section = anchors(sample, kept, judgements) | apart
            else:
                measured = verdicts(sample.frame, kept, judgements, STATEMENT_REASONS)
                section = {"sample": sample.id} | measured | apart
                if replay is not None:
                    counts = await replayed_counts(connection, sample.document_id, items, judgements, replay)
                    section |= {"replayed": counts}
        # the accounts whose judgements are counted - each item's latest, whoever gave it
        entry[sample.kind] = section | {"judges": await judges_of(connection, sample.id)}
    return entry


async def report(
    connection: psycopg.AsyncConnection, sample_ids: Sequence[int], *, replay: Replay | None = None
) -> dict[str, Any]:
    """The entries of the samples' documents, in the order first named, a statement sample's with what
    ``replay`` reads of its document; Refused where a sample is not there, or two samples of one kind name
    one document."""
    by_document: dict[Any, list[Sample]] = {}
    for sample_id in dict.fromkeys(sample_ids):
        sample = await sample_by_id(connection, sample_id)
        if sample is None:
            raise Refused("unknown_sample", f"no sample {sample_id}")
        those = by_document.setdefault(sample.document_id, [])
        if any(other.kind == sample.kind for other in those):
            raise Refused("kind_twice", f"two {sample.kind} samples of one document")
        those.append(sample)
    try:
        made = {"documents": [await _entry(connection, samples, replay) for samples in by_document.values()]}
    except LookupError:  # its document taken away meanwhile, its samples with it
        raise Refused("unknown_sample", "a sample went with its document") from None
    try:
        closed(made)
    except ValueError:  # a stratum's name longer than a leaf, say
        raise Refused(NOT_CLOSED, "a key or leaf is no count, rate or code") from None
    return made


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.quality.report", description=__doc__.splitlines()[0])
    parser.add_argument("--sample", required=True, type=int, action="append")
    parser.add_argument("--replayed", action="store_true")
    return parser


async def _report(settings: Settings, sample_ids: Sequence[int], replayed: bool) -> dict[str, Any]:
    async with snapshot(settings.database_url.get_secret_value()) as connection:  # read only, one snapshot
        replay = None
        if replayed:
            replay = replay_of(connection, open_storage(settings), LLMSettings(), settings.ontology_dir)
        return await report(connection, sample_ids, replay=replay)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))  # a call amiss exits with 2
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        made = asyncio.run(
            _report(settings, args.sample, args.replayed), loop_factory=asyncio.SelectorEventLoop
        )
    except (Refused, ReplayRefused) as refused:  # a replay's: its document kept no answer of X4
        log.error("%s", refused)
        return 1
    try:
        closed(made)  # report() checks it; checked again where it is printed
    except ValueError:
        log.error("%s: a key or leaf is no count, rate or code", NOT_CLOSED)
        return 1
    sys.stdout.buffer.write((json.dumps(made, indent=1) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
