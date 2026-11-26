"""How rdflib runs the SPARQL constraints of X5's shapes (cur-shapes.ttl, profil-shapes.ttl): pyshacl asks
each query once per focus node with ``$this`` bound, but rdflib orders a group's triples before it knows
that - fewest variables first, ``$this`` counted as one. A triple such as ``?holder rdf:type/rdfs:subClassOf*
cur:Statement`` then runs first, unbound, and reads every statement of the document for every focus: X5's
time grows with focus nodes times rows (measured: a level assignment 11 ms at 1,000 statements, 54 ms at
5,000). The constraints open with the triples ``$this`` binds in a group of their own, which rdflib joins
before the rest, bound; a check that binds nothing (a type, a unit, a kind) follows them or stands in an
EXISTS, evaluated per row.

The guard here walks each query as rdflib translated it - its groups in their order, a join's right side
bound by its left where rdflib joins them so ("lazy"; a join of a join it is not), an EXISTS by the row it
filters - and finds a triple whose subject nothing has bound yet, unless it reads the model alone (a
concept's scheme, a relation's shortcut). Its limits: it does not see a product of rows that are all bound
from ``$this`` (a node's workloads joined with each other before their kinds are checked: cheap per row,
but the cube of a node's workloads), and it walks the node kinds the shapes use - a ``MINUS`` or another
kind it does not know it leaves unread, which misses a scan there rather than turning red. What each
rewritten constraint finds, the same before its rewrite and after: test_shape_query_cases.py."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rdflib import BNode, Graph, Namespace, Variable
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.term import Node

from app.pipeline.shacl_child import SHAPE_FILES

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
SH = Namespace("http://www.w3.org/ns/shacl#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
# triples that read the model alone, whatever the document: a concept's scheme, a relation's shortcut
MODEL_ONLY = {SKOS.inScheme, CUR.shortcut}
THIS = Variable("this")


def shapes() -> Graph:
    graph = Graph()
    for name in SHAPE_FILES:
        graph.parse(ONTOLOGY / name, format="turtle")
    return graph


def constraints() -> Iterator[tuple[str, str]]:
    """Each SPARQL constraint's shape and query, the shapes' prefixes declared."""
    graph = shapes()
    prefixes = "".join(f"PREFIX {prefix}: <{namespace}>\n" for prefix, namespace in graph.namespaces())
    for shape, constraint in graph.subject_objects(SH.sparql):
        for query in graph.objects(constraint, SH.select):
            yield str(shape).rsplit("#", 1)[-1], prefixes + str(query)


def unbound_scans(query: str) -> list[str]:
    """The triples of the translated query that run with an unbound subject (and no bound object)."""
    found: list[str] = []

    def walk(node: Any, bound: frozenset[Node]) -> frozenset[Node]:
        if not isinstance(node, CompValue):
            return bound
        if node.name == "BGP":
            for subject, predicate, value in node.triples:
                anchored = not isinstance(subject, Variable | BNode) or subject in bound or value in bound
                if not anchored and predicate not in MODEL_ONLY:
                    found.append(f"{subject.n3()} {predicate.n3()} {value.n3()}")
                bound |= {term for term in (subject, value) if isinstance(term, Variable | BNode)}
            return bound
        if node.name == "Join":  # a lazy join runs its right side once per row of its left
            left = walk(node.p1, bound)
            right = walk(node.p2, left if node.lazy else bound)
            return left | right
        if node.name == "LeftJoin":
            left = walk(node.p1, bound)
            walk(node.p2, left)
            expressions(node.get("expr"), left)
            return left
        if node.name == "Union":
            return bound | (walk(node.p1, bound) & walk(node.p2, bound))
        if node.name == "Filter":
            inner = walk(node.p, bound)
            expressions(node.expr, inner)
            return inner
        if node.name == "Extend":
            return walk(node.p, bound) | {node.var}
        return walk(node.get("p"), bound) if "p" in node else bound

    def expressions(expression: Any, bound: frozenset[Node]) -> None:
        if isinstance(expression, CompValue):
            if expression.name in ("Builtin_EXISTS", "Builtin_NOTEXISTS"):
                walk(expression.graph, bound)
            for value in expression.values():
                expressions(value, bound)
        elif isinstance(expression, list | tuple):
            for value in expression:
                expressions(value, bound)

    walk(translateQuery(parseQuery(query)).algebra, frozenset({THIS}))
    return found


def test_no_constraint_reads_the_document_s_rows_before_this_binds_its_start() -> None:
    scans = {shape: scan for shape, query in constraints() if (scan := unbound_scans(query))}

    assert scans == {}


def test_the_guard_finds_a_type_test_that_runs_before_this() -> None:
    # the task-demand constraint as it stood: its type path ran first, unbound
    query = (
        "PREFIX cur: <https://w3id.org/wlo/curriculum/core#>\n"
        "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "SELECT $this WHERE { ?holder cur:levelAssignment $this . "
        "?holder rdf:type/rdfs:subClassOf* cur:Statement }"
    )

    assert len(unbound_scans(query)) == 1
