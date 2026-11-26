"""How the Kern graph (app/exports/kern_rdf.py) names a document's rows (plan M3a A1): one graph, two
namings.

A draft names every row ``urn:uuid:<id>`` - the draft IRI a document has until it is frozen (plan M1,
IRIs) - so a SHACL focus of X5 is the id of the row it is about. A frozen document is named by the IRIs
freezing stored: its work, the document, its specifications and their variants, its nodes, statements and
rules, its assessments (plan M3a J);
a row of these without its IRI refuses the naming (ValueError), as no urn:uuid leaves the service in an
export, and so do the rows of a document not frozen - a draft copy's carry the IRIs of the revision it
copies, but no time it was frozen. Anchors, the file and the second layer's values (levels, time spans,
workloads, applicability contexts; plan M3a E4, H1) have no identity beyond their document: each is a blank
node, the same one for the same row throughout one build - a frozen naming serves one graph.
"""

from typing import Literal, Protocol
from uuid import UUID

from rdflib import BNode, URIRef

from app.exports.kern_rows import Row

RowKind = Literal[
    "work", "document", "specification", "variant", "node", "statement", "anchor", "file", "level_assignment",
    "time_span", "workload", "applicability_context", "rule", "assessment",
]  # fmt: skip
_NAMED_BY_IRI: frozenset[RowKind] = frozenset(
    {"work", "document", "specification", "variant", "node", "statement", "rule", "assessment"}
)


class Naming(Protocol):
    frozen: bool  # whether the names are the frozen document's, which then says when it was frozen

    def of(self, kind: RowKind, row: Row) -> URIRef | BNode: ...


def row_iri(row_id: UUID) -> URIRef:
    return URIRef(f"urn:uuid:{row_id}")


class _DraftNaming:
    frozen = False

    def of(self, kind: RowKind, row: Row) -> URIRef | BNode:
        return row_iri(row["id"])


class _FrozenNaming:
    frozen = True

    def __init__(self) -> None:
        self._blank: dict[UUID, BNode] = {}

    def of(self, kind: RowKind, row: Row) -> URIRef | BNode:
        if kind not in _NAMED_BY_IRI:
            return self._blank.setdefault(row["id"], BNode())
        if kind == "document" and row["frozen_at"] is None:
            raise ValueError(f"the document {row['id']} is not frozen: a draft is named by its rows' ids")
        if row["iri"] is None:
            raise ValueError(f"the {kind} {row['id']} has no IRI: a frozen document names each of its rows")
        return URIRef(row["iri"])


def draft_naming() -> Naming:
    """Every row by its urn:uuid."""
    return _DraftNaming()


def frozen_naming() -> Naming:
    """Each row by its stored IRI, an anchor and the file by a blank node; a fresh one for each graph."""
    return _FrozenNaming()
