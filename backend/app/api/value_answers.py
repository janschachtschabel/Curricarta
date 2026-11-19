"""A holder's values as the tree answers them (plan M3a E2; app/domain/l2.py): its levels, time spans and
workloads, each kind in order, a workload with its periods - each value with its id, the fields of its
kind by the keys of the values' form (GET /profiles/{sector}/form, ``values``), its origin, review status
and revision. A number is answered as a JSON number."""

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, PlainSerializer

from app.domain.l2 import HeldValues, Level, Stated, TimeSpan, Workload

Number = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class StatedOut(BaseModel):
    id: UUID  # names the value in a set that keeps it (PUT …/values) and in a review
    origin: str
    review_status: str
    revision: int  # the value's own, as a review names it


class LevelOut(StatedOut):
    level: str
    level_to: str | None  # a range's end
    relation: str | None
    dimension: str | None
    competence_dimension: str | None


class TimeSpanOut(StatedOut):
    time_kind: str
    span_from: Number | None
    span_to: Number | None
    time_relation: str | None


class WorkloadOut(StatedOut):
    amount: Number
    amount_to: Number | None
    unit: str
    workload_kind: str | None
    is_recommendation: bool
    minutes_per_unit: int | None
    total: bool  # the holder's whole
    periods: list[TimeSpanOut]  # the time spans it is given in, in order


class ValuesOut(BaseModel):
    level_assignments: list[LevelOut]
    time_spans: list[TimeSpanOut]
    workloads: list[WorkloadOut]


def values_out(held: HeldValues) -> ValuesOut:
    return ValuesOut(
        level_assignments=[_level(level) for level in held.levels],
        time_spans=[_time_span(span) for span in held.time_spans],
        workloads=[_workload(workload) for workload in held.workloads],
    )


def _stated(value_id: UUID | None, stated: Stated) -> dict[str, Any]:
    return {
        "id": value_id,
        "origin": stated.origin,
        "review_status": stated.review_status,
        "revision": stated.revision,
    }


def _level(level: Level) -> LevelOut:
    value = level.value
    return LevelOut(
        **_stated(value.id, level.stated),
        level=value.level,
        level_to=value.level_to,
        relation=value.relation,
        dimension=value.dimension,
        competence_dimension=value.competence_dimension,
    )


def _time_span(span: TimeSpan) -> TimeSpanOut:
    value = span.value
    return TimeSpanOut(
        **_stated(value.id, span.stated),
        time_kind=value.time_kind,
        span_from=value.span_from,
        span_to=value.span_to,
        time_relation=value.time_relation,
    )


def _workload(workload: Workload) -> WorkloadOut:
    value = workload.value
    return WorkloadOut(
        **_stated(value.id, workload.stated),
        amount=value.amount,
        amount_to=value.amount_to,
        unit=value.unit,
        workload_kind=value.workload_kind,
        is_recommendation=value.is_recommendation,
        minutes_per_unit=value.minutes_per_unit,
        total=value.total,
        periods=[_time_span(period) for period in workload.periods],
    )
