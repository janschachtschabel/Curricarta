"""Taking a document or a register entry away (H-4e): DELETE /api/v1/documents/{id} and
/api/v1/sources/{id}, 204 with no body.

A document goes with all it holds, by whom sees it - its owner, the editors, the admins (as the editor's
routes; app/api/document_access.py) -, never frozen and never beside its job waiting or running. Its entry,
its conversion, its jobs and the ledger's bookings stay. An entry goes by its owner, or by an editor or an
admin where it has an owner; never a seed entry, one with documents, or one whose fetch or a conversion
of its file waits or runs. Its file goes after, where no other entry holds it.

The store's part follows the commit (app/emptying.py): a document's runs and exports are emptied by the
request as far as the store lets it, the rest by the next sweep (python -m app.retention); a file's object
by the sweep alone, under the file's lock."""

import logging
from typing import Annotated, Any, assert_never
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import require_account
from app.api.document_access import visible_document
from app.api.edit_answers import REFUSED, audit, refusal_of
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.source_content import EDITORS
from app.core.auth import Principal
from app.db.deleting import EntryHeld, drop_document, drop_orphan_file, drop_source
from app.db.editing import guard_document
from app.db.source_queries import Reader, get_source
from app.emptying import sweep_prefixes

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
Responses = dict[int | str, dict[str, Any]]

DOCUMENT_RESPONSES: Responses = {
    404: {"model": ErrorBody, "description": "no_document: none the caller may read"},
    409: {
        "model": ErrorBody,
        "description": "frozen: a frozen document stays; job_open (details.job_id to the owner and the"
        " admins): its job waits or runs",
    },
}
SOURCE_RESPONSES: Responses = {
    404: {"model": ErrorBody, "description": "No such entry for the caller"},
    409: {
        "model": ErrorBody,
        "description": "seed_entry: an entry of no account stays; has_documents (details.documents: how"
        " many): its documents go first; job_open (details.job_id to the owner and the admins): its fetch"
        " or a conversion of its file waits or runs",
    },
}


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    tags=["documents"],
    summary="Take a document away with all it holds; its entry and conversion stay",
    responses=DOCUMENT_RESPONSES,
)
async def delete_document(document_id: UUID, request: Request, who: Account) -> Response:
    async with request.app.state.pool.connection() as connection:
        try:
            async with connection.transaction():
                document = await visible_document(connection, who, document_id)
                await guard_document(connection, document_id)  # the tree's lock; frozen, job_open
                places = await drop_document(connection, document_id)
                if places is None:  # taken away meanwhile
                    raise Refusal(404, "no_document", "No such document.")
                details = {"source": str(document.source_id), "revision": document.revision}
                await audit(connection, who, "document.delete", f"document:{document_id}", details)
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
    await sweep_prefixes(request.app.state.pool, request.app.state.storage, places)
    return Response(status_code=204)


@router.delete(
    "/sources/{source_id}",
    status_code=204,
    tags=["sources"],
    summary="Take a register entry away; its file goes where no other entry holds it",
    responses=SOURCE_RESPONSES,
)
async def delete_source(source_id: UUID, request: Request, who: Account) -> Response:
    assert who.account_id is not None  # noqa: S101 - require_account refuses visitors
    editor = bool(who.roles & EDITORS)
    async with request.app.state.pool.connection() as connection:
        async with connection.transaction():
            found = await get_source(connection, Reader(who.account_id, editor), source_id, for_update=True)
            if found is None:
                raise HTTPException(404, "No such register entry.")
            entry, _ = found
            try:
                await drop_source(connection, source_id, entry)
            except EntryHeld as held:
                named = "admin" in who.roles or entry["owner_id"] == who.account_id
                raise _refusal(held, named=named) from held
            details = {"sha256": None if entry["sha256"] is None else bytes(entry["sha256"]).hex()}
            await audit(connection, who, "source.delete", f"source:{source_id}", details)
        if entry["file_id"] is not None:
            # a transaction of its own, under the file's lock, which an upload of the same bytes waits for;
            # a failure leaves the file to the sweep, which looks for files no entry holds
            try:
                async with connection.transaction():
                    await drop_orphan_file(connection, entry["file_id"])
            except psycopg.Error as error:
                log.warning("the file of a taken entry stays for the sweep: %s", type(error).__name__)
    return Response(status_code=204)


def _refusal(held: EntryHeld, *, named: bool) -> Refusal:
    match held.code:
        case "seed_entry":
            return Refusal(409, "seed_entry", "An entry of no account stays in the register.")
        case "has_documents":
            return Refusal(
                409,
                "has_documents",
                "Documents were made of the entry: take them away first.",
                details={"documents": held.count},
            )
        case "job_open":
            return Refusal(
                409,
                "job_open",
                "A job of the entry waits or runs: take it away once that has ended.",
                details={"job_id": str(held.job_id)} if named else None,
            )
        case _:
            assert_never(held.code)
