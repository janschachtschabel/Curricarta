"""A document's rules as rows (plan M3a I, E10; migration rule_link): each rules frame part with its parsed
values - read off its content in the keys of X3's schema, a unit and a kind of requirement named by the
concepts their notations name -, where it came from, how far it is reviewed, its revision, its links by role
and its anchors (``rules_of``); the edit's keys of the content (``CONTENT_KEYS``). The Kern graph reads the
rules ``stated``: a rejected rule left out, and a link to a rejected statement, as the graph leaves those out.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

CV = "https://w3id.org/wlo/curriculum/vocab#"
LinkRole = Literal["applies_to", "option", "requires"]
TargetKind = Literal["node", "statement", "specification", "variant"]
# the edit's keys of a rule's content, by the keys of X3's schema it keeps them in
CONTENT_KEYS: Final = {
    "kind": "ruleKind", "verbatim": "verbatim", "min_count": "minCount", "max_count": "maxCount",
    "min_amount": "minAmount", "max_amount": "maxAmount", "amount_unit": "amountUnit",
    "requirement_kind": "requirementKind", "max_share": "maxShare", "option_texts": "optionTexts",
}  # fmt: skip
# a notation of the content as the concept of its list it names: the active one, else the last retired
_RULES = """
SELECT f.id, f.iri, f.content, f.origin_iri, f.review_status_iri, f.revision, f.by_hand,
    (SELECT c.iri FROM vocab_concept c
     WHERE c.scheme_iri = %(units)s AND c.notation = f.content ->> 'amountUnit'
     ORDER BY c.retired_in DESC NULLS FIRST LIMIT 1) AS amount_unit,
    (SELECT c.iri FROM vocab_concept c
     WHERE c.scheme_iri = %(kinds)s AND c.notation = f.content ->> 'requirementKind'
     ORDER BY c.retired_in DESC NULLS FIRST LIMIT 1) AS requirement_kind
FROM frame_part f
WHERE f.document_id = %(document)s AND f.part_kind = 'rules'
    AND (NOT %(stated)s OR f.review_status_iri <> %(rejected)s)
ORDER BY f.position
"""
_LINKS = """
SELECT l.frame_part_id, l.role,
    coalesce(l.node_id, l.statement_id, l.specification_id, l.variant_id) AS target,
    CASE WHEN l.node_id IS NOT NULL THEN 'node' WHEN l.statement_id IS NOT NULL THEN 'statement'
         WHEN l.specification_id IS NOT NULL THEN 'specification' ELSE 'variant' END AS kind,
    l.variant_specification_id AS of
FROM rule_link l
WHERE {where} AND (NOT %(stated)s OR NOT EXISTS (
    SELECT FROM statement s WHERE s.id = l.statement_id AND s.review_status_iri = %(rejected)s))
ORDER BY l.frame_part_id, l.role, l.position
"""
# a rule's anchors, their blocks in the document's order
_ANCHORS = """
SELECT a.frame_part_id, a.page_start, a.page_end,
    ARRAY(SELECT b.block_id FROM anchor_block b JOIN document_block d
              ON d.conversion_id = b.conversion_id AND d.block_id = b.block_id
          WHERE b.anchor_id = a.id ORDER BY d.page, d.seq) AS blocks
FROM anchor a JOIN frame_part f ON f.id = a.frame_part_id
WHERE a.document_id = %(document)s AND f.part_kind = 'rules'
ORDER BY a.id
"""


@dataclass(frozen=True)
class Link:
    target: UUID
    kind: TargetKind
    of: UUID | None = field(default=None, compare=False)  # a variant's specification


@dataclass(frozen=True)
class RuleAnchor:
    page_start: int | None
    page_end: int | None
    blocks: tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    id: UUID
    iri: str | None  # given when its document is frozen
    kind: str  # X3's ruleKind: selection, prerequisite, completion, recognition, progression
    verbatim: str
    min_count: int | None
    max_count: int | None
    min_amount: Decimal | None
    max_amount: Decimal | None
    amount_unit: str | None  # a concept of cv:WorkloadUnits
    requirement_kind: str | None  # a concept of cv:RequirementKinds
    max_share: Decimal | None
    option_texts: tuple[str, ...]  # as the document names them, where no link names them
    applies_to: tuple[Link, ...]
    options: tuple[Link, ...]
    requires: tuple[Link, ...]
    origin: str
    review_status: str
    revision: int
    by_hand: bool
    anchors: tuple[RuleAnchor, ...]


async def rules_of(
    connection: psycopg.AsyncConnection, document_id: UUID, *, stated: bool = False
) -> list[Rule]:
    """The document's rules in their order, in one snapshot - of a read-only transaction of its own, or of the
    caller's (as app/db/value_rows.py reads); ``stated``: as the Kern graph states them."""
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        return await _read(connection, document_id, stated)
    async with connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return await _read(connection, document_id, stated)


async def links_of(connection: psycopg.AsyncConnection, rule_id: UUID) -> dict[LinkRole, tuple[Link, ...]]:
    """The rule's links by role, each role's in their order."""
    params = {"rule": rule_id, "stated": False, "rejected": CV + "rev_rejected"}
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_LINKS.format(where="l.frame_part_id = %(rule)s"), params)
        return _by_role(await cursor.fetchall()).get(rule_id, {})


async def _read(connection: psycopg.AsyncConnection, document_id: UUID, stated: bool) -> list[Rule]:
    params = {
        "document": document_id, "stated": stated, "rejected": CV + "rev_rejected",
        "units": CV + "WorkloadUnits", "kinds": CV + "RequirementKinds",
    }  # fmt: skip
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_RULES, params)
        rows = await cursor.fetchall()
        await cursor.execute(_LINKS.format(where="l.document_id = %(document)s"), params)
        links = _by_role(await cursor.fetchall())
        await cursor.execute(_ANCHORS, params)
        anchors: defaultdict[UUID, list[RuleAnchor]] = defaultdict(list)
        for found in await cursor.fetchall():
            anchors[found["frame_part_id"]].append(
                RuleAnchor(found["page_start"], found["page_end"], tuple(found["blocks"]))
            )
    return [_rule(row, links.get(row["id"], {}), tuple(anchors[row["id"]])) for row in rows]


def _by_role(rows: list[dict[str, Any]]) -> dict[UUID, dict[LinkRole, tuple[Link, ...]]]:
    found: defaultdict[UUID, defaultdict[LinkRole, list[Link]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        found[row["frame_part_id"]][row["role"]].append(Link(row["target"], row["kind"], row["of"]))
    return {rule: {role: tuple(links) for role, links in roles.items()} for rule, roles in found.items()}


def _rule(
    row: dict[str, Any], links: dict[LinkRole, tuple[Link, ...]], anchors: tuple[RuleAnchor, ...]
) -> Rule:
    content = row["content"]
    texts = content.get("optionTexts")
    texts = [text for text in texts if isinstance(text, str)] if isinstance(texts, list) else []
    return Rule(
        id=row["id"], iri=row["iri"], kind=str(content.get("ruleKind")),
        verbatim=str(content.get("verbatim")),
        min_count=_count(content.get("minCount")), max_count=_count(content.get("maxCount")),
        min_amount=_number(content.get("minAmount")), max_amount=_number(content.get("maxAmount")),
        amount_unit=row["amount_unit"], requirement_kind=row["requirement_kind"],
        max_share=_number(content.get("maxShare")),
        option_texts=tuple(texts),
        applies_to=links.get("applies_to", ()), options=links.get("option", ()),
        requires=links.get("requires", ()), origin=row["origin_iri"], review_status=row["review_status_iri"],
        revision=row["revision"], by_hand=row["by_hand"], anchors=anchors,
    )  # fmt: skip


def _count(value: Any) -> int | None:
    """A count as X3 gave it: a whole number, else none."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return int(value) if value == int(value) else None


def _number(value: Any) -> Decimal | None:
    """An amount or a share as X3 gave it, as the decimal its JSON wrote; a finite number, else none."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return Decimal(str(value))
