"""A document of the first layer as Curriculum-Kern 1.0 RDF (plan M1 8.3; konzept §4, §5): the document, the
work it is a version of, its revision and the file it is in (plan M3a A1), the rights status of its wordings
and where it came from (C1), the edition it supersedes by that edition's IRI (B2), its specifications and
their variants, its nodes (cur:partOf the parent node, a root at its one specification), statements and the
anchors of nodes and statements, as the rows of app/exports/kern_rows.py hold them, the values of the
second layer at their holders (plan M3a F1, app/exports/kern_values.py) and each specification's
applicability (plan M3a H1, app/exports/kern_scope.py), its rules with their anchors (plan M3a I,
app/exports/kern_rules.py) and the document's assessments (plan M3a J, app/exports/kern_assessments.py).

One graph under either naming (app/exports/kern_naming.py): a draft's, each row ``urn:uuid:<id>``, so a
SHACL focus node of X5 is the id of the row it is about; or a frozen document's, by its stored IRIs, which
alone states when the document was frozen (prov:generatedAtTime). A node lacks the docking points every
unit of it checked absent (cur:checkedAbsent). Left out: the frame parts but rules, and their anchors (in the
Kern they would be nodes of function fn_frame), the profile's own terms, and the anchors of the document and
of specifications.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from rdflib import OWL, PROV, RDF, SKOS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS

from app.exports.kern_assessments import add_assessments
from app.exports.kern_naming import Naming, RowKind, draft_naming
from app.exports.kern_rows import KernRows, Row
from app.exports.kern_rules import add_rules, rule_names
from app.exports.kern_scope import add_scope
from app.exports.kern_values import add_values
from app.sources.mem.tree import storable_iri

# The version of the graph this module writes of the rows app/exports/kern_rows.py reads, and of how X5
# checks it (app/pipeline/shacl_child.py, its shapes, model and pyshacl): X5 records it with each check
# (app/db/runs.py), a draft checked under an older one is owed a check, and an export says when a frozen
# document was checked under another. tests/exports/test_kern_versions.py pins it to all of these: a change
# of the check alone is a new version too, owing every draft a check and moving the kept exports' fingerprint.
KERN_GRAPH_VERSION = 7
CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
CV = Namespace("https://w3id.org/wlo/curriculum/vocab#")
_SPECIFICATION_CLASSES = {
    "curriculum": CUR.Curriculum,
    "competencyFramework": CUR.CompetencyFramework,
    "qualificationSpecification": CUR.QualificationSpecification,
    "assessmentSpecification": CUR.AssessmentSpecification,
}
_TEXTS = ("levelText", "timeText", "contextText", "referenceMarker")  # details as written, xsd:string
_DATES = {4: XSD.gYear, 7: XSD.gYearMonth, 10: XSD.date}  # by length: YYYY, YYYY-MM, YYYY-MM-DD

Name = URIRef | BNode
Names = Mapping[UUID, Name]


def kern_graph(rows: KernRows, naming: Naming | None = None) -> Graph:
    """The document's Kern graph under ``naming`` - a draft's where none is given - its namespaces bound."""
    if naming is None:
        naming = draft_naming()
    graph = Graph()
    for prefix, namespace in (
        ("cur", CUR), ("cv", CV), ("dct", DCTERMS), ("owl", OWL), ("prov", PROV), ("skos", SKOS),
        ("xsd", XSD),
    ):  # fmt: skip
        graph.bind(prefix, namespace)
    names = _names(rows, naming) | rule_names(rows, naming)
    document = names[rows.document["id"]]
    specifications = [row["id"] for row in rows.specifications]
    _document(graph, rows.document, names, specifications)
    if naming.frozen:
        _add(graph, document, PROV.generatedAtTime, rows.document["frozen_at"])
    if rows.work is not None:
        _work(graph, rows.work, names, document)
    _file(graph, rows.file, names, document)
    for specification in rows.specifications:
        _specification(graph, specification, names)
    for variant in rows.variants:
        _variant(graph, variant, names)
    for node in rows.nodes:
        _node(graph, node, names, _parent(node, names, specifications, document))
    at_place = {(row["node_id"], row["position"]): row["id"] for row in rows.statements}
    for statement in rows.statements:
        _statement(graph, statement, names, at_place)
    for anchor in rows.anchors:
        _anchor(graph, anchor, names, document)
    add_values(graph, rows, naming)
    add_scope(graph, rows, naming)
    add_rules(graph, rows, names)
    add_assessments(graph, rows, naming)
    return graph


def _names(rows: KernRows, naming: Naming) -> dict[UUID, Name]:
    """Each row's name, by its id."""
    kinds: list[tuple[RowKind, list[Row]]] = [
        ("document", [rows.document]), ("work", [rows.work] if rows.work is not None else []),
        ("file", [rows.file]), ("specification", rows.specifications), ("variant", rows.variants),
        ("node", rows.nodes), ("statement", rows.statements), ("anchor", rows.anchors),
    ]  # fmt: skip
    return {row["id"]: naming.of(kind, row) for kind, items in kinds for row in items}


def _add(graph: Graph, subject: Name, predicate: URIRef, value: Any, **literal: Any) -> None:
    """``subject predicate value``, where there is a value: an IRI as given, else a literal."""
    if value is None:
        return
    graph.add((subject, predicate, value if isinstance(value, URIRef) else Literal(value, **literal)))


def _iri(value: str | None) -> URIRef | None:
    return None if value is None else URIRef(value)


def _date(value: str | None) -> Literal | None:
    return None if value is None else Literal(value, datatype=_DATES[len(value)])


def _document(graph: Graph, row: Row, names: Names, specifications: Sequence[UUID]) -> None:
    subject = names[row["id"]]
    graph.add((subject, RDF.type, CUR.Document))
    graph.add((subject, OWL.versionInfo, Literal(str(row["revision"]))))  # its revisions share its IRI
    # the rights status of its wordings, as the register holds it (plan M3a E13: no licence of our own)
    graph.add(
        (subject, DCTERMS.rights, Literal(f"Rechtestatus der Wortlaute: {row['rights_status']}", lang="de"))
    )
    _sources(graph, subject, row)
    _add(graph, subject, DCTERMS.title, row["title"])
    _add(graph, subject, DCTERMS.publisher, row["issuer"])
    _add(graph, subject, CUR.edition, row["edition"])
    _add(graph, subject, CUR.supersedes, _iri(row["supersedes_iri"]))  # frozen: its IRI in either naming
    for predicate, column in (
        (CUR.documentType, "document_type_iri"), (CUR.educationSector, "sector_iri"),
        (CUR.legalForm, "legal_form_iri"), (CUR.documentBinding, "binding_iri"),
        (CUR.lifecycle, "lifecycle_iri"),
    ):  # fmt: skip
        _add(graph, subject, predicate, _iri(row[column]))
    for region in row["region_iris"]:
        graph.add((subject, CUR.region, URIRef(region)))
    for predicate, column in (
        (CUR.issued, "issued"),
        (CUR.validFrom, "valid_from"),
        (CUR.validUntil, "valid_until"),
    ):
        _add(graph, subject, predicate, _date(row[column]))
    for specification in specifications:
        graph.add((subject, CUR.represents, names[specification]))


def _sources(graph: Graph, subject: Name, row: Row) -> None:
    """Where the document came from (plan M3a E13): its register entry's address, where it has one - an
    uploaded entry of none leaves its file's checksum to say it -; an import's MEM plan, as its source and
    origin, MEM's attribution, and the licence recorded for MEM's data at the plan, never the wordings'
    (plan M2 E14, as app/exports/mem_ttl.py states them)."""
    _add(graph, subject, DCTERMS.source, _address(row["source_url"]))
    if row["mem_iri"] is None:
        return
    plan = URIRef(row["mem_iri"])
    graph.add((subject, DCTERMS.source, plan))
    graph.add((subject, PROV.wasDerivedFrom, plan))
    _add(graph, subject, DCTERMS.bibliographicCitation, row["mem_attribution"])
    _add(graph, plan, DCTERMS.license, _address(row["mem_licence"]))


def _address(value: str | None) -> URIRef | Literal | None:
    """An address as an IRI, where one can hold it; else as written."""
    if not value:
        return None
    return URIRef(value) if storable_iri(value) else Literal(value)


def _work(graph: Graph, row: Row, names: Names, document: Name) -> None:
    subject = names[row["id"]]
    graph.add((subject, RDF.type, CUR.Work))
    graph.add((subject, DCTERMS.title, Literal(row["title"])))
    graph.add((document, CUR.versionOf, subject))


def _file(graph: Graph, row: Row, names: Names, document: Name) -> None:
    subject = names[row["id"]]
    graph.add((subject, RDF.type, CUR.SourceFile))
    graph.add((subject, CUR.checksum, Literal(row["sha256"])))
    graph.add((subject, CUR.containsDocument, document))


def _specification(graph: Graph, row: Row, names: Names) -> None:
    subject = names[row["id"]]
    graph.add((subject, RDF.type, _SPECIFICATION_CLASSES[row["spec_kind"]]))
    _add(graph, subject, DCTERMS.title, row["title"])
    _add(graph, subject, CUR.fieldText, row["field_text"])


def _variant(graph: Graph, row: Row, names: Names) -> None:
    subject = names[row["id"]]
    graph.add((subject, RDF.type, CUR.Variant))
    _add(graph, subject, SKOS.prefLabel, row["label"])
    _add(graph, subject, CUR.variantKind, URIRef(row["variant_kind_iri"]))
    graph.add((subject, CUR.variantOf, names[row["specification_id"]]))


def _parent(node: Row, names: Names, specifications: Sequence[UUID], document: Name) -> Name:
    """A node's parent node; a root's the one specification it applies to, else the document's one
    specification, else the document itself (cur:partOf takes all three)."""
    if node["parent_id"] is not None:
        return names[node["parent_id"]]
    named = [item for item in node["applies_to"] if item in specifications]
    if len(named) == 1:
        return names[named[0]]
    return names[specifications[0]] if len(specifications) == 1 else document


def _node(graph: Graph, row: Row, names: Names, parent: Name) -> None:
    subject = names[row["id"]]
    graph.add((subject, RDF.type, CUR.CurriculumNode))
    graph.add((subject, CUR.partOf, parent))
    for predicate, column in (
        (CUR.nodeFunction, "function_iri"), (CUR.nodeType, "node_type_iri"),
        (CUR.obligation, "obligation_iri"),
        (CUR.scopeShare, "scope_share_iri"), (CUR.extractionDepth, "extraction_depth_iri"),
        (CUR.origin, "origin_iri"), (CUR.reviewStatus, "review_status_iri"),
    ):  # fmt: skip
        _add(graph, subject, predicate, _iri(row[column]))
    _add(graph, subject, CUR.code, row["code"])
    _add(graph, subject, CUR.codeAssigned, row["code_assigned"])
    _add(graph, subject, CUR.originalTitle, row["original_title"], lang=row["title_language"])
    _add(graph, subject, CUR.position, row["position"])
    for applies in row["applies_to"]:
        graph.add((subject, CUR.appliesTo, names[applies]))
    for point in row["checked_absent"]:
        graph.add((subject, CUR.checkedAbsent, URIRef(point)))


def _statement(graph: Graph, row: Row, names: Names, at_place: Mapping[tuple[UUID, int], UUID]) -> None:
    subject = names[row["id"]]
    language = row["language"]
    graph.add((subject, RDF.type, CUR.Statement))
    graph.add((subject, CUR.partOf, names[row["node_id"]]))
    _add(graph, subject, CUR.verbatim, row["verbatim"], lang=language)
    _add(graph, subject, CUR.leadIn, row["lead_in"], lang=language)
    for predicate, column in (
        (CUR.statementKind, "statement_kind_iri"), (CUR.statementSubkind, "subkind_iri"),
        (CUR.obligation, "obligation_iri"), (CUR.origin, "origin_iri"),
        (CUR.reviewStatus, "review_status_iri"),
    ):  # fmt: skip
        _add(graph, subject, predicate, _iri(row[column]))
    for addressee in row["addressees"]:
        graph.add((subject, CUR.addressee, URIRef(addressee)))
    for marker in row["layout_markers"]:
        graph.add((subject, CUR.layoutMarker, URIRef(marker)))
    _add(graph, subject, CUR.textHash, row["text_hash"])
    details = row["details"]
    for name in _TEXTS:
        _add(graph, subject, CUR[name], details.get(name))
    _add(graph, subject, CUR.exampleText, details.get("exampleText"), lang=language)
    _add(graph, subject, CUR.purpose, details.get("purposeText"), lang=language)
    _add(graph, subject, CUR.code, details.get("codeText"))  # its number or mark as the document prints it
    for marker in details.get("crossCuttingMarkers", []):
        graph.add((subject, CUR.crossCuttingMarker, Literal(marker)))
    for position in details.get("targetsContent", []):
        if (target := at_place.get((row["node_id"], position))) is not None:
            graph.add((subject, CUR.targetsContent, names[target]))


def _anchor(graph: Graph, row: Row, names: Names, document: Name) -> None:
    subject = names[row["id"]]
    graph.add((names[row["statement_id"] or row["node_id"] or row["frame_part_id"]], CUR.anchor, subject))
    graph.add((subject, RDF.type, CUR.SourceAnchor))
    graph.add((subject, CUR.inDocument, document))
    for predicate, column in (
        (CUR.pageStart, "page_start"), (CUR.pageEnd, "page_end"), (CUR.printedPage, "printed_page"),
        (CUR.quote, "quote"), (CUR.charStart, "char_start"), (CUR.charEnd, "char_end"),
        (CUR.tableCell, "table_cell"), (CUR.sectionPath, "section_path"),
    ):  # fmt: skip
        _add(graph, subject, predicate, row[column])
    for block in row["blocks"]:
        graph.add((subject, CUR.blockId, Literal(block)))
    _add(graph, subject, CUR.matchKind, _iri(row["match_kind_iri"]))
    score: Decimal | None = row["match_score"]
    _add(graph, subject, CUR.matchScore, score)
