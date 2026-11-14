"""MEM-Schule's catalogue (plan M2, E11): an admin starts its reading, one at a time (the job
source.mem_catalog, app/sources/mem/catalog.py); the redaktion and the admin look a plan up in it to
import, by region (a Land's; DE the KMK's standards), Land, subject and title, each plan with its region,
the page with when the catalogue was last read (none: never). A second start while one waits or runs is
refused (409 ``catalog_running``, naming the job to follow); the job is followed and cancelled as any.

The redaktion and the admins import a plan of the catalogue into a new document of an entry's finished
conversion (plan M2, E1; Detailplan M2-5c): in one transaction the document - theirs, of the school
sector, the plan's Land its region (DE for the KMK's standards, as land:DE is theirs) -, the plan it names
(app/db/mem_plans.record_import), its type (Lehrplan; Bildungsstandards for the KMK's) and its
specification (curriculum; competencyFramework), the job extract.mem_import under the document's
extraction key (app/sources/mem/import_job.py) and the audit's entry. A plan the catalogue does not hold
is refused (422 ``mem_unknown_plan``), a conversion not finished or not of the entry's file (404
``mem_no_conversion``), a plan the conversion took already (409 ``mem_plan_taken``, naming its document).

The conversion's document of the plan is made first; where the index ``document_mem_import`` finds one
there already - asked before, or in a request beside this one - that one is looked at under its tree's
lock: of the same entry, its job ended and its run IM not done, the import starts again on it (202, the
same document, as it was first written); else the plan is taken (409). Its job goes in the document's
owner's lane, as every job of the document (app/api/document_check.py).
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.api.deps import require_role
from app.api.document_access import reader
from app.api.documents import DocumentOut, document_out
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.jobs import JobOut, job_out
from app.core.auth import Principal
from app.core.logging import current_request_id
from app.db.accounts import record_audit
from app.db.documents import (
    Document,
    DocumentError,
    create_document,
    document_for_job,
    imported_document,
    set_document_type,
)
from app.db.mem_plans import (
    MAX_DOCUMENT_TITLE,
    MemPlan,
    catalog_read_at,
    find_plans,
    plan_by_iri,
    record_import,
)
from app.db.nodes import lock_tree
from app.db.profile import add_specification
from app.db.runs import done_stages
from app.domain.l1 import SpecificationDraft
from app.domain.text import storable
from app.jobs.queue import OpenJob, account_lane, enqueue
from app.jobs.state import job_state
from app.pipeline.extraction import unique_key
from app.sources.mem import import_kind
from app.sources.mem.catalog import KIND, enqueue_catalog
from app.sources.mem.classes import SCHUL
from app.sources.mem.queries import LP
from app.sources.mem.sparql import KMK_GRAPH, MAX_IRI
from app.vocab.lookup import lands_of_region, region_of_land, regions_of_lands

router = APIRouter(prefix="/api/v1", tags=["sources"], responses=AUTH_RESPONSES)
Admin = Annotated[Principal, Depends(require_role("admin"))]
Importer = Annotated[Principal, Depends(require_role("admin", "redaktion"))]
Storable = AfterValidator(storable)  # what goes on to a query as it came
Iri = Annotated[str | None, Query(min_length=1, max_length=MAX_IRI), Storable]
IMPORT_INDEX = "document_mem_import"  # one import of a plan per conversion (migration 0030)


class CatalogStarted(BaseModel):
    job_id: UUID


class MemPlanOut(BaseModel):
    iri: str
    graph: str
    land_iri: str | None
    title: str
    class_iri: str
    subjects: list[str]
    school_types: list[str]
    licence: str | None
    attribution: str | None
    read_at: datetime  # when the catalogue last read the plan
    region: str | None  # its Land's region (DE-SN), DE for the KMK's standards; none where none matches


class MemPlanPage(BaseModel):
    plans: list[MemPlanOut]
    total: int
    catalog_read_at: datetime | None  # when the catalogue last read a plan: none, never


class MemImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # a plan of the catalogue (GET /mem/plans)
    plan_iri: Annotated[str, Field(min_length=1, max_length=MAX_IRI), Storable]
    conversion_id: UUID  # the entry's finished conversion the plan's wordings are looked for in


class MemImportStarted(BaseModel):
    document: DocumentOut
    job: JobOut


@router.post(
    "/mem/catalog",
    status_code=202,
    summary="Read MEM-Schule's plans into the catalogue (admins)",
    responses={409: {"model": ErrorBody, "description": "A reading waits or runs already: details.job_id"}},
)
async def start_catalog(request: Request, admin: Admin) -> CatalogStarted:
    """The reading as a job of the admin's (``GET /api/v1/jobs/{id}``)."""
    assert admin.account_id is not None  # noqa: S101 - require_role refuses visitors
    async with request.app.state.pool.connection() as connection, connection.transaction():
        started, running = await enqueue_catalog(connection, account_lane(admin.account_id))
        if started is None:
            raise Refusal(
                409, "catalog_running", "A reading of the catalogue waits or runs already.",
                details={"job_id": str(running)},
            )  # fmt: skip
        await record_audit(
            connection, admin.account_id, admin.name, KIND, f"job:{started}", {}, current_request_id()
        )
    return CatalogStarted(job_id=started)


@router.get(
    "/mem/plans",
    summary="Look MEM-Schule's plans up (redaktion, admins)",
    responses={422: {"model": ErrorBody, "description": "unknown_region, validation_failed"}},
)
async def list_plans(
    request: Request,
    who: Importer,
    region: Annotated[str | None, Query(pattern=r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")] = None,
    land: Iri = None,
    subject: Iri = None,
    title: Annotated[str | None, Query(min_length=1, max_length=200), Storable] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> MemPlanPage:
    """A page of the plans of a region (its notation; DE the KMK's) and a Land (its IRI, ``LP_0000029``)
    with a subject (its IRI) whose title holds ``title`` in any case, by title; the number of all of them,
    and when the catalogue was last read."""
    async with request.app.state.pool.connection() as connection:
        lands, graph = None, None
        if region == "DE":
            graph = KMK_GRAPH
        elif region is not None and (lands := await lands_of_region(connection, region, LP)) is None:
            raise Refusal(422, "unknown_region", "No such region.")
        plans, total = await find_plans(
            connection, land=land, subject=subject, title=title, lands=lands, graph=graph, limit=limit,
            offset=offset,
        )  # fmt: skip
        regions = await regions_of_lands(connection, {plan.land_iri for plan in plans if plan.land_iri})
        read_at = await catalog_read_at(connection)
    return MemPlanPage(
        plans=[_plan_out(plan, regions) for plan in plans], total=total, catalog_read_at=read_at
    )


def _plan_out(plan: MemPlan, regions: dict[str, str]) -> MemPlanOut:
    region = "DE" if plan.graph == KMK_GRAPH else regions.get(plan.land_iri or "")
    # a plan read from the table carries when it was read (read_at)
    return MemPlanOut.model_validate({**vars(plan), "region": region})


@router.post(
    "/sources/{source_id}/mem-import",
    status_code=202,
    summary="Import a MEM-Schule plan into a document of the entry's finished conversion (redaktion, admins)",
    responses={
        404: {
            "model": ErrorBody,
            "description": "mem_no_conversion: no finished conversion of the entry's file",
        },
        409: {
            "model": ErrorBody,
            "description": "mem_plan_taken: the conversion took the plan, details.document_id",
        },
        422: {
            "model": ErrorBody,
            "description": "mem_unknown_plan: the catalogue holds no such plan; validation_failed: the body",
        },
        503: {
            "model": ErrorBody,
            "description": "service_unavailable: the plan's document was taken back, try again",
        },
    },
)
async def start_import(
    source_id: UUID, body: MemImportRequest, request: Request, who: Importer
) -> MemImportStarted:
    """The new document and its waiting job (``GET /api/v1/jobs/{id}``), as the module says."""
    assert who.account_id is not None  # noqa: S101 - require_role refuses visitors
    async with request.app.state.pool.connection() as connection, connection.transaction():
        plan = await plan_by_iri(connection, body.plan_iri)
        if plan is None:
            raise Refusal(422, "mem_unknown_plan", "The catalogue holds no such plan.")
        kmk = plan.graph == KMK_GRAPH
        if kmk:
            region: str | None = "DE"  # land:DE is the KMK's: a cue scoped to it applies
        else:
            region = None if plan.land_iri is None else await region_of_land(connection, plan.land_iri)
        try:
            document = await _made(connection, request, who, source_id, body.conversion_id, plan, region)
        except psycopg.errors.UniqueViolation as taken:  # the savepoint took the new document back
            if taken.diag.constraint_name != IMPORT_INDEX:
                raise
            document, restart = await _to_restart(connection, source_id, body.conversion_id, plan.iri), True
        else:
            await set_document_type(
                connection, document.id, SCHUL + ("dt-Bildungsstandards" if kmk else "dt-Lehrplan")
            )
            await add_specification(
                connection, document.id,
                SpecificationDraft("S1", "competencyFramework" if kmk else "curriculum",
                                   plan.title[:MAX_DOCUMENT_TITLE], None, {}, ()),
            )  # fmt: skip
            restart = False
        payload = {"document_id": str(document.id)}
        try:
            job_id = await enqueue(
                connection,
                import_kind.KIND,
                account_lane(document.owner_id),
                payload,
                unique_key=unique_key(document.id),
            )
        except OpenJob:  # a job of the document waits or runs: the plan is taken
            raise _taken(document.id) from None
        # looked at once no job of the document is open but this one: a job ends after its run IM is done,
        # so a run done before is seen here, whatever lock its writer took; the refusal takes the job back
        if restart and "IM" in await done_stages(connection, document.id):
            raise _taken(document.id)
        await record_audit(
            connection, who.account_id, who.name, "document.mem_import", f"document:{document.id}",
            {"source": str(source_id), "conversion": str(body.conversion_id), "plan": plan.iri,
             "job": str(job_id), "restart": restart, "regions": list(document.regions)},
            current_request_id(),
        )  # fmt: skip
        return await _started(connection, who, document.id, job_id)


async def _to_restart(
    connection: psycopg.AsyncConnection, source_id: UUID, conversion_id: UUID, plan_iri: str
) -> Document:
    """The conversion's document of the plan, to start its import again: of this entry - looked at under
    its tree's lock, as every start of a job of it is, so that two restarts go one after the other; else
    409 ``mem_plan_taken``. A job of it waiting or running is the enqueue's to find (OpenJob), a run IM
    done the route's once the job is enqueued."""
    existing = await imported_document(connection, conversion_id, plan_iri)
    if existing is None:  # taken back since the index found it: a request again makes it anew
        raise Refusal(
            503,
            "service_unavailable",
            "The plan's document was being taken back: try again.",
            {"Retry-After": "5"},
        )
    await lock_tree(connection, existing.id)
    if existing.source_id != source_id:
        raise _taken(existing.id)
    return existing


def _taken(document_id: UUID) -> Refusal:
    return Refusal(
        409, "mem_plan_taken", "This conversion took the plan already.",
        details={"document_id": str(document_id)},
    )  # fmt: skip


async def _made(
    connection: psycopg.AsyncConnection,
    request: Request,
    who: Principal,
    source_id: UUID,
    conversion_id: UUID,
    plan: MemPlan,
    region: str | None,
) -> Document:
    """The new document of the import, naming its plan - in a savepoint: a UniqueViolation of
    IMPORT_INDEX takes it back."""
    async with connection.transaction():
        try:
            document = await create_document(
                connection,
                reader(who),
                third_party_content=request.app.state.settings.third_party_markdown != "hidden",
                source_id=source_id,
                conversion_id=conversion_id,
                sector="school",
                regions=[region] if region else [],
            )
        except DocumentError as refused:
            # the sector is the vocabulary's own, the region read from it in this transaction: an unknown
            # one is a vocabulary the deployment lacks, a 500
            if refused.code != "no_conversion":
                raise
            raise Refusal(
                404, "mem_no_conversion", "No finished conversion of this entry to import into."
            ) from None
        await record_import(connection, document.id, plan)
    return document


async def _started(
    connection: psycopg.AsyncConnection, who: Principal, document_id: UUID, job_id: UUID
) -> MemImportStarted:
    document = await document_for_job(connection, document_id)
    state = await job_state(connection, job_id, None)
    assert document is not None and state is not None  # noqa: S101 - written in this transaction
    return MemImportStarted(document=await document_out(connection, document, who), job=job_out(state))
