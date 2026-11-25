"""The Kern export of a frozen document (plan M3a C2, E6, E8): ``GET /documents/{id}/kern.ttl`` gives its
Curriculum-Kern 1.0 graph as Turtle under the IRIs freezing gave (app/exports/kern_export.py) - an extracted
document's as an import's from MEM-Schule, which keeps its MEM export beside it (app/api/exports.py) - by who
may read the document and its entry's content (404 ``no_document``, 403 ``file_hidden``). Only a frozen
document is exported (409 ``export_not_frozen``), only one whose rows all have their IRIs (409
``export_unnamed``: frozen before its specifications were named, until ``python -m app.db.name_frozen``
ran); a build that did not end in its time is no answer (503 ``export_unavailable``, try again), nor one gone
from the store between its build and its reading. Exports of both kinds are counted together per account
and minute (429 ``too_many_exports``, EXPORTS_PER_MINUTE). The violations the editors accepted when they
froze it are counted in a header (``Curricarta-Accepted-Violations``), as in the file's head (plan M3a E7);
where X5 checked it under another graph than is built now, ``Curricarta-Graph-Version`` names both
(``checked=unknown; built=1``), as the file's head does.

The database connections are let go before the build: it runs in a child process for seconds.
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
from app.exports.kern_child import checked_under
from app.exports.kern_export import ExportUnnamed, KernExporter
from app.exports.kern_rows import read_document
from app.exports.mem_export import ExportUnavailable

router = APIRouter(prefix="/api/v1", tags=["documents"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
RETRY_AFTER_S = 30
VIOLATIONS_HEADER = "Curricarta-Accepted-Violations"
GRAPH_HEADER = "Curricarta-Graph-Version"


@router.get(
    "/documents/{document_id}/kern.ttl",
    summary="Export a frozen document as Curriculum-Kern RDF (Turtle), under the IRIs freezing gave",
    status_code=200,  # FastAPI reads it from the response class's signature otherwise
    response_class=ObjectDownload,
    responses={
        200: {
            "content": {"text/turtle": {"schema": {"type": "string", "format": "binary"}}},
            "description": "The document's Kern Turtle, as a download; the violations the editors accepted "
            f"when they froze it in {VIOLATIONS_HEADER}; where X5 checked it under another graph than is "
            f"built now, both versions in {GRAPH_HEADER} (checked=unknown; built=1)",
        },
        403: {
            "model": ErrorBody,
            "description": "file_hidden: the entry's content is not the caller's to read",
        },
        404: {"model": ErrorBody, "description": "no_document: none the caller may read"},
        409: {
            "model": ErrorBody,
            "description": "export_not_frozen; export_unnamed: frozen before its specifications were named "
            "(python -m app.db.name_frozen)",
        },
        429: {"model": ErrorBody, "description": "too_many_exports: wait and try again"},
        503: {"model": ErrorBody, "description": "export_unavailable: the build did not end, try again"},
    },
)
async def export_kern(document_id: UUID, request: Request, who: Account) -> ObjectDownload:
    assert who.account_id is not None  # noqa: S101 - require_account refuses visitors
    settings = request.app.state.settings
    async with request.app.state.pool.connection() as connection:
        document = await readable_document(connection, who, settings, document_id)
        if document.frozen_at is None:
            raise Refusal(409, "export_not_frozen", "Only a frozen document is exported: freeze it first.")
        await within_limit(
            connection, who.account_id, "export", settings.exports_per_minute, "too_many_exports"
        )
    async with request.app.state.pool.connection() as connection:  # idle: the rows in one snapshot
        rows = await read_document(connection, document.id)
    exporter: KernExporter = request.app.state.kern_exporter
    try:
        made = await exporter.export(rows)
    except ExportUnnamed:
        raise Refusal(
            409, "export_unnamed",
            "The document was frozen before its specifications were named: the operators name them with "
            "python -m app.db.name_frozen.",
        ) from None  # fmt: skip
    except ExportUnavailable:
        raise Refusal(
            503, "export_unavailable", "The export was not built in its time: try again.",
            {"Retry-After": str(RETRY_AFTER_S)},
        ) from None  # fmt: skip
    try:
        stream = await request.app.state.storage.open_stream(made.key)
    except ObjectNotFound:  # taken from the store since the exporter looked: the next request makes it anew
        raise Refusal(
            503, "export_unavailable", "The export is being made anew: try again.",
            {"Retry-After": str(RETRY_AFTER_S)},
        ) from None  # fmt: skip
    headers = {
        "Content-Disposition": f'attachment; filename="kern-{document.id}-r{rows.document["revision"]}.ttl"',
        "Cache-Control": "private, no-store",
        VIOLATIONS_HEADER: str(rows.document["violations"]),
    }
    if (versions := checked_under(rows.document)) is not None:
        headers[GRAPH_HEADER] = versions
    if stream.size is not None:
        headers["Content-Length"] = str(stream.size)
    return ObjectDownload(stream, media_type="text/turtle; charset=utf-8", headers=headers)
