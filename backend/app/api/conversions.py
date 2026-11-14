"""A register entry's conversion (X0): asked for, followed, read page by page (plan M1, 3.6).

The conversion belongs to the entry's file, which entries of several accounts may share by its
SHA-256; so it is reached through an entry, and who may ask for it and read it is who may read the
entry's file (app/api/source_content.py). Its job is named only to those who may follow it - the
account that started it, an admin (app/api/jobs.py); another sees the conversion's own state. That an
account's own upload comes with a conversion already done tells it that the same file was here
before: the price of converting a file once, whoever brings it.

Asking starts the job of the engine's conversions (app/conversion/job.py) and answers 202, or gives
back the conversion there - waiting, running or done - with 200; a failed one is asked anew. The
engines asked of are those CONVERSION_ENGINES offers; where none is named - the page names none -, the
first of them whose pages the account may spend on: Docling's cost, and an account without pages left
starts none of its conversions (app/api/limits.py), but pdfplumber's, where it is offered too. A
conversion is read by the engine named, else the first there in the order offered, then one by an
engine no longer offered: what was converted before the converter came stays found, and what Docling
converted stays readable after it went. Asked are only the engines that read the entry's type
(app/conversion/readers.py): a PDF, a scan by Docling alone, a DOCX and an HTML page by Docling - a
type none offered reads is refused (not_pdf); the type goes with the job, which holds the file to it.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from app.api.deps import principal, require_account
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.limits import admit_pages, within_limit
from app.api.source_content import content_row, refuse_visitor, visitors_may_read
from app.conversion.base import Block, Cell, EngineName, offered_engines
from app.conversion.job import BILLABLE, KIND, READS_SCANS, kind_of
from app.conversion.readers import ENDINGS, READS, readers
from app.core.auth import Principal
from app.core.ids import new_id
from app.core.logging import current_request_id
from app.db.accounts import record_audit
from app.db.conversions import (
    ConversionState,
    ConversionStatus,
    blocks_on_page,
    conversion_for,
    lock_conversion,
    start_conversion,
    tables_running_onto,
)
from app.jobs.queue import account_lane, enqueue
from app.usage.ledger import usage_of

router = APIRouter(prefix="/api/v1", tags=["conversions"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
Caller = Annotated[Principal, Depends(principal)]


class FindingOut(BaseModel):
    code: str
    params: dict[str, Any]


class ConversionOut(BaseModel):
    id: UUID
    engine: EngineName
    engine_version: str | None
    status: ConversionStatus
    # why it failed: a FailureCode (app/db/conversions.py) - unreadable, too_many_pages, too_dense,
    # needs_ocr, too_many_ocr_pages, empty, timed_out, died, crashed, not_pdf, file_gone, no_pages - or the
    # code of the job that ended without it (handler_error, cancelled, lease_lost)
    error_code: str | None
    # the job converting it, for those who may follow it (GET /api/v1/jobs/{id}); else null
    job_id: UUID | None
    pages: int | None
    printed_pages: list[str | None] | None
    findings: list[FindingOut]
    created_at: datetime
    finished_at: datetime | None


class ConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: EngineName | None = None  # none: as the module says, by the conversion there and the pages left


class ContinuedOut(BaseModel):
    """A table begun on an earlier page and running on to this one: its block's ID, the page it
    begins on, and its cells on this page - a table joined over pages is one block, on its first."""

    id: str
    page: int
    cells: list[Cell]


class PageOut(BaseModel):
    page: int
    printed_page: str | None
    blocks: list[Block]
    continued: list[ContinuedOut]


CONTENT_REFUSALS: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorBody, "description": "file_hidden: the entry's file is for its editors only"},
    404: {"model": ErrorBody, "description": "No such entry for the caller; no_file: it has no file yet"},
}


@router.post(
    "/sources/{source_id}/conversions",
    summary="Ask for the conversion of the entry's file into blocks",
    status_code=202,
    responses={
        200: {"model": ConversionOut, "description": "The conversion there: waiting, running or done"},
        **CONTENT_REFUSALS,
        403: {
            "model": ErrorBody,
            "description": "file_hidden: the entry's file is for its editors only; no_pages: the account"
            " has no pages left for an engine that costs",
        },
        422: {
            "model": ErrorBody,
            "description": "not_pdf: the file is of no type the engines asked of read; engine_not_offered:"
            " the service converts with another",
        },
        429: {"model": ErrorBody, "description": "too_many_conversions: started too many this minute"},
    },
)
async def ask_conversion(
    source_id: UUID,
    request: Request,
    response: Response,
    who: Account,
    body: Annotated[ConversionRequest | None, Body()] = None,
) -> ConversionOut:
    settings = request.app.state.settings
    named = (body or ConversionRequest()).engine
    if named is not None and named not in settings.conversion_engine_list:
        offered = ", ".join(settings.conversion_engine_list)
        raise Refusal(422, "engine_not_offered", f"The service converts with {offered}.")
    assert who.account_id is not None  # noqa: S101 - require_account refuses visitors
    async with request.app.state.pool.connection() as connection, connection.transaction():
        row = await content_row(connection, who, settings, source_id)
        file_id = _file_of(row)
        mime = row["mime"]
        reading = readers(settings.conversion_engine_list, mime, row["file_name"])
        if not reading or (named is not None and named not in reading):
            raise _not_read([named] if named else settings.conversion_engine_list)
        engine = named or await _engine_for(connection, reading, who.account_id, file_id)
        await lock_conversion(connection, file_id, engine)
        there = await conversion_for(connection, file_id, engine)
        if there is not None and there.status != "failed":
            response.status_code = 200
            return _out(there, who)
        if engine in BILLABLE:
            await admit_pages(connection, who.account_id)
        # one limit for every engine's conversions, named by the first kind
        await within_limit(
            connection, who.account_id, KIND, settings.conversions_per_minute, "too_many_conversions"
        )
        conversion_id = there.id if there else new_id()
        job_id = await enqueue(
            connection,
            kind_of(engine),
            account_lane(who.account_id),
            {"conversion_id": str(conversion_id), "mime": mime},
        )
        await start_conversion(
            connection,
            conversion_id,
            source_file_id=file_id,
            engine=engine,
            account_id=who.account_id,
            job_id=job_id,
        )
        await record_audit(
            connection,
            who.account_id,
            who.name,
            "source.convert",
            f"source:{source_id}",
            {"conversion": str(conversion_id), "job": str(job_id), "engine": engine},
            current_request_id(),
        )
        started = await conversion_for(connection, file_id, engine)
    assert started is not None  # noqa: S101 - started in this transaction
    return _out(started, who)


@router.get(
    "/sources/{source_id}/conversion",
    summary="The conversion of the entry's file: how far it is, its pages and findings",
    responses={
        403: CONTENT_REFUSALS[403],
        404: {
            "model": ErrorBody,
            "description": "No such entry for the caller; no_file: it has no file yet; no_conversion: none"
            " was asked for",
        },
    },
)
async def get_conversion(
    source_id: UUID, request: Request, who: Caller, engine: EngineName | None = None
) -> ConversionOut:
    if who.anonymous and not visitors_may_read(request.app.state.settings):
        raise refuse_visitor()
    async with request.app.state.pool.connection() as connection:
        state = await _conversion(connection, who, request, source_id, engine)
    return _out(state, who)


@router.get(
    "/sources/{source_id}/conversion/blocks",
    summary="The blocks of one page of the converted file, in reading order",
    responses={
        403: CONTENT_REFUSALS[403],
        404: {
            "model": ErrorBody,
            "description": "No such entry for the caller; no_file; no_conversion; no_such_page: the file"
            " has fewer pages",
        },
        409: {"model": ErrorBody, "description": "not_converted: the conversion is not done"},
    },
)
async def get_blocks(
    source_id: UUID,
    request: Request,
    who: Caller,
    page: Annotated[int, Query(ge=1, le=100_000)],
    engine: EngineName | None = None,
) -> PageOut:
    if who.anonymous and not visitors_may_read(request.app.state.settings):
        raise refuse_visitor()
    async with request.app.state.pool.connection() as connection:
        state = await _conversion(connection, who, request, source_id, engine)
        if state.status != "done" or state.pages is None or state.printed_pages is None:
            raise Refusal(409, "not_converted", "The conversion is not done.")
        if page > state.pages:
            raise Refusal(404, "no_such_page", f"The file has {state.pages} pages.")
        blocks, continued = await read_page(connection, state.id, page)
    return PageOut(page=page, printed_page=state.printed_pages[page - 1], blocks=blocks, continued=continued)


async def read_page(
    connection: Any, conversion_id: UUID, page: int
) -> tuple[list[Block], list[ContinuedOut]]:
    """A page of a conversion as answered: its blocks in reading order, and the tables begun on an earlier
    page that run onto it (also the document's page, app/api/document_blocks.py)."""
    blocks = await blocks_on_page(connection, conversion_id, page)
    running = await tables_running_onto(connection, conversion_id, page)
    return blocks, [
        ContinuedOut(id=table.block_id, page=table.page, cells=list(table.cells)) for table in running
    ]


_KINDS = {mime: ending[1:].upper() for mime, ending in ENDINGS.items()}  # PDF, DOCX, HTML


def _not_read(engines: list[str]) -> Refusal:
    kinds = [_KINDS[mime] for mime in ENDINGS if any(mime in READS[engine] for engine in engines)]
    return Refusal(
        422, "not_pdf", f"Converted with {' or '.join(engines)} are {', '.join(kinds)} files; this is none."
    )


async def _engine_for(connection: Any, offered: list[str], account_id: UUID, file_id: UUID) -> str:
    """The engine asked of where none is named, of those ``offered`` that read the file's type: that of a
    conversion of the file there and not failed - it costs nothing -, else the first offered whose pages
    the account may spend on, a free one's always, but one that failed on this file for this account's
    want of pages, or because it reads no scan and the file is one; else the first offered that could
    read it (and its refusal, no_pages)."""
    there = {engine: await conversion_for(connection, file_id, engine) for engine in offered}
    standing = [engine for engine, state in there.items() if state is not None and state.status != "failed"]
    if standing:
        return standing[0]
    left: int | None = None
    if any(engine in BILLABLE for engine in offered):
        left = (await usage_of(connection, account_id)).pages_left
    # asked again, an engine that reads no scan would fail on the scan again; Docling refused one too before
    # it read scans (3b-1): that says nothing of it now
    unread = {
        engine
        for engine, state in there.items()
        if state and state.error_code == "needs_ocr" and engine not in READS_SCANS
    }
    for engine in offered:
        failed = there[engine]
        wanting = failed is not None and failed.error_code == "no_pages" and failed.account_id == account_id
        if engine not in unread and (engine not in BILLABLE or (left != 0 and not wanting)):
            return engine
    return next((engine for engine in offered if engine not in unread), offered[0])


async def _conversion(
    connection: Any, who: Principal, request: Request, source_id: UUID, engine: str | None
) -> ConversionState:
    """The conversion by ``engine``; where none is named, the first there and not failed in the order the
    service offers its engines, then by one it no longer offers - a failed one only where no other is."""
    settings = request.app.state.settings
    row = await content_row(connection, who, settings, source_id)
    offered = settings.conversion_engine_list
    names = [engine] if engine else [*offered, *(name for name in offered_engines() if name not in offered)]
    found = [
        state
        for name in names
        if (state := await conversion_for(connection, _file_of(row), name)) is not None
    ]
    if not found:
        raise Refusal(404, "no_conversion", "The entry's file has not been converted.")
    return next((state for state in found if state.status != "failed"), found[0])


def _file_of(row: dict[str, Any]) -> UUID:
    if row["file_id"] is None:
        raise Refusal(404, "no_file", "The entry has no file yet.")
    file_id: UUID = row["file_id"]
    return file_id


def _out(state: ConversionState, who: Principal) -> ConversionOut:
    follows = "admin" in who.roles or (
        who.account_id is not None and state.job_lane == account_lane(who.account_id)
    )
    return ConversionOut(
        id=state.id,
        engine=state.engine,  # the table's CHECK holds it to EngineName; pydantic checks it again
        engine_version=state.engine_version,
        status=state.status,
        error_code=state.error_code,
        job_id=state.job_id if follows else None,
        pages=state.pages,
        printed_pages=state.printed_pages,
        findings=[FindingOut(**finding) for finding in state.findings],
        created_at=state.created_at,
        finished_at=state.finished_at,
    )
