"""A node's placements as the editors write them and the store gives them back (plan M3a K; cur-kern.ttl,
cur:Placement): the node - a module, a learning field, a course unit - placed in a specification or a variant
of its document (one at least; a variant of that specification where both are named), at a node of the
document where it says one, with how binding it is there (cv:Obligations) and its weight in the grade. The
time spans and workloads it has in that place are values at it (app/domain/l2.py, a holder "placement"). Set
as the node's whole (app/db/placements.py); which rows and concepts the store takes it checks (migration
placement)."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final
from uuid import UUID

from app.domain.l2 import HeldValues, Stated

MOST_PLACEMENTS: Final = 50  # of one node


@dataclass(frozen=True)
class PlacementDraft:
    """A placement of the node, an editor's: one named by its ``id`` is that one, kept; one without is new."""

    obligation: str  # cv:Obligations
    specification_id: UUID | None = None
    variant_id: UUID | None = None
    in_node_id: UUID | None = None  # where in the specification or variant
    grade_weight: Decimal | None = None
    id: UUID | None = None


@dataclass(frozen=True)
class Place:
    """A specification of the document a node may be placed in, with its variants (id, label), by their
    keys."""

    id: UUID
    title: str
    variants: tuple[tuple[UUID, str], ...]


@dataclass(frozen=True)
class PlacementRow:
    id: UUID
    node_id: UUID  # the node placed (cur:placedUnit)
    position: int  # among the placements of its node, from 1
    specification_id: UUID | None
    variant_id: UUID | None
    in_node_id: UUID | None
    obligation: str
    grade_weight: Decimal | None
    iri: str | None  # given when the document is frozen
    stated: Stated  # where it came from, how far it is reviewed, its revision
    values: HeldValues = field(default_factory=HeldValues)  # its time spans and workloads
