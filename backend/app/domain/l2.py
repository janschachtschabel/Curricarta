"""The second layer's values at a holder of the first, as the editor hands them to the store and the store
gives them back (plan M3a D2): levels (cur:LevelAssignment), time spans (cur:TimeSpan) and workloads
(cur:Workload), each a holder's set of its kind in order. A draft with an ``id`` is that row of the holder,
kept; one without is a new row. A workload's periods (cur:inPeriod) are time spans of the workload alone,
replaced with it. A specification's applicability contexts (cur:ApplicabilityContext, plan M3a H1) are
set with its values: each with a sector, a formality, the institution and the target group as written, and
time spans and levels of its own, replaced with it as a workload's periods are. Values are IRIs and
numbers: which concepts the vocabularies hold, whether a level is a level, and the order of the numbers the
store checks (migrations l2_values, applicability). A number is one, not NaN nor the endless: a draft
refuses those itself (ValueRefused, by the name of the store's check).

A level at a rule's frame part has its column already; it is written with the rules (plan M3a I).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

HolderKind = Literal["node", "statement", "specification"]


class ValueRefused(Exception):
    """The store refuses a value of a set: ``check`` names the constraint it breaks, where it has one;
    ``context`` the place of the applicability context in the set the value is or stands in, where it does."""

    def __init__(self, check: str | None, context: int | None = None) -> None:
        super().__init__(f"a value breaks {check}")
        self.check = check
        self.context = context


def _finite(check: str, number: Decimal | None) -> None:
    """Refuse NaN and the endless, which the store's numeric takes and its orders let pass."""
    if number is not None and not number.is_finite():
        raise ValueRefused(check)


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

    def __post_init__(self) -> None:
        _finite("time_span_span_from_finite", self.span_from)
        _finite("time_span_span_to_finite", self.span_to)


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

    def __post_init__(self) -> None:
        _finite("workload_amount_finite", self.amount)
        _finite("workload_amount_to_finite", self.amount_to)


@dataclass(frozen=True)
class ContextDraft:
    """An applicability context: an AND of what it states (cur:educationSector, cur:formality, the
    institution and the target group as written) and of the time spans and levels it holds."""

    sector: str | None = None  # cv:EducationSectors
    formality: str | None = None  # cv:Formalities
    institution_text: str | None = None
    target_group_text: str | None = None
    levels: tuple[LevelDraft, ...] = ()
    time_spans: tuple[TimeSpanDraft, ...] = ()
    id: UUID | None = None


@dataclass(frozen=True)
class ValueDrafts:
    """A holder's values, every kind of them: what a set leaves out goes."""

    levels: tuple[LevelDraft, ...] = ()
    time_spans: tuple[TimeSpanDraft, ...] = ()
    workloads: tuple[WorkloadDraft, ...] = ()
    contexts: tuple[ContextDraft, ...] = ()  # a specification's alone


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
class Context:
    value: ContextDraft  # its levels and time spans empty: they stand in ``levels`` and ``time_spans``
    stated: Stated
    levels: tuple[Level, ...] = ()
    time_spans: tuple[TimeSpan, ...] = ()


@dataclass(frozen=True)
class HeldValues:
    """A holder's stored values, each kind in order."""

    levels: tuple[Level, ...] = ()
    time_spans: tuple[TimeSpan, ...] = ()
    workloads: tuple[Workload, ...] = ()
    contexts: tuple[Context, ...] = ()  # a specification's


Values = Mapping[Holder, HeldValues]
