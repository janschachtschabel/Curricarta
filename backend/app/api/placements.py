"""A node's placements set by an editor (plan M3a K, E11; app/db/placements.py): set as the node's whole on
its revision - one named by its ``id`` kept, one left out gone with its values, a new or changed one an
editor's proposal -, read with the tree (GET /documents/{id}/tree, ``placements`` at each node); and the time
spans and workloads of one placement set as a whole on its revision (app/api/values.py). By the document's
owner and the editors; refused as app/api/edit_answers.py says - a placement the store does not take as
``invalid_field`` with its path in the set and why (``placements[1].variant_id``), a stale revision with the
node or the placement as it stands, a stranger's as none at all. Audited by counts, never by what the
placements say."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require_account
from app.api.document_access import readable_document, reader
from app.api.document_tree import NodeRowOut, node_as_read
from app.api.edit_answers import HIDDEN, REFUSED, answers, audit, refusal_of, stale
from app.api.errors import AUTH_RESPONSES, Refusal
from app.api.placement_answers import PlacementOut, placement_out
from app.api.values import VALUE_RESPONSES, Iri, ValuesIn, set_values
from app.core.auth import Principal
from app.db.editing import DOCUMENT_OF_NODE, StaleRevision, target_of
from app.db.placement_rows import placements_of
from app.db.placements import DOCUMENT_OF_PLACEMENT, replace_placements
from app.domain.l2 import Holder
from app.domain.placements import MOST_PLACEMENTS, PlacementDraft

router = APIRouter(prefix="/api/v1", tags=["documents"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
# a grade weight: a number from 0, at most 15 digits, refused unechoed
Weight = Annotated[Decimal, Field(ge=0, max_digits=15, allow_inf_nan=False)]


class PlacementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None  # a placement of the node's kept; none a new one
    specification_id: UUID | None = None  # one of the document's, or
    variant_id: UUID | None = None  # one of its specifications' variants - one of the two at least
    in_node_id: UUID | None = None  # a node of the document, where in it
    obligation: Iri  # cv:Obligations
    grade_weight: Weight | None = None

    def draft(self) -> PlacementDraft:
        return PlacementDraft(**self.model_dump())


class PlacementsIn(BaseModel):
    """The node's placements, all of them: what the set leaves out goes."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)  # the node's, as it was read
    placements: list[PlacementIn] = Field(max_length=MOST_PLACEMENTS)


@router.put(
    "/nodes/{node_id}/placements",
    summary="Set where a node is placed - in which specifications and variants, how binding - as a whole",
    responses=answers("no_node: none the caller may read", VALUE_RESPONSES) | HIDDEN,
)
async def set_node_placements(
    node_id: UUID, body: PlacementsIn, request: Request, who: Account
) -> NodeRowOut:
    gone = Refusal(404, "no_node", "No such node.")
    drafts = [entry.draft() for entry in body.placements]
    async with request.app.state.pool.connection() as connection:
        document_id: UUID | None = None
        try:
            async with connection.transaction():
                target = await target_of(connection, DOCUMENT_OF_NODE, reader(who), node_id)
                if target is None:
                    raise gone
                document_id = target.document_id
                await readable_document(connection, who, request.app.state.settings, document_id)
                revision = await replace_placements(
                    connection, reader(who), node_id, body.expected_revision, drafts
                )
                if revision is None:  # taken away meanwhile
                    raise gone
                details = {"document": str(document_id), "revision": revision, "placements": len(drafts)}
                await audit(connection, who, "node.placements", f"node:{node_id}", details)
        except StaleRevision as error:
            raise stale("node", await node_as_read(connection, who, node_id)) from error
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
        read = await node_as_read(connection, who, node_id)
    if read is None:  # taken away right after
        raise gone
    return read


@router.put(
    "/placements/{placement_id}/values",
    summary="Set a placement's time spans and workloads as a whole",
    responses=answers("no_placement: none the caller may read", VALUE_RESPONSES) | HIDDEN,
)
async def set_placement_values(
    placement_id: UUID, body: ValuesIn, request: Request, who: Account
) -> PlacementOut:
    gone = Refusal(404, "no_placement", "No such placement.")
    found = await set_values(request, who, Holder("placement", placement_id), body, placement_as_read, gone)
    assert isinstance(found, PlacementOut)  # noqa: S101 - the placement's reader
    return found


async def placement_as_read(
    connection: psycopg.AsyncConnection, who: Principal, placement_id: UUID
) -> PlacementOut | None:
    """The placement as the tree has it, where the caller sees it."""
    target = await target_of(connection, DOCUMENT_OF_PLACEMENT, reader(who), placement_id)
    if target is None:
        return None
    found = await placements_of(connection, target.document_id)
    return next((placement_out(row) for row in found if row.id == placement_id), None)
