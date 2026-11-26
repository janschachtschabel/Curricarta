"""The second layer's values in the Kern graph (plan M3a F1; cur-kern.ttl, cur:Workload, cur:TimeSpan,
cur:LevelAssignment): each holder the graph states - a specification, a node, a statement - names its
workloads (cur:totalWorkload for its whole, else cur:workload), its time spans and its level assignments,
each value typed and with what its row holds - numbers as xsd:decimal, where it came from at a level
(cur:origin, which a level's shapes read) -, a workload's periods under it (cur:inPeriod). The values are
those app/exports/kern_rows.py reads, rejected ones left out; a level at a rule's frame part is the rules'
(plan M3a I). A value is named as the naming names its kind (app/exports/kern_naming.py): a draft's by its
urn:uuid, so X5 finds it at its row, a frozen one's by a blank node. Holders and values are visited in the
order the rows are read, so a frozen naming labels the blank nodes alike in every build.
"""

from decimal import Decimal
from uuid import UUID

from rdflib import RDF, XSD, BNode, Graph, Literal, Namespace, URIRef

from app.domain.l2 import Holder, HolderKind, Level, TimeSpan, Workload
from app.exports.kern_naming import Naming, RowKind
from app.exports.kern_rows import KernRows, Row

CUR = Namespace("https://w3id.org/wlo/curriculum/core#")  # as app/exports/kern_rdf.py, which calls here
Name = URIRef | BNode


def add_values(graph: Graph, rows: KernRows, naming: Naming) -> None:
    """The values of the rows' holders, each at its holder, as the module says."""
    holders: tuple[tuple[HolderKind, list[Row]], ...] = (
        ("specification", rows.specifications), ("node", rows.nodes), ("statement", rows.statements),
    )  # fmt: skip
    for kind, items in holders:
        for row in items:
            held = rows.values.get(Holder(kind, row["id"]))
            if held is None:
                continue
            subject = naming.of(kind, row)
            for level in held.levels:
                graph.add((subject, CUR.levelAssignment, level_value(graph, level, naming)))
            for span in held.time_spans:
                graph.add((subject, CUR.timeSpan, time_span_value(graph, span, naming)))
            for workload in held.workloads:
                predicate = CUR.totalWorkload if workload.value.total else CUR.workload
                graph.add((subject, predicate, workload_value(graph, workload, naming)))


def named(graph: Graph, kind: RowKind, value_id: UUID | None, type_: URIRef, naming: Naming) -> Name:
    """The value's name under the naming, typed ``type_``."""
    subject = naming.of(kind, {"id": value_id})
    graph.add((subject, RDF.type, type_))
    return subject


def _add(graph: Graph, subject: Name, predicate: URIRef, value: str | Decimal | int | None) -> None:
    """``subject predicate value`` where there is a value: a concept's IRI, a number as its datatype."""
    if value is None:
        return
    if isinstance(value, str):
        graph.add((subject, predicate, URIRef(value)))
    elif isinstance(value, Decimal):
        graph.add((subject, predicate, Literal(value, datatype=XSD.decimal)))
    else:
        graph.add((subject, predicate, Literal(value)))


def level_value(graph: Graph, level: Level, naming: Naming) -> Name:
    """The level assignment, named and typed, with what its row holds; its name."""
    value = level.value
    subject = named(graph, "level_assignment", value.id, CUR.LevelAssignment, naming)
    _add(graph, subject, CUR.level, value.level)
    _add(graph, subject, CUR.levelTo, value.level_to)
    _add(graph, subject, CUR.levelRelation, value.relation)
    _add(graph, subject, CUR.levelDimension, value.dimension)
    _add(graph, subject, CUR.competenceDimension, value.competence_dimension)
    _add(graph, subject, CUR.origin, level.stated.origin)
    return subject


def time_span_value(graph: Graph, span: TimeSpan, naming: Naming) -> Name:
    """The time span, named and typed, with what its row holds; its name."""
    value = span.value
    subject = named(graph, "time_span", value.id, CUR.TimeSpan, naming)
    _add(graph, subject, CUR.timeKind, value.time_kind)
    _add(graph, subject, CUR["from"], value.span_from)
    _add(graph, subject, CUR.to, value.span_to)
    _add(graph, subject, CUR.timeRelation, value.time_relation)
    return subject


def workload_value(graph: Graph, workload: Workload, naming: Naming) -> Name:
    """The workload, named and typed, with what its row holds and its periods; its name."""
    value = workload.value
    subject = named(graph, "workload", value.id, CUR.Workload, naming)
    _add(graph, subject, CUR.amount, value.amount)
    _add(graph, subject, CUR.amountTo, value.amount_to)
    _add(graph, subject, CUR.unit, value.unit)
    _add(graph, subject, CUR.workloadKind, value.workload_kind)
    graph.add((subject, CUR.isRecommendation, Literal(value.is_recommendation)))
    _add(graph, subject, CUR.minutesPerUnit, value.minutes_per_unit)
    for period in workload.periods:
        graph.add((subject, CUR.inPeriod, time_span_value(graph, period, naming)))
    return subject
