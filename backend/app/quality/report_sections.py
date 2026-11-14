"""The gold report's sections (plan H-3 §3.4; app/quality/report.py says what each holds): a statement's or
an anchor's verdicts over the strata of the frame kept when drawn, an anchor sample's found anchors and its
rows not found, a block sample's recall - counts and rates alone."""

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

from app.db.gold import Item, Judgement, Sample
from app.db.gold_report import found_in_blocks
from app.quality.rates import recall, weighted, wilson

STATEMENT_REASONS = ("not_a_statement", "not_in_document", "node", "boundary", "kind", "fields")
ANCHOR_REASONS = ("boundary", "wrong_place")  # of a found anchor; "missed" is not_found's
FRONT = "front:"  # the strata of the title pages' anchors
NOT_FOUND = "notFound:"
_DIGITS = 4

Section = dict[str, Any]


def rate(value: float | None) -> float | None:
    return None if value is None else round(value, _DIGITS)


def verdicts(
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
        weighing[name] = rate(weighted({s: frame.get(s, 0) for s in strata}, hits)) if not still else None
        total = sum(hit for hit, _ in hits.values())
        pooled[name] = rate(total / judged) if judged else None
        interval = [rate(end) for end in wilson(total, judged)] if judged else None
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


def anchors(sample: Sample, items: Sequence[Item], judgements: Mapping[int, Judgement]) -> Section:
    """The found anchors' precision - over the strata not ``notFound:*``, all of them and again without
    the title pages' - and, beside it, the rows the import did not find: how many of those judged hold a
    wording that is there after all (``missed``)."""
    found = [item for item in items if not item.stratum.startswith(NOT_FOUND)]
    frame = {stratum: n for stratum, n in sample.frame.items() if not stratum.startswith(NOT_FOUND)}
    inside = [item for item in found if not item.stratum.startswith(FRONT)]
    without = verdicts(
        {stratum: n for stratum, n in frame.items() if not stratum.startswith(FRONT)},
        inside,
        judgements,
        ANCHOR_REASONS,
    )
    unfound = [item for item in items if item.stratum.startswith(NOT_FOUND)]
    lost = [judgements[item.id].verdict for item in unfound if item.id in judgements]
    judged = sum(1 for verdict in lost if verdict is not None)
    missed = lost.count("wrong")
    population = sum(n for stratum, n in sample.frame.items() if stratum.startswith(NOT_FOUND))
    return {
        "sample": sample.id,
        "title_pages": sample.title_pages,
        **verdicts(frame, found, judgements, ANCHOR_REASONS),
        "without_front": {key: without[key] for key in ("judged", "open", "weighted", "pooled")},
        "not_found": {
            "frame": population,
            "drawn": len(unfound),
            "judged": judged,
            "open": len(unfound) - judged,
            "missed": missed,
            "missed_rate": rate(missed / judged) if judged else None,
        },
    }


async def blocks(
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
        "recall": rate(made.recall), "missed_blocks": made.missed_blocks,
        "surplus_blocks": made.surplus_blocks, "surplus": made.surplus,
    }  # fmt: skip
