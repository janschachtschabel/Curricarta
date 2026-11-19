"""The IRIs a document's rows get when it is frozen (plan M1 9.6, Paket 9b H6; plan M3a B1).

Specifications are named by their keys under the document (``<document>/spec/<key>``), their variants by
theirs under their specification (``…/variant/<key>``), each group in the order of its keys; a key with no
ASCII letter or digit by its place among them (app/domain/iris.py). Revisions share the document's IRI, so a
key another revision named takes that name (``GivenByKey``), and a name another revision gave is none to give
again. Nodes are named from the top, by the path of their codes under the document, each group of siblings
in its order. A statement is numbered under its node - ``<node>/s-<n>`` - from the highest number given under
its IRI (``statement_serial``, and ``served``: what every revision gave under it), so that no number is given
twice, though a draft copy took one away or dropped the node and made it anew at its code's path. What a draft
copy brought along keeps its IRI, whatever its code or key says now: an IRI once given stays. What is new is
named past every IRI the document's rows hold - its siblings', a node's moved away from there, a
specification's -: a segment one holds counts on ("lf-1-2"). A rejected statement is none of the curriculum's
and gets no IRI; one it had stays.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.domain.iris import (
    SegmentCounter,
    key_segment,
    node_iri,
    node_segments,
    specification_iri,
    statement_iri,
    variant_iri,
)


@dataclass(frozen=True)
class NodeRow:
    id: UUID
    parent_id: UUID | None
    position: int
    code: str | None
    code_assigned: bool
    iri: str | None
    statement_serial: int


@dataclass(frozen=True)
class StatementRow:
    id: UUID
    node_id: UUID
    position: int
    iri: str | None
    rejected: bool


@dataclass(frozen=True)
class SpecificationRow:
    id: UUID
    key: str
    iri: str | None


@dataclass(frozen=True)
class VariantRow:
    id: UUID
    specification_id: UUID
    key: str
    iri: str | None


@dataclass(frozen=True)
class GivenByKey:
    """What the revisions of the document named by key: a specification's IRI by its key, a variant's by its
    specification's key and its own."""

    specifications: Mapping[str, str] = field(default_factory=dict)
    variants: Mapping[tuple[str, str], str] = field(default_factory=dict)


@dataclass(frozen=True)
class Named:
    """The IRIs given now, by row; the nodes' statement numbers where they grew."""

    nodes: dict[UUID, str] = field(default_factory=dict)
    statements: dict[UUID, str] = field(default_factory=dict)
    serials: dict[UUID, int] = field(default_factory=dict)
    specifications: dict[UUID, str] = field(default_factory=dict)
    variants: dict[UUID, str] = field(default_factory=dict)


def name_rows(
    document: str,
    nodes: Iterable[NodeRow],
    statements: Iterable[StatementRow],
    served: Mapping[str, int] | None = None,
    *,
    specifications: Iterable[SpecificationRow] = (),
    variants: Iterable[VariantRow] = (),
    given: GivenByKey | None = None,
) -> Named:
    """The IRIs the rows of the document ``document`` (its frozen IRI) lack, given as above; ``served`` the
    highest statement number by node IRI the revisions of the document have given, ``given`` what they named
    by key."""
    nodes, statements = list(nodes), list(statements)
    specifications, variants = list(specifications), list(variants)
    given = given or GivenByKey()
    rows: list[NodeRow | StatementRow | SpecificationRow | VariantRow] = [
        *nodes,
        *statements,
        *specifications,
        *variants,
    ]
    held = _Held(
        [row.iri for row in rows if row.iri is not None]
        + [*given.specifications.values(), *given.variants.values()]
    )
    named = Named()
    _specifications(document, specifications, variants, given, held, named)
    children: dict[UUID | None, list[NodeRow]] = defaultdict(list)
    for row in nodes:
        children[row.parent_id].append(row)
    said: dict[UUID, list[StatementRow]] = defaultdict(list)
    for statement in statements:
        said[statement.node_id].append(statement)
    pending: list[tuple[str, Sequence[NodeRow]]] = [(document, children[None])]
    while pending:
        parent, siblings = pending.pop()
        for row, iri in _siblings(
            parent, sorted(siblings, key=lambda sibling: sibling.position), held, named
        ):
            _statements(row, iri, said[row.id], max(row.statement_serial, (served or {}).get(iri, 0)), named)
            pending.append((iri, children[row.id]))
    return named


class _Held:
    """The segments held under each IRI: by the document's rows, by what its revisions named, by what is
    named now."""

    def __init__(self, iris: Iterable[str]) -> None:
        self._under: dict[str, set[str]] = defaultdict(set)
        for iri in iris:
            parent, _, segment = iri.rpartition("/")
            self._under[parent].add(segment)

    def counter(self, parent: str) -> SegmentCounter:
        """A counter of the segments under ``parent``, past those held there; what it gives is held."""
        return SegmentCounter(self._under[parent])


def _specifications(
    document: str,
    specifications: Sequence[SpecificationRow],
    variants: Sequence[VariantRow],
    given: GivenByKey,
    held: _Held,
    named: Named,
) -> None:
    # a name given by key is taken where no row of the document holds it and none took it in this run
    taken = {row.iri for row in [*specifications, *variants] if row.iri is not None}
    by_id: dict[UUID, tuple[str, str]] = {}  # each specification's key and IRI
    counter = held.counter(f"{document}/spec")
    for place, row in enumerate(sorted(specifications, key=lambda one: one.key), start=1):
        iri = row.iri or _free(given.specifications.get(row.key), f"{document}/spec/", taken)
        if iri is None:
            iri = specification_iri(document, counter.take(key_segment(row.key, place)))
        if row.iri is None:
            named.specifications[row.id] = iri
        by_id[row.id] = (row.key, iri)
    of: dict[UUID, list[VariantRow]] = defaultdict(list)
    for variant in variants:
        of[variant.specification_id].append(variant)
    for specification_id, group in of.items():
        key, under = by_id[specification_id]
        counter = held.counter(f"{under}/variant")
        for place, variant in enumerate(sorted(group, key=lambda one: one.key), start=1):
            iri = variant.iri or _free(given.variants.get((key, variant.key)), f"{under}/variant/", taken)
            if iri is None:
                iri = variant_iri(under, counter.take(key_segment(variant.key, place)))
            if variant.iri is None:
                named.variants[variant.id] = iri


def _free(name: str | None, under: str, taken: set[str]) -> str | None:
    """``name`` where it is one under ``under`` none of ``taken`` holds, then taken; else None."""
    if name is None or not name.startswith(under) or name in taken:
        return None
    taken.add(name)
    return name


def _siblings(
    parent: str, siblings: Sequence[NodeRow], held: _Held, named: Named
) -> list[tuple[NodeRow, str]]:
    counter = held.counter(parent)
    segments = node_segments([(row.code or "", row.code_assigned) for row in siblings])
    placed = []
    for row, segment in zip(siblings, segments, strict=True):
        iri = row.iri
        if iri is None:
            named.nodes[row.id] = iri = node_iri(parent, [counter.take(segment)])
        placed.append((row, iri))
    return placed


def _statements(row: NodeRow, iri: str, statements: Sequence[StatementRow], given: int, named: Named) -> None:
    serial = given
    for statement in sorted(statements, key=lambda said: said.position):
        if statement.iri is None and not statement.rejected:
            serial += 1
            named.statements[statement.id] = statement_iri(iri, serial)
    if serial != given:
        named.serials[row.id] = serial
