"""A document's placements in the Kern graph (plan M3a K; cur-kern.ttl, cur:Placement, cur-shapes.ttl
PlacementShape): each a cur:Placement of the node it places (cur:placedUnit) in its specification
(cur:inSpecification) or variant (cur:forVariant), at the node it names (cur:inNode), with its obligation
(cur:obligation), its weight in the grade (cur:gradeWeight, xsd:decimal), where it came from and how far it is
reviewed, and its time spans and workloads in that place (cur:timeSpan, cur:workload - cur:totalWorkload for
its whole -, as app/exports/kern_values.py states a holder's). A rejected one is left out, as a rejected value
is. Named as the naming names a placement (app/exports/kern_naming.py): its urn:uuid in a draft, so X5 finds
it at its row, its stored IRI once frozen. The placements are those app/exports/kern_rows.py reads, by node
and in each node's order. A node's cur:appliesTo stays beside them: a placement says more, but stands not for
it."""

from rdflib import RDF, XSD, Graph, Literal, Namespace, URIRef

from app.domain.l2 import Holder
from app.domain.placements import PlacementRow
from app.exports.kern_naming import Naming
from app.exports.kern_rows import KernRows, Row
from app.exports.kern_values import time_span_value, workload_value

CUR = Namespace("https://w3id.org/wlo/curriculum/core#")  # as app/exports/kern_rdf.py, which calls here
_REJECTED = "https://w3id.org/wlo/curriculum/vocab#rev_rejected"


def add_placements(graph: Graph, rows: KernRows, naming: Naming) -> None:
    """The rows' placements, each with its values, as the module says."""
    nodes: dict[object, Row] = {row["id"]: row for row in rows.nodes}
    specifications: dict[object, Row] = {row["id"]: row for row in rows.specifications}
    variants: dict[object, Row] = {row["id"]: row for row in rows.variants}
    for placement in rows.placements:
        if placement.stated.review_status == _REJECTED:
            continue
        subject = naming.of("placement", _row(placement))
        graph.add((subject, RDF.type, CUR.Placement))
        graph.add((subject, CUR.placedUnit, naming.of("node", nodes[placement.node_id])))
        if placement.specification_id is not None:
            specification = specifications[placement.specification_id]
            graph.add((subject, CUR.inSpecification, naming.of("specification", specification)))
        if placement.variant_id is not None:
            graph.add((subject, CUR.forVariant, naming.of("variant", variants[placement.variant_id])))
        if placement.in_node_id is not None:
            graph.add((subject, CUR.inNode, naming.of("node", nodes[placement.in_node_id])))
        graph.add((subject, CUR.obligation, URIRef(placement.obligation)))
        if placement.grade_weight is not None:
            graph.add((subject, CUR.gradeWeight, Literal(placement.grade_weight, datatype=XSD.decimal)))
        graph.add((subject, CUR.origin, URIRef(placement.stated.origin)))
        graph.add((subject, CUR.reviewStatus, URIRef(placement.stated.review_status)))
        held = rows.values.get(Holder("placement", placement.id))
        if held is None:
            continue
        for span in held.time_spans:
            graph.add((subject, CUR.timeSpan, time_span_value(graph, span, naming)))
        for workload in held.workloads:
            predicate = CUR.totalWorkload if workload.value.total else CUR.workload
            graph.add((subject, predicate, workload_value(graph, workload, naming)))


def _row(placement: PlacementRow) -> Row:
    """The placement as the naming reads a row: its id and the IRI it is named by once frozen."""
    return {"id": placement.id, "iri": placement.iri}
