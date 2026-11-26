"""What each SPARQL constraint X5's shapes rewrote to bind ``$this`` first finds (test_shape_queries.py): at a
focus that breaks it and one that keeps it, and at the foci the rewritten parts decide - a check that moved
into an EXISTS or an OPTIONAL, a sum over several rows. Each case gives the same result on the shapes as
they stood before the rewrite and as they stand, and fails on a copy of the new text without the part it
pins (measured by mutants when the rewrite was made; the old text is in the repository's history)."""

from pathlib import Path

from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef
from rdflib.term import Node

from app.pipeline.shacl_child import validate_graph

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
CV = Namespace("https://w3id.org/wlo/curriculum/vocab#")
LVL = Namespace("https://w3id.org/wlo/curriculum/level/")
HS = Namespace("https://w3id.org/wlo/curriculum/profile/higher-education#")
BERUF = Namespace("https://w3id.org/wlo/curriculum/profile/vocational#")
EX = Namespace("https://example.org/shape-queries/")


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
    # a part not typed an assessment does not count: its weight would push the third one over
    data = Graph()
    for whole, weights in ((EX.over, (60, 50)), (EX.within, (40, 50)), (EX.untyped_part, (60, 50))):
        typed(data, whole, CUR.Assessment)
        for at, weight in enumerate(weights):
            part = URIRef(f"{whole}-part-{at}")
            data.add((part, CUR.partOf, whole))
            data.add((part, CUR.weightPercent, Literal(weight)))
            if not (whole == EX.untyped_part and at == 1):
                data.add((part, RDF.type, CUR.Assessment))

    assert found(data, "Gewichte der direkten Teile") == {str(EX.over)}


def workload(graph: Graph, holder: Node, unit: URIRef, amount: int, kind: URIRef | None = None) -> None:
    value = BNode()
    graph.add((holder, CUR.workload, value))
    typed(graph, value, CUR.Workload, unit=unit, amount=Literal(amount))
    if kind is not None:
        graph.add((value, CUR.workloadKind, kind))


def test_a_module_whose_hours_per_credit_leave_twenty_five_to_thirty_is_found_and_no_other() -> None:
    data = Graph()
    for node, hours in ((EX.light, 100), (EX.fitting, 140), (EX.uncredited, 100)):
        typed(data, node, CUR.CurriculumNode, nodeType=HS.Modul)
        workload(data, node, CV.unit_hour, hours, CV.wl_totalWorkload)
        if node != EX.uncredited:  # hours alone: no ratio
            workload(data, node, CV.unit_ectsCredit, 5)

    assert found(data, "Arbeitsaufwand je Leistungspunkt") == {str(EX.light)}


def test_a_module_whose_contact_and_self_study_miss_its_total_is_found_and_no_other() -> None:
    data = Graph()
    for node, contact in ((EX.missing, 60), (EX.summing, 70), (EX.unstudied, 60)):
        typed(data, node, CUR.CurriculumNode, nodeType=HS.Modul)
        workload(data, node, CV.unit_hour, 150, CV.wl_totalWorkload)
        workload(data, node, CV.unit_hour, contact, CV.wl_contactTime)
        if node != EX.unstudied:  # no self-study: nothing to add up
            workload(data, node, CV.unit_hour, 80, CV.wl_selfStudy)

    assert found(data, "Kontaktzeit und Selbststudium") == {str(EX.missing)}


# each a placement in semester 1 of its curriculum: obligation, kind of its span, credits at it (or, where
# it has none, the module's)
BOUND, SEMESTER = CV.obl_binding, CV.time_semester
Placed = tuple[URIRef, URIRef, tuple[int, ...], tuple[int, ...]]
SEMESTERS: dict[URIRef, list[Placed]] = {
    EX.heavy: [(BOUND, SEMESTER, (25,), ()), (BOUND, SEMESTER, (), (20,))],
    EX.light_curriculum: [(BOUND, SEMESTER, (15,), ()), (BOUND, SEMESTER, (20,), ())],
    # an elective placement and one in a grade level do not count: they would push the semester over 40
    EX.with_elective: [
        (BOUND, SEMESTER, (15,), ()), (BOUND, SEMESTER, (20,), ()),
        (CV.obl_elective, SEMESTER, (10,), ()),
    ],
    EX.with_grade_level: [
        (BOUND, SEMESTER, (15,), ()), (BOUND, SEMESTER, (20,), ()),
        (BOUND, CV.time_gradeLevel, (10,), ()),
    ],
    # a placement's two credit workloads both count: the sum runs over their rows
    EX.twice_credited: [(BOUND, SEMESTER, (25, 25), ())],
}  # fmt: skip


def test_a_semester_whose_binding_modules_carry_over_forty_credits_is_found_and_no_other() -> None:
    data = Graph()
    for curriculum, placements in SEMESTERS.items():
        typed(data, curriculum, CUR.Curriculum)
        for at, (obligation, kind, at_placement, at_module) in enumerate(placements):
            placement, module, span = URIRef(f"{curriculum}-p{at}"), URIRef(f"{curriculum}-m{at}"), BNode()
            typed(data, module, CUR.CurriculumNode)
            typed(data, placement, CUR.Placement, inSpecification=curriculum, obligation=obligation,
                  placedUnit=module, timeSpan=span)  # fmt: skip
            typed(data, span, CUR.TimeSpan, timeKind=kind, **{"from": Literal(1)})
            for holder, amounts in ((placement, at_placement), (module, at_module)):
                for amount in amounts:
                    workload(data, holder, CV.unit_ectsCredit, amount)

    assert found(data, "Pflichtmodule eines Fachsemesters") == {str(EX.heavy), str(EX.twice_credited)}


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
    # backed by a confirmed or an official alignment; one not typed an alignment backs nothing
    data = Graph()
    for said, typed_as, status, origin in (
        (EX.unbacked, True, CV.rev_proposed, CV.orig_human),
        (EX.backed, True, CV.rev_confirmed, CV.orig_human),
        (EX.official, True, CV.rev_proposed, CV.orig_official),
        (EX.untyped_alignment, False, CV.rev_confirmed, CV.orig_human),
    ):
        typed(data, said, CUR.Statement)
        data.add((said, CUR.majorOverlap, EX.other))
        alignment = URIRef(f"{said}-alignment")
        for name, value in (("source", said), ("target", EX.other), ("relation", CV.rel_majorOverlap),
                            ("reviewStatus", status), ("origin", origin)):  # fmt: skip
            data.add((alignment, CUR[name], value))
        if typed_as:
            data.add((alignment, RDF.type, CUR.Alignment))

    assert found(data, "Kurzform-Kante ohne") == {str(EX.unbacked), str(EX.untyped_alignment)}


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
