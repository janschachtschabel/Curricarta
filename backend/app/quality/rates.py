"""The gold standard's arithmetic (plan H-3 §3.4), pure: a rate weighted by each stratum's share of the
population when drawn, the Wilson interval of a pooled rate, recall over the judged blocks, and what a
replay would keep and lose of the judgements. A rate that cannot be said is None, never 0."""

import math
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

Z95 = 1.959963984540054  # the standard normal's 97.5th percentile: a two-sided 95 % interval
VERDICTS = ("correct", "imprecise", "wrong")

Key = tuple[str, str | None]  # a statement's wording hash and first block: what a judgement follows


def weighted(frame: Mapping[str, int], counts: Mapping[str, tuple[int, int]]) -> float | None:
    """Σ (N_s / N) · (hits_s / judged_s) over the strata of ``frame`` (N_s, the population of each when
    drawn); ``counts`` gives (hits, judged) by stratum. None where a stratum of the frame with a population
    has no judged item - its share cannot be said - or the frame is empty."""
    total = sum(frame.values())
    if total == 0:
        return None
    rate = 0.0
    for stratum, population in frame.items():
        if population == 0:
            continue
        hits, judged = counts.get(stratum, (0, 0))
        if judged == 0:
            return None
        rate += population / total * hits / judged
    return rate


def wilson(hits: int, n: int) -> tuple[float, float]:
    """The Wilson score interval, 95 %, of ``hits`` in ``n``; ValueError where nothing was judged."""
    if n < 1:
        raise ValueError("an interval needs one judged item at least")
    if not 0 <= hits <= n:
        raise ValueError("the hits lie between 0 and the judged")
    p = hits / n
    z2 = Z95 * Z95
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class Recall:
    expected: int  # Σ the statements the judge counted in the blocks
    found: int  # Σ min(found, expected): no block finds more than it holds
    recall: float | None  # found / expected; None where nothing is expected
    missed_blocks: int  # expected > 0, none found
    surplus_blocks: int  # expected 0, some found: counted apart
    surplus: int  # Σ max(found - expected, 0)


def recall(rows: Sequence[tuple[int, int]]) -> Recall:
    """Recall over judged blocks, each (expected, found)."""
    expected = sum(e for e, _ in rows)
    found = sum(min(f, e) for e, f in rows)
    return Recall(
        expected=expected,
        found=found,
        recall=found / expected if expected else None,
        missed_blocks=sum(1 for e, f in rows if e > 0 and f == 0),
        surplus_blocks=sum(1 for e, f in rows if e == 0 and f > 0),
        surplus=sum(max(f - e, 0) for e, f in rows),
    )


def replayed(
    judged: Sequence[tuple[Key, str]], *, stored: Collection[Key], read_now: Collection[Key]
) -> dict[str, int]:
    """What today's reader, read over the run's answers again, would do with the judged statements: keep
    one whose wording it reads at the same first block (whatever row it becomes), lose the rest - by
    verdict; and how many it reads that the stored statements do not hold, which nobody judged.

    A judgement follows its key, not a row: two judged items of one key are both kept where the reader
    reads that key once - they are the same wording at the same place. The statements are counted as
    many as there are: each one read beyond those of its key stored is new (the population grows by it)."""
    now, before = Counter(read_now), Counter(stored)
    effect = {f"{fate}_{verdict}": 0 for fate in ("kept", "gone") for verdict in VERDICTS}
    for key, verdict in judged:
        effect[f"{'kept' if key in now else 'gone'}_{verdict}"] += 1
    return effect | {"new_unjudged": (now - before).total()}
