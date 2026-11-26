"""A document's assessments in the Kern graph (plan M3a J; cur-kern.ttl, cur:Assessment, cur-shapes.ttl
AssessmentShape): each a cur:Assessment of its kind (cur:assessmentKind), a part (cur:partOf) of the
assessment, specification or node it stands under, with its name (skos:prefLabel), its duration in minutes
(cur:durationMinutes, xsd:integer), its weight in percent (cur:weightPercent, xsd:decimal), whether it is
graded (cur:graded), where it came from and how far it is reviewed, what it assesses (cur:assesses) - the
nodes and statements the graph states: a rejected statement is none of them - and the levels at it
(cur:levelAssignment, as app/exports/kern_values.py states a value). A rejected one is left out with its
parts and their levels, as a rejected value is (plan M3a L): a part of it would be a part of nothing stated.
Named as the naming names an assessment (app/exports/kern_naming.py): its urn:uuid in a draft, so X5 finds it
at its row, its stored IRI once frozen.
Its anchors are not stated, as a specification's are not (app/exports/kern_rdf.py). The assessments are those
app/exports/kern_rows.py reads, each part after its parent.
"""

from rdflib import RDF, SKOS, XSD, Graph, Literal, Namespace, URIRef

from app.domain.assessments import AssessmentRow
from app.domain.l2 import Holder
from app.exports.kern_naming import Naming, RowKind
from app.exports.kern_rows import KernRows, Row
from app.exports.kern_values import level_value

CUR = Namespace("https://w3id.org/wlo/curriculum/core#")  # as app/exports/kern_rdf.py, which calls here
_REJECTED = "https://w3id.org/wlo/curriculum/vocab#rev_rejected"


def add_assessments(graph: Graph, rows: KernRows, naming: Naming) -> None:
    """The rows' assessments, each at its parent, as the module says."""
    held: dict[str, dict[object, Row]] = {
        "specification": {row["id"]: row for row in rows.specifications},
        "node": {row["id"]: row for row in rows.nodes},
        "statement": {row["id"]: row for row in rows.statements},
        "assessment": {row.id: _row(row) for row in rows.assessments},
    }
    left_out: set[object] = set()
    for assessment in rows.assessments:  # each part after its parent: a rejected one's parts follow it
        if assessment.stated.review_status == _REJECTED or assessment.parent_id in left_out:
            left_out.add(assessment.id)
            continue
        subject = naming.of("assessment", held["assessment"][assessment.id])
        graph.add((subject, RDF.type, CUR.Assessment))
        graph.add((subject, CUR.assessmentKind, URIRef(assessment.assessment_kind)))
        parent: RowKind = assessment.parent_kind
        graph.add((subject, CUR.partOf, naming.of(parent, held[parent][assessment.parent_id])))
        if assessment.label is not None:
            graph.add((subject, SKOS.prefLabel, Literal(assessment.label)))
        if assessment.duration_minutes is not None:
            graph.add(
                (subject, CUR.durationMinutes, Literal(assessment.duration_minutes, datatype=XSD.integer))
            )
        if assessment.weight_percent is not None:
            graph.add((subject, CUR.weightPercent, Literal(assessment.weight_percent, datatype=XSD.decimal)))
        if assessment.graded is not None:
            graph.add((subject, CUR.graded, Literal(assessment.graded)))
        graph.add((subject, CUR.origin, URIRef(assessment.stated.origin)))
        graph.add((subject, CUR.reviewStatus, URIRef(assessment.stated.review_status)))
        for target in assessment.targets:
            if (row := held[target.kind].get(target.id)) is not None:
                graph.add((subject, CUR.assesses, naming.of(target.kind, row)))
        values = rows.values.get(Holder("assessment", assessment.id))
        for level in () if values is None else values.levels:
            graph.add((subject, CUR.levelAssignment, level_value(graph, level, naming)))


def _row(assessment: AssessmentRow) -> Row:
    """The assessment as the naming reads a row: its id and the IRI it is named by once frozen."""
    return {"id": assessment.id, "iri": assessment.iri}
