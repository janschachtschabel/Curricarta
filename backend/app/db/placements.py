"""A node's placements, as the editors write them (plan M3a K, E11; migration placement,
app/domain/placements.py): set as the node's whole on its revision, as its values are (app/db/values.py) - a
draft naming an ``id`` keeps that placement of the node, one left out goes with its time spans and workloads
and the findings on all of it, a new one is an editor's proposal (origin human, proposed), and a kept one
whose fields change becomes one, on its next revision; one only moved keeps its revision. A set that changes
something counts the node's revision one up and notes the document edited, which owes X5 a check; one that
changes nothing leaves all as it was. The time spans and workloads at a placement are its values, set as a
whole on its revision (app/db/values.py, a holder "placement"). Read by document, and named when the document
is frozen, in app/db/placement_rows.py.

A set holds the tree's lock and refuses what every edit of the tree refuses (app/db/editing.py ``guard``);
StaleRevision where the node stands at another revision. Each placement is in a specification or a variant of
the document - a variant of that specification where both are named -, at a node of it but the node itself,
with an obligation cv:Obligations holds active (a kept one retired since stays until it is changed);
FieldError, by the placement's path in the set (``placements[1].variant_id``) and why, at the first that is
not - ``placements[1]`` ``unknown_value`` for an id that is none of the node's placements, or is named twice.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

from app.db.anchors import new_entity
from app.db.documents import DOCUMENT_VISIBLE
from app.db.editing import (
    CV,
    DOCUMENT_OF_NODE,
    HUMAN,
    PROPOSED,
    SECTOR,
    StaleRevision,
    drop_findings,
    guard,
    mark_edited,
    target_of,
)
from app.db.source_queries import Reader
from app.domain.placements import PlacementDraft
from app.vocab.form_values import FieldError

OBLIGATIONS: Final = CV + "Obligations"
DOCUMENT_OF_PLACEMENT = f"""
SELECT d.id, sector.notation FROM placement p JOIN document d ON d.id = p.document_id {SECTOR}
WHERE p.id = %(id)s AND {DOCUMENT_VISIBLE}
"""  # noqa: S608 - fixed parts
# what a placement says, beside where it stands among its node's: what a set compares and writes
_FIELDS: Final = ("specification_id", "variant_id", "in_node_id", "obligation_iri", "grade_weight")
_CURRENT = """
SELECT id, position, specification_id, variant_id, in_node_id, obligation_iri, grade_weight
FROM placement WHERE node_id = %s ORDER BY position FOR UPDATE
"""
_SPECIFICATIONS = "SELECT id FROM specification WHERE document_id = %s AND id = ANY(%s)"
_VARIANTS = """
SELECT v.id, v.specification_id FROM variant v JOIN specification s ON s.id = v.specification_id
WHERE s.document_id = %s AND v.id = ANY(%s)
"""
_NODES = "SELECT id FROM node WHERE document_id = %s AND id = ANY(%s)"
_ACTIVE = """
SELECT c.iri FROM vocab_concept c JOIN vocab_scheme s ON s.iri = c.scheme_iri
WHERE c.scheme_iri = %s AND c.iri = ANY(%s) AND c.retired_in IS NULL AND s.retired_in IS NULL
"""
# what goes with placements taken away: their time spans and workloads, a workload's periods
_HELD = """
SELECT id FROM time_span WHERE placement_id = ANY(%(gone)s)
UNION ALL SELECT id FROM workload WHERE placement_id = ANY(%(gone)s)
UNION ALL SELECT t.id FROM time_span t JOIN workload w ON w.id = t.workload_id
    WHERE w.placement_id = ANY(%(gone)s)
"""
_PROPOSAL: Final = sql.SQL(
    "origin_iri = %s, rule_id = NULL, review_status_iri = %s, revision = revision + 1, updated_at = now()"
)

Standing = tuple[int, dict[str, Any]]  # a stored placement's position and fields


async def replace_placements(
    connection: psycopg.AsyncConnection,
    reader: Reader,
    node_id: UUID,
    expected_revision: int,
    drafts: Sequence[PlacementDraft],
) -> int | None:
    """Set the node's placements to ``drafts``, on its revision ``expected_revision``, as above; the node's
    revision after, None where ``reader`` sees no such node. StaleRevision, FieldError or a refusal of
    ``guard``, and then nothing is changed."""
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT_OF_NODE, reader, node_id)
        if target is None:
            return None
        document_id = target.document_id
        await guard(connection, document_id)
        cursor = await connection.execute("SELECT revision FROM node WHERE id = %s FOR UPDATE", (node_id,))
        found = await cursor.fetchone()
        if found is None:  # taken away meanwhile
            return None
        if found[0] != expected_revision:
            raise StaleRevision(found[0])
        current = await _current(connection, node_id)
        wanted = [(draft.id, place, _fields(draft)) for place, draft in enumerate(drafts, start=1)]
        await _check(connection, document_id, node_id, wanted, current)
        kept = {placement for placement, _, _ in wanted if placement is not None}
        gone = [placement for placement in current if placement not in kept]
        if not gone and all(
            placement is not None and current[placement] == (place, fields)
            for placement, place, fields in wanted
        ):
            return expected_revision
        await _write(connection, document_id, node_id, wanted, current, gone)
        cursor = await connection.execute(
            "UPDATE node SET revision = revision + 1 WHERE id = %s RETURNING revision", (node_id,)
        )
        raised = await cursor.fetchone()
        assert raised is not None  # noqa: S101 - the row locked above
        await mark_edited(connection, document_id)
        return int(raised[0])


def _fields(draft: PlacementDraft) -> dict[str, Any]:
    return {
        "specification_id": draft.specification_id, "variant_id": draft.variant_id,
        "in_node_id": draft.in_node_id, "obligation_iri": draft.obligation,
        "grade_weight": draft.grade_weight,
    }  # fmt: skip


async def _current(connection: psycopg.AsyncConnection, node_id: UUID) -> dict[UUID, Standing]:
    """The node's placements, locked, by id."""
    cursor = await connection.execute(_CURRENT, (node_id,))
    return {row[0]: (row[1], dict(zip(_FIELDS, row[2:], strict=True))) for row in await cursor.fetchall()}


async def _check(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    node_id: UUID,
    wanted: Sequence[tuple[UUID | None, int, dict[str, Any]]],
    current: dict[UUID, Standing],
) -> None:
    """FieldError at the first placement of ``wanted`` the store does not take, as the module says."""

    def named(key: str) -> list[Any]:
        return list({fields[key] for _, _, fields in wanted if fields[key] is not None})

    cursor = await connection.execute(_SPECIFICATIONS, (document_id, named("specification_id")))
    specifications = {row for (row,) in await cursor.fetchall()}
    cursor = await connection.execute(_VARIANTS, (document_id, named("variant_id")))
    variants: dict[UUID, UUID] = dict(await cursor.fetchall())
    cursor = await connection.execute(_NODES, (document_id, named("in_node_id")))
    nodes = {row for (row,) in await cursor.fetchall()}
    cursor = await connection.execute(_ACTIVE, (OBLIGATIONS, named("obligation_iri")))
    active = {row for (row,) in await cursor.fetchall()}
    seen: set[UUID] = set()
    for place, (placement, _, fields) in enumerate(wanted):
        at = f"placements[{place}]"
        if placement is not None and (placement not in current or placement in seen):
            raise FieldError(at, "unknown_value")
        if placement is not None:
            seen.add(placement)
        kept = current[placement][1] if placement is not None else {}
        specification, variant, in_node = (
            fields["specification_id"],
            fields["variant_id"],
            fields["in_node_id"],
        )
        if specification is None and variant is None:
            raise FieldError(f"{at}.specification_id", "required")
        if specification is not None and specification not in specifications:
            raise FieldError(f"{at}.specification_id", "not_offered")
        if variant is not None and (
            variant not in variants or specification not in (None, variants[variant])
        ):
            raise FieldError(f"{at}.variant_id", "not_offered")
        if in_node is not None and (in_node not in nodes or in_node == node_id):
            raise FieldError(f"{at}.in_node_id", "not_offered")
        obligation = fields["obligation_iri"]
        if obligation not in active and obligation != kept.get("obligation_iri"):
            raise FieldError(f"{at}.obligation", "not_offered")
        weight: Decimal | None = fields["grade_weight"]
        if weight is not None and (not weight.is_finite() or weight < 0):
            raise FieldError(f"{at}.grade_weight", "refused")


async def _write(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    node_id: UUID,
    wanted: Sequence[tuple[UUID | None, int, dict[str, Any]]],
    current: dict[UUID, Standing],
    gone: Sequence[UUID],
) -> None:
    """Take the placements ``gone`` away with their values and the findings on them, change the kept ones that
    changed, write the new ones; the positions are checked at the end, once all stand."""
    await connection.execute("SET CONSTRAINTS placement_position DEFERRED")
    if gone:
        cursor = await connection.execute(_HELD, {"gone": list(gone)})
        held = [row for (row,) in await cursor.fetchall()]
        await drop_findings(connection, document_id, [*gone, *held])
        await connection.execute("DELETE FROM placement WHERE id = ANY(%s)", (list(gone),))
    variants: dict[UUID, UUID] = {}
    if named := [fields["variant_id"] for _, _, fields in wanted if fields["variant_id"] is not None]:
        cursor = await connection.execute(
            "SELECT id, specification_id FROM variant WHERE id = ANY(%s)", (named,)
        )
        variants = dict(await cursor.fetchall())
    for placement, place, fields in wanted:
        columns = fields | {"position": place, "variant_specification_id": variants.get(fields["variant_id"])}
        if placement is None:
            await _insert(connection, document_id, node_id, columns)
            continue
        position, stored = current[placement]
        if stored != fields:
            await _update(connection, placement, columns, proposal=True)
        elif position != place:
            await _update(connection, placement, {"position": place}, proposal=False)
    await connection.execute("SET CONSTRAINTS placement_position IMMEDIATE")


async def _insert(
    connection: psycopg.AsyncConnection, document_id: UUID, node_id: UUID, columns: dict[str, Any]
) -> None:
    values = {
        "id": await new_entity(connection, "placement"), "document_id": document_id, "node_id": node_id,
        "obligation_scheme": OBLIGATIONS, "origin_scheme": CV + "Origins", "origin_iri": HUMAN,
        "review_status_scheme": CV + "ReviewStatuses", "review_status_iri": PROPOSED,
    } | columns  # fmt: skip
    await connection.execute(
        sql.SQL("INSERT INTO placement ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() * len(values)),
        ),
        tuple(values.values()),
    )


async def _update(
    connection: psycopg.AsyncConnection, placement: UUID, columns: dict[str, Any], *, proposal: bool
) -> None:
    """The kept placement at its new position; changed, as an editor's proposal on its next revision."""
    assigned: list[sql.Composable] = [sql.SQL("{} = %s").format(sql.Identifier(key)) for key in columns]
    if proposal:
        assigned.append(_PROPOSAL)
    params = (*columns.values(), *((HUMAN, PROPOSED) if proposal else ()), placement)
    await connection.execute(
        sql.SQL("UPDATE placement SET {} WHERE id = %s").format(sql.SQL(", ").join(assigned)), params
    )
