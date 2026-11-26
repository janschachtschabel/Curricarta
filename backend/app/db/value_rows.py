"""The second layer's values as rows (plan M3a D2; migrations l2_values, applicability): which columns each
table holds, a draft's content as the columns take it, a row read back as a draft - and the document's
values read by holder (``values_of``), which app/db/values.py sets. A specification's applicability contexts
are read with its values, each with the time spans and levels it holds (plan M3a H1)."""

from collections import defaultdict
from typing import Any, Final, LiteralString
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.domain.l2 import (
    Context,
    ContextDraft,
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
    "assessment": "assessment_id",  # its levels (plan M3a J)
    "placement": "placement_id",  # its time spans and workloads (plan M3a K)
}
TABLES: Final[tuple[LiteralString, ...]] = (
    "level_assignment",
    "time_span",
    "workload",
    "applicability_context",
)
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
    "applicability_context": (
        "sector_scheme", "sector_iri", "formality_scheme", "formality_iri", "institution_text",
        "target_group_text",
    ),
}  # fmt: skip
# the holders' columns each table has: a level's at a frame part, a time span's at a workload and both at an
# applicability context read too
HOLDERS_OF: Final[dict[str, tuple[LiteralString, ...]]] = {
    "level_assignment": (
        "node_id", "statement_id", "specification_id", "frame_part_id", "applicability_context_id",
        "assessment_id",
    ),
    "time_span": ("node_id", "specification_id", "workload_id", "applicability_context_id", "placement_id"),
    "workload": ("node_id", "specification_id", "placement_id"),
    "applicability_context": ("specification_id",),
}  # fmt: skip
# the rows that hold values of their own beside their holder's, by the column those name them by
NESTED: Final[dict[str, tuple[LiteralString, tuple[LiteralString, ...]]]] = {
    "workload": ("workload_id", ("time_span",)),
    "applicability_context": ("applicability_context_id", ("level_assignment", "time_span")),
}
_STATED: Final = sql.SQL("origin_iri, review_status_iri, rule_id, revision")


async def values_of(connection: psycopg.AsyncConnection, document_id: UUID) -> Values:
    """The document's values by holder, each kind in order: one query a kind, all in one snapshot - in a
    read-only transaction of its own; within the caller's, as that one reads (as app/db/tree.py does), so a
    set between two reads never shows a workload without its periods. A level at a rule's frame part is
    the rules' (plan M3a I) and not among them."""
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        return await _values_of(connection, document_id)
    async with connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return await _values_of(connection, document_id)


async def _values_of(connection: psycopg.AsyncConnection, document_id: UUID) -> Values:
    rows = {
        table: await read_rows(connection, table, sql.SQL("document_id = %s"), document_id)
        for table in TABLES
    }
    levels: defaultdict[Holder, list[Level]] = defaultdict(list)
    spans: defaultdict[Holder, list[TimeSpan]] = defaultdict(list)
    periods: defaultdict[UUID, list[TimeSpan]] = defaultdict(list)
    workloads: defaultdict[Holder, list[Workload]] = defaultdict(list)
    contexts: defaultdict[Holder, list[Context]] = defaultdict(list)
    in_context: defaultdict[UUID, list[Level]] = defaultdict(list)
    spans_in_context: defaultdict[UUID, list[TimeSpan]] = defaultdict(list)
    for row in rows["level_assignment"]:
        level = Level(level_of(row), stated_of(row))
        if row["applicability_context_id"] is not None:
            in_context[row["applicability_context_id"]].append(level)
        elif (holder := holder_of(row)) is not None:
            levels[holder].append(level)
    for row in rows["time_span"]:
        span = TimeSpan(time_span_of(row), stated_of(row))
        if row["workload_id"] is not None:
            periods[row["workload_id"]].append(span)
        elif row["applicability_context_id"] is not None:
            spans_in_context[row["applicability_context_id"]].append(span)
        elif (holder := holder_of(row)) is not None:
            spans[holder].append(span)
    for row in rows["workload"]:
        if (holder := holder_of(row)) is not None:
            workloads[holder].append(Workload(workload_of(row), stated_of(row), tuple(periods[row["id"]])))
    for row in rows["applicability_context"]:
        held = (tuple(in_context[row["id"]]), tuple(spans_in_context[row["id"]]))
        contexts[Holder("specification", row["specification_id"])].append(
            Context(context_of(row), stated_of(row), *held)
        )
    return {
        holder: HeldValues(
            tuple(levels[holder]), tuple(spans[holder]), tuple(workloads[holder]), tuple(contexts[holder])
        )
        for holder in {*levels, *spans, *workloads, *contexts}
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


def context_content(draft: ContextDraft) -> dict[str, Any]:
    return {
        "sector_scheme": _scheme("EducationSectors", draft.sector), "sector_iri": draft.sector,
        "formality_scheme": _scheme("Formalities", draft.formality), "formality_iri": draft.formality,
        "institution_text": draft.institution_text, "target_group_text": draft.target_group_text,
    }  # fmt: skip


def context_of(row: dict[str, Any]) -> ContextDraft:
    """A context's row as a draft, without the values it holds."""
    return ContextDraft(
        sector=row["sector_iri"], formality=row["formality_iri"], institution_text=row["institution_text"],
        target_group_text=row["target_group_text"], id=row["id"],
    )  # fmt: skip


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
