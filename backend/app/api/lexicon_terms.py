"""The editors' decisions on the terms X1 found no type for (plan M1 10.4; app/db/term_review.py,
app/lexicon/new_terms.py): every term the documents' profiles name, once for its sector, regions and word,
with its first places and any decision, and a decision on one term, made again over the last - a new cue
names a node type of the sector's profile and its role; a term peculiar to its document or misread names
neither. By the editors (Redaktion, Admin) alone, refused before anything is read; audited. The new cues reach
the files, unverified, by python -m app.lexicon.export_reviews and the research's importer."""

import asyncio
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

import psycopg
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.api.edit_answers import audit
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.lexicon_review import NOT_EDITOR, Account, editors_only
from app.db.sources import sector_by_notation
from app.db.term_review import (
    ROLE,
    Choice,
    Judged,
    TermDecision,
    TermReview,
    decide_term,
    held_cues,
    occurrences,
    review_of,
    term_reviews,
)
from app.domain.text import UNSTORABLE
from app.lexicon.held import HeldCue, TermKey, by_word, holding
from app.lexicon.new_terms import KEY_LIMIT, MIN_SIGNS, NewTerm, Occurrence, gather, regions_of, term_key
from app.vocab.lookup import labels, profile_concepts, terminology_profile

router = APIRouter(prefix="/api/v1", tags=["lexicon"], responses=AUTH_RESPONSES)
Role = Literal["pref", "alt", "cue"]  # what a new cue may be; negative and homonym need hints it has none of
Region = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")]


class TermDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sector: str = Field(min_length=1, max_length=64)  # its notation, "school"
    regions: list[Region] = Field(min_length=1, max_length=17)
    term: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]  # any form
    decision: TermDecision
    maps_to: str | None = Field(default=None, min_length=1, max_length=500)
    role: Role | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None

    @field_validator("sector", "term", "maps_to", "note")
    @classmethod
    def _storable(cls, value: str | None) -> str | None:
        if value is not None and UNSTORABLE.search(value):
            raise ValueError("a NUL or a lone surrogate is no text the database keeps")
        return value

    @model_validator(mode="after")
    def _a_cue_names_its_target(self) -> Self:
        self.note = self.note or None  # blank is none
        if len(term_key(self.term)) > KEY_LIMIT:
            raise ValueError(f"no term has a key of more than {KEY_LIMIT} signs")
        if self.decision == "cue":
            if self.maps_to is None or self.role is None:
                raise ValueError("a new cue names the node type it points to (maps_to) and its role")
        elif self.maps_to is not None or self.role is not None:
            raise ValueError("only a new cue names a target and a role")
        return self


class TermDecisionOut(BaseModel):
    sector: str
    regions: list[str]
    term: str  # as judged
    decision: TermDecision
    maps_to: str | None
    role: str | None  # its notation: pref, alt, cue
    note: str | None
    content: dict[str, Any]  # what else was judged: the functions suggested, how many documents named it
    decided_by: str
    decided_at: datetime
    applied: bool | None  # a new cue: whether an active cue of the profile says it; None, nothing to apply


class PlaceOut(BaseModel):
    document: UUID
    title: str | None
    block: str | None
    function: str | None  # suggested by X1


class HeldOut(BaseModel):
    iri: str
    own: bool  # the sector's own lexicon: the importer takes no new cue of its words
    by_word: bool  # its word holds the term; else its pattern alone, which counts for its targets only
    surface_form: str | None
    pattern: str | None
    maps_to: list[str]
    role: str  # its IRI
    regions: list[str]  # their IRIs; none, everywhere


class TermOut(BaseModel):
    sector: str
    regions: list[str]
    term: str  # in the form the documents write most
    documents: int
    functions: list[str]
    occurrences: list[PlaceOut]  # the first; `documents` counts them all
    held: list[HeldOut]  # the active cues that hold the word already, the own lexicon's first
    decision: TermDecisionOut | None


class TermsOut(BaseModel):
    terms: list[TermOut]  # by sector, regions and word
    gone: list[TermDecisionOut]  # decisions on terms no document names any more
    labels: dict[str, str]  # every concept named above by its German label


@router.get(
    "/lexicon/terms",
    summary="The terms X1 found no type for and every decision on them - the editors alone",
    responses=NOT_EDITOR,
)
async def terms_list(request: Request, who: Account) -> TermsOut:
    editors_only(who)
    async with request.app.state.pool.connection() as connection, connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")  # one moment
        found = await occurrences(connection)
        made = await term_reviews(connection)
        cues = await held_cues(connection)
    # the connection back in the pool first, and the patterns searched off the loop
    terms, held = await asyncio.to_thread(_listed, found, cues)
    decided = {(review.sector_iri, review.regions, review.key): review for review in made}
    named = {_key(term) for term in terms}
    async with request.app.state.pool.connection() as connection:  # the labels alone, a moment later
        shown = await labels(connection, _shown(terms, held.values(), made))
    return TermsOut(
        terms=[_term(term, decided.get(_key(term)), held.get(_key(term), ())) for term in terms],
        gone=[_decision(review) for key, review in decided.items() if key not in named],
        labels=shown,
    )


@router.post(
    "/lexicon/terms",
    summary="Decide on a term X1 found no type for, over any decision before - the editors alone",
    responses=NOT_EDITOR
    | {
        404: {"model": ErrorBody, "description": "no_term: no document names it, nor was it decided before"},
        422: {
            "model": ErrorBody,
            "description": "too_short: a word under four signs gives no cue; not_a_node_type: no node type of"
            " the sector's active profile",
        },
    },
)
async def decide_on_term(body: TermDecisionIn, request: Request, who: Account) -> TermDecisionOut:
    editors_only(who)
    assert who.account_id is not None  # noqa: S101 - require_account refuses visitors
    regions, key = regions_of(body.regions), term_key(body.term)
    async with request.app.state.pool.connection() as connection, connection.transaction():
        judged = await _judged(connection, body.sector, regions, key)
        if judged is None:
            raise Refusal(404, "no_term", "No document names this term, nor was it decided before.")
        if body.decision == "cue" and len(judged.surface_form) < MIN_SIGNS:  # as the importer measures it
            raise Refusal(422, "too_short", f"A word of fewer than {MIN_SIGNS} signs gives no cue.")
        if body.maps_to is not None and body.maps_to not in await _node_types(connection, body.sector):
            raise Refusal(422, "not_a_node_type", "A new cue points to a node type of the sector's profile.")
        role = None if body.role is None else ROLE + body.role
        made = await decide_term(
            connection, who.account_id, judged, Choice(body.decision, body.maps_to, role, body.note)
        )
        await audit(
            connection,
            who,
            "lexicon.term",
            f"term:{body.sector}:{','.join(regions)}:{key}",
            {"decision": made.decision, "maps_to": made.maps_to, "role": body.role},
        )
    return _decision(made)


async def _judged(
    connection: psycopg.AsyncConnection, sector: str, regions: tuple[str, ...], key: str
) -> Judged | None:
    """The term as the documents name it now, else as it was decided; None where neither."""
    sector_iri = await sector_by_notation(connection, sector)
    if sector_iri is None:
        return None
    profile = await terminology_profile(connection, sector)
    named = [
        term
        for term in gather(await occurrences(connection, sector_iri))
        if _key(term) == (sector_iri, regions, key)
    ]
    if named:
        (term,) = named
        content = {"functions": list(term.functions), "documents": term.documents}
        return Judged(sector_iri, regions, key, term.term, profile, content)
    before = await review_of(connection, sector_iri, regions, key)
    if before is None:
        return None
    return Judged(sector_iri, regions, key, before.surface_form, profile, before.content)


async def _node_types(connection: psycopg.AsyncConnection, sector: str) -> set[str]:
    values = await profile_concepts(connection, sector)
    return set() if values is None else set(values.node_types)


def _listed(
    found: list[Occurrence], cues: list[HeldCue]
) -> tuple[list[NewTerm], dict[TermKey, tuple[HeldCue, ...]]]:
    terms = gather(found)
    return terms, holding(terms, cues)


def _shown(terms: list[NewTerm], held: Iterable[tuple[HeldCue, ...]], made: list[TermReview]) -> set[str]:
    """The IRIs the list shows: of the terms (their places' functions among them), the cues holding them, and
    the decisions."""
    shown = {iri for term in terms for iri in term.functions}
    shown |= {iri for cues in held for cue in cues for iri in (*cue.maps_to, cue.role, *cue.regions)}
    for review in made:
        shown.update(review.content.get("functions", ()))
        if review.maps_to is not None:
            shown.add(review.maps_to)
    return shown


def _key(term: NewTerm) -> TermKey:
    return (term.sector_iri, term.regions, term.key)


def _term(term: NewTerm, decision: TermReview | None, held: tuple[HeldCue, ...]) -> TermOut:
    return TermOut(
        sector=term.sector,
        regions=list(term.regions),
        term=term.term,
        documents=term.documents,
        functions=list(term.functions),
        occurrences=[
            PlaceOut(document=place.document, title=place.title, block=place.block, function=place.function)
            for place in term.occurrences
        ],
        held=[
            HeldOut(
                iri=cue.iri,
                own=cue.own,
                by_word=by_word(cue, term.key),
                surface_form=cue.surface_form,
                pattern=cue.pattern,
                maps_to=list(cue.maps_to),
                role=cue.role,
                regions=list(cue.regions),
            )
            for cue in held
        ],
        decision=None if decision is None else _decision(decision),
    )


def _decision(review: TermReview) -> TermDecisionOut:
    return TermDecisionOut(
        sector=review.sector,
        regions=list(review.regions),
        term=review.surface_form,
        decision=review.decision,
        maps_to=review.maps_to,
        role=None if review.role is None else review.role.removeprefix(ROLE),
        note=review.note,
        content=review.content,
        decided_by=review.decided_by,
        decided_at=review.decided_at,
        applied=review.applied,
    )
