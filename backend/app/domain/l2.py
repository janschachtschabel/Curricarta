"""The second layer's values at a holder of the first, as the editor hands them to the store and the store
gives them back (plan M3a D2): levels (cur:LevelAssignment), time spans (cur:TimeSpan) and workloads
(cur:Workload), each a holder's set of its kind in order. A draft with an ``id`` is that row of the holder,
kept; one without is a new row. A workload's periods (cur:inPeriod) are time spans of the workload alone,
replaced with it. Values are IRIs and numbers: which concepts the vocabularies hold, whether a level is a
level, and the order of the numbers the store checks (migration l2_values).

A level at a rule's frame part has its column already; it is written with the rules (plan M3a I).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

HolderKind = Literal["node", "statement", "specification"]


@dataclass(frozen=True)
class Holder:
    """The row a set of values is written at: a node, a statement or a specification of a document."""

    kind: HolderKind
    id: UUID


@dataclass(frozen=True)
class LevelDraft:
    level: str
    level_to: str | None = None  # a range's end
    relation: str | None = None  # cv:LevelRelations
    dimension: str | None = None  # cv:LevelDimensions, where not the level system's own
    competence_dimension: str | None = None
    id: UUID | None = None


@dataclass(frozen=True)
class TimeSpanDraft:
    time_kind: str  # cv:TimeKinds
    span_from: Decimal | None = None
    span_to: Decimal | None = None
    time_relation: str | None = None  # cv:TimeRelations
    id: UUID | None = None


@dataclass(frozen=True)
class WorkloadDraft:
    amount: Decimal
    unit: str  # cv:WorkloadUnits
    amount_to: Decimal | None = None
    workload_kind: str | None = None  # cv:WorkloadKinds
    is_recommendation: bool = False
    minutes_per_unit: int | None = None
    total: bool = False  # the holder's whole (cur:totalWorkload)
    periods: tuple[TimeSpanDraft, ...] = ()
    id: UUID | None = None


@dataclass(frozen=True)
class ValueDrafts:
    """A holder's values, every kind of them: what a set leaves out goes."""

    levels: tuple[LevelDraft, ...] = ()
    time_spans: tuple[TimeSpanDraft, ...] = ()
    workloads: tuple[WorkloadDraft, ...] = ()


@dataclass(frozen=True)
class Stated:
    """Where a stored value came from, how far it is reviewed, and its revision."""

    origin: str
    review_status: str
    rule_id: str | None
    revision: int


@dataclass(frozen=True)
class Level:
    value: LevelDraft  # with its id
    stated: Stated


@dataclass(frozen=True)
class TimeSpan:
    value: TimeSpanDraft
    stated: Stated


@dataclass(frozen=True)
class Workload:
    value: WorkloadDraft  # its periods empty: they stand in ``periods``
    stated: Stated
    periods: tuple[TimeSpan, ...] = ()


@dataclass(frozen=True)
class HeldValues:
    """A holder's stored values, each kind in order."""

    levels: tuple[Level, ...] = ()
    time_spans: tuple[TimeSpan, ...] = ()
    workloads: tuple[Workload, ...] = ()


Values = Mapping[Holder, HeldValues]
