"""A MEM plan's tree as the core's drafts (plan M2, E2/E8; Teilplan M2-5).

Each part becomes one row by the rules ``mem-rules/2`` (app/sources/mem/classes.py): a node with its title,
or a statement with its kind, subkind and addressee under the node of its parent. Every row is imported
(``orig_import``, no rule id) and proposed for review, and keeps what MEM says of its part (``MemTrace``):
its IRI where the tables take it, its classes, and what the core has no column for - cleaned of the signs
the database cannot hold. A statement at the top of the plan has no node to hang at: such statements hang
under one node of the plan's title, made for them, with no part of MEM behind it.

The anchor search looks for the rows' wordings in the document's order (``rows_in_order``): a node before
its parts, the parts in the plan's order, the node of the plan's title first. The core keeps a node's
statements before its child nodes; the search does not.
"""

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.l1 import AnchorDraft, MemTrace, NodeDraft, StatementDraft
from app.sources.mem.classes import MemRules, Typed, typed
from app.sources.mem.tree import UNSTORABLE, MemPart, MemTree, storable_iri

CV = "https://w3id.org/wlo/curriculum/vocab#"
IMPORTED, PROPOSED = CV + "orig_import", CV + "rev_proposed"
MAX_TITLE = 2000  # a node's original title holds as many signs at most
MAX_WORDING = 20_000  # a statement's wording too


@dataclass(frozen=True)
class Row:
    """A wording to look for: a part's IRI - the plan's for the node of its title - and whether it is a
    node's title."""

    key: str
    wording: str
    node: bool


def rows_in_order(tree: MemTree, rules: MemRules, plan_iri: str, plan_title: str) -> list[Row]:
    """The rows' wordings in the document's order."""
    rows = [Row(plan_iri, _title(plan_title), True)] if _loose(tree, rules) else []
    for root in tree.roots:
        rows.extend(_rows(root, rules))
    return rows


def drafts_from(
    tree: MemTree, rules: MemRules, plan_iri: str, plan_title: str, anchors: Mapping[str, AnchorDraft]
) -> list[NodeDraft]:
    """The tree as nodes at the top, each row with the anchor the search found for its key (``Row.key``)."""
    loose = _loose(tree, rules)
    drafts: list[NodeDraft] = []
    if loose:
        statements = tuple(_statement(part, typed(part, rules), anchors[part.iri]) for part in loose)
        drafts.append(
            NodeDraft(
                function=CV + "fn_area",
                origin=IMPORTED,
                review_status=PROPOSED,
                original_title=_title(plan_title),
                anchors=(anchors[plan_iri],),
                statements=statements,
            )
        )
    drafts.extend(
        _node(root, typed(root, rules), rules, anchors) for root in tree.roots if typed(root, rules).node
    )
    return drafts


def rule_counts(tree: MemTree, rules: MemRules) -> Counter[str]:
    """How many parts each rule typed (reference, kmk, cue, base, kmk_element, unknown), for the run's
    result."""
    return Counter(typed(part, rules).rule for part in tree.parts.values())


def _loose(tree: MemTree, rules: MemRules) -> list[MemPart]:
    """The statements at the top of the plan."""
    return [root for root in tree.roots if not typed(root, rules).node]


def _rows(part: MemPart, rules: MemRules) -> Iterator[Row]:
    found = typed(part, rules)
    yield Row(part.iri, _title(part.label) if found.node else _wording(part.label), found.node)
    for child in part.children:
        yield from _rows(child, rules)


def _node(part: MemPart, found: Typed, rules: MemRules, anchors: Mapping[str, AnchorDraft]) -> NodeDraft:
    statements, children = [], []
    for child in part.children:
        kind = typed(child, rules)
        if kind.node:
            children.append(_node(child, kind, rules, anchors))
        else:
            statements.append(_statement(child, kind, anchors[child.iri]))
    assert found.function is not None  # noqa: S101 - a node's typing names its function
    return NodeDraft(
        function=found.function, origin=IMPORTED, review_status=PROPOSED, node_type=found.node_type,
        original_title=_title(part.label), anchors=(anchors[part.iri],), statements=tuple(statements),
        children=tuple(children), mem=_trace(part),
    )  # fmt: skip


def _statement(part: MemPart, found: Typed, anchor: AnchorDraft) -> StatementDraft:
    assert found.kind is not None and found.addressee is not None  # noqa: S101 - a statement's typing names both
    return StatementDraft(
        verbatim=_wording(part.label), kind=found.kind, addressees=(found.addressee,), anchors=(anchor,),
        origin=IMPORTED, review_status=PROPOSED, subkind=found.subkind, mem=_trace(part),
    )  # fmt: skip


def _trace(part: MemPart) -> MemTrace | None:
    """What MEM says of the part; none where the tables do not take its IRI."""
    if not storable_iri(part.iri):
        return None
    texts = {"description": part.description, "number": part.number, "hours": part.hours, "page": part.page}
    lists = {"grades": part.grades, "other_parents": part.other_parents, "holders": part.holders,
             "targets": part.targets}  # fmt: skip
    properties: dict[str, Any] = {name: _clean(value) for name, value in texts.items() if value}
    if part.position is not None:
        properties["position"] = part.position
    if part.reference:  # reached by "hat Verweis" alone: no part of the plan in MEM
        properties["held_only"] = True
    properties |= {name: [_clean(value) for value in values] for name, values in lists.items() if values}
    return MemTrace(part.iri, tuple(_clean(klass) for klass in part.classes), properties)


def _clean(value: str) -> str:
    return UNSTORABLE.sub("", value)


def _title(label: str) -> str:
    return label[:MAX_TITLE]


def _wording(label: str) -> str:
    return label[:MAX_WORDING]
