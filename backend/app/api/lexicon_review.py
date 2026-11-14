"""The editors' review of the research cues (plan M1 10.3; app/db/cue_review.py, app/lexicon/sample.py): the
sample - a tenth of each stratum, sector and regions - and every other cue decided, and a decision on one
cue, made again over the last. A confirmation raises a cue to the strength given, up to 0.9, only with where
it was found. By the editors (Redaktion, Admin) alone, refused before anything is read; audited. The
decisions reach the files by python -m app.lexicon.export_reviews and the research's importer."""

from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.api.deps import require_account
from app.api.edit_answers import audit
from app.api.errors import AUTH_RESPONSES, ErrorBody, Refusal
from app.api.source_content import EDITORS
from app.core.auth import Principal
from app.db.cue_review import CueDecision, Decision, ResearchCue, decide, decisions, research_cues
from app.domain.text import UNSTORABLE
from app.lexicon.sample import Stratum, sample
from app.vocab.lookup import labels

router = APIRouter(prefix="/api/v1", tags=["lexicon"], responses=AUTH_RESPONSES)
Account = Annotated[Principal, Depends(require_account)]
NOT_EDITOR: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorBody, "description": "not_editor: the editors alone review the lexicon"}
}


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cue: str = Field(min_length=1, max_length=500)  # the research cue's IRI
    decision: CueDecision
    strength: Decimal | None = Field(
        default=None, ge=Decimal("0.5"), le=Decimal("0.9"), max_digits=3, decimal_places=2
    )
    evidence: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None

    @field_validator("cue", "evidence", "note")
    @classmethod
    def _storable(cls, value: str | None) -> str | None:
        if value is not None and UNSTORABLE.search(value):
            raise ValueError("a NUL or a lone surrogate is no text the database keeps")
        return value

    @model_validator(mode="after")
    def _raised_only_with_evidence(self) -> Self:
        self.evidence = self.evidence or None  # blank is none
        self.note = self.note or None
        if self.decision == "confirmed" and (self.strength is None or self.evidence is None):
            raise ValueError("a confirmation names a strength and where the cue was found (evidence)")
        if self.decision == "rejected" and self.strength is not None:
            raise ValueError("a rejection has no strength")
        return self


class DecisionOut(BaseModel):
    cue: str
    decision: CueDecision
    strength: Decimal | None
    evidence: str | None
    note: str | None
    content: dict[str, Any]  # what was judged, as the cue said it then
    decided_by: str
    decided_at: datetime
    retired: bool  # the cue, since
    applied: (
        bool  # the files' release holds it: confirmed - active, verified at its strength; rejected - retired
    )


class ReviewCueOut(BaseModel):
    iri: str
    sector: str
    regions: list[str]
    surface_form: str | None
    pattern: str | None
    role: str
    kind: str
    maps_to: list[str]
    strength: Decimal | None
    verified: bool
    sources: list[str]
    notes: list[str]  # where the research found it, and what it proposed
    recognition_hints: list[str]
    examples: list[str]
    sampled: bool  # in the sample; else listed for its decision
    decision: DecisionOut | None


class StratumOut(BaseModel):
    sector: str
    regions: list[str]
    cues: int
    sampled: int
    decided: int


class ReviewOut(BaseModel):
    strata: list[StratumOut]  # in their order
    items: list[ReviewCueOut]  # the sample, stratum by stratum in the seed's order; then the others decided
    retired: list[DecisionOut]  # decisions on cues no longer active
    labels: dict[str, str]  # every concept named above by its German label; a class or property none


@router.get(
    "/lexicon/review",
    summary="The sample of the research cues and every cue decided - the editors alone",
    responses=NOT_EDITOR,
)
async def review_list(request: Request, who: Account) -> ReviewOut:
    editors_only(who)
    async with request.app.state.pool.connection() as connection, connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")  # one release
        cues = await research_cues(connection)
        made = await decisions(connection)
        decided = {decision.cue: decision for decision in made}
        picked = sample(cues)
        sampled = {cue.iri for cue in picked}
        others = [cue for cue in cues if cue.iri in decided and cue.iri not in sampled]
        named = await labels(connection, _named([*picked, *others], made))  # of the same release
    active = {cue.iri for cue in cues}
    counts: dict[str, Counter[Stratum]] = {
        "cues": Counter(cue.stratum for cue in cues),
        "sampled": Counter(cue.stratum for cue in picked),
        "decided": Counter(cue.stratum for cue in cues if cue.iri in decided),
    }
    return ReviewOut(
        strata=[
            StratumOut(
                sector=stratum[0],
                regions=list(stratum[1]),
                cues=counts["cues"][stratum],
                sampled=counts["sampled"][stratum],
                decided=counts["decided"][stratum],
            )
            for stratum in sorted(counts["cues"])
        ],
        items=[_item(cue, cue.iri in sampled, decided.get(cue.iri)) for cue in [*picked, *others]],
        retired=[_decision(decision) for decision in made if decision.cue not in active],
        labels=named,
    )


@router.post(
    "/lexicon/review",
    summary="Decide on a research cue, over any decision before - the editors alone",
    responses=NOT_EDITOR
    | {404: {"model": ErrorBody, "description": "no_cue: no active research cue, nor one decided before"}},
)
async def review_cue(body: DecisionIn, request: Request, who: Account) -> DecisionOut:
    editors_only(who)
    assert who.account_id is not None  # noqa: S101 - require_account refuses visitors
    async with request.app.state.pool.connection() as connection, connection.transaction():
        made = await decide(
            connection, who.account_id, body.cue, body.decision, body.strength, body.evidence, body.note
        )
        if made is None:
            raise Refusal(404, "no_cue", "No active research cue, nor one decided before, has this IRI.")
        strength = None if made.strength is None else str(made.strength)
        await audit(
            connection,
            who,
            "lexicon.review",
            f"cue:{made.cue}",
            {"decision": made.decision, "strength": strength},
        )
    return _decision(made)


def editors_only(who: Principal) -> None:
    if not who.roles & EDITORS:
        raise Refusal(403, "not_editor", "Only the editors review the lexicon.")


def _named(cues: list[ResearchCue], made: list[Decision]) -> set[str]:
    """The IRIs the list shows: of the cues, and of what was judged of each decided."""
    shown = {iri for cue in cues for iri in (*cue.maps_to, cue.role, cue.kind, *cue.regions)}
    for decision in made:
        judged = decision.content
        shown.update([*judged["maps_to"], *judged["scope_regions"], judged["role"], judged["kind"]])
    return shown


def _item(cue: ResearchCue, sampled: bool, decision: Decision | None) -> ReviewCueOut:
    return ReviewCueOut(
        iri=cue.iri,
        sector=cue.sector,
        regions=list(cue.regions),
        surface_form=cue.surface_form,
        pattern=cue.pattern,
        role=cue.role,
        kind=cue.kind,
        maps_to=list(cue.maps_to),
        strength=cue.strength,
        verified=cue.verified,
        sources=list(cue.sources),
        notes=list(cue.notes),
        recognition_hints=list(cue.recognition_hints),
        examples=list(cue.examples),
        sampled=sampled,
        decision=None if decision is None else _decision(decision),
    )


def _decision(decision: Decision) -> DecisionOut:
    return DecisionOut(
        cue=decision.cue,
        decision=decision.decision,
        strength=decision.strength,
        evidence=decision.evidence,
        note=decision.note,
        content=decision.content,
        decided_by=decision.decided_by,
        decided_at=decision.decided_at,
        retired=decision.retired,
        applied=decision.applied,
    )
