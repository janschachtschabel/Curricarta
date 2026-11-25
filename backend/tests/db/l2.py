"""Rows the tests of the second layer's value tables share (migrations l2_values, applicability): the few
concepts they point at, beside those of tests.db.l1, and a level, time span, workload or applicability
context at a holder."""

import uuid
from typing import Any, Literal

import psycopg

from tests.db.l1 import CUR, CV, add_entity, seed_vocabulary

LVL = "https://w3id.org/wlo/curriculum/level/"
FKF = "https://w3id.org/wlo/curriculum/profile/vocational#"
ValueTable = Literal["time_span", "workload", "level_assignment", "applicability_context"]
# scheme -> its concepts: (IRI, types, broader), as tests.db.l1.CONCEPTS
L2_CONCEPTS: dict[str, list[tuple[str, list[str], list[str]]]] = {
    CV + "TimeKinds": [(CV + "time_gradeLevel", [], []), (CV + "time_phase", [], [])],
    CV + "TimeRelations": [(CV + "trel_during", [], [])],
    CV + "WorkloadUnits": [(CV + "unit_lesson", [], [])],
    CV + "WorkloadKinds": [(CV + "wl_guidanceValue", [], [])],
    CV + "LevelRelations": [(CV + "lrel_target", [], [])],
    CV + "LevelDimensions": [(CV + "dim_stage", [], [])],
    LVL + "EQF": [(LVL + "EQF-4", [CUR + "LevelConcept"], []), (LVL + "EQF-5", [CUR + "LevelConcept"], [])],
    FKF + "FKFModel": [(FKF + "fkf-kenntnisse", [CUR + "CompetenceDimension"], [])],
    CV + "Formalities": [(CV + "form_formal", [], []), (CV + "form_nonFormal", [], [])],
}
# What each table asks of a row, beside its holder and its origin
DEFAULTS: dict[ValueTable, dict[str, Any]] = {
    "time_span": {
        "time_kind_scheme": CV + "TimeKinds",
        "time_kind_iri": CV + "time_gradeLevel",
        "span_from": 5,
        "span_to": 6,
    },
    "workload": {
        "amount": 40,
        "amount_to": 50,
        "unit_scheme": CV + "WorkloadUnits",
        "unit_iri": CV + "unit_lesson",
    },
    "level_assignment": {"level_iri": LVL + "EQF-4"},
    "applicability_context": {"sector_scheme": CV + "EducationSectors", "sector_iri": CV + "sec_school"},
}


def seed_l2_vocabulary(connection: psycopg.Connection) -> None:
    """The concepts of tests.db.l1 and those the value tables point at."""
    seed_vocabulary(connection)
    seed_vocabulary(connection, L2_CONCEPTS)


def add_value(
    connection: psycopg.Connection,
    table: ValueTable,
    document: uuid.UUID,
    holder: str,
    holder_id: uuid.UUID | None,
    **columns: Any,
) -> uuid.UUID:
    """A row of ``table`` in the document at its ``holder`` column's row ``holder_id``, an editor's
    proposal, with ``columns`` beside its defaults."""
    made = add_entity(connection, table)
    values = {
        "document_id": document,
        holder: holder_id,
        "position": 1,
        "origin_scheme": CV + "Origins",
        "origin_iri": CV + "orig_human",
        "review_status_scheme": CV + "ReviewStatuses",
        "review_status_iri": CV + "rev_proposed",
        **DEFAULTS[table],
    } | columns
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    connection.execute(
        f"INSERT INTO {table} (id, {names}) VALUES (%s, {marks})",  # noqa: S608 - the tests' own names
        (made, *values.values()),
    )
    return made
