"""A node's placements as the tree answers them (plan M3a K; app/domain/placements.py): each with the
specification or variant it is in, the node it is at, its obligation and grade weight, its IRI once frozen,
where it came from, how far it is reviewed and its revision - the token a set of its values is made on -, and
its time spans and workloads (app/api/value_answers.py)."""

from uuid import UUID

from pydantic import BaseModel

from app.api.value_answers import Number, ValuesOut, values_out
from app.domain.placements import PlacementRow


class PlacementOut(BaseModel):
    id: UUID  # names it in a set of the node's placements that keeps it (PUT /nodes/{id}/placements)
    node_id: UUID  # the node it places
    position: int  # among the node's placements, from 1
    specification_id: UUID | None
    variant_id: UUID | None
    in_node_id: UUID | None  # where in the specification or variant
    obligation: str  # cv:Obligations
    grade_weight: Number | None
    iri: str | None  # given when its document was frozen
    origin: str
    review_status: str
    revision: int  # the set of its values names it (PUT /placements/{id}/values)
    values: ValuesOut  # its time spans and workloads


class PlacedOut(PlacementOut):
    """A placement as a set of its values answers it: with its node's revision, which that set counted too -
    the token of the next set of the node's placements (PUT /nodes/{id}/placements)."""

    node_revision: int


def placement_out(row: PlacementRow) -> PlacementOut:
    return PlacementOut(
        id=row.id, node_id=row.node_id, position=row.position, specification_id=row.specification_id,
        variant_id=row.variant_id, in_node_id=row.in_node_id, obligation=row.obligation,
        grade_weight=row.grade_weight, iri=row.iri, origin=row.stated.origin,
        review_status=row.stated.review_status, revision=row.stated.revision, values=values_out(row.values),
    )  # fmt: skip
