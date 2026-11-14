"""The source register: what an account brings in - uploads (plan M1, 1.7) and imports by URL
(1.8); reading and keeping the register are app/api/source_register.py (1.9, 1.10).

The upload route has no body parameter on purpose: FastAPI reads such a body before it checks
the token, so the form is read here, after it. BodyLimit (app/api/body_limit.py) bounds the body
before anything reads it; the form parser spools the file in pieces and counts it, and a file
past MAX_UPLOAD_MB is refused by that count before any of it is read. The spooled file is then
examined and stored a piece at a time, never held whole: under 10 MiB of memory an upload, whatever
its size (examine_file says what it holds). A process takes
MAX_CONCURRENT_UPLOADS uploads at once (audit 2026-11-14), each from before its form is read to
after its file is stored: one more waits UPLOAD_WAIT_S, holding no connection, then is told to
come back.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.datastructures import UploadFile

from app.api.body_limit import MIB
from app.api.deps import require_account
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.limits import within_limit
from app.core.auth import Principal, plain_text
from app.core.logging import current_request_id
from app.db.accounts import record_audit
from app.db.sources import StoredFile, record_upload, record_url_source
from app.jobs.queue import account_lane, enqueue
from app.sources import fetch_job
from app.sources.archives import ArchiveTooLarge, ArchiveUnreadable
from app.sources.filetype import (
    MAX_NAME_SIGNS,
    DetectedType,
    UnsupportedType,
    base_name,
    examine_file,
    stored_name,
)
from app.sources.register import Provenance, RegisterStatus, RightsStatus
from app.sources.url_fetch import UrlNotAllowed, check_url

router = APIRouter(prefix="/api/v1", tags=["sources"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
UPLOAD_PATH = "/api/v1/sources"
MAX_TITLE_SIGNS = 500
UPLOAD_WAIT_S = 10.0  # how long an upload waits for a slot of the process before it is sent back


def _limit_refusal(code: str, actions: str) -> dict[str, Any]:
    """The 429 of a route with a limit per account, beside the sign-in limit every route has."""
    description = (
        f"{code}: the account's {actions} of the minute are used up (Retry-After);"
        " too_many_requests: too many failed sign-ins from this address"
    )
    return {"model": ErrorBody, "description": description}


UPLOAD_REFUSALS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorBody, "description": "The form cannot be read, or holds more than one file"},
    413: {"model": ErrorBody, "description": "The file, or the archive it is, is too large"},
    415: {"model": ErrorBody, "description": "No type a conversion reads"},
    429: _limit_refusal("too_many_uploads", "uploads"),
    503: {
        "model": ErrorBody,
        "description": "uploads_busy: the process takes no more uploads now (Retry-After)",
    },
}
# The form as the route reads it itself: a body parameter would be read before the token check
UPLOAD_FORM = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary", "description": "Up to MAX_UPLOAD_MB"},
                        "title": {
                            "type": "string",
                            "maxLength": MAX_TITLE_SIGNS,
                            "description": "The entry's title; else the file's name names it",
                        },
                    },
                }
            }
        },
    }
}


class SourceFileOut(BaseModel):
    name: str
    mime: str
    size: int
    sha256: str


class SourceOut(BaseModel):
    id: UUID
    title: str
    provenance: Provenance
    rights_status: RightsStatus
    register_status: RegisterStatus
    file: SourceFileOut | None


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    # checked as the upload form's is, with the same codes (_checked_title); the spec names the bound
    title: Annotated[str, Field(json_schema_extra={"maxLength": MAX_TITLE_SIGNS})] = ""


class ImportOut(BaseModel):
    source: SourceOut
    job_id: UUID


@router.post(
    "/sources",
    status_code=201,
    summary="Upload a curriculum document",
    responses=UPLOAD_REFUSALS,
    openapi_extra=UPLOAD_FORM,
)
async def upload_source(request: Request, who: Account) -> SourceOut:
    """A form with ``file`` and, if wished, ``title`` (else the file's name names the entry)."""
    settings = request.app.state.settings
    assert who.account_id is not None  # noqa: S101 - require_account refuses visitors
    async with request.app.state.pool.connection() as connection:
        await within_limit(
            connection, who.account_id, "source.upload", settings.uploads_per_minute, "too_many_uploads"
        )
    # the slot first: a form waiting for one would hold its spooled file in /tmp
    async with _upload_slot(request.app.state.upload_slots), request.form(max_files=1, max_fields=2) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise Refusal(422, "file_missing", "The form holds no file.")
        given_title = form.get("title")
        received = upload.filename or ""
        detected, digest, size = await asyncio.to_thread(_examined, upload, settings.max_upload_mb * MIB)
        file_name = stored_name(received, detected)
        title = _title(given_title if isinstance(given_title, str) else None, file_name)
        stored = StoredFile(
            sha256=digest, size=size, mime=detected.mime, storage_key=f"sources/{digest.hex()}"
        )
        storage = request.app.state.storage
        if not await storage.exists(stored.storage_key):  # the same bytes are stored once
            # from the spooled file the digest was taken of; it goes with the form
            await storage.put_file(stored.storage_key, upload.file, size)
    async with request.app.state.pool.connection() as connection, connection.transaction():
        source_id = await record_upload(
            connection,
            owner=who.account_id,
            stored=stored,
            file_name=file_name,
            received_name=base_name(received)[:MAX_NAME_SIGNS],
            title=title,
        )
        details = {"sha256": digest.hex(), "size": size, "mime": detected.mime}
        await record_audit(
            connection,
            who.account_id,
            who.name,
            "source.upload",
            f"source:{source_id}",
            details,
            current_request_id(),
        )
    return SourceOut(
        id=source_id,
        title=title,
        provenance="upload",
        rights_status="unklar",
        register_status="acquired",
        file=SourceFileOut(name=file_name, mime=detected.mime, size=size, sha256=digest.hex()),
    )


@router.post(
    "/sources/import",
    status_code=202,
    summary="Import a curriculum document by its URL",
    responses={429: _limit_refusal("too_many_imports", "imports")},
)
async def import_source(body: ImportIn, request: Request, who: Account) -> ImportOut:
    """The register entry now, unchecked; its fetch as a job (``GET /api/v1/jobs/{id}``)."""
    try:
        url = check_url(body.url)
    except UrlNotAllowed as error:
        raise Refusal(422, "url_invalid", str(error)) from None
    title = _checked_title(body.title)
    settings = request.app.state.settings
    assert who.account_id is not None  # noqa: S101 - require_account refuses visitors
    async with request.app.state.pool.connection() as connection:
        await within_limit(
            connection, who.account_id, "source.import", settings.url_imports_per_minute, "too_many_imports"
        )
        # one transaction: never an entry without its job, nor a job without its entry
        async with connection.transaction():
            source_id = await record_url_source(connection, owner=who.account_id, url=url, title=title)
            job_id = await enqueue(
                connection, fetch_job.KIND, account_lane(who.account_id), {"source_id": str(source_id)}
            )
            # the host only: a query may carry a token of the portal's
            details = {"host": urlsplit(url).hostname, "job": str(job_id)}
            await record_audit(
                connection,
                who.account_id,
                who.name,
                "source.import",
                f"source:{source_id}",
                details,
                current_request_id(),
            )
    source = SourceOut(
        id=source_id,
        title=title,
        provenance="url",
        rights_status="unklar",
        register_status="unchecked",
        file=None,
    )
    return ImportOut(source=source, job_id=job_id)


@asynccontextmanager
async def _upload_slot(slots: asyncio.Semaphore) -> AsyncIterator[None]:
    """One of the process's upload slots, held for the block and given back however it ends; a
    wait past ``UPLOAD_WAIT_S`` is refused before anything of the body is read."""
    try:
        async with asyncio.timeout(UPLOAD_WAIT_S):
            await slots.acquire()
    except TimeoutError:
        raise Refusal(
            503, "uploads_busy", "The service takes no more uploads now: try again.", {"Retry-After": "5"}
        ) from None
    try:
        yield
    finally:
        slots.release()


def _examined(upload: UploadFile, limit: int) -> tuple[DetectedType, bytes, int]:
    """``examine_file`` of the file the form parser spooled (to /tmp past a MiB), never held whole;
    its refusals as the API words them. The parser counted the file as it spooled it: a file past
    ``limit`` is refused before any of it is read. Blocks: run in a thread."""
    if upload.size is not None and upload.size > limit:
        raise _too_large(limit)
    try:
        detected, digest, size = examine_file(upload.filename, upload.file)
    except (UnsupportedType, ArchiveUnreadable):
        raise Refusal(415, "unsupported_type", "The file is of no type a conversion reads.") from None
    except ArchiveTooLarge:
        raise Refusal(413, "archive_too_large", "The archive expands beyond what a document holds.") from None
    if size > limit:  # a file the parser did not count
        raise _too_large(limit)
    return detected, digest, size


def _too_large(limit: int) -> Refusal:
    return Refusal(413, "file_too_large", f"The file is larger than {limit // MIB} MB.")


def _title(given: str | None, file_name: str) -> str:
    """The upload's title: the one given, else the file's name without its ending."""
    if given is None or not given.strip():
        # the stem trimmed ("Lehrplan .pdf"); should nothing be left, the whole name
        return PurePosixPath(file_name).stem[:MAX_TITLE_SIGNS].strip() or file_name[:MAX_TITLE_SIGNS]
    return _checked_title(given)


def _checked_title(given: str) -> str:
    """A title as a caller gave it (upload form, import), trimmed and in one spelling; refused
    with a code of its own when it hides signs or is too long. Empty stays empty."""
    try:
        title = plain_text(given.strip())
    except ValueError:
        raise Refusal(422, "title_invalid", "The title holds control or invisible signs.") from None
    if len(title) > MAX_TITLE_SIGNS:
        raise Refusal(422, "title_too_long", f"The title is longer than {MAX_TITLE_SIGNS} signs.")
    return title
