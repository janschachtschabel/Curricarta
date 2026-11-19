"""The editor's form of the second layer's values (plan M3a E1; app/domain/l2.py): which kinds of value -
levels, time spans, workloads - a holder is offered, the fields of each, and the active values of their
lists. A field's key is the draft's attribute it sets, and ``path`` the shapes' property it follows, as
in app/vocab/forms.py; tests/vocab/test_forms.py holds each kind no laxer than its shape demands and a
holder offered no kind its shape or the store has no room for (a statement's time span, plan M3a D1).

Levels and competence dimensions come from many level systems and competency models (24 systems in one
list are not to be chosen from): each is offered with its scheme as its group, the groups in the order of
their labels, a group's levels in their rank. A list holds active concepts of active schemes alone, as
the editor's other lists do: a retired one is set no more, though a value keeps it until it is changed
(app/vocab/value_checks.py). A workload's periods are time spans, with the time span's fields.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, Literal

import psycopg

from app.domain.l2 import HolderKind
from app.vocab.forms import FormField
from app.vocab.lookup import ConceptDetails, concept_details

CV = "https://w3id.org/wlo/curriculum/vocab#"
CUR = "https://w3id.org/wlo/curriculum/core#"
ValueKind = Literal["level_assignments", "time_spans", "workloads"]
LEVELS, DIMENSIONS = "levels", "competence_dimensions"  # a class's concepts, grouped by their schemes
_GROUPED: Final = {LEVELS: CUR + "LevelConcept", DIMENSIONS: CUR + "CompetenceDimension"}
# no profile's phases are a vocabulary the profiles share yet: a time span is no named phase (plan M3a D1)
_NOT_OFFERED: Final = frozenset({CV + "time_phase"})

VALUE_FIELDS: Mapping[ValueKind, tuple[FormField, ...]] = {
    "level_assignments": (
        FormField("level", "concept", True, False, values=LEVELS, path="cur:level"),
        FormField("level_to", "concept", False, False, values=LEVELS, path="cur:levelTo"),
        FormField(
            "relation", "concept", False, False, values=CV + "LevelRelations", path="cur:levelRelation"
        ),
        FormField(
            "dimension", "concept", False, False, values=CV + "LevelDimensions", path="cur:levelDimension"
        ),
        FormField(
            "competence_dimension", "concept", False, False, values=DIMENSIONS, path="cur:competenceDimension"
        ),
    ),
    "time_spans": (
        FormField("time_kind", "concept", True, False, values=CV + "TimeKinds", path="cur:timeKind"),
        FormField("span_from", "number", False, False, path="cur:from"),
        FormField("span_to", "number", False, False, path="cur:to"),
        FormField(
            "time_relation", "concept", False, False, values=CV + "TimeRelations", path="cur:timeRelation"
        ),
    ),
    "workloads": (
        FormField("amount", "number", True, False, path="cur:amount"),
        FormField("amount_to", "number", False, False, path="cur:amountTo"),
        FormField("unit", "concept", True, False, values=CV + "WorkloadUnits", path="cur:unit"),
        FormField(
            "workload_kind", "concept", False, False, values=CV + "WorkloadKinds", path="cur:workloadKind"
        ),
        FormField("is_recommendation", "boolean", False, False),
        FormField("minutes_per_unit", "number", False, False),  # a whole number, as the document says it
        FormField("total", "boolean", False, False),  # the holder's whole (cur:totalWorkload)
    ),
}
VALUE_HOLDERS: Mapping[ValueKind, tuple[HolderKind, ...]] = {
    "level_assignments": ("node", "statement", "specification"),
    "time_spans": ("node", "specification"),
    "workloads": ("node", "specification"),
}
TABLE_OF: Mapping[ValueKind, str] = {
    "level_assignments": "level_assignment", "time_spans": "time_span", "workloads": "workload",
}  # fmt: skip
PERIODS: Final[ValueKind] = "time_spans"  # what a workload's periods are
_RANK, _DIMENSION = CUR + "rank", CUR + "levelDimension"
# every concept of the class, retired ones too: a kept value may name one, and its system still rules it
_GROUPED_VALUES = """
SELECT c.iri, c.scheme_iri, s.pref_labels, c.properties -> %(rank)s -> 0 ->> 'value' AS rank,
    s.properties -> %(dimension)s -> 0 ->> 'iri' AS dimension, c.retired_in IS NULL AND s.retired_in IS NULL
FROM vocab_concept c JOIN vocab_scheme s ON s.iri = c.scheme_iri
WHERE %(type)s = ANY (c.types)
"""
_SCHEME_VALUES = """
SELECT c.iri FROM vocab_concept c JOIN vocab_scheme s ON s.iri = c.scheme_iri
WHERE c.scheme_iri = %s AND c.retired_in IS NULL AND s.retired_in IS NULL
"""


@dataclass(frozen=True)
class LevelRule:
    """Levels of these dimensions - their system's (``cur:levelDimension``) or the assignment's own - a holder
    of this kind never holds, but where its type is ``unless`` (a statement's kind, a specification's kind):
    the SPARQL constraints of the core's LevelAssignmentShape, which tests/vocab/test_level_rules.py holds
    against the shapes."""

    holder: HolderKind
    dimensions: frozenset[str]
    unless: str | None = None


_GRADED = frozenset(
    {CV + "dim_grading", CV + "dim_conduct"}
)  # at an assessment, its specification, a standard
LEVEL_RULES: Final = (
    LevelRule("statement", frozenset({CV + "dim_qualification"})),  # at a qualification or a specification
    LevelRule("statement", _GRADED, unless=CV + "kind_standard"),
    LevelRule("node", _GRADED),
    LevelRule("specification", _GRADED, unless="assessmentSpecification"),
)


@dataclass(frozen=True)
class ValueForm:
    """The values of each list field by its key, active ones alone - those of a group by group, in the
    order of the groups' labels and their rank, the others in the order of their labels -; the group of
    each value that has one, and each group's label."""

    values: Mapping[str, tuple[ConceptDetails, ...]]
    group_of: Mapping[str, str]  # a value's IRI: its scheme's - a retired one's too
    groups: Mapping[str, str]  # a group's IRI: its label
    dimension_of: Mapping[str, str | None]  # a level's IRI: its system's dimension (cv:LevelDimensions)


async def value_form_of(connection: psycopg.AsyncConnection) -> ValueForm:
    """The values' form: one for every sector, as the level systems and units are every sector's."""
    by_source: dict[str, tuple[ConceptDetails, ...]] = {}
    group_of: dict[str, str] = {}
    groups: dict[str, str] = {}
    dimension_of: dict[str, str | None] = {}
    for source, value_class in _GROUPED.items():
        cursor = await connection.execute(
            _GROUPED_VALUES, {"rank": _RANK, "dimension": _DIMENSION, "type": value_class}
        )
        found = await cursor.fetchall()
        for iri, scheme, labels, _, dimension, _ in found:
            group_of[iri] = scheme
            groups[scheme] = _label(labels) or scheme
            if source == LEVELS:
                dimension_of[iri] = dimension
        ranks = {iri: _number(rank) for iri, _, _, rank, _, active in found if active}
        details = await concept_details(connection, list(ranks))
        order = {
            iri: (groups[group_of[iri]].casefold(), group_of[iri], rank is None, rank or 0)
            for iri, rank in ranks.items()
        }
        by_source[source] = tuple(
            sorted(details.values(), key=lambda value: (*order[value.iri], value.label.casefold()))
        )
    values: dict[str, tuple[ConceptDetails, ...]] = {}
    for field in (field for fields in VALUE_FIELDS.values() for field in fields):
        if field.values is None:
            continue
        if field.values not in by_source:
            cursor = await connection.execute(_SCHEME_VALUES, (field.values,))
            iris = [iri for (iri,) in await cursor.fetchall() if iri not in _NOT_OFFERED]
            details = await concept_details(connection, iris)
            by_source[field.values] = tuple(
                sorted(details.values(), key=lambda value: value.label.casefold())
            )
        values[field.key] = by_source[field.values]
    return ValueForm(values, group_of, groups, dimension_of)


def _label(labels: dict[str, str], language: str = "de") -> str | None:
    """The label in ``language``, else in the first other one there is."""
    return labels.get(language) or next((labels[other] for other in sorted(labels)), None)


def _number(value: str | None) -> Decimal | None:
    """A rank as the loader keeps its literal; none where it is no number."""
    try:
        number = None if value is None else Decimal(value)
    except InvalidOperation:
        return None
    return number if number is not None and number.is_finite() else None
