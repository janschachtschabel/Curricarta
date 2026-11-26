"""The SHACL validation X5 runs in a child process (plan M1 8.4; app/pipeline/shacl.py starts it).

As ontology/pruefung/pruefe.py checks the examples: the shapes of cur-shapes.ttl and profil-shapes.ttl,
no inference (konzept §14: RDFS inference would hide 22 class checks), the model in the data graph -
``sh:class`` reads ``rdfs:subClassOf`` from cur-kern, the In… shapes ``skos:inScheme``, the node type and
subkind checks ``skos:broader``. Measured on the examples and on documents as the export writes them
(plan M1, Nachtrag 8a): the model without the lexicons, alignments and migration finds what the whole
model finds; and rdflib parses and translates a SPARQL constraint's query anew for each focus node - two
thirds of the time - so its translation is kept for the run (``queries_kept_translated``), the reuse
rdflib's ``prepareQuery`` stands for.

Every node the shapes target is a focus, the model's too; the results are kept on the data's subjects
(``_results``), a blank node's given to the row that holds it. pyshacl's ``focus_nodes`` is not used: it
filters the nested shape a ``sh:node`` (``sh:or``, ``sh:not``, ...) evaluates on a value by the same list,
so no value's vocabulary (``shs:In…``) was ever checked, leaves out every blank node, and tests each
target against the list - a time growing with the square of the rows (audit 2026-11-14). Measured on a
synthetic document (app/exports/measure_kern.py), on a machine under other load: 2,400 rows 7-11 s,
17-19 s with it; 11,000 rows 30-41 s, 228 s with it; 200 rows 2.2-2.8 s, 1.5-2.0 s with it - the model's
own nodes, a second at most.

Two shape sets: ``kern``, the core's and the profiles' over the core's model, as above; and ``mem``, the
MEM-Schule shapes (ontology/mem/shapes, plan M2) over the class chain of the FWU ontology
(ontology/mem/lp-klassen.ttl), as lp.ttl gives it. A state class whose base class follows from its
function value only does not reach it so; the export writes that base class beside it (plan M2, E9).

pyshacl is imported here alone, in the child: the worker never loads it.
"""

import contextlib
import json
import logging
import traceback
import typing
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef
from rdflib.term import Node

from app.core.child import ChildLog, log_peak, stand_alone, write
from app.vocab.loader import MODEL_DIRS

SH = Namespace("http://www.w3.org/ns/shacl#")
SHAPE_FILES = ("ontologie/cur-shapes.ttl", "profile/profil-shapes.ttl")
ShapeSet = typing.Literal["kern", "mem"]  # rdflib's Literal is the one imported
MEM_DIR = "mem"  # in the image beside MODEL_DIRS (deploy/api.Dockerfile)
# named, as SHAPE_FILES: a folder missing or emptied fails, rather than every graph conforming
MEM_SHAPE_FILES = tuple(
    f"{MEM_DIR}/shapes/{name}.ttl" for name in ("bereich", "lehrplan", "textual-entity", "verweis")
)
MEM_MODEL = f"{MEM_DIR}/lp-klassen.ttl"
_LEFT_OUT = ("-lexikon", "cur-alignments", "migration")  # no shape a document's row meets reads them
_LIBRARIES = ("rdflib", "pyshacl", "owlrl")
_SEVERITIES = {str(SH.Violation): "violation", str(SH.Warning): "warning", str(SH.Info): "info"}
_SEE_DETAILS = "See details for more information."  # pyshacl's, where a nested shape's result says more
_PREFIXES = (
    ("cur", "https://w3id.org/wlo/curriculum/core#"),
    ("dct", "http://purl.org/dc/terms/"),
    ("skos", "http://www.w3.org/2004/02/skos/core#"),
    ("prov", "http://www.w3.org/ns/prov#"),
)


class ShaclResult(NamedTuple):
    focus: str  # the focus node's IRI
    shape: str  # the node shape's name in shs: (of a property shape, its node shape's)
    severity: str  # violation, warning, info
    path: str | None  # the property, as a CURIE where its namespace is bound
    message: str
    value: str | None
    component: str | None  # the constraint component's name
    lang: str | None = None  # the message's language where the shape gave one (sh:message "…"@de)
    held_by: str | None = None  # a blank node's: the properties from the row it is moved to down to it


def model_paths(ontology_dir: Path) -> list[Path]:
    # the folders the image holds; their files, not their subfolders: as pruefe.py
    paths = [path for folder in MODEL_DIRS for path in sorted((ontology_dir / folder).glob("*.ttl"))]
    return [path for path in paths if not any(mark in path.name for mark in _LEFT_OUT)]


def validate_graph(ontology_dir: Path, data: Graph, shapes: ShapeSet = "kern") -> list[ShaclResult]:
    """The results of the set's shapes over ``data`` at its subjects - a blank node's at the row holding it
    (``_holder``) -: its model read, the queries kept."""
    from pyshacl import validate

    if shapes == "mem":
        shape_graph = _parsed([ontology_dir / name for name in MEM_SHAPE_FILES])
        model = _parsed([ontology_dir / MEM_MODEL])
    elif shapes == "kern":
        shape_graph = _parsed([ontology_dir / name for name in SHAPE_FILES])
        model = _parsed(model_paths(ontology_dir))
    else:
        raise ValueError(f"{shapes!r} is no shape set (kern, mem)")
    with queries_kept_translated():
        _, report, _ = validate(
            model + data, shacl_graph=shape_graph, inference="none", advanced=True, allow_warnings=True,
            meta_shacl=False,
        )  # fmt: skip
    return _results(report, shape_graph, data)


@contextlib.contextmanager
def queries_kept_translated() -> Iterator[None]:
    """rdflib's SPARQL queries translated once each, while the block runs: pyshacl asks the same query
    text for each focus node, with ``$this`` bound by initBindings, and rdflib parses it each time."""
    from rdflib.plugins.sparql import processor
    from rdflib.plugins.sparql.algebra import translateQuery
    from rdflib.plugins.sparql.evaluate import evalQuery
    from rdflib.plugins.sparql.parser import parseQuery

    asked = processor.SPARQLProcessor.query
    kept: dict[tuple[Any, ...], Any] = {}

    def query(  # the signature of SPARQLProcessor.query
        self: Any,
        text: Any,
        initBindings: Any = None,
        initNs: Any = None,
        base: Any = None,
        DEBUG: bool = False,
    ) -> Any:
        if not isinstance(text, str):
            return asked(self, text, initBindings or {}, initNs or {}, base, DEBUG)
        key = (text, base, tuple(sorted((initNs or {}).items())))
        if key not in kept:
            kept[key] = translateQuery(parseQuery(text), base, initNs or {})
        return evalQuery(self.graph, kept[key], initBindings or {}, base)

    processor.SPARQLProcessor.query = query  # type: ignore[method-assign, assignment]
    try:
        yield
    finally:
        processor.SPARQLProcessor.query = asked  # type: ignore[method-assign]


def run_child(ontology_dir: str, data: str, shapes: ShapeSet, told: ChildLog, out: str) -> None:
    """The child: validate the N-Triples file ``data`` by the shape set, and leave the results in ``out``."""
    stand_alone(told, _LIBRARIES)
    # pyshacl's validate logs to a logger of its own, which it sets to INFO with a handler of its own on
    # every call: a filter it leaves holds the quiet rule there (stand_alone's), and what passes it is
    # written twice - by the root's handler and once more, plain, by pyshacl's own on stderr
    quietest = max(logging.WARNING, logging.getLogger().level)
    logging.getLogger("pyshacl-validate").addFilter(lambda record: record.levelno >= quietest)
    try:
        _answer(ontology_dir, data, shapes, out)
    finally:
        log_peak()  # however it ends: the measure of CHILD_MEMORY_LIMIT_MB


def _answer(ontology_dir: str, data: str, shapes: ShapeSet, out: str) -> None:
    # MemoryError too - an allocation past CHILD_MEMORY_LIMIT_MB -: crashed, by its kind
    try:
        results = validate_graph(Path(ontology_dir), Graph().parse(Path(data), format="nt"), shapes)
    except Exception as error:
        frames = "".join(traceback.format_tb(error.__traceback__))
        logging.getLogger(__name__).error("the SHACL validation raised %s\n%s", type(error).__name__, frames)
        write(Path(out) / "crashed.json", json.dumps({"error": type(error).__name__}))
        raise SystemExit(1) from None
    write(Path(out) / "result.json", json.dumps([list(result) for result in results]))


def _parsed(paths: list[Path]) -> Graph:
    graph = Graph()
    for path in paths:
        if not path.is_file():  # rdflib would read a missing path as a URL ("C:" its scheme)
            raise FileNotFoundError(path)
        graph.parse(path, format="turtle")
    return graph


def _results(report: Graph, shapes: Graph, data: Graph) -> list[ShaclResult]:
    subjects = set(data.subjects())
    found = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        focus = report.value(result, SH.focusNode)
        # a nested shape's result (sh:detail of another) is part of that one's finding: its focus is the value
        if focus not in subjects or (None, SH.detail, result) in report:
            continue
        shape = report.value(result, SH.sourceShape)
        if isinstance(shape, BNode):
            shape = shapes.value(None, SH.property, shape) or shape
        path = report.value(result, SH.resultPath)
        value = report.value(result, SH.value)
        component = report.value(result, SH.sourceConstraintComponent)
        message = report.value(result, SH.resultMessage)  # pyshacl's own, English, where the shape gave none
        row, held_by = _holder(data, focus)
        found.append(
            ShaclResult(
                row, _name(shape), _SEVERITIES[str(report.value(result, SH.resultSeverity))],
                _path(report, path),
                _message(report, result),
                None if value is None else str(value), None if component is None else _name(component),
                _language(message, report.value(result, SH.sourceConstraint), shapes), held_by,
            )
        )  # fmt: skip
    return sorted(found, key=lambda result: [part or "" for part in result])


def _holder(data: Graph, focus: Any) -> tuple[str, str | None]:
    """The focus as the row it is about, and the properties it is held by there: a named node itself, by
    none; a blank node - X1's reading of an applicability, a value or an anchor once frozen - the nearest
    named subject that holds it, followed back through the blank nodes between (the first by name where
    several are as near), by the properties from it down to the focus (``cur:applicability/cur:timeSpan``,
    the first by name where there are several); a blank node nothing named holds, itself (``_:``), which
    the caller gives to the document."""
    if not isinstance(focus, BNode):
        return str(focus), None
    ways: dict[Node, str] = {focus: ""}  # a node's properties down to the focus
    layer: set[Node] = {focus}
    while layer:
        found: dict[Node, str] = {}
        for node in layer:
            for subject, predicate in data.subject_predicates(node):
                if subject in ways:
                    continue
                way = "/".join(filter(None, (_curie(URIRef(str(predicate))), ways[node])))
                found[subject] = min(way, found.get(subject, way))
        named = sorted((str(holder), way) for holder, way in found.items() if not isinstance(holder, BNode))
        if named:
            return named[0]
        ways |= found
        layer = set(found)
    return f"_:{focus}", None


def _message(report: Graph, result: Any) -> str:
    """The result's message; pyshacl's "See details" of a shape nested in it (sh:node) given as what the
    nested shape's results say, for no finding keeps them (``_results``)."""
    message = str(report.value(result, SH.resultMessage) or "")
    if not message.endswith(_SEE_DETAILS):
        return message
    nested = sorted(_message(report, detail) for detail in report.objects(result, SH.detail))
    return " ".join([message.removesuffix(_SEE_DETAILS).rstrip(), *nested])


def _language(message: Any, constraint: Any, shapes: Graph) -> str | None:
    """The message's language: its literal's - or, where pyshacl wrote a SPARQL constraint's message
    anew without it, the language the constraint declares its message in."""
    if isinstance(message, Literal) and message.language:
        return message.language
    declared = None if constraint is None else shapes.value(constraint, SH.message)
    return declared.language if isinstance(declared, Literal) else None


def _path(report: Graph, path: Any) -> str | None:
    """The result's property as a CURIE, an inverse one as SPARQL writes it ("^cur:represents")."""
    if isinstance(path, URIRef):
        return _curie(path)
    inverse = None if path is None else report.value(path, SH.inversePath)
    return f"^{_curie(inverse)}" if isinstance(inverse, URIRef) else None


def _curie(path: URIRef) -> str:
    for prefix, namespace in _PREFIXES:
        if str(path).startswith(namespace):
            return f"{prefix}:{str(path).removeprefix(namespace)}"
    return str(path)


def _name(term: Any) -> str:
    text = str(term)
    return text.rsplit("#", 1)[-1] if "#" in text else text
