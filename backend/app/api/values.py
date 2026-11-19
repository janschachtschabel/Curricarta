"""The second layer's values of a holder set by an editor (plan M3a E2, E11; app/db/values.py): a node's
levels, time spans and workloads, a statement's levels - each set as a whole on the holder's revision, a
value named by its ``id`` kept, one left out gone, a new or changed one an editor's proposal. By the
document's owner and the editors; answered with the holder as the tree has it (GET /documents/{id}/tree,
``values``), refused as app/api/edit_answers.py says - a value the form does not take as ``invalid_field``
with its path in the set (app/vocab/value_checks.py), a stale revision with the holder as it stands.
Audited by counts, never by what the values say. A specification's values follow with its editing.
"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Annotated, Any, Final
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.deps import require_account
from app.api.document_access import readable_document, reader
from app.api.document_tree import NodeRowOut, StatementOut, node_as_read, statement_as_read
from app.api.edit_answers import HIDDEN, REFUSED, Responses, answers, audit, refusal_of, stale
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.core.auth import Principal
from app.db.editing import DOCUMENT_OF_NODE, StaleRevision, target_of
from app.db.statement_editing import DOCUMENT_OF_STATEMENT
from app.db.values import UnknownValue, ValueRefused, replace_values, values_of
from app.domain.l2 import Holder, HolderKind, LevelDraft, TimeSpanDraft, ValueDrafts, WorkloadDraft
from app.vocab.form_values import FieldError
from app.vocab.value_checks import check_values, kind_of_check, path_of
from app.vocab.value_forms import value_form_of

router = APIRouter(prefix="/api/v1", tags=["documents"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
_DOCUMENT_OF: Final[dict[HolderKind, str]] = {"node": DOCUMENT_OF_NODE, "statement": DOCUMENT_OF_STATEMENT}
MOST_VALUES: Final = 20  # of a kind at a holder, and periods of a workload
# a concept's IRI; one no list offers is refused by the form, unechoed
Iri = Annotated[str, StringConstraints(min_length=1, max_length=500)]
# a value's number: at most 15 digits, which a JSON number answers back unchanged (app/api/value_answers.py)
Number = Annotated[Decimal, Field(ge=0, max_digits=15, allow_inf_nan=False)]
VALUE_RESPONSES: Responses = {
    409: {
        "model": ErrorBody,
        "description": "stale_revision (details.current: the holder as it stands), job_open (details.job_id"
        " to the owner and the admins), frozen, not_extracted (X4 has not read every package)",
    },
    422: {
        "model": ErrorBody,
        "description": "invalid_field (details: field - its path in the set, workloads[1].unit -, problem)",
    },
}


class LevelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None  # a value of the holder's kept; none a new one
    level: Iri
    level_to: Iri | None = None
    relation: Iri | None = None
    dimension: Iri | None = None
    competence_dimension: Iri | None = None


class TimeSpanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    time_kind: Iri
    span_from: Number | None = None
    span_to: Number | None = None
    time_relation: Iri | None = None


class WorkloadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    amount: Number
    amount_to: Number | None = None
    unit: Iri
    workload_kind: Iri | None = None
    is_recommendation: bool = False
    minutes_per_unit: int | None = Field(default=None, ge=1, le=2**31 - 1)  # the store's integer
    total: bool = False
    periods: list[TimeSpanIn] = Field(default=[], max_length=MOST_VALUES)


class ValuesIn(BaseModel):
    """The holder's values, every kind named: what the set leaves out goes."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)  # the holder's, as it was read
    level_assignments: list[LevelIn] = Field(max_length=MOST_VALUES)
    time_spans: list[TimeSpanIn] = Field(max_length=MOST_VALUES)
    workloads: list[WorkloadIn] = Field(max_length=MOST_VALUES)


@router.put(
    "/nodes/{node_id}/values",
    summary="Set a node's levels, time spans and workloads as a whole",
    responses=answers("no_node: none the caller may read", VALUE_RESPONSES) | HIDDEN,
)
async def set_node_values(node_id: UUID, body: ValuesIn, request: Request, who: Account) -> NodeRowOut:
    gone = Refusal(404, "no_node", "No such node.")
    found = await _set(request, who, Holder("node", node_id), body, node_as_read, gone)
    assert isinstance(found, NodeRowOut)  # noqa: S101 - the node's reader
    return found


@router.put(
    "/statements/{statement_id}/values",
    summary="Set a statement's levels as a whole",
    responses=answers("no_statement: none the caller may read", VALUE_RESPONSES) | HIDDEN,
)
async def set_statement_values(
    statement_id: UUID, body: ValuesIn, request: Request, who: Account
) -> StatementOut:
    gone = Refusal(404, "no_statement", "No such statement.")
    found = await _set(request, who, Holder("statement", statement_id), body, statement_as_read, gone)
    assert isinstance(found, StatementOut)  # noqa: S101 - the statement's reader
    return found


AsRead = Callable[[psycopg.AsyncConnection, Principal, UUID], Awaitable[BaseModel | None]]


async def _set(
    request: Request, who: Principal, holder: Holder, body: ValuesIn, as_read: AsRead, gone: Refusal
) -> BaseModel:
    """Set the holder's values to ``body``; the holder as the tree has it after, ``gone`` where there is none
    the caller may read."""
    async with request.app.state.pool.connection() as connection:
        document_id: UUID | None = None
        drafts = ValueDrafts()
        try:
            async with connection.transaction():
                target = await target_of(connection, _DOCUMENT_OF[holder.kind], reader(who), holder.id)
                if target is None:
                    raise gone
                document_id = target.document_id
                await readable_document(connection, who, request.app.state.settings, document_id)
                drafts = _drafts(body)
                held = (await values_of(connection, document_id)).get(holder)
                check_values(await value_form_of(connection), holder.kind, drafts, held)
                revision = await replace_values(
                    connection, reader(who), holder, body.expected_revision, drafts
                )
                if revision is None:  # taken away meanwhile
                    raise gone
                await audit(connection, who, f"{holder.kind}.values", f"{holder.kind}:{holder.id}", {
                    "document": str(document_id), "revision": revision, **_counts(drafts),
                })  # fmt: skip
        except StaleRevision as error:
            raise stale(holder.kind, await as_read(connection, who, holder.id)) from error
        except UnknownValue as error:
            refused = FieldError(path_of(drafts, error.value_id), "unknown_value")
            raise await refusal_of(connection, who, document_id, refused) from error
        except ValueRefused as error:
            refused = FieldError(kind_of_check(error.check), "refused")
            raise await refusal_of(connection, who, document_id, refused) from error
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
        read = await as_read(connection, who, holder.id)
    if read is None:  # taken away right after
        raise gone
    return read


def _drafts(body: ValuesIn) -> ValueDrafts:
    def span(entry: TimeSpanIn) -> TimeSpanDraft:
        return TimeSpanDraft(**entry.model_dump())

    return ValueDrafts(
        levels=tuple(LevelDraft(**entry.model_dump()) for entry in body.level_assignments),
        time_spans=tuple(span(entry) for entry in body.time_spans),
        workloads=tuple(
            WorkloadDraft(**entry.model_dump(exclude={"periods"}), periods=tuple(map(span, entry.periods)))
            for entry in body.workloads
        ),
    )


def _counts(drafts: ValueDrafts) -> dict[str, Any]:
    """What the audit says of a set: how many of each kind, never what they say."""
    return {
        "level_assignments": len(drafts.levels),
        "time_spans": len(drafts.time_spans),
        "workloads": len(drafts.workloads),
        "periods": sum(len(workload.periods) for workload in drafts.workloads),
    }
