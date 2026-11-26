"""The gate of a MEM export (plan M2-6, E10): what refuses the export of an import's frozen state.

The MEM shapes' violations of the export's graph (app/pipeline/shacl_child.py, shape set ``mem``), each
naming the row whose subject it was found at - the document, a node, a statement - so that the editors
find it; warnings and infos refuse nothing. A document of no class known is refused before them: no shape
would target it, and its export would pass unchecked (``DocumentClass``).
"""

from collections.abc import Sequence
from dataclasses import astuple, dataclass
from uuid import UUID

from rdflib import RDF, URIRef

from app.exports.mem_ttl import MemExport
from app.pipeline.shacl_child import ShaclResult

NO_CLASS = "DocumentClass"
# what the gate refuses by: raised with every change of it or of the check in its child (shacl_child.py),
# so that an export or a refusal kept under another gate is made and checked anew (app/exports/mem_export.py,
# fingerprint; the pinned pyshacl's version is part of it on its own). 2: the child validates without
# pyshacl's focus list - nested shapes and blank nodes are checked, a blank node's result goes to its
# holder (audit 2026-11-14) -, so an export or refusal kept under 1 is checked anew
GATE_VERSION = "mem-gate/2"


@dataclass(frozen=True)
class Violation:
    focus: str  # the subject's IRI, a MEM IRI where the row went out under its own
    row_kind: str | None  # document, node or statement; none for a subject of no row (a blank node's)
    row_id: UUID | None
    shape: str
    path: str | None
    message: str


def violations(results: Sequence[ShaclResult], export: MemExport) -> list[Violation]:
    """What refuses the export, ordered by their subjects: none where it may go out."""
    found = [
        _violation(result.focus, export, result.shape, result.path, result.message)
        for result in results
        if result.severity == "violation"
    ]
    document = next(focus for focus, (kind, _) in export.subjects.items() if kind == "document")
    if (URIRef(document), RDF.type, None) not in export.graph:
        found.append(_violation(document, export, NO_CLASS, None, "The plan's class is not known."))
    return sorted(found, key=lambda each: tuple("" if part is None else str(part) for part in astuple(each)))


def _violation(focus: str, export: MemExport, shape: str, path: str | None, message: str) -> Violation:
    kind, row = export.subjects.get(focus, (None, None))
    return Violation(focus, kind, row, shape, path, message)
