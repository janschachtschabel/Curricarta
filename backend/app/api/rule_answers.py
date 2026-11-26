"""A rule as the editors' routes take and answer it (plan M3a I; app/api/rules.py, app/db/rule_rows.py): its
fields, its links each with what the editors know its target by, its anchors; what a rule may name, the
choices of a unit and a kind of requirement; an edit's fields and a new rule's."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.document_tree import Closed
from app.api.statement_editing import Anchors
from app.api.value_answers import Number
from app.api.values import Iri
from app.api.values import Number as NumberIn
from app.db.rule_rows import Link, Rule, TargetKind
from app.db.rules import RuleKind
from app.vocab.forms import MOST_TEXT, MOST_VERBATIM

MOST_LINKS = 50  # of a role at a rule
MOST_COUNT = 2_147_483_647  # a count as JSON and the store keep it
LABEL = 200  # signs of a linked statement's wording a list shows
Verbatim = Annotated[str, StringConstraints(min_length=1, max_length=MOST_VERBATIM)]
OptionText = Annotated[str, StringConstraints(min_length=1, max_length=MOST_TEXT)]
Count = Annotated[int, Field(ge=0, le=MOST_COUNT)]
Share = Annotated[Decimal, Field(ge=0, le=1, max_digits=15, allow_inf_nan=False)]
Targets = Annotated[list[UUID], Field(max_length=MOST_LINKS)]


class LinkOut(BaseModel):
    id: UUID
    kind: TargetKind
    label: str | None  # what the editors know it by; none for a row no list names


class AnchorOut(BaseModel):
    page_start: int | None
    page_end: int | None
    blocks: list[str]


class RuleOut(BaseModel):
    id: UUID
    iri: str | None  # given when the document is frozen
    kind: str  # selection, prerequisite, completion, recognition, progression
    verbatim: str
    min_count: int | None
    max_count: int | None
    min_amount: Number | None
    max_amount: Number | None
    amount_unit: str | None  # cv:WorkloadUnits
    requirement_kind: str | None  # cv:RequirementKinds
    max_share: Number | None  # of a recognition, from 0 to 1
    option_texts: list[str]  # the options as written, where no link names them
    applies_to: list[LinkOut]
    options: list[LinkOut]  # a selection's
    requires: list[LinkOut]  # a prerequisite's
    origin: str
    review_status: str
    revision: int  # the token of an edit and of taking it away
    by_hand: bool  # an editor's: taken away, it is deleted
    anchors: list[AnchorOut]


class TargetOut(BaseModel):
    id: UUID
    kind: TargetKind
    label: str


class ChoiceOut(BaseModel):
    iri: str
    label: str


class RulesOut(BaseModel):
    editable: bool  # the caller may edit them now
    closed: Closed | None  # why nobody may now, whoever reads
    rules: list[RuleOut]  # in the document's order
    targets: list[TargetOut]  # what a rule may name: specifications, variants, nodes from the top
    units: list[ChoiceOut]  # active ones, by their labels
    requirement_kinds: list[ChoiceOut]


class RuleEditIn(BaseModel):
    """The fields to set; one left out stays, None empties it. A link field names all its targets."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)  # the rule's, as it was read
    kind: RuleKind | None = None
    verbatim: Verbatim | None = None
    min_count: Count | None = None
    max_count: Count | None = None
    min_amount: NumberIn | None = None
    max_amount: NumberIn | None = None
    amount_unit: Iri | None = None
    requirement_kind: Iri | None = None
    max_share: Share | None = None
    option_texts: list[OptionText] | None = Field(default=None, max_length=MOST_LINKS)
    applies_to: Targets | None = None
    options: Targets | None = None
    requires: Targets | None = None


class NewRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: RuleKind
    verbatim: Verbatim
    anchors: Anchors = []  # one at least: none is anchor_missing


def cut(text: str) -> str:
    return text if len(text) <= LABEL else text[: LABEL - 1] + "…"


def links_out(links: tuple[Link, ...], labels: dict[UUID, str]) -> list[LinkOut]:
    return [LinkOut(id=link.target, kind=link.kind, label=labels.get(link.target)) for link in links]


def rule_out(rule: Rule, labels: dict[UUID, str]) -> RuleOut:
    return RuleOut(
        id=rule.id, iri=rule.iri, kind=rule.kind, verbatim=rule.verbatim, min_count=rule.min_count,
        max_count=rule.max_count, min_amount=rule.min_amount, max_amount=rule.max_amount,
        amount_unit=rule.amount_unit, requirement_kind=rule.requirement_kind, max_share=rule.max_share,
        option_texts=list(rule.option_texts), applies_to=links_out(rule.applies_to, labels),
        options=links_out(rule.options, labels), requires=links_out(rule.requires, labels),
        origin=rule.origin, review_status=rule.review_status, revision=rule.revision, by_hand=rule.by_hand,
        anchors=[AnchorOut(page_start=each.page_start, page_end=each.page_end, blocks=list(each.blocks))
                 for each in rule.anchors],
    )  # fmt: skip
