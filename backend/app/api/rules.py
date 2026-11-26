"""A document's rules for the editors (plan M3a I, E10; app/db/rules.py): read by who reads the document's
content, with what they may name - its specifications, their variants and its nodes - and the units and kinds
of requirement to choose from; a rule's parsed values and links set on its revision, a rule added on blocks
chosen as a statement is, a rule taken away - rejected where a run read it, deleted where an editor made it -
by the document's owner and the editors. Refused as app/api/edit_answers.py says - a field the rule does not
take so as ``invalid_field``, a stale revision with the rule as it stands, a rule added nowhere as
``anchor_missing``; audited by the fields named, never by what they say.
"""

from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import require_account
from app.api.document_access import readable_content, readable_document, reader, visible_document
from app.api.document_tree import closed_of
from app.api.edit_answers import HIDDEN, REFUSED, Responses, answers, audit, refusal_of, stale
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.rule_answers import ChoiceOut, NewRuleIn, RuleEditIn, RuleOut, RulesOut, TargetOut, cut, rule_out
from app.api.source_content import EDITORS
from app.api.statement_editing import TakenOut
from app.core.auth import Principal
from app.db.editing import DOCUMENT, StaleRevision, extracted, target_of
from app.db.rule_rows import targets_of
from app.db.rules import DOCUMENT_OF_RULE, add_rule, drop_or_reject_rule, edit_rule, rules_of
from app.db.statement_editing import HandAnchor
from app.jobs.queue import open_job
from app.pipeline.extraction import unique_key
from app.vocab.form_values import FieldError
from app.vocab.lookup import concept_details

router = APIRouter(prefix="/api/v1", tags=["documents"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
Revision = Annotated[int, Query(ge=1, description="The rule's revision as it was read")]
NO_RULE = "no_rule: none the caller may read"
_CHOICES = {"units": "WorkloadUnits", "requirement_kinds": "RequirementKinds"}
_CLOSED = (
    "job_open (details.job_id to the owner and the admins), frozen,"
    " not_extracted (X4 has not read every package)"
)
RULE_RESPONSES: Responses = {
    409: {
        "model": ErrorBody,
        "description": f"stale_revision (details.current: the rule as it stands), {_CLOSED}",
    },
    422: {"model": ErrorBody, "description": "invalid_field (details: field, problem)"},
}
ADD_RESPONSES: Responses = RULE_RESPONSES | {
    409: {"model": ErrorBody, "description": _CLOSED},
    422: {"model": ErrorBody, "description": "invalid_field (details: field, problem), anchor_missing"},
}
TAKE_RESPONSES: Responses = {409: RULE_RESPONSES[409]}


@router.get(
    "/documents/{document_id}/rules",
    summary="The document's rules with what they apply to, their options and what they require",
    responses={
        403: {
            "model": ErrorBody,
            "description": "file_hidden: the entry's content is no longer yours to read",
        },
        404: {"model": ErrorBody, "description": "no_document: none the caller may read"},
    },
)
async def read_rules(document_id: UUID, request: Request, who: Account) -> RulesOut:
    async with request.app.state.pool.connection() as connection, connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        document = await visible_document(connection, who, document_id)
        await readable_content(connection, who, request.app.state.settings, document)
        found = await rules_of(connection, document_id)
        targets, said = await targets_of(connection, document_id)
        choices = {key: await _choices(connection, scheme) for key, scheme in _CHOICES.items()}
        job = await open_job(connection, unique_key(document_id))
        all_there = await extracted(connection, document_id)
    closed = closed_of(frozen=document.frozen_at is not None, job_open=job is not None, extracted=all_there)
    labels = {target.id: target.label for target in targets} | {key: cut(text) for key, text in said.items()}
    return RulesOut(
        editable=closed is None and (bool(who.roles & EDITORS) or document.owner_id == who.account_id),
        closed=closed,
        rules=[rule_out(rule, labels) for rule in found],
        targets=[TargetOut(id=target.id, kind=target.kind, label=target.label) for target in targets],
        **choices,
    )


@router.patch(
    "/rules/{rule_id}",
    summary="Set a rule's kind, wording, parsed values and links - the rule an editor's proposal after",
    responses=answers(NO_RULE, RULE_RESPONSES) | HIDDEN,
)
async def edit_a_rule(rule_id: UUID, body: RuleEditIn, request: Request, who: Account) -> RuleOut:
    given: dict[str, Any] = body.model_dump(include=body.model_fields_set - {"expected_revision"})
    async with request.app.state.pool.connection() as connection:
        document_id: UUID | None = None
        try:
            async with connection.transaction():
                document_id = await _document_of(connection, request, who, rule_id)
                revision = await edit_rule(connection, reader(who), rule_id, body.expected_revision, given)
                if revision is None:  # taken away meanwhile
                    raise _gone()
                details = {"document": str(document_id), "revision": revision, "fields": sorted(given)}
                await audit(connection, who, "rule.edit", f"rule:{rule_id}", details)
        except StaleRevision as error:
            raise stale("rule", await rule_as_read(connection, who, rule_id)) from error
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
        return await _read(connection, who, rule_id)


@router.post(
    "/documents/{document_id}/rules",
    status_code=201,
    summary="Add a rule after the document's others, on the blocks chosen - an editor's proposal",
    responses=answers("no_document: none the caller may read", ADD_RESPONSES) | HIDDEN,
)
async def add_a_rule(document_id: UUID, body: NewRuleIn, request: Request, who: Account) -> RuleOut:
    anchors = [HandAnchor(blocks=tuple(anchor.blocks), page=anchor.page) for anchor in body.anchors]
    async with request.app.state.pool.connection() as connection:
        try:
            async with connection.transaction():
                if await target_of(connection, DOCUMENT, reader(who), document_id) is None:
                    raise Refusal(404, "no_document", "No such document.")
                await readable_document(connection, who, request.app.state.settings, document_id)
                made = await add_rule(connection, reader(who), document_id, body.kind, body.verbatim, anchors)
                if made is None:  # taken away meanwhile
                    raise Refusal(404, "no_document", "No such document.")
                details = {"document": str(document_id), "kind": body.kind, "anchors": len(anchors)}
                await audit(connection, who, "rule.add", f"rule:{made}", details)
        except FieldError as error:
            if (error.key, error.problem) == ("anchors", "required"):
                raise Refusal(
                    422, "anchor_missing", "A rule stands somewhere in its source: name where."
                ) from error
            raise await refusal_of(connection, who, document_id, error) from error
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
        return await _read(connection, who, made)


@router.delete(
    "/rules/{rule_id}",
    summary="Take a rule away: reject a run's, delete an editor's own",
    responses=answers(NO_RULE, TAKE_RESPONSES) | HIDDEN,
)
async def take_a_rule(rule_id: UUID, expected_revision: Revision, request: Request, who: Account) -> TakenOut:
    async with request.app.state.pool.connection() as connection:
        document_id: UUID | None = None
        try:
            async with connection.transaction():
                document_id = await _document_of(connection, request, who, rule_id)
                taken = await drop_or_reject_rule(connection, reader(who), rule_id, expected_revision)
                if taken is None:
                    raise _gone()
                action = "rule.delete" if taken.outcome == "deleted" else "rule.reject"
                if taken.changed:  # a rule rejected already is none to note again
                    await audit(connection, who, action, f"rule:{rule_id}", {"document": str(document_id)})
        except StaleRevision as error:
            raise stale("rule", await rule_as_read(connection, who, rule_id)) from error
        except REFUSED as error:
            raise await refusal_of(connection, who, document_id, error) from error
    return TakenOut(outcome=taken.outcome, revision=taken.revision)


async def rule_as_read(connection: psycopg.AsyncConnection, who: Principal, rule_id: UUID) -> RuleOut | None:
    """The rule as its document's list has it, where the caller sees it."""
    target = await target_of(connection, DOCUMENT_OF_RULE, reader(who), rule_id)
    if target is None:
        return None
    found = await rules_of(connection, target.document_id)
    targets, said = await targets_of(connection, target.document_id)
    labels = {each.id: each.label for each in targets} | {key: cut(text) for key, text in said.items()}
    return next((rule_out(rule, labels) for rule in found if rule.id == rule_id), None)


async def _read(connection: psycopg.AsyncConnection, who: Principal, rule_id: UUID) -> RuleOut:
    read = await rule_as_read(connection, who, rule_id)
    if read is None:  # taken away right after
        raise _gone()
    return read


async def _document_of(
    connection: psycopg.AsyncConnection, request: Request, who: Principal, rule_id: UUID
) -> UUID:
    """The rule's document, whose content the caller reads; 404 where it sees none."""
    target = await target_of(connection, DOCUMENT_OF_RULE, reader(who), rule_id)
    if target is None:
        raise _gone()
    await readable_document(connection, who, request.app.state.settings, target.document_id)
    return target.document_id


async def _choices(connection: psycopg.AsyncConnection, scheme: str) -> list[ChoiceOut]:
    """The active concepts of the vocabulary's scheme, by their labels."""
    cursor = await connection.execute(
        "SELECT c.iri FROM vocab_concept c JOIN vocab_scheme s ON s.iri = c.scheme_iri"
        " WHERE c.scheme_iri = %s AND c.retired_in IS NULL AND s.retired_in IS NULL",
        ("https://w3id.org/wlo/curriculum/vocab#" + scheme,),
    )
    details = await concept_details(connection, [iri for (iri,) in await cursor.fetchall()])
    ordered = sorted(details.values(), key=lambda value: value.label.casefold())
    return [ChoiceOut(iri=value.iri, label=value.label) for value in ordered]


def _gone() -> Refusal:
    return Refusal(404, "no_rule", "No such rule.")
