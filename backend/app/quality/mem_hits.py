"""The anchor search's hit rate of a MEM import (plan M2, E15; plan H-3 §1.2), from its run's result
(app/sources/mem/import_job.py): the rows found ``exact``, ``whitespace``, ``elided`` or ``normalized`` over
the rows searched - ``fuzzy``, ``notFound`` and the rows past the search's time (``unsearched``) apart -, for
nodes' titles and statements and both together, once over all rows and once without the title pages.

The rows found on the title pages are those the import counted apart (``front``), by the function the
import and the anchor sample share (app/pipeline/toc.py ``title_page_blocks``). Where the import found no
contents, ``front`` is null: no title pages are known, ``title_pages`` says ``unknown`` and the figure
without them is null - never the one over all rows under its name.

The strata are the anchor sample's (app/quality/populations.py): ``<kind>:node`` and ``<kind>:statement``,
a row on the title pages under ``front:node`` or ``front:statement`` instead, empty ones left out - so that
the automatic figure stands beside the human one stratum by stratum. Where the two still differ by
construction:

- the kind here is the search's stage; the sample's is the match kind X5 reckoned on the anchor after it;
- the rows past the search's time are ``unsearched`` here and ``notFound`` in the sample;
- the title pages here are those the import found; the sample's those found when it was drawn, by the
  document's cues then;
- the run's result stays as the import left it; the sample draws the rows still as imported - a row an
  editor reworded, or a statement rejected, since is out of it."""

from collections.abc import Mapping
from typing import Any

HIT = ("exact", "whitespace", "elided", "normalized")  # E15: found as the plan words it
KINDS = ("node", "statement")
FRONT = "front"  # the strata of the title pages, before node or statement
_DIGITS = 4

Counts = Mapping[str, Mapping[str, int]]  # by node and statement: by stage


def _measure(counted: Mapping[str, int]) -> dict[str, Any]:
    rows = sum(counted.values())
    unsearched = counted.get("unsearched", 0)
    hit = sum(counted.get(stage, 0) for stage in HIT)
    searched = rows - unsearched
    return {
        "rows": rows,
        "searched": searched,
        "hit": hit,
        "fuzzy": counted.get("fuzzy", 0),
        "not_found": counted.get("notFound", 0),
        "unsearched": unsearched,
        "hit_rate": round(hit / searched, _DIGITS) if searched else None,
    }


def _measures(stages: Counts) -> dict[str, Any]:
    made = {kind: _measure(stages.get(kind, {})) for kind in KINDS}
    pooled: dict[str, int] = {}
    for kind in KINDS:
        for stage, count in stages.get(kind, {}).items():
            pooled[stage] = pooled.get(stage, 0) + count
    return made | {"rows": _measure(pooled)}


def _without(stages: Counts, front: Counts) -> dict[str, dict[str, int]]:
    return {
        kind: {
            stage: count - front.get(kind, {}).get(stage, 0) for stage, count in stages.get(kind, {}).items()
        }
        for kind in KINDS
    }


def hits(result: Mapping[str, Any]) -> dict[str, Any]:
    """The hit rates of an import run's ``result`` (its ``stages`` and ``front``), and its rows by stratum."""
    stages: Counts = result.get("stages") or {}
    front: Counts | None = result.get("front")
    inside = _without(stages, front or {})
    strata: dict[str, int] = {}
    for kind in KINDS:
        for stage, count in inside[kind].items():
            strata[f"{stage}:{kind}"] = count
        if front is not None:
            strata[f"{FRONT}:{kind}"] = sum(front.get(kind, {}).values())
    return {
        "title_pages": "unknown" if front is None else "set_apart",
        "strata": {stratum: count for stratum, count in strata.items() if count},
        "all": _measures(stages),
        "without_front": None if front is None else _measures(inside),
    }
