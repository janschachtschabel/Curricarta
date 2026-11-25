"""The rows a set of a holder's values asks for (plan M3a D2, H1; app/db/values.py writes them): each draft
as the row it keeps - named by its ``id``, one of the holder's of its kind and place - or a new one, a
workload's periods and a context's time spans and levels under their outer row. A draft naming a row that is
none of those, or one named twice, refuses the set (UnknownValue); a kind the holder has no column for is
``not_held`` (ValueRefused)."""

from dataclasses import dataclass
from typing import Any, LiteralString
from uuid import UUID

from app.db.value_rows import (
    HOLDERS_OF,
    NESTED,
    context_content,
    level_content,
    time_content,
    workload_content,
)
from app.domain.l2 import ValueDrafts, ValueRefused

# A row as it stands: its holder's column and row, its position, what it says
Standing = tuple[tuple[str, UUID], int, dict[str, Any]]
# A value held under a workload or a context, as a set has it: its table, the id it keeps, what it says
Inner = tuple[LiteralString, UUID | None, dict[str, Any]]


class UnknownValue(Exception):
    """A draft names by id a row that is no value of its kind at its place in the set."""

    def __init__(self, value_id: UUID) -> None:
        super().__init__(f"{value_id} is no value of its kind at this holder")
        self.value_id = value_id


@dataclass(frozen=True)
class Planned:
    """A value as the set has it: where it stands (``table``, its holder's column and row, its position)
    and what it says; ``id`` its kept row's, None for a new one - a new workload with the contents of its
    periods, a new context with those of its time spans and levels, which stand under it once it is written
    (``inner``: each one's table, position and content)."""

    table: LiteralString
    id: UUID | None
    holder: tuple[LiteralString, UUID]
    position: int
    content: dict[str, Any]
    inner: tuple[tuple[LiteralString, int, dict[str, Any]], ...] = ()


def planned(
    drafts: ValueDrafts, holder: tuple[LiteralString, UUID], current: dict[UUID, Standing]
) -> list[Planned]:
    """The rows the set asks for. UnknownValue where a draft's id is none of ``current`` of its kind and
    place, or is named twice; ValueRefused where the holder has no column for a kind of them."""
    planned: list[Planned] = []
    if holder[0] not in HOLDERS_OF["workload"] and (drafts.time_spans or drafts.workloads):
        raise ValueRefused("not_held")
    if holder[0] not in HOLDERS_OF["applicability_context"] and drafts.contexts:
        raise ValueRefused("not_held")

    def row(table: LiteralString, value_id: UUID | None, at: tuple[LiteralString, UUID], place: int,
            content: dict[str, Any]) -> Planned:  # fmt: skip
        if value_id is not None and (
            value_id not in current
            or current[value_id][0] != at
            or current[value_id][2].keys() != content.keys()  # another kind's row
            or any(each.id == value_id for each in planned)
        ):
            raise UnknownValue(value_id)
        return Planned(table, value_id, at, place, content)

    def nested(
        outer: tuple[LiteralString, UUID | None, int, dict[str, Any]], inner: list[Inner]
    ) -> list[Planned]:
        """A workload with its periods, a context with its values: each inner one kept under the kept outer
        row, or new with a new one, under which it is written; positions count by kind."""
        table, outer_id, place, content = outer
        counted: dict[str, int] = {}
        placed = []
        for kind, inner_id, inner_content in inner:
            counted[kind] = counted.get(kind, 0) + 1
            placed.append((kind, inner_id, counted[kind], inner_content))
        if outer_id is None:  # what it holds is new as it is
            if (named := next((each[1] for each in placed if each[1] is not None), None)) is not None:
                raise UnknownValue(named)
            return [Planned(table, None, holder, place, content, tuple((k, at, c) for k, _, at, c in placed))]
        column = NESTED[table][0]
        return [row(table, outer_id, holder, place, content)] + [
            row(kind, inner_id, (column, outer_id), at, inner_content)
            for kind, inner_id, at, inner_content in placed
        ]

    for place, level in enumerate(drafts.levels, 1):
        planned.append(row("level_assignment", level.id, holder, place, level_content(level)))
    for place, span in enumerate(drafts.time_spans, 1):
        planned.append(row("time_span", span.id, holder, place, time_content(span)))
    for place, workload in enumerate(drafts.workloads, 1):
        periods: list[Inner] = [("time_span", period.id, time_content(period)) for period in workload.periods]
        planned += nested(("workload", workload.id, place, workload_content(workload)), periods)
    for place, context in enumerate(drafts.contexts, 1):
        held: list[Inner] = [("level_assignment", level.id, level_content(level)) for level in context.levels]
        held += [("time_span", span.id, time_content(span)) for span in context.time_spans]
        planned += nested(("applicability_context", context.id, place, context_content(context)), held)
    return planned
