"""The Kern export's child process (plan M3a C1; app/exports/kern_export.py starts it): a frozen document's
rows, read from a file, built into its Kern graph under its stored IRIs (app/exports/kern_rdf.py,
app/exports/kern_naming.py) and written as Turtle - seconds of CPU for a long document, which neither the
API's event loop nor a thread of it (the GIL) may spend.

The bytes are the same for the same rows in every process: the serializer sorts subjects and objects, and
a blank node - an anchor, the file - sorts by its label, which rdflib draws at random; here each takes the
next of a fixed row of labels, in the order the graph names its rows (read in a fixed order). Comment
lines head the file: the document's IRI, its revision and the violations the editors accepted when they
froze it (plan M3a E7) - and, where X5 checked it under another graph than this builder writes
(KERN_GRAPH_VERSION), the version it checked and this one's: frozen, it is checked no more, and the
count stays the one accepted.

What the child does not answer - it raised, or ended without its file - the parent counts as no export.
"""

import logging
import os
import pickle
import traceback
from pathlib import Path

from rdflib import BNode, URIRef

from app.core.child import ChildLog, log_peak, stand_alone, write
from app.exports.kern_naming import Naming, RowKind, frozen_naming
from app.exports.kern_rdf import KERN_GRAPH_VERSION, kern_graph
from app.exports.kern_rows import KernRows, Row

# the version of what the build writes beside the graph (KERN_GRAPH_VERSION): another makes the kept exports
# unused; tests/exports/test_kern_versions.py pins it to the source
KERN_EXPORT = "kern-ttl/2"
ANSWER = "kern.ttl"
_LIBRARIES = ("rdflib",)


class _FixedBlanks:
    """The frozen naming, each blank node relabelled by the order it was first named in."""

    frozen = True

    def __init__(self, naming: Naming) -> None:
        self._naming = naming
        self._labels: dict[BNode, BNode] = {}

    def of(self, kind: RowKind, row: Row) -> URIRef | BNode:
        name = self._naming.of(kind, row)
        if isinstance(name, BNode):
            return self._labels.setdefault(name, BNode(f"b{len(self._labels)}"))
        return name


def turtle(rows: KernRows) -> bytes:
    """The frozen document's Kern Turtle, its comment lines first."""
    graph = kern_graph(rows, _FixedBlanks(frozen_naming()))
    document = rows.document
    head = (
        f"# Curriculum-Kern 1.0 ({KERN_EXPORT})\n"
        f"# document: <{document['iri']}>\n"
        f"# revision: {document['revision']}\n"
        f"# accepted violations: {document['violations']}\n"
    )
    if (checked := _checked_version(document)) is not None:
        head += f"# checked under graph version: {checked}, built with graph version: {KERN_GRAPH_VERSION}\n"
    return head.encode() + graph.serialize(format="turtle", encoding="utf-8")


def checked_under(document: Row) -> str | None:
    """``checked=<version>; built=<version>`` where X5 checked the frozen document under another graph than
    this builder writes - ``unknown`` where its check recorded none (migration 0036) -; None where it is
    the same."""
    checked = _checked_version(document)
    return None if checked is None else f"checked={checked}; built={KERN_GRAPH_VERSION}"


def _checked_version(document: Row) -> str | None:
    checked = document["checked_graph"]
    if checked == KERN_GRAPH_VERSION:
        return None
    return "unknown" if checked is None else str(checked)


def run_child(rows: str, told: ChildLog, out: str) -> None:
    """The child: the Turtle of the pickled rows in the file ``rows``, left in ``out``."""
    stand_alone(told, _LIBRARIES)
    try:
        _answer(Path(rows), Path(out))
    finally:
        log_peak()  # however it ends: the measure of CHILD_MEMORY_LIMIT_MB


def _answer(rows: Path, out: Path) -> None:
    # MemoryError too - an allocation past CHILD_MEMORY_LIMIT_MB -: crashed, by its kind
    try:
        data = turtle(pickle.loads(rows.read_bytes()))  # noqa: S301 - the parent's own file, of its own rows
    except Exception as error:
        frames = "".join(traceback.format_tb(error.__traceback__))
        logging.getLogger(__name__).error("the Kern export raised %s\n%s", type(error).__name__, frames)
        write(out / "crashed.txt", type(error).__name__)
        raise SystemExit(1) from None
    part = out / (ANSWER + ".part")  # whole or not at all: the parent reads only the renamed file
    part.write_bytes(data)
    os.replace(part, out / ANSWER)
