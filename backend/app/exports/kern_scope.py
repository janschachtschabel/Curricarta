"""A specification's applicability in the Kern graph (plan M3a H1; cur-kern.ttl, cur:ApplicabilityContext,
cur-shapes.ttl ApplicabilityContextShape): each context the editors set, at its specification
(cur:applicability), states its education sector, its formality, and the time spans and levels it holds
(cur:timeSpan, cur:levelAssignment, as app/exports/kern_values.py states a value). It is named as a value
is (app/exports/kern_naming.py): its urn:uuid in a draft, so X5 finds it at its row, a blank node once
frozen. The institution and the target group as written have no property of the core yet (cur:institutionType
and cur:targetGroup name concepts of a profile's): they stay in the store.

A specification without context rows states what X1 read of it (specification.applicability) as one
context: its sector and formality, its time and level as written (cur:timeText, cur:levelText) - a blank
node in either naming, as it is no row of its own; none where X1 read none of these. Once the editors set a
context, theirs stand alone - rejected all, none stands: X1's reading does not return in their place. An OR
of contexts (cur:alternativeContext) is not stated.
"""

from collections.abc import Mapping
from typing import Any

from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef

from app.domain.l2 import Context, Holder
from app.exports.kern_naming import Naming
from app.exports.kern_rows import KernRows
from app.exports.kern_values import level_value, named, time_span_value

CUR = Namespace("https://w3id.org/wlo/curriculum/core#")  # as app/exports/kern_rdf.py, which calls here
Name = URIRef | BNode
# what X1 read of a specification's applicability, by its key there: the property each is stated by
_READ_CONCEPTS = {"sector": CUR.educationSector, "formality": CUR.formality}
_READ_TEXTS = {"timeText": CUR.timeText, "levelText": CUR.levelText}


def add_scope(graph: Graph, rows: KernRows, naming: Naming) -> None:
    """The applicability of each of the rows' specifications, as the module says."""
    for specification in rows.specifications:
        subject = naming.of("specification", specification)
        held = rows.values.get(Holder("specification", specification["id"]))
        contexts = () if held is None else held.contexts
        for context in contexts:
            graph.add((subject, CUR.applicability, _context(graph, context, naming)))
        if contexts or specification["has_contexts"]:
            continue
        if (read := _read(graph, specification["applicability"])) is not None:
            graph.add((subject, CUR.applicability, read))


def _context(graph: Graph, context: Context, naming: Naming) -> Name:
    value = context.value
    subject = named(graph, "applicability_context", value.id, CUR.ApplicabilityContext, naming)
    for predicate, concept in ((CUR.educationSector, value.sector), (CUR.formality, value.formality)):
        if concept is not None:
            graph.add((subject, predicate, URIRef(concept)))
    for span in context.time_spans:
        graph.add((subject, CUR.timeSpan, time_span_value(graph, span, naming)))
    for level in context.levels:
        graph.add((subject, CUR.levelAssignment, level_value(graph, level, naming)))
    return subject


def _read(graph: Graph, applicability: Mapping[str, Any]) -> BNode | None:
    """What X1 read as a context of its own; none where it read nothing the graph states."""
    stated: list[tuple[URIRef, URIRef | Literal]] = [
        (predicate, URIRef(applicability[key])) for key, predicate in _READ_CONCEPTS.items()
        if applicability.get(key)
    ]  # fmt: skip
    stated += [(predicate, Literal(applicability[key])) for key, predicate in _READ_TEXTS.items()
               if applicability.get(key)]  # fmt: skip
    if not stated:
        return None
    subject = BNode()
    graph.add((subject, RDF.type, CUR.ApplicabilityContext))
    for predicate, value in stated:
        graph.add((subject, predicate, value))
    return subject
