"""A document's specifications for the editors (plan M3a H1; app/db/specifications.py): read with their
variants, their own levels, time spans and workloads and their applicability contexts - each context with
the time spans and levels it holds -, by who reads the document's content; a specification's title and
field set on its revision, and its values and contexts set as a whole on it (app/db/values.py), by the
document's owner and the editors. Its kind and its key - which its IRI is made of - stay. Refused as
app/api/edit_answers.py says - a value or context field the form does not take as ``invalid_field`` with
its path in the set (``contexts[0].sector``), a stale revision with the specification as it stands; audited
by the fields named and by counts, never by what they say.
"""

from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.api.deps import require_account
from app.api.document_access import readable_content, readable_document, reader, visible_document
from app.api.document_tree import Closed, _closed
from app.api.edit_answers import HIDDEN, REFUSED, Responses, answers, audit, refusal_of, stale
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.source_content import EDITORS
from app.api.value_answers import LevelOut, StatedOut, TimeSpanOut, ValuesOut, values_out
from app.api.values import MOST_VALUES, VALUE_RESPONSES, Iri, LevelIn, TimeSpanIn, ValuesIn, set_values
from app.core.auth import Principal
from app.db.editing import StaleRevision, extracted, target_of
from app.db.specifications import FIELDS, SpecificationRow, edit_specification, specifications_of
from app.db.values import DOCUMENT_OF_SPECIFICATION
from app.domain.l2 import Context, ContextDraft, HeldValues, Holder, ValueDrafts
from app.domain.text import storable
from app.jobs.queue import open_job
from app.pipeline.extraction import unique_key
from app.vocab.value_forms import SPECIFICATION_TYPES

router = APIRouter(prefix="/api/v1", tags=["documents"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
NO_SPECIFICATION = "no_specification: none the caller may read"
EDIT_RESPONSES: Responses = {
    409: {
        "model": ErrorBody,
        "description": "stale_revision (details.current: the specification as it stands), job_open"
        " (details.job_id to the owner and the admins), frozen, not_extracted (X4 has not read every"
        " package)",
    },
    422: {"model": ErrorBody, "description": "invalid_field (details: field, problem)"},
}


def _blank_none(value: str | None) -> str | None:
    """A text as the store keeps it: a blank one none."""
    return None if value is None or not value.strip() else value


# a context's text as written: refused where the store would refuse it, unechoed
ContextText = Annotated[
    str | None, StringConstraints(max_length=FIELDS["field_text"]), AfterValidator(storable),
    AfterValidator(_blank_none),
]  # fmt: skip


class VariantOut(BaseModel):
    id: UUID
    key: str
    label: str
    variant_kind: str  # cv:VariantKinds


class ContextOut(StatedOut):
    sector: str | None  # cv:EducationSectors
    formality: str | None  # cv:Formalities
    institution_text: str | None
    target_group_text: str | None
    level_assignments: list[LevelOut]
    time_spans: list[TimeSpanOut]


class SpecificationOut(BaseModel):
    id: UUID
    key: str  # what its IRI is made of: it stays
    spec_kind: (
        str  # X1's: curriculum, competencyFramework, qualificationSpecification, assessmentSpecification
    )
    type: str  # its class in the core (cur:Curriculum …), as a level rule's ``unless`` names it
    title: str
    field_text: str | None
    revision: int  # the token of an edit and of a set of its values
    variants: list[VariantOut]  # read only: X1's
    values: ValuesOut  # its own levels, time spans and workloads
    contexts: list[ContextOut]  # its applicability contexts, each with its time spans and levels


class SpecificationsOut(BaseModel):
    editable: bool  # the caller may edit them now
    closed: Closed | None  # why nobody may now, whoever reads
    specifications: list[SpecificationOut]  # by key


class SpecificationEditIn(BaseModel):
    """The fields to set; one left out stays, a blank field text empties it."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)  # the specification's, as it was read
    title: str | None = None
    field_text: str | None = None


class ContextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None  # a context of the specification's kept; none a new one
    sector: Iri | None = None
    formality: Iri | None = None
    institution_text: ContextText = None
    target_group_text: ContextText = None
    level_assignments: list[LevelIn] = Field(default=[], max_length=MOST_VALUES)
    time_spans: list[TimeSpanIn] = Field(default=[], max_length=MOST_VALUES)


class SpecificationValuesIn(ValuesIn):
    """The specification's values and its applicability contexts, every kind named: what the set leaves out
    goes - a context with its time spans and levels."""

    contexts: list[ContextIn] = Field(max_length=MOST_VALUES)

    def drafts(self) -> ValueDrafts:
        made = super().drafts()
        contexts = tuple(
            ContextDraft(
                **entry.model_dump(
                    include={"id", "sector", "formality", "institution_text", "target_group_text"}
                ),
                levels=tuple(level.draft() for level in entry.level_assignments),
                time_spans=tuple(span.draft() for span in entry.time_spans),
            )
            for entry in self.contexts
        )
        return ValueDrafts(made.levels, made.time_spans, made.workloads, contexts)


@router.get(
    "/documents/{document_id}/specifications",
    summary="The document's specifications with their variants, values and applicability contexts",
    responses={
        403: {
            "model": ErrorBody,
            "description": "file_hidden: the entry's content is no longer yours to read",
        },
        404: {"model": ErrorBody, "description": "no_document: none the caller may read"},
    },
)
async def read_specifications(document_id: UUID, request: Request, who: Account) -> SpecificationsOut:
    async with request.app.state.pool.connection() as connection, connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        document = await visible_document(connection, who, document_id)
        await readable_content(connection, who, request.app.state.settings, document)
        found = await specifications_of(connection, document_id)
        job = await open_job(connection, unique_key(document_id))
        all_there = await extracted(connection, document_id)
    closed = _closed(frozen=document.frozen_at is not None, job_open=job is not None, extracted=all_there)
    return SpecificationsOut(
        editable=closed is None and (bool(who.roles & EDITORS) or document.owner_id == who.account_id),
        closed=closed,
        specifications=[_specification(row) for row in found],
    )


@router.patch(
    "/specifications/{specification_id}",
    summary="Set a specification's title or field",
    responses=answers(NO_SPECIFICATION, EDIT_RESPONSES) | HIDDEN,
)
async def edit_a_specification(
    specification_id: UUID, body: SpecificationEditIn, request: Request, who: Account
) -> SpecificationOut:
    given: dict[str, Any] = body.model_dump(include=body.model_fields_set - {"expected_revision"})
    async with request.app.state.pool.connection() as connection:
        document_id: UUID | None = None
        try:
            async with connection.transaction():
                document_id = await _document_of(connection, request, who, specification_id)
                revision = await edit_specification(
                    connection, reader(who), specification_id, body.expected_revision, given
                )
                if revision is None:  # taken away meanwhile
                    raise _gone()
                details = {"document": str(document_id), "revision": revision, "fields": sorted(given)}
                await audit(
                    connection, who, "specification.edit", f"specification:{specification_id}", details
                )
        except StaleRevision as error:
            raise stale(
                "specification", await specification_as_read(connection, who, specification_id)
            ) from error
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
        read = await specification_as_read(connection, who, specification_id)
    if read is None:  # taken away right after
        raise _gone()
    return read


@router.put(
    "/specifications/{specification_id}/values",
    summary="Set a specification's levels, time spans, workloads and applicability contexts as a whole",
    responses=answers(NO_SPECIFICATION, VALUE_RESPONSES) | HIDDEN,
)
async def set_specification_values(
    specification_id: UUID, body: SpecificationValuesIn, request: Request, who: Account
) -> SpecificationOut:
    holder = Holder("specification", specification_id)
    found = await set_values(request, who, holder, body, specification_as_read, _gone())
    assert isinstance(found, SpecificationOut)  # noqa: S101 - the specification's reader
    return found


async def specification_as_read(
    connection: psycopg.AsyncConnection, who: Principal, specification_id: UUID
) -> SpecificationOut | None:
    """The specification as its document's list has it, where the caller sees it."""
    target = await target_of(connection, DOCUMENT_OF_SPECIFICATION, reader(who), specification_id)
    if target is None:
        return None
    found = await specifications_of(connection, target.document_id)
    return next((_specification(row) for row in found if row.id == specification_id), None)


async def _document_of(
    connection: psycopg.AsyncConnection, request: Request, who: Principal, specification_id: UUID
) -> UUID:
    """The specification's document, whose content the caller reads; 404 where it sees none."""
    target = await target_of(connection, DOCUMENT_OF_SPECIFICATION, reader(who), specification_id)
    if target is None:
        raise _gone()
    await readable_document(connection, who, request.app.state.settings, target.document_id)
    return target.document_id


def _gone() -> Refusal:
    return Refusal(404, "no_specification", "No such specification.")


def _specification(row: SpecificationRow) -> SpecificationOut:
    return SpecificationOut(
        id=row.id, key=row.key, spec_kind=row.spec_kind, type=SPECIFICATION_TYPES[row.spec_kind],
        title=row.title, field_text=row.field_text, revision=row.revision,
        variants=[VariantOut(id=each.id, key=each.key, label=each.label, variant_kind=each.variant_kind)
                  for each in row.variants],
        values=values_out(row.values), contexts=[_context(each) for each in row.values.contexts],
    )  # fmt: skip


def _context(context: Context) -> ContextOut:
    value = context.value
    held = values_out(HeldValues(levels=context.levels, time_spans=context.time_spans))
    return ContextOut(
        id=value.id, origin=context.stated.origin, review_status=context.stated.review_status,
        revision=context.stated.revision, sector=value.sector, formality=value.formality,
        institution_text=value.institution_text, target_group_text=value.target_group_text,
        level_assignments=held.level_assignments, time_spans=held.time_spans,
    )  # fmt: skip
