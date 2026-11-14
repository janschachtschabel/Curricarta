"""The queries of one MEM plan (plan M2, E8/E11), after the old app's tree.py, which they proved on the
endpoint: the parts of a plan collected along has-part (``BFO_0000051+``) - Bavaria states the closure,
Saxony only the direct parts, one path reads both - and everything the import reads about a part beside
them; and the references a part holds, which are no parts.

Each reads a Land's or the standards' graph with the shared ones (``MemSparql.from_clauses``), names the
plan only through ``mem_iri``, and is read in pages: the parts or references in a subquery ordered by IRI,
cut by LIMIT and OFFSET, the rest of the query joined to them - the store walks the path once a page, and
a page's rows are the next ones. A count of each tells the client when it has all (MemSparql.select_pages).
"""

from app.sources.mem.sparql import MemSparql, mem_iri

PREFIXES = (
    "PREFIX lp: <https://w3id.org/lehrplan/ontology/>\n"
    "PREFIX obo: <http://purl.obolibrary.org/obo/>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX dcterms: <http://purl.org/dc/terms/>\n"
    "PREFIX dc: <http://purl.org/dc/elements/1.1/>\n"
    "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
)
LP = "https://w3id.org/lehrplan/ontology/"
SEPARATOR = "|"
# Saxony tags its labels @de, Bavaria leaves them untagged, the ontology adds English ones: a German
# label before an untagged one, the least of several, so that two imports agree
GERMAN = 'lang({var}) = "de" || lang({var}) = ""'
LABELS = (
    '  OPTIONAL {{ {node} rdfs:label ?de . FILTER(lang(?de) = "de") }}\n'
    '  OPTIONAL {{ {node} rdfs:label ?plain . FILTER(lang(?plain) = "") }}\n'
)


def _label_read(node: str) -> str:
    """The label the import reads of ``node``, bound as ?l: German, else untagged, else the preferred label
    in either (Berlin names its parts with skos:prefLabel alone); unbound where it has none of these."""
    return (
        f"{LABELS.format(node=node)}"
        f"  OPTIONAL {{ {node} skos:prefLabel ?pl . FILTER({GERMAN.format(var='?pl')}) }}\n"
        "  BIND(COALESCE(?de, ?plain, ?pl) AS ?l)\n"
    )


def plan_count(sparql: MemSparql, graph: str, plan: str) -> str:
    """The number of the plan's types among a Land's Lehrplan and the KMK's Bildungsstandard - 0 once the
    graph holds the plan no more: the import asks before it reads a plan the catalogue named, which may
    have gone since (plan M2, E11)."""
    return (
        f"{PREFIXES}SELECT (COUNT(*) AS ?count)\n{sparql.from_clauses(graph)}\n"
        f"WHERE {{ VALUES ?base {{ lp:LP_0000438 lp:LP_0000571 }} {mem_iri(plan)} a ?base . }}"
    )


def closure_count(sparql: MemSparql, graph: str, plan: str) -> str:
    """The number of the plan's parts."""
    return (
        f"{PREFIXES}SELECT (COUNT(DISTINCT ?n) AS ?count)\n{sparql.from_clauses(graph)}\n"
        f"WHERE {{ {mem_iri(plan)} obo:BFO_0000051+ ?n . }}"
    )


def closure_page(sparql: MemSparql, graph: str, plan: str, limit: int, offset: int) -> str:
    """One page of the plan's parts, a row each: label (German, else untagged, else the preferred label),
    classes, description, grades, number, position, hours, the Land's page, and its ancestors among
    has-part's subjects."""
    return (
        f"{PREFIXES}"
        "SELECT ?n (MIN(?l) AS ?label)\n"
        f'       (GROUP_CONCAT(DISTINCT ?t; separator="{SEPARATOR}") AS ?types)\n'
        "       (SAMPLE(?d) AS ?description)\n"
        f'       (GROUP_CONCAT(DISTINCT ?g; separator="{SEPARATOR}") AS ?grades)\n'
        "       (SAMPLE(?nr) AS ?number) (SAMPLE(?pos) AS ?position)\n"
        "       (SAMPLE(?h) AS ?hours) (SAMPLE(?u) AS ?page)\n"
        f'       (GROUP_CONCAT(DISTINCT ?a; separator="{SEPARATOR}") AS ?ancestors)\n'
        f"{sparql.from_clauses(graph)}\n"
        "WHERE {\n"
        f"  {{ SELECT DISTINCT ?n WHERE {{ {mem_iri(plan)} obo:BFO_0000051+ ?n . }}"
        f" ORDER BY ?n LIMIT {int(limit)} OFFSET {int(offset)} }}\n"
        f"{_label_read('?n')}"
        f'  OPTIONAL {{ ?n rdf:type ?t . FILTER(STRSTARTS(STR(?t), "{LP}")) }}\n'
        # the full text before a label: where a description has both, its label is a short preview
        "  OPTIONAL { ?n lp:LP_0030051 ?b .\n"
        "             OPTIONAL { ?b dcterms:description|dc:description ?full . }\n"
        "             OPTIONAL { ?b rdfs:label ?short . }\n"
        "             BIND(COALESCE(?full, ?short) AS ?d) }\n"
        "  OPTIONAL { ?n lp:LP_0000026 ?g . }\n"
        "  OPTIONAL { ?n lp:LP_0030057 ?nr . }\n"
        "  OPTIONAL { ?n lp:LP_0000460 ?pos . }\n"
        # the hours are a Zeitspezifikation's value: Berlin's other specifications came as hours otherwise
        "  OPTIONAL { ?n lp:LP_0000024 ?zs . ?zs a lp:LP_0000508 ; lp:LP_0000344 ?h . }\n"
        "  OPTIONAL { ?n lp:LP_0000463 ?u . }\n"
        "  OPTIONAL { ?a obo:BFO_0000051 ?n . }\n"
        "}\n"
        "GROUP BY ?n"
    )


_TYPED = (
    '  FILTER(isLiteral(?v) && lang(?v) = "" && datatype(?v) != <http://www.w3.org/2001/XMLSchema#string>)\n'
)
# One branch a measure: the parts it holds for, bound as ?x
_PLAN = "{plan}"  # where a branch names the plan
LABEL_SHAPES = {
    "label_de": '?n rdfs:label ?l . FILTER(lang(?l) = "de")',
    "label_untagged": '?n rdfs:label ?l . FILTER(isLiteral(?l) && lang(?l) = "")',
    "label_other_language": '?n rdfs:label ?l . FILTER(lang(?l) != "" && lang(?l) != "de")',
    "pref_label_only": "?n skos:prefLabel ?l . FILTER NOT EXISTS { ?n rdfs:label ?any }",
    "typed_number": f"?n lp:LP_0030057 ?v .\n{_TYPED}",
    "typed_hours": f"?n lp:LP_0000024 ?zs . ?zs a lp:LP_0000508 ; lp:LP_0000344 ?v .\n{_TYPED}",
    "typed_grade": f"?n lp:LP_0000026 ?v .\n{_TYPED}",
    # exclusive: no label the closure's query reads (closure_page), so the part is titled by its IRI's tail;
    # its own walk binds ?n, which a branch of OPTIONALs alone would leave unbound
    "no_label": f"{_PLAN} obo:BFO_0000051+ ?n .\n{_label_read('?n')}  FILTER(!BOUND(?l))",
}


def label_shape_count(sparql: MemSparql, graph: str, plan: str) -> str:
    """How many of the plan's parts carry each shape of label the closure's query reads (plan H-3, A10):
    an ``rdfs:label`` tagged ``@de``, one untagged, one in another language, a ``skos:prefLabel`` and no
    ``rdfs:label``; and how many state their number, hours or grades as a literal of a datatype - a row a
    measure, a measure no part holds for absent. The label shapes overlap and do not add up: a part with a
    German and an English label counts under both, ``pref_label_only`` takes a preferred label in any
    language. ``no_label`` alone is exclusive: the parts the closure's query reads no label of
    (``closure_page``, by the same patterns), which the import titles by their IRI's tail. Asked only on the
    operator's word, never by an import."""
    branches = "\n  UNION\n".join(
        f'  {{ {pattern.replace(_PLAN, mem_iri(plan))}\n    BIND("{measure}" AS ?measure) BIND(?n AS ?x) }}'
        for measure, pattern in LABEL_SHAPES.items()
    )
    return (
        f"{PREFIXES}SELECT ?measure (COUNT(DISTINCT ?x) AS ?count)\n{sparql.from_clauses(graph)}\n"
        "WHERE {\n"
        f"  {{ SELECT DISTINCT ?n WHERE {{ {mem_iri(plan)} obo:BFO_0000051+ ?n . }} }}\n"
        f"{branches}\n"
        "}\n"
        "GROUP BY ?measure"
    )


def reference_count(sparql: MemSparql, graph: str, plan: str) -> str:
    """The number of (holder, reference) pairs among the plan's parts."""
    return (
        f"{PREFIXES}SELECT (COUNT(*) AS ?count)\n{sparql.from_clauses(graph)}\n"
        "WHERE { SELECT DISTINCT ?x ?v WHERE {\n"
        f"  {{ SELECT DISTINCT ?x WHERE {{ {mem_iri(plan)} obo:BFO_0000051+ ?x . }} }}\n"
        "  ?x lp:LP_0030071 ?v . } }"
    )


def reference_page(sparql: MemSparql, graph: str, plan: str, limit: int, offset: int) -> str:
    """One page of the references the plan's parts hold (``hat Verweis``): the holder, the reference,
    its label (as a part's), its classes, and everything it points at (``verweist auf``), joined as
    ``target``."""
    return (
        f"{PREFIXES}"
        "SELECT ?x ?v (MIN(?l) AS ?label)\n"
        f'       (GROUP_CONCAT(DISTINCT ?t; separator="{SEPARATOR}") AS ?types)\n'
        f'       (GROUP_CONCAT(DISTINCT ?to; separator="{SEPARATOR}") AS ?target)\n'
        f"{sparql.from_clauses(graph)}\n"
        "WHERE {\n"
        "  { SELECT DISTINCT ?x ?v WHERE {\n"
        f"      {{ SELECT DISTINCT ?x WHERE {{ {mem_iri(plan)} obo:BFO_0000051+ ?x . }} }}\n"
        f"      ?x lp:LP_0030071 ?v . }} ORDER BY ?x ?v LIMIT {int(limit)} OFFSET {int(offset)} }}\n"
        f"{_label_read('?v')}"
        f'  OPTIONAL {{ ?v rdf:type ?t . FILTER(STRSTARTS(STR(?t), "{LP}")) }}\n'
        "  OPTIONAL { ?v lp:LP_0030072 ?to . }\n"
        "}\n"
        "GROUP BY ?x ?v"
    )
