"""``python -m app.quality.report --sample <id> [--sample <id> ...]``: what the judgements of gold samples
measure (plan H-3 §3.4), as JSON on stdout - each document one entry, whatever samples of it are named:

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
  drawn; apart, ``not_found``: of the rows the import did not find, how many were judged and how many of
  those hold a wording that is there after all (``missed``, ``missed_rate``).

Each leaf is a number, a truth value, null or a code of ``LEAF``: no wording, quote or note can pass."""

import argparse
import asyncio
import json
import logging
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db.gold import Item, Judgement, Sample, items_of, judgements_of, judges_of, sample_by_id
from app.db.gold_report import found_in_blocks, head_of
from app.db.pool import CONNECTION_OPTIONS
from app.quality.rates import recall, weighted, wilson

log = logging.getLogger(__name__)

LEAF = r"[A-Za-z0-9_.:/+-]{1,60}"  # no space: no wording passes
STATEMENT_REASONS = ("not_a_statement", "not_in_document", "node", "boundary", "kind", "fields")
ANCHOR_REASONS = ("boundary", "wrong_place")  # of a found anchor; "missed" is not_found's
FRONT = "front:"  # the strata of the title pages' anchors
NOT_FOUND = "notFound:"
_DIGITS = 4

Section = dict[str, Any]


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _token(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(LEAF, value) else None


def _rate(value: float | None) -> float | None:
    return None if value is None else round(value, _DIGITS)


def _verdicts(
    frame: Mapping[str, int],
    items: Sequence[Item],
    judgements: Mapping[int, Judgement],
    reasons: Sequence[str],
) -> Section:
    """A statement's or anchor's measures over the strata of ``frame`` and the items in them."""
    strata: dict[str, dict[str, int]] = {}
    for stratum in sorted(set(frame) | {item.stratum for item in items}):
        verdicts = [judgements[i.id].verdict for i in items if i.stratum == stratum and i.id in judgements]
        given = [verdict for verdict in verdicts if verdict is not None]
        drawn = sum(1 for item in items if item.stratum == stratum)
        strata[stratum] = {"frame": frame.get(stratum, 0), "drawn": drawn, "judged": len(given)} | {
            verdict: given.count(verdict) for verdict in ("correct", "imprecise", "wrong")
        } | {"unjudged": drawn - len(given)}  # fmt: skip
    counted = {
        "precision_strict": ("correct",),
        "precision_lenient": ("correct", "imprecise"),
        "wrong_rate": ("wrong",),
    }
    judged = sum(row["judged"] for row in strata.values())
    still = sum(row["unjudged"] for row in strata.values())
    pooled: dict[str, Any] = {"by": "item", "judged": judged}
    weighing: dict[str, Any] = {"by": "frame_when_drawn", "open": still}
    for name, hits_of in counted.items():
        hits = {stratum: (sum(row[v] for v in hits_of), row["judged"]) for stratum, row in strata.items()}
        # said once every drawn item is judged: a stratum's rate on part of its items is not yet its own
        weighing[name] = _rate(weighted({s: frame.get(s, 0) for s in strata}, hits)) if not still else None
        total = sum(hit for hit, _ in hits.values())
        pooled[name] = _rate(total / judged) if judged else None
        interval = [_rate(end) for end in wilson(total, judged)] if judged else None
        pooled[f"{name}_pooled_wilson95"] = interval  # the pooled rate's alone, never the weighted one's
    named: list[str] = [r for item in items if item.id in judgements for r in judgements[item.id].reasons]
    return {
        "strata": strata,
        "reasons": {reason: named.count(reason) for reason in reasons},
        "judged": judged,
        "open": still,
        "weighted": weighing,
        "pooled": pooled,
    }


def _anchors(sample: Sample, items: Sequence[Item], judgements: Mapping[int, Judgement]) -> Section:
    """The found anchors' precision - over the strata not ``notFound:*``, all of them and again without
    the title pages' - and, beside it, the rows the import did not find: how many of those judged hold a
    wording that is there after all (``missed``)."""
    found = [item for item in items if not item.stratum.startswith(NOT_FOUND)]
    frame = {stratum: n for stratum, n in sample.frame.items() if not stratum.startswith(NOT_FOUND)}
    inside = [item for item in found if not item.stratum.startswith(FRONT)]
    without = _verdicts(
        {stratum: n for stratum, n in frame.items() if not stratum.startswith(FRONT)},
        inside,
        judgements,
        ANCHOR_REASONS,
    )
    lost = [judgements[i.id].verdict for i in items if i.stratum.startswith(NOT_FOUND) and i.id in judgements]
    judged = sum(1 for verdict in lost if verdict is not None)
    missed = lost.count("wrong")
    return {
        "sample": sample.id,
        "title_pages": sample.title_pages,
        **_verdicts(frame, found, judgements, ANCHOR_REASONS),
        "without_front": {key: without[key] for key in ("judged", "open", "weighted", "pooled")},
        "not_found": {
            "judged": judged,
            "missed": missed,
            "missed_rate": _rate(missed / judged) if judged else None,
        },
    }


async def _blocks(
    connection: psycopg.AsyncConnection,
    sample: Sample,
    items: Sequence[Item],
    judgements: Mapping[int, Judgement],
) -> Section:
    counted = {item.block_id: judgements[item.id].expected for item in items if item.id in judgements}
    expected = {block: count for block, count in counted.items() if block is not None and count is not None}
    found = await found_in_blocks(connection, sample.document_id, expected)
    made = recall([(count, found.get(block, 0)) for block, count in expected.items()])
    return {
        "sample": sample.id, "title_pages": sample.title_pages, "judged": len(expected),
        "open": len(items) - len(expected), "expected": made.expected, "found": made.found,
        "recall": _rate(made.recall), "missed_blocks": made.missed_blocks,
        "surplus_blocks": made.surplus_blocks, "surplus": made.surplus,
    }  # fmt: skip


async def _entry(connection: psycopg.AsyncConnection, samples: Sequence[Sample]) -> Section:
    head = await head_of(connection, samples[0].document_id)
    entry: Section = {
        "label": _token(samples[0].label),
        "source_kind": "mem_import" if "IM" in head.runs else "extraction",
        "regions": [_token(region) for region in head.regions],
        "sector": _token(head.sector),
        "pages": head.pages,
        "runs": {
            stage: {
                "model": _token(run.model),
                "prompt": _token(run.prompt),
                "lexicon_release": run.lexicon_release,
            }
            for stage, run in sorted(head.runs.items())
            if _token(stage)
        },
        "samples": [
            {"id": s.id, "kind": s.kind, "label": _token(s.label), "seed": _token(s.seed)} for s in samples
        ],
    }
    for sample in samples:
        items = await items_of(connection, sample.id)
        judgements = await judgements_of(connection, sample.id)
        if sample.kind == "block":
            section = await _blocks(connection, sample, items, judgements)
        elif sample.kind == "anchor":
            section = _anchors(sample, items, judgements)
        else:
            section = {"sample": sample.id} | _verdicts(sample.frame, items, judgements, STATEMENT_REASONS)
        # the accounts whose judgements are counted - each item's latest, whoever gave it
        entry[sample.kind] = section | {"judges": await judges_of(connection, sample.id)}
    return entry


def closed(value: object) -> None:
    """ValueError where a key or leaf is other than a number, a truth value, null or a code of LEAF."""
    if isinstance(value, dict):
        for key, inner in value.items():
            closed(key)
            closed(inner)
    elif isinstance(value, list):
        for inner in value:
            closed(inner)
    elif not (value is None or isinstance(value, bool | int | float) or _token(value) is not None):
        raise ValueError("a report holds counts, rates and codes alone")


async def report(connection: psycopg.AsyncConnection, sample_ids: Sequence[int]) -> dict[str, Any]:
    """The entries of the samples' documents, in the order first named; Refused where a sample is not
    there, or two samples of one kind name one document."""
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
        made = {"documents": [await _entry(connection, samples) for samples in by_document.values()]}
    except LookupError:  # its document taken away meanwhile, its samples with it
        raise Refused("unknown_sample", "a sample went with its document") from None
    try:
        closed(made)
    except ValueError:  # a stratum's name longer than a leaf, say
        raise Refused("report_not_closed", "a key or leaf is no count, rate or code") from None
    return made


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.quality.report", description=__doc__.splitlines()[0])
    parser.add_argument("--sample", required=True, type=int, action="append")
    return parser


async def _report(settings: Settings, sample_ids: Sequence[int]) -> dict[str, Any]:
    url = settings.database_url.get_secret_value()
    async with await psycopg.AsyncConnection.connect(
        url, autocommit=True, **CONNECTION_OPTIONS
    ) as connection:
        return await report(connection, sample_ids)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))  # a call amiss exits with 2
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        made = asyncio.run(_report(settings, args.sample), loop_factory=asyncio.SelectorEventLoop)
    except Refused as refused:
        log.error("%s", refused)
        return 1
    sys.stdout.buffer.write((json.dumps(made, indent=1) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
