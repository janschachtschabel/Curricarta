"""The second layer's values as rows (plan M3a D2; migration l2_values): which columns each table holds,
a draft's content as the columns take it, a row read back as a draft - and the document's values read by
holder (``values_of``), which app/db/values.py sets."""

from collections import defaultdict
from typing import Any, Final, LiteralString
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.domain.l2 import (
    HeldValues,
    Holder,
    HolderKind,
    Level,
    LevelDraft,
    Stated,
    TimeSpan,
    TimeSpanDraft,
    Values,
    Workload,
    WorkloadDraft,
)

CV = "https://w3id.org/wlo/curriculum/vocab#"
COLUMN_OF: Final[dict[HolderKind, LiteralString]] = {
    "node": "node_id",
    "statement": "statement_id",
    "specification": "specification_id",
}
TABLES: Final[tuple[LiteralString, ...]] = ("level_assignment", "time_span", "workload")
# Each table's content columns: what a set writes and compares, beside holder and position
CONTENT: Final[dict[str, tuple[LiteralString, ...]]] = {
    "level_assignment": (
        "level_iri", "level_to_iri", "relation_scheme", "relation_iri", "dimension_scheme", "dimension_iri",
        "competence_dimension_iri",
    ),
    "time_span": (
        "time_kind_scheme", "time_kind_iri", "span_from", "span_to", "time_relation_scheme",
        "time_relation_iri",
    ),
    "workload": (
        "amount", "amount_to", "unit_scheme", "unit_iri", "workload_kind_scheme", "workload_kind_iri",
        "is_recommendation", "minutes_per_unit", "total",
    ),
}  # fmt: skip
# the holders' columns each table has: a level's at a frame part and a time span's at a workload read too
HOLDERS_OF: Final[dict[str, tuple[LiteralString, ...]]] = {
    "level_assignment": ("node_id", "statement_id", "specification_id", "frame_part_id"),
    "time_span": ("node_id", "specification_id", "workload_id"),
    "workload": ("node_id", "specification_id"),
}
_STATED: Final = sql.SQL("origin_iri, review_status_iri, rule_id, revision")


async def values_of(connection: psycopg.AsyncConnection, document_id: UUID) -> Values:
    """The document's values by holder, each kind in order: one query a kind. A level at a rule's frame part
    is the rules' (plan M3a I) and not among them."""
    rows = {
        table: await read_rows(connection, table, sql.SQL("document_id = %s"), document_id)
        for table in TABLES
    }
    levels: defaultdict[Holder, list[Level]] = defaultdict(list)
    spans: defaultdict[Holder, list[TimeSpan]] = defaultdict(list)
    periods: defaultdict[UUID, list[TimeSpan]] = defaultdict(list)
    workloads: defaultdict[Holder, list[Workload]] = defaultdict(list)
    for row in rows["level_assignment"]:
        if (holder := holder_of(row)) is not None:
            levels[holder].append(Level(level_of(row), stated_of(row)))
    for row in rows["time_span"]:
        span = TimeSpan(time_span_of(row), stated_of(row))
        if row["workload_id"] is not None:
            periods[row["workload_id"]].append(span)
        elif (holder := holder_of(row)) is not None:
            spans[holder].append(span)
    for row in rows["workload"]:
        if (holder := holder_of(row)) is not None:
            workloads[holder].append(Workload(workload_of(row), stated_of(row), tuple(periods[row["id"]])))
    return {
        holder: HeldValues(tuple(levels[holder]), tuple(spans[holder]), tuple(workloads[holder]))
        for holder in {*levels, *spans, *workloads}
    }


async def read_rows(
    connection: psycopg.AsyncConnection, table: str, where: sql.Composable, value: Any, *, lock: bool = False
) -> list[dict[str, Any]]:
    """The rows of ``table`` ``where`` says of ``value``, in order: ids, holders, content, statement."""
    columns = ("id", "position", *HOLDERS_OF[table], *CONTENT[table])
    query = sql.SQL("SELECT {}, {} FROM {} WHERE {} ORDER BY position, id{}").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        _STATED,
        sql.Identifier(table),
        where,
        sql.SQL(" FOR UPDATE") if lock else sql.SQL(""),
    )
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(query, (value,))
        return await cursor.fetchall()


def row_content(table: str, row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in CONTENT[table]}


def holder_of(row: dict[str, Any]) -> Holder | None:
    """The holder of a stored row; None for one at a rule's frame part or a workload (a period)."""
    for kind, column in COLUMN_OF.items():
        if row.get(column) is not None:
            return Holder(kind, row[column])
    return None


def stated_of(row: dict[str, Any]) -> Stated:
    return Stated(row["origin_iri"], row["review_status_iri"], row["rule_id"], row["revision"])


def _scheme(scheme: str, value: str | None) -> str | None:
    """The scheme column of an optional concept: set where the concept is."""
    return None if value is None else CV + scheme


def level_content(draft: LevelDraft) -> dict[str, Any]:
    return {
        "level_iri": draft.level, "level_to_iri": draft.level_to,
        "relation_scheme": _scheme("LevelRelations", draft.relation), "relation_iri": draft.relation,
        "dimension_scheme": _scheme("LevelDimensions", draft.dimension), "dimension_iri": draft.dimension,
        "competence_dimension_iri": draft.competence_dimension,
    }  # fmt: skip


def time_content(draft: TimeSpanDraft) -> dict[str, Any]:
    return {
        "time_kind_scheme": CV + "TimeKinds", "time_kind_iri": draft.time_kind,
        "span_from": draft.span_from, "span_to": draft.span_to,
        "time_relation_scheme": _scheme("TimeRelations", draft.time_relation),
        "time_relation_iri": draft.time_relation,
    }  # fmt: skip


def workload_content(draft: WorkloadDraft) -> dict[str, Any]:
    return {
        "amount": draft.amount, "amount_to": draft.amount_to,
        "unit_scheme": CV + "WorkloadUnits", "unit_iri": draft.unit,
        "workload_kind_scheme": _scheme("WorkloadKinds", draft.workload_kind),
        "workload_kind_iri": draft.workload_kind, "is_recommendation": draft.is_recommendation,
        "minutes_per_unit": draft.minutes_per_unit, "total": draft.total,
    }  # fmt: skip


def level_of(row: dict[str, Any]) -> LevelDraft:
    return LevelDraft(
        level=row["level_iri"], level_to=row["level_to_iri"], relation=row["relation_iri"],
        dimension=row["dimension_iri"], competence_dimension=row["competence_dimension_iri"], id=row["id"],
    )  # fmt: skip


def time_span_of(row: dict[str, Any]) -> TimeSpanDraft:
    return TimeSpanDraft(
        time_kind=row["time_kind_iri"], span_from=row["span_from"], span_to=row["span_to"],
        time_relation=row["time_relation_iri"], id=row["id"],
    )  # fmt: skip


def workload_of(row: dict[str, Any]) -> WorkloadDraft:
    return WorkloadDraft(
        amount=row["amount"], unit=row["unit_iri"], amount_to=row["amount_to"],
        workload_kind=row["workload_kind_iri"], is_recommendation=row["is_recommendation"],
        minutes_per_unit=row["minutes_per_unit"], total=row["total"], id=row["id"],
    )  # fmt: skip
