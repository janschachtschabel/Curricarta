"""The export of a frozen MEM import (plan M2-6, E10; Nachtrag M2-1): ``GET /documents/{id}/export.ttl``
gives MEM's own RDF of it as Turtle, checked against the MEM shapes (app/exports/mem_export.py) - by who
may read the document and its entry's content (404 ``no_document``, 403 ``file_hidden``). Only a frozen
document is exported (409 ``export_not_frozen``), only an import (409 ``not_mem_import``); a state the shapes
refuse is not (409 ``export_invalid``, its violations by row, at most MAX_LISTED of them); a check that did
not end in its time is no answer (503 ``export_unavailable``, try again), nor one gone from the store
between its look and its reading; exports are counted per account and minute, once the document is one to
export (429 ``too_many_exports``, EXPORTS_PER_MINUTE).

The database connections are let go before the check: it runs in a child process for seconds.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_account
from app.api.document_access import readable_document
from app.api.downloads import ObjectDownload
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.limits import within_limit
from app.core.auth import Principal
from app.core.storage import ObjectNotFound
from app.exports.mem_export import ExportUnavailable, Invalid, MemExporter, violation_dict
from app.exports.mem_rows import read_mem_document

router = APIRouter(prefix="/api/v1", tags=["documents"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
MAX_LISTED = 200  # violations named in a refusal; ``total`` counts them all
RETRY_AFTER_S = 30


@router.get(
    "/documents/{document_id}/export.ttl",
    summary="Export a frozen import from MEM-Schule as MEM's RDF (Turtle), checked against the MEM shapes",
    status_code=200,  # FastAPI reads it from the response class's signature otherwise
    response_class=ObjectDownload,
    responses={
        200: {
            "content": {"text/turtle": {"schema": {"type": "string", "format": "binary"}}},
            "description": "The document's MEM Turtle, as a download",
        },
        403: {
            "model": ErrorBody,
            "description": "file_hidden: the entry's content is not the caller's to read",
        },
        404: {"model": ErrorBody, "description": "no_document: none the caller may read"},
        409: {
            "model": ErrorBody,
            "description": "export_not_frozen, not_mem_import; export_invalid: details.violations, .total",
        },
        429: {"model": ErrorBody, "description": "too_many_exports: wait and try again"},
        503: {"model": ErrorBody, "description": "export_unavailable: the check did not end, try again"},
    },
)
async def export_mem(document_id: UUID, request: Request, who: Account) -> ObjectDownload:
    assert who.account_id is not None  # noqa: S101 - require_account refuses visitors
    settings = request.app.state.settings
    async with request.app.state.pool.connection() as connection:
        document = await readable_document(connection, who, settings, document_id)
        # what never changes first: a freeze would not make an export of a document of no import
        if document.mem_iri is None:
            raise Refusal(409, "not_mem_import", "Only an import from MEM-Schule is exported as MEM's RDF.")
        if document.frozen_at is None:
            raise Refusal(409, "export_not_frozen", "Only a frozen document is exported: freeze it first.")
        await within_limit(
            connection, who.account_id, "export", settings.exports_per_minute, "too_many_exports"
        )
    async with request.app.state.pool.connection() as connection:  # idle: the rows in one snapshot
        rows = await read_mem_document(connection, document.id)
    exporter: MemExporter = request.app.state.mem_exporter
    try:
        made = await exporter.export(rows)
    except ExportUnavailable:
        raise Refusal(
            503, "export_unavailable", "The check of the export did not end: try again.",
            {"Retry-After": str(RETRY_AFTER_S)},
        ) from None  # fmt: skip
    if isinstance(made, Invalid):
        raise Refusal(
            409, "export_invalid", "The document does not meet the MEM shapes: see the violations.",
            details={"total": len(made.violations),
                     "violations": [violation_dict(found) for found in made.violations[:MAX_LISTED]]},
        )  # fmt: skip
    try:
        stream = await request.app.state.storage.open_stream(made.key)
    except ObjectNotFound:  # taken from the store since the exporter looked: the next request makes it anew
        raise Refusal(
            503, "export_unavailable", "The export is being made anew: try again.",
            {"Retry-After": str(RETRY_AFTER_S)},
        ) from None  # fmt: skip
    headers = {
        "Content-Disposition": f'attachment; filename="mem-{document.id}.ttl"',
        "Cache-Control": "private, no-store",
    }
    if stream.size is not None:
        headers["Content-Length"] = str(stream.size)
    return ObjectDownload(stream, media_type="text/turtle; charset=utf-8", headers=headers)
