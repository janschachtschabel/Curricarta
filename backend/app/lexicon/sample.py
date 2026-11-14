"""The sample of the research cues the editors check (plan M1 10.3): a tenth of each stratum - a sector
and the regions a cue holds in -, rounded up, so at least one. Within a stratum the cues stand in the order
a fixed seed gives their IRIs, so a cue's place depends on its IRI alone: the same cues give the same
sample, whatever their order and whatever the other strata hold, and a cue leaves the sample only when its
stratum shrinks or a cue ahead of it comes in."""

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable
from typing import Protocol

SEED = "curricarta-m1-10c"  # another seed is another sample, and the editors' decisions refer to this one
SHARE = 10  # one cue in ten

type Stratum = tuple[str, tuple[str, ...]]  # a sector, and the regions in their order


class Sampled(Protocol):
    @property
    def iri(self) -> str: ...

    @property
    def stratum(self) -> Stratum: ...


def sample[S: Sampled](cues: Iterable[S]) -> list[S]:
    """The sample of `cues`, stratum by stratum in their order, each in the seed's order."""
    strata: dict[Stratum, list[S]] = defaultdict(list)
    for cue in cues:
        strata[cue.stratum].append(cue)
    picked: list[S] = []
    for stratum in sorted(strata):
        held = sorted(strata[stratum], key=lambda cue: _place(cue.iri))
        picked += held[: math.ceil(len(held) / SHARE)]
    return picked


def _place(iri: str) -> str:
    return hashlib.sha256(f"{SEED}\n{iri}".encode()).hexdigest()
