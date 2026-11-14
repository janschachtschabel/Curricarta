"""A frozen MEM import as MEM's own RDF (plan M2-6; E7-E9, E14): the graph the export checks against the MEM
shapes and hands out as Turtle.

- **Subjects (E7):** a row the import wrote and nobody changed (origin ``orig_import``, a MEM IRI) goes out
  under its MEM IRI - reviewed or not, a review keeps the origin; a row an editor changed goes out under its
  own IRI, ``prov:wasDerivedFrom`` its MEM IRI; a row the editors made under its own IRI. The document goes
  out under its own IRI, ``dcterms:source`` and ``prov:wasDerivedFrom`` the MEM plan. Only a frozen
  document is exported - a draft copy carries its revision's IRIs, but no ``frozen_at`` -, and only an
  import: anything else, and a changed row without an IRI of its own, is refused (ValueError).
- **Classes (E8/E9):** an unchanged row's classes as MEM gave them, and where none of them reaches a base
  class through the chain the shapes read, the table's base class beside them
  (app/sources/mem/classes.base_to_add); a changed or new row the base class of its core typing
  (``generic_class``) and of MEM's classes only those of that base. A node the core types by no base (an
  area of another type, a subunit) keeps the base its MEM classes reach - a title fix makes no Fragment of a
  Kompetenzspezifikation with parts -, an area a Bereich or Leitperspektive first, a subunit MEM names a
  Verweis a Verweis first, as the import typed it. A reference statement the editors made or made one - of no
  target and no holder MEM named, as the core names neither - goes out as a Hinweis: MEM's reference shape
  could not be met. One MEM named stays a reference, and fails that shape as MEM gave it.
- **Structure:** every row is part of its parent (``BFO_0000050``, and the parent has it,
  ``BFO_0000051``), a root of the document - but a reference MEM reaches by ``hat Verweis`` alone
  (``held_only``), which MEM makes no part. An unchanged reference is held (``LP_0030071``) by the
  holders MEM named alone - none is made up in MEM's name, so one MEM names none fails its shape -, one
  the editors made or changed by its node; a reference points at its targets (``LP_0030072``). An unchanged
  row keeps every holder and target MEM named, whatever its class; a changed one only where it still is a
  reference by its classes' bases. What MEM said beside - number,
  position, grades, hours, page, description, further parents (both ways, as the main one) - goes back
  out as MEM writes it; the description and the hours as the blank nodes MEM gives them, rebuilt from
  their text.
- **Rights (E14):** the attribution (``dcterms:bibliographicCitation``) and the rights status of the
  wordings (``dcterms:rights``) at the document; a licence recorded for the MEM data is the MEM plan's
  (``<plan> dcterms:license``), never the wordings' - none is written while none is recorded.

A MEM IRI that another row of the document carries is that row's subject; one no row carries is written as
it stands, where the tables would take it (tree.storable_iri), else left out.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from typing import Literal as Kind
from uuid import UUID

from rdflib import RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV
from rdflib.term import Node

from app.exports.kern_rows import Row
from app.exports.mem_rows import MemRows
from app.sources.mem.classes import BASE_ORDER, MemModel, base_to_add, generic_class
from app.sources.mem.queries import LP
from app.sources.mem.tree import VERWEIS, storable_iri

MEM_EXPORT = "mem-ttl/1"
OBO = "http://purl.obolibrary.org/obo/"
PART_OF, HAS_PART = URIRef(OBO + "BFO_0000050"), URIRef(OBO + "BFO_0000051")
HOLDS, POINTS_AT = URIRef(LP + "LP_0030071"), URIRef(LP + "LP_0030072")
LEHRPLAN, STANDARD = LP + "LP_0000438", LP + "LP_0000571"
_IMPORTED = "https://w3id.org/wlo/curriculum/vocab#orig_import"
_REFERENCE = "https://w3id.org/wlo/curriculum/vocab#kind_reference"
_AREA = "https://w3id.org/wlo/curriculum/vocab#fn_area"
_SUBUNIT = "https://w3id.org/wlo/curriculum/vocab#fn_subunit"
_BEREICH, _FRAGMENT, _HINWEIS = LP + "LP_0000349", LP + "LP_0001015", LP + "LP_0000852"
_LEITPERSPEKTIVE = LP + "LP_0030325"
# what MEM says beside a part, as the import kept it (app/sources/mem/drafts.py, _trace)
_TEXTS = {"number": LP + "LP_0030057", "position": LP + "LP_0000460"}
_VALUES = {"grades": LP + "LP_0000026", "page": LP + "LP_0000463"}


@dataclass(frozen=True)
class MemExport:
    graph: Graph
    # the subject of each row and of the document: what it is and its id, to name a violation's row
    subjects: Mapping[str, tuple[Kind["document", "node", "statement"], UUID]]


def mem_graph(rows: MemRows, model: MemModel) -> MemExport:
    """The import's graph, as the module says."""
    graph = Graph()
    for prefix, namespace in (("lp", LP), ("obo", OBO), ("dcterms", str(DCTERMS)), ("prov", str(PROV))):
        graph.bind(prefix, namespace)
    document = _document(graph, rows.document)
    subjects: dict[str, tuple[Kind["document", "node", "statement"], UUID]] = {
        str(document): ("document", rows.document["id"])
    }
    by_id: dict[UUID, URIRef] = {}
    for kind, found in (("node", rows.nodes), ("statement", rows.statements)):
        for row in found:
            by_id[row["id"]] = subject = _subject(row)
            subjects[str(subject)] = (kind, row["id"])  # type: ignore[assignment]  # one of the two kinds
    by_mem = {row["mem_iri"]: by_id[row["id"]] for row in (*rows.nodes, *rows.statements) if row["mem_iri"]}
    for node in rows.nodes:
        parent = document if node["parent_id"] is None else by_id[node["parent_id"]]
        _row(graph, node, by_id[node["id"]], parent, model, by_mem)
        _label(graph, by_id[node["id"]], node["original_title"], node["title_language"])
    for statement in rows.statements:
        subject, holder = by_id[statement["id"]], by_id[statement["node_id"]]
        referring = _row(graph, statement, subject, holder, model, by_mem)
        _label(graph, subject, statement["verbatim"], statement["language"])
        if referring and statement["statement_kind_iri"] == _REFERENCE and not _unchanged(statement):
            graph.add((holder, HOLDS, subject))
    return MemExport(graph, subjects)


def _document(graph: Graph, row: Row) -> URIRef:
    if not row["iri"] or row["frozen_at"] is None:
        raise ValueError(f"document {row['id']} is not frozen: only a frozen one is exported")
    if not row["mem_iri"]:
        raise ValueError(f"document {row['id']} names no MEM plan: it is no import")
    document, plan = URIRef(row["iri"]), URIRef(row["mem_iri"])
    klass = row["mem_class_iri"]
    if klass:  # a plan of no class known is typed by none: no shape targets it (the gate decides)
        graph.add((document, RDF.type, URIRef(klass)))
        if klass != STANDARD:
            graph.add((document, RDF.type, URIRef(LEHRPLAN)))
    if row["mem_land_iri"]:
        graph.add((document, URIRef(LP + "LP_0000029"), URIRef(row["mem_land_iri"])))
    for subject in row["mem_subjects"]:
        graph.add((document, URIRef(LP + "LP_0000537"), _value(subject)))
    for school_type in row["mem_school_types"]:
        graph.add((document, URIRef(LP + "LP_0000812"), _value(school_type)))
    if row["title"]:
        graph.add((document, RDFS.label, Literal(row["title"], lang="de")))
    graph.add((document, DCTERMS.source, plan))
    graph.add((document, PROV.wasDerivedFrom, plan))
    if row["mem_attribution"]:
        graph.add((document, DCTERMS.bibliographicCitation, Literal(row["mem_attribution"])))
    rights = f"Rechtestatus der Wortlaute: {row['rights_status']}"
    graph.add((document, DCTERMS.rights, Literal(rights, lang="de")))
    if row["mem_licence"]:
        licence = row["mem_licence"]
        graph.add((plan, DCTERMS.license, URIRef(licence) if storable_iri(licence) else Literal(licence)))
    return document


def _unchanged(row: Row) -> bool:
    return row["origin_iri"] == _IMPORTED and row["mem_iri"] is not None


def _subject(row: Row) -> URIRef:
    if _unchanged(row):
        return URIRef(row["mem_iri"])
    if not row["iri"]:
        raise ValueError(f"row {row['id']} has no IRI of its own: only a frozen document is exported")
    return URIRef(row["iri"])


def _row(
    graph: Graph, row: Row, subject: URIRef, parent: URIRef, model: MemModel, by_mem: Mapping[str, URIRef]
) -> bool:
    """The row's triples; whether its holders and targets go out - every unchanged row's, as MEM named them,
    a changed row's where its classes' bases make it a reference."""
    classes = _classes(row, model)
    for klass in classes:
        graph.add((subject, RDF.type, URIRef(klass)))
    properties: Mapping[str, Any] = row["mem_properties"] or {}
    referring = _unchanged(row) or any(VERWEIS in _bases(klass, model) for klass in classes)
    if not (referring and properties.get("held_only")):
        graph.add((subject, PART_OF, parent))
        graph.add((parent, HAS_PART, subject))
    if row["mem_iri"] and not _unchanged(row):
        graph.add((subject, PROV.wasDerivedFrom, URIRef(row["mem_iri"])))
    _beside(graph, subject, properties, by_mem, referring=referring)
    return referring


def _classes(row: Row, model: MemModel) -> list[str]:
    stored: list[str] = list(row["mem_classes"] or ())
    if _unchanged(row):
        added = base_to_add(stored, model)
        found = [*stored, *([added] if added else [])]
        if found:
            return found
    generic = generic_class(
        function=row.get("function_iri"),
        node_type=row.get("node_type_iri"),
        kind=row.get("statement_kind_iri"),
    )
    function = row.get("function_iri")
    if generic == _FRAGMENT and function in (_AREA, _SUBUNIT):  # the core's typing names no base
        reached = set().union(*(_bases(klass, model) for klass in stored))
        if function == _AREA:
            order: tuple[str, ...] = (_BEREICH, _LEITPERSPEKTIVE, *BASE_ORDER)
        else:  # a subunit: a Verweis first, as the import typed one (app/sources/mem/classes.py)
            order = (VERWEIS, *BASE_ORDER) if VERWEIS in stored else BASE_ORDER
        generic = next((base for base in order if base in reached), generic)
    properties = row["mem_properties"] or {}
    if (
        not _unchanged(row)
        and row.get("statement_kind_iri") == _REFERENCE
        and generic == VERWEIS
        and not properties.get("targets")
        and not properties.get("holders")
    ):  # a reference the editors made: nothing in the core names its target
        generic = _HINWEIS
    return [generic, *(klass for klass in stored if klass != generic and generic in _bases(klass, model))]


def _bases(klass: str, model: MemModel) -> frozenset[str]:
    own = frozenset({klass}) & frozenset(BASE_ORDER)
    return own | model.chain_bases.get(klass, frozenset()) | model.table_bases.get(klass, frozenset())


def _beside(
    graph: Graph,
    subject: URIRef,
    properties: Mapping[str, Any],
    by_mem: Mapping[str, URIRef],
    *,
    referring: bool,
) -> None:
    for name, predicate in _TEXTS.items():
        if name in properties:
            graph.add((subject, URIRef(predicate), Literal(properties[name])))
    for name, predicate in _VALUES.items():
        found = properties.get(name)
        for value in [found] if isinstance(found, str) else found or ():
            graph.add((subject, URIRef(predicate), _value(value)))
    if description := properties.get("description"):
        blank = BNode()
        graph.add((subject, URIRef(LP + "LP_0030051"), blank))
        graph.add((blank, DCTERMS.description, Literal(description)))
    if hours := properties.get("hours"):
        blank = BNode()
        graph.add((subject, URIRef(LP + "LP_0000024"), blank))
        graph.add((blank, RDF.type, URIRef(LP + "LP_0000508")))
        graph.add((blank, URIRef(LP + "LP_0000344"), Literal(hours)))
    for parent in _resolved(properties.get("other_parents", ()), by_mem):
        graph.add((subject, PART_OF, parent))
        graph.add((parent, HAS_PART, subject))
    if not referring:  # holding and pointing are a reference's: one an editor made another kind has none
        return
    for holder in _resolved(properties.get("holders", ()), by_mem):
        graph.add((holder, HOLDS, subject))
    for target in properties.get("targets", ()):
        graph.add((subject, POINTS_AT, _value(target)))


def _value(value: str) -> Node:
    return URIRef(value) if storable_iri(value) else Literal(value)


def _resolved(iris: Iterable[str], by_mem: Mapping[str, URIRef]) -> list[URIRef]:
    return [by_mem.get(iri) or URIRef(iri) for iri in iris if iri in by_mem or storable_iri(iri)]


def _label(graph: Graph, subject: URIRef, text: str | None, language: str | None) -> None:
    if text:
        graph.add((subject, RDFS.label, Literal(text, lang=language) if language else Literal(text)))
