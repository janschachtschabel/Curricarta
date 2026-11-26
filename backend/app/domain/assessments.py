"""A document's assessments as the editors write them and the store gives them back (plan M3a J;
cur-kern.ttl, cur:Assessment): an examination, a part or area of one, a module exam, coursework - each a
part of one other assessment, of a specification or of a node of its document (cur:partOf), of a kind of the
core's (cv:AssessmentKinds), with its name, its duration in minutes, its weight among the parts of its parent
in percent and whether it is graded, as the document says them; what it assesses (cur:assesses) are nodes and
statements of its document, in the editors' order. The levels it is graded in are values at it
(app/domain/l2.py, a holder "assessment"); which kinds, levels and parents the store takes it checks
(migration assessment, app/db/assessments.py).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from app.domain.l2 import Level, Stated

ParentKind = Literal["assessment", "specification", "node"]
TargetKind = Literal["node", "statement"]
# the fields an edit may set, by the keys the editor names them by; ``targets`` the whole list at once
FIELDS: Final = (
    "parent_id", "assessment_kind", "label", "duration_minutes", "weight_percent", "graded", "targets",
)  # fmt: skip
MOST_LABEL: Final = 1000  # as the table's check has it
MOST_TARGETS: Final = 200  # of one assessment


@dataclass(frozen=True)
class AssessmentDraft:
    """A new assessment, an editor's: under ``parent_id`` - an assessment, a specification or a node of the
    document -, after the parts there."""

    parent_id: UUID
    assessment_kind: str  # cv:AssessmentKinds
    label: str | None = None
    duration_minutes: int | None = None
    weight_percent: Decimal | None = None
    graded: bool | None = None
    targets: tuple[UUID, ...] = ()  # nodes and statements of the document


@dataclass(frozen=True)
class Target:
    """What an assessment assesses: a node or a statement, named by its code and title or its wording."""

    kind: TargetKind
    id: UUID
    label: str | None


@dataclass(frozen=True)
class AssessmentRow:
    id: UUID
    parent_kind: ParentKind
    parent_id: UUID
    position: int  # among the parts of its parent, from 1
    assessment_kind: str
    label: str | None
    duration_minutes: int | None
    weight_percent: Decimal | None
    graded: bool | None
    iri: str | None  # given when the document is frozen
    stated: Stated  # where it came from, how far it is reviewed, its revision
    targets: tuple[Target, ...] = ()
    levels: tuple[Level, ...] = ()  # the levels at it (cur:levelAssignment)


@dataclass(frozen=True)
class Choice:
    """A row an assessment may be a part of or assess: a specification by its title, a node by its code and
    title."""

    kind: Literal["specification", "node"]
    id: UUID
    label: str | None
