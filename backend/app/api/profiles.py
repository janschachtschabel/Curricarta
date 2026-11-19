"""A sector's form for the editor (plan M1 9.1; app/vocab/forms.py): the fields of a node and of a
statement, each list with the active values of the sector's profile and their texts - and the second
layer's values (plan M3a E1; app/vocab/value_forms.py): which kinds a node, a statement and a
specification are offered, with the fields of each, levels and competence dimensions grouped by their
level system or model. Every account reads it; a sector without an active profile has none (404
``unknown_sector``)."""

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel

from app.api.deps import require_account
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.core.auth import Principal
from app.domain.l2 import HolderKind
from app.vocab.forms import FieldKind, FormField, form_of
from app.vocab.lookup import ConceptDetails
from app.vocab.value_forms import (
    LEVEL_RULES,
    PERIODS,
    VALUE_FIELDS,
    VALUE_HOLDERS,
    ValueForm,
    ValueKind,
    value_form_of,
)

router = APIRouter(prefix="/api/v1", tags=["profiles"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
Sector = Annotated[str, Path(min_length=1, max_length=40, pattern=r"^[a-z][a-zA-Z]*$")]


class ValueOut(BaseModel):
    iri: str
    notation: str | None
    label: str
    alt_labels: list[str]
    definition: str | None
    note: str | None  # skos:scopeNote
    delimitation: str | None  # what it is not for
    examples: list[str]
    broader: list[str]  # the core values it refines: a node type's function, a subkind's kind
    group: str | None  # a level's system, a competence dimension's model (FormOut.groups); none for others
    dimension: str | None  # a level's system's (cv:LevelDimensions), which ValueKindOut.rules name


class FieldOut(BaseModel):
    key: str
    kind: FieldKind
    required: bool
    many: bool
    most: int | None  # signs, for a text
    values: list[ValueOut] | None  # a list's, active ones in the order of their labels


class LevelRuleOut(BaseModel):
    """A level of these dimensions - its system's or the assignment's own - the holder never holds, but where
    its type (a statement's kind, a specification's) is ``unless``."""

    holder: HolderKind
    dimensions: list[str]
    unless: str | None


class ValueKindOut(BaseModel):
    holders: list[HolderKind]  # those offered this kind: PUT /nodes/{id}/values, /statements/{id}/values
    fields: list[FieldOut]
    periods: ValueKind | None  # the kind a workload's periods are, with that kind's fields
    rules: list[LevelRuleOut]  # a level's, by its dimension; a range's end is of its start's system too


class FormOut(BaseModel):
    sector: str
    profile: str
    node: list[FieldOut]
    statement: list[FieldOut]
    values: dict[ValueKind, ValueKindOut]
    groups: dict[str, str]  # the label of each group a value names


@router.get(
    "/profiles/{sector}/form",
    summary="The fields of a node and of a statement, with the values of the sector's profile",
    responses={404: {"model": ErrorBody, "description": "unknown_sector: no active profile of this sector"}},
)
async def read_form(sector: Sector, request: Request, who: Account) -> FormOut:
    async with request.app.state.pool.connection() as connection:
        form = await form_of(connection, sector)
        if form is None:
            raise Refusal(404, "unknown_sector", "No active profile of this education sector.")
        valued = await value_form_of(connection)
    return FormOut(
        sector=form.sector,
        profile=form.profile,
        node=[_field(field, form.values) for field in form.node],
        statement=[_field(field, form.values) for field in form.statement],
        values={
            kind: ValueKindOut(
                holders=list(VALUE_HOLDERS[kind]),
                fields=[_field(field, valued.values, valued) for field in fields],
                periods=PERIODS if kind == "workloads" else None,
                rules=[
                    LevelRuleOut(holder=rule.holder, dimensions=sorted(rule.dimensions), unless=rule.unless)
                    for rule in LEVEL_RULES
                    if kind == "level_assignments"
                ],
            )
            for kind, fields in VALUE_FIELDS.items()
        },
        groups=dict(valued.groups),
    )


def _field(
    field: FormField, offered: Mapping[str, tuple[ConceptDetails, ...]], valued: ValueForm | None = None
) -> FieldOut:
    values = offered.get(field.key) if field.values is not None else None
    return FieldOut(
        key=field.key,
        kind=field.kind,
        required=field.required,
        many=field.many,
        most=field.most,
        values=None if values is None else [_value(value, valued) for value in values],
    )


def _value(value: ConceptDetails, valued: ValueForm | None) -> ValueOut:
    return ValueOut(
        iri=value.iri,
        notation=value.notation,
        label=value.label,
        alt_labels=list(value.alt_labels),
        definition=value.definition,
        note=value.note,
        delimitation=value.delimitation,
        examples=list(value.examples),
        broader=list(value.broader),
        group=None if valued is None else valued.group_of.get(value.iri),
        dimension=None if valued is None else valued.dimension_of.get(value.iri),
    )
