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
concept's scheme, a relation's shortcut). The cases below hold what each rewritten constraint finds, at a
focus that breaks it and one that keeps it: the same before its rewrite and after."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef, Variable
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.term import Node

from app.pipeline.shacl_child import SHAPE_FILES, validate_graph

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
SH = Namespace("http://www.w3.org/ns/shacl#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
CV = Namespace("https://w3id.org/wlo/curriculum/vocab#")
LVL = Namespace("https://w3id.org/wlo/curriculum/level/")
HS = Namespace("https://w3id.org/wlo/curriculum/profile/higher-education#")
BERUF = Namespace("https://w3id.org/wlo/curriculum/profile/vocational#")
EX = Namespace("https://example.org/shape-queries/")
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


# what each rewritten constraint finds, at a focus that breaks it and one that keeps it


def found(data: Graph, message: str) -> set[str]:
    """The focus nodes of the results whose message starts so."""
    return {result.focus for result in validate_graph(ONTOLOGY, data) if result.message.startswith(message)}


def typed(graph: Graph, subject: Node, kind: URIRef, **values: Node) -> Node:
    graph.add((subject, RDF.type, kind))
    for name, value in values.items():
        graph.add((subject, CUR[name], value))
    return subject


def level_at(graph: Graph, holder: URIRef, kind: URIRef, origin: URIRef) -> BNode:
    level = BNode()
    typed(graph, holder, kind)
    graph.add((holder, CUR.levelAssignment, level))
    typed(graph, level, CUR.LevelAssignment, level=LVL["afb-II"], origin=origin)
    return level


def test_a_task_demand_level_at_a_statement_not_from_the_source_is_found_and_no_other() -> None:
    data = Graph()
    level_at(data, EX.said, CUR.Statement, CV.orig_human)
    level_at(data, EX.quoted, CUR.Statement, CV.orig_source)
    level_at(data, EX.node, CUR.CurriculumNode, CV.orig_human)

    assert found(data, "Anforderungsbereich an einer Aussage") == {str(EX.said)}


def test_a_statement_anchored_unsharply_is_found_and_one_anchored_exactly_is_not() -> None:
    data = Graph()
    for said, kind in ((EX.unsharp, CV.match_fuzzy), (EX.exact, CV.match_exact)):
        anchor = BNode()
        typed(data, said, CUR.Statement)
        data.add((said, CUR.anchor, anchor))
        typed(data, anchor, CUR.SourceAnchor, matchKind=kind)

    assert found(data, "Fundstelle unscharf") == {str(EX.unsharp)}


def test_an_assessment_whose_parts_weigh_over_a_hundred_is_found_and_no_other() -> None:
    data = Graph()
    for whole, weights in ((EX.over, (60, 50)), (EX.within, (40, 50))):
        typed(data, whole, CUR.Assessment)
        for at, weight in enumerate(weights):
            part = URIRef(f"{whole}-part-{at}")
            typed(data, part, CUR.Assessment, partOf=whole, weightPercent=Literal(weight))

    assert found(data, "Gewichte der direkten Teile") == {str(EX.over)}


def workload(graph: Graph, holder: Node, unit: URIRef, amount: int, kind: URIRef | None = None) -> None:
    value = BNode()
    graph.add((holder, CUR.workload, value))
    typed(graph, value, CUR.Workload, unit=unit, amount=Literal(amount))
    if kind is not None:
        graph.add((value, CUR.workloadKind, kind))


def test_a_module_whose_hours_per_credit_leave_twenty_five_to_thirty_is_found_and_no_other() -> None:
    data = Graph()
    for node, hours in ((EX.light, 100), (EX.fitting, 140)):
        typed(data, node, CUR.CurriculumNode, nodeType=HS.Modul)
        workload(data, node, CV.unit_hour, hours, CV.wl_totalWorkload)
        workload(data, node, CV.unit_ectsCredit, 5)

    assert found(data, "Arbeitsaufwand je Leistungspunkt") == {str(EX.light)}


def test_a_module_whose_contact_and_self_study_miss_its_total_is_found_and_no_other() -> None:
    data = Graph()
    for node, contact in ((EX.missing, 60), (EX.summing, 70)):
        typed(data, node, CUR.CurriculumNode, nodeType=HS.Modul)
        workload(data, node, CV.unit_hour, 150, CV.wl_totalWorkload)
        workload(data, node, CV.unit_hour, contact, CV.wl_contactTime)
        workload(data, node, CV.unit_hour, 80, CV.wl_selfStudy)

    assert found(data, "Kontaktzeit und Selbststudium") == {str(EX.missing)}


def test_a_semester_whose_binding_modules_carry_over_forty_credits_is_found_and_no_other() -> None:
    # credits at the placement or, where it has none, at the module placed
    data = Graph()
    for curriculum, credits in ((EX.heavy, (25, 20)), (EX.light_curriculum, (15, 20))):
        typed(data, curriculum, CUR.Curriculum)
        for at, amount in enumerate(credits):
            placement, module, semester = (
                URIRef(f"{curriculum}-p{at}"),
                URIRef(f"{curriculum}-m{at}"),
                BNode(),
            )
            typed(data, module, CUR.CurriculumNode)
            typed(data, placement, CUR.Placement, inSpecification=curriculum, obligation=CV.obl_binding,
                  placedUnit=module, timeSpan=semester)  # fmt: skip
            typed(data, semester, CUR.TimeSpan, timeKind=CV.time_semester, **{"from": Literal(1)})
            workload(data, placement if at == 0 else module, CV.unit_ectsCredit, amount)

    assert found(data, "Pflichtmodule eines Fachsemesters") == {str(EX.heavy)}


def test_a_decomposition_of_a_statement_of_another_kind_is_found_and_no_other() -> None:
    data = Graph()
    for decomposition, kind in ((EX.of_content, CV.kind_content), (EX.of_outcome, CV.kind_learningOutcome)):
        said = URIRef(f"{decomposition}-statement")
        typed(data, said, CUR.Statement, statementKind=kind)
        typed(data, decomposition, CUR.Decomposition, decomposes=said)

    assert found(data, "Zerlegt wird nur") == {str(EX.of_content)}


def test_a_module_without_credits_at_itself_or_a_placement_is_found_and_no_other() -> None:
    data = Graph()
    for node in (EX.without, EX.with_own, EX.placed):
        typed(data, node, CUR.CurriculumNode, nodeType=HS.Modul)
    workload(data, EX.with_own, CV.unit_ectsCredit, 5)
    workload(data, EX.without, CV.unit_hour, 150)
    typed(data, EX.placement, CUR.Placement, placedUnit=EX.placed)
    workload(data, EX.placement, CV.unit_ectsCredit, 5)

    assert found(data, "Modul ohne Leistungspunkte") == {str(EX.without)}


def test_a_module_without_learning_outcomes_is_found_and_no_other() -> None:
    data = Graph()
    for node, kind in ((EX.no_outcome, CV.kind_content), (EX.outcome, CV.kind_learningOutcome)):
        typed(data, node, CUR.CurriculumNode, nodeType=HS.Modul)
        typed(data, URIRef(f"{node}-statement"), CUR.Statement, partOf=node, statementKind=kind)

    assert found(data, "MRVO: Modul ohne Lernergebnisse") == {str(EX.no_outcome)}


def test_a_shortcut_without_a_confirmed_or_official_alignment_is_found_and_no_other() -> None:
    data = Graph()
    for said, status in ((EX.unbacked, CV.rev_proposed), (EX.backed, CV.rev_confirmed)):
        typed(data, said, CUR.Statement)
        data.add((said, CUR.majorOverlap, EX.other))
        alignment = URIRef(f"{said}-alignment")
        typed(data, alignment, CUR.Alignment, source=said, target=EX.other, relation=CV.rel_majorOverlap,
              reviewStatus=status)  # fmt: skip

    assert found(data, "Kurzform-Kante ohne") == {str(EX.unbacked)}


def test_a_learning_field_without_a_training_year_is_found_and_no_other() -> None:
    data = Graph()
    for node, kind in ((EX.no_year, CV.time_gradeLevel), (EX.year, CV.time_trainingYear)):
        span = BNode()
        typed(data, node, CUR.CurriculumNode, nodeType=BERUF.Lernfeld, timeSpan=span)
        typed(data, span, CUR.TimeSpan, timeKind=kind)

    assert found(data, "Lernfeld ohne Ausbildungsjahr") == {str(EX.no_year)}


def test_a_learning_field_whose_lessons_are_not_a_multiple_of_twenty_is_found_and_no_other() -> None:
    data = Graph()
    for node, lessons in ((EX.odd, 70), (EX.even, 80)):
        typed(data, node, CUR.CurriculumNode, nodeType=BERUF.Lernfeld)
        workload(data, node, CV.unit_lesson, lessons)

    assert found(data, "Zeitrichtwert eines Lernfelds") == {str(EX.odd)}
