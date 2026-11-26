"""A document's assessments for the editors (plan M3a J; app/db/assessments.py, app/db/assessment_rows.py):
read by who reads the document's content, each part after the assessment it is a part of, with what it
assesses and the levels at it, beside what an assessment may be a part of or assess (``choices``) and the
kinds the list offers (``kinds``); one added under its parent, one's fields and what it assesses set on its
revision, one taken away with its parts, and the levels at one set as a whole on its revision
(app/api/values.py) - by the document's owner and the editors. Refused as app/api/edit_answers.py says - a
field the store does not take as ``invalid_field`` with the field and why (``parent_id`` ``cycle`` for a
parent among its own parts), a stale revision with the assessment as it stands, a stranger's as no
assessment at all; audited by the fields named and by counts, never by what they say.
"""

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require_account
from app.api.document_access import readable_content, readable_document, reader, visible_document
from app.api.document_tree import Closed, closed_of
from app.api.edit_answers import HIDDEN, REFUSED, TAKE_RESPONSES, Responses, answers, audit, refusal_of, stale
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.source_content import EDITORS
from app.api.value_answers import Number, StatedOut, ValuesOut, values_out
from app.api.values import VALUE_RESPONSES, Iri, ValuesIn, set_values
from app.core.auth import Principal
from app.db.assessment_choices import choices_of, kinds_of
from app.db.assessment_rows import assessments_of
from app.db.assessments import DOCUMENT_OF_ASSESSMENT, add_assessment, drop_assessment, edit_assessment
from app.db.editing import StaleRevision, extracted, target_of
from app.domain.assessments import MOST_LABEL, MOST_TARGETS, AssessmentDraft, AssessmentRow
from app.domain.l2 import HeldValues, Holder
from app.jobs.queue import open_job
from app.pipeline.extraction import unique_key

router = APIRouter(prefix="/api/v1", tags=["documents"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
Revision = Annotated[int, Query(ge=1, description="The assessment's revision as it was read")]
NO_ASSESSMENT = "no_assessment: none the caller may read"
EDIT_RESPONSES: Responses = {
    409: {
        "model": ErrorBody,
        "description": "stale_revision (details.current: the assessment as it stands), job_open"
        " (details.job_id to the owner and the admins), frozen, not_extracted (X4 has not read every"
        " package)",
    },
    422: {"model": ErrorBody, "description": "invalid_field (details: field, problem)"},
}
# a weight in percent, a duration in whole minutes: as the store's checks have them, refused unechoed
Weight = Annotated[Decimal, Field(ge=0, le=100, max_digits=15, allow_inf_nan=False)]
Minutes = Annotated[int, Field(ge=0, le=2**31 - 1)]
Label = Annotated[str, Field(max_length=MOST_LABEL)]
Targets = Annotated[list[UUID], Field(max_length=MOST_TARGETS)]


class TargetOut(BaseModel):
    kind: str  # node, statement
    id: UUID
    label: str | None  # a node's code and title, a statement's wording cut


class AssessmentOut(StatedOut):
    parent_kind: str  # assessment, specification, node
    parent_id: UUID
    position: int  # among the parts of its parent, from 1
    assessment_kind: str  # cv:AssessmentKinds
    label: str | None
    duration_minutes: int | None
    weight_percent: Number | None
    graded: bool | None
    iri: str | None  # given when the document is frozen
    targets: list[TargetOut]  # what it assesses, in order
    values: ValuesOut  # the levels at it (its time spans and workloads none)


class ChoiceOut(BaseModel):
    kind: str  # specification, node
    id: UUID
    label: str | None


class KindOut(BaseModel):
    iri: str  # cv:AssessmentKinds, active
    label: str


class AssessmentsOut(BaseModel):
    editable: bool  # the caller may edit them now
    closed: Closed | None  # why nobody may now, whoever reads
    assessments: list[AssessmentOut]  # each part after the assessment it is a part of
    choices: list[ChoiceOut]  # the specifications and nodes an assessment may be a part of or assess
    kinds: list[KindOut]  # the kinds the list offers, by their labels


class NewAssessmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: UUID  # an assessment, a specification or a node of the document
    assessment_kind: Iri
    label: Label | None = None
    duration_minutes: Minutes | None = None
    weight_percent: Weight | None = None
    graded: bool | None = None
    targets: Targets = []  # nodes and statements of the document


class AssessmentEditIn(BaseModel):
    """The fields to set; one left out stays, a blank label empties it, ``targets`` replaces them all."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)  # the assessment's, as it was read
    parent_id: UUID | None = None
    assessment_kind: Iri | None = None
    label: Label | None = None
    duration_minutes: Minutes | None = None
    weight_percent: Weight | None = None
    graded: bool | None = None
    targets: Targets | None = None


class DroppedOut(BaseModel):
    assessments: int  # the assessment and its parts


@router.get(
    "/documents/{document_id}/assessments",
    summary="The document's assessments with what they assess and the levels at them",
    responses={
        403: {
            "model": ErrorBody,
            "description": "file_hidden: the entry's content is no longer yours to read",
        },
        404: {"model": ErrorBody, "description": "no_document: none the caller may read"},
    },
)
async def read_assessments(document_id: UUID, request: Request, who: Account) -> AssessmentsOut:
    async with request.app.state.pool.connection() as connection, connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        document = await visible_document(connection, who, document_id)
        await readable_content(connection, who, request.app.state.settings, document)
        found = await assessments_of(connection, document_id)
        choices = await choices_of(connection, document_id)
        kinds = await kinds_of(connection)
        job = await open_job(connection, unique_key(document_id))
        all_there = await extracted(connection, document_id)
    closed = closed_of(frozen=document.frozen_at is not None, job_open=job is not None, extracted=all_there)
    return AssessmentsOut(
        editable=closed is None and (bool(who.roles & EDITORS) or document.owner_id == who.account_id),
        closed=closed,
        assessments=[_assessment(row) for row in found],
        choices=[ChoiceOut(kind=each.kind, id=each.id, label=each.label) for each in choices],
        kinds=[KindOut(iri=kind.iri, label=kind.label) for kind in kinds],
    )


@router.post(
    "/documents/{document_id}/assessments",
    status_code=201,
    summary="Add an assessment after the parts of its parent - an editor's proposal",
    responses=answers("no_document: none the caller may read", EDIT_RESPONSES) | HIDDEN,
)
async def add_an_assessment(
    document_id: UUID, body: NewAssessmentIn, request: Request, who: Account
) -> AssessmentOut:
    draft = AssessmentDraft(**body.model_dump(exclude={"targets"}), targets=tuple(body.targets))
    async with request.app.state.pool.connection() as connection:
        try:
            async with connection.transaction():
                await readable_document(connection, who, request.app.state.settings, document_id)
                made = await add_assessment(connection, reader(who), document_id, draft)
                if made is None:  # taken away meanwhile
                    raise Refusal(404, "no_document", "No such document.")
                details = {"document": str(document_id), "targets": len(draft.targets)}
                await audit(connection, who, "assessment.add", f"assessment:{made}", details)
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
        return await _read(connection, who, made)


@router.patch(
    "/assessments/{assessment_id}",
    summary="Set an assessment's fields or what it assesses - the assessment an editor's proposal after",
    responses=answers(NO_ASSESSMENT, EDIT_RESPONSES) | HIDDEN,
)
async def edit_an_assessment(
    assessment_id: UUID, body: AssessmentEditIn, request: Request, who: Account
) -> AssessmentOut:
    given: dict[str, Any] = body.model_dump(include=body.model_fields_set - {"expected_revision"})
    if given.get("parent_id", False) is None or given.get("assessment_kind", False) is None:
        raise Refusal(422, "invalid_field", "An assessment has a parent and a kind.", details={
            "field": "parent_id" if given.get("parent_id", False) is None else "assessment_kind",
            "problem": "required",
        })  # fmt: skip
    if given.get("targets", False) is None:
        given["targets"] = []
    async with request.app.state.pool.connection() as connection:
        document_id: UUID | None = None
        try:
            async with connection.transaction():
                document_id = await _document_of(connection, request, who, assessment_id)
                revision = await edit_assessment(
                    connection, reader(who), assessment_id, body.expected_revision, given
                )
                if revision is None:  # taken away meanwhile
                    raise _gone()
                details = {"document": str(document_id), "revision": revision, "fields": sorted(given)}
                await audit(connection, who, "assessment.edit", f"assessment:{assessment_id}", details)
        except StaleRevision as error:
            raise stale("assessment", await assessment_as_read(connection, who, assessment_id)) from error
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
        return await _read(connection, who, assessment_id)


@router.delete(
    "/assessments/{assessment_id}",
    summary="Take an assessment away with its parts and the findings on them",
    responses=answers(NO_ASSESSMENT, TAKE_RESPONSES) | HIDDEN,
)
async def drop_an_assessment(
    assessment_id: UUID, expected_revision: Revision, request: Request, who: Account
) -> DroppedOut:
    async with request.app.state.pool.connection() as connection:
        document_id: UUID | None = None
        try:
            async with connection.transaction():
                document_id = await _document_of(connection, request, who, assessment_id)
                dropped = await drop_assessment(connection, reader(who), assessment_id, expected_revision)
                if dropped is None:
                    raise _gone()
                details = {"document": str(document_id), "assessments": dropped}
                await audit(connection, who, "assessment.drop", f"assessment:{assessment_id}", details)
        except StaleRevision as error:
            raise stale("assessment", await assessment_as_read(connection, who, assessment_id)) from error
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
    return DroppedOut(assessments=dropped)


@router.put(
    "/assessments/{assessment_id}/values",
    summary="Set the levels at an assessment as a whole",
    responses=answers(NO_ASSESSMENT, VALUE_RESPONSES) | HIDDEN,
)
async def set_assessment_values(
    assessment_id: UUID, body: ValuesIn, request: Request, who: Account
) -> AssessmentOut:
    found = await set_values(
        request, who, Holder("assessment", assessment_id), body, assessment_as_read, _gone()
    )
    assert isinstance(found, AssessmentOut)  # noqa: S101 - the assessment's reader
    return found


async def assessment_as_read(
    connection: psycopg.AsyncConnection, who: Principal, assessment_id: UUID
) -> AssessmentOut | None:
    """The assessment as its document's list has it, where the caller sees it."""
    target = await target_of(connection, DOCUMENT_OF_ASSESSMENT, reader(who), assessment_id)
    if target is None:
        return None
    found = await assessments_of(connection, target.document_id)
    return next((_assessment(row) for row in found if row.id == assessment_id), None)


async def _read(connection: psycopg.AsyncConnection, who: Principal, assessment_id: UUID) -> AssessmentOut:
    read = await assessment_as_read(connection, who, assessment_id)
    if read is None:  # taken away right after
        raise _gone()
    return read


async def _document_of(
    connection: psycopg.AsyncConnection, request: Request, who: Principal, assessment_id: UUID
) -> UUID:
    """The assessment's document, whose content the caller reads; 404 where it sees none."""
    target = await target_of(connection, DOCUMENT_OF_ASSESSMENT, reader(who), assessment_id)
    if target is None:
        raise _gone()
    await readable_document(connection, who, request.app.state.settings, target.document_id)
    return target.document_id


def _gone() -> Refusal:
    return Refusal(404, "no_assessment", "No such assessment.")


def _assessment(row: AssessmentRow) -> AssessmentOut:
    return AssessmentOut(
        id=row.id, origin=row.stated.origin, review_status=row.stated.review_status,
        revision=row.stated.revision, parent_kind=row.parent_kind, parent_id=row.parent_id,
        position=row.position, assessment_kind=row.assessment_kind, label=row.label,
        duration_minutes=row.duration_minutes, weight_percent=row.weight_percent, graded=row.graded,
        iri=row.iri, values=values_out(HeldValues(levels=row.levels)),
        targets=[TargetOut(kind=each.kind, id=each.id, label=each.label) for each in row.targets],
    )  # fmt: skip
