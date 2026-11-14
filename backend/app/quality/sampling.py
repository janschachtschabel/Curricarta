"""The stratified sample of the gold standard (plan H-3 §3.2), seeded as the lexicon's is
(app/lexicon/sample.py): every stratum that holds items gets its least - all it has, where it holds fewer -,
and the rest of the size goes to the strata by their share, the largest remainders first, never more than
a stratum holds. Within a stratum the items stand in the order the seed gives their keys, so an item's place
depends on its key alone: the same items give the same sample, whatever their order, and what one stratum
holds changes nothing of which items another gives. Two items of one key stand in the order they came."""

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from fractions import Fraction


def place(seed: str, key: str) -> str:
    """Where the seed puts the key: the SHA-256 of both, one line each."""
    return hashlib.sha256(f"{seed}\n{key}".encode()).hexdigest()


def allotted(frame: Mapping[str, int], size: int, *, least: int = 2) -> dict[str, int]:
    """How many items each stratum of ``frame`` (its population by stratum) gives, the strata in their
    order; an empty stratum gives none. Their leasts may together exceed ``size``."""
    given = {stratum: min(least, held) for stratum, held in sorted(frame.items()) if held > 0}
    rest = size - sum(given.values())
    while rest > 0:
        room = {stratum: frame[stratum] - count for stratum, count in given.items() if count < frame[stratum]}
        if not room:
            break  # everyone taken
        total = sum(frame[stratum] for stratum in room)
        shares = {stratum: Fraction(rest * frame[stratum], total) for stratum in room}
        added = {stratum: min(int(shares[stratum]), room[stratum]) for stratum in room}
        left = rest - sum(added.values())
        for stratum in sorted(room, key=lambda each: (-(shares[each] % 1), each)):
            if left == 0:
                break
            if added[stratum] < room[stratum]:
                added[stratum] += 1
                left -= 1
        for stratum, count in added.items():
            given[stratum] += count
        rest -= sum(added.values())  # what a full stratum could not take goes round again
    return given


def drawn[T](
    items: Iterable[T],
    *,
    seed: str,
    size: int,
    stratum: Callable[[T], str],
    key: Callable[[T], str],
    least: int = 2,
) -> list[T]:
    """The sample of ``items``: stratum by stratum in their order, each the first of the seed's order."""
    strata: dict[str, list[T]] = defaultdict(list)
    for item in items:
        strata[stratum(item)].append(item)
    counts = allotted({name: len(held) for name, held in strata.items()}, size, least=least)
    picked: list[T] = []
    for name, count in counts.items():
        picked += sorted(strata[name], key=lambda item: place(seed, key(item)))[:count]
    return picked
