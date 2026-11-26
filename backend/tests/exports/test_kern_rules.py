"""A document's rules in the Kern graph (plan M3a I; app/exports/kern_rules.py): each a rule of its kind's
class with its wording in its language, its anchor, its parsed values, where it came from and how far it is
reviewed, what it applies to, its options and what it requires; option texts no link names stay text
(cur:parsedExpression). Each kind passes its shape; a selection rule of fewer options than its maxCount is a
violation - but one of fewer than two linked options, as X3 reads them all as text, is a rule of no kind
(cur:Rule) until the editors link two (plan M3a I, decision rule). A rejected rule is not in the graph."""

from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from rdflib import RDF, XSD, BNode, Literal, URIRef
from rdflib.namespace import PROV

from app.db.rule_rows import Link, Rule, RuleAnchor
from app.db.rules import add_rule, drop_or_reject_rule, edit_rule
from app.db.statement_editing import HandAnchor
from app.exports.kern_naming import draft_naming, frozen_naming
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.kern_rows import KernRows, read_document
from tests.db.test_editing import document, one
from tests.db.test_freeze import BASE, DOC, ready
from tests.db.test_nodes import connection, owner, url
from tests.exports.test_kern_naming import assert_isomorphic, under_frozen_names
from tests.exports.test_kern_values import CV, results, uri
from tests.pipeline.test_shacl import a_document

pytestmark = pytest.mark.anyio
__all__ = ["connection", "document", "url"]  # the fixtures, shared with tests/db
HUMAN, PROPOSED = CV + "orig_human", CV + "rev_proposed"


def a_rule(kind: str, **values: Any) -> Rule:
    fields: dict[str, Any] = {
        "id": uuid4(), "iri": None, "kind": kind, "verbatim": "Eine Regel.", "min_count": None,
        "max_count": None, "min_amount": None, "max_amount": None, "amount_unit": None,
        "requirement_kind": None, "max_share": None, "option_texts": (), "applies_to": (), "options": (),
        "requires": (), "origin": HUMAN, "review_status": PROPOSED, "revision": 1, "by_hand": True,
        "anchors": (RuleAnchor(1, None, ("p1-b1",)),),
    } | values  # fmt: skip
    return Rule(**fields)


def with_rules(rows: KernRows, *rules: Rule) -> KernRows:
    """The document with ``rules``, each on an anchor of its own."""
    anchors = [
        {"id": uuid4(), "node_id": None, "statement_id": None, "frame_part_id": rule.id, "page_start": 1,
         "page_end": None, "printed_page": None, "quote": None, "match_kind_iri": None, "match_score": None,
         "char_start": None, "char_end": None, "table_cell": None, "section_path": None, "blocks": ["p1-b1"]}
        for rule in rules
    ]  # fmt: skip
    return replace(rows, rules=list(rules), anchors=[*rows.anchors, *anchors])


def targets(rows: KernRows) -> dict[str, Link]:
    return {
        "specification": Link(rows.specifications[0]["id"], "specification"),
        "node": Link(rows.nodes[0]["id"], "node"),
        "statement": Link(rows.statements[0]["id"], "statement"),
    }


def found(rows: KernRows) -> set[tuple[str, str, str]]:
    """The results the rules add to the document without them: focus, shape, severity."""
    anchors = [anchor for anchor in rows.anchors if anchor.get("frame_part_id") is None]
    plain = results(kern_graph(replace(rows, rules=[], anchors=anchors)))
    return {(item.focus, item.shape, item.severity) for item in results(kern_graph(rows)) - plain}


def test_each_kind_of_rule_passes_its_shape() -> None:
    rows = a_document([CV + "addr_learner"])
    at = targets(rows)
    applies = (at["specification"],)
    rules = (
        a_rule("selection", min_count=1, max_count=2, min_amount=Decimal(10), max_amount=Decimal(20),
               amount_unit=CV + "unit_ectsCredit", options=(at["node"], at["statement"]), applies_to=applies),
        a_rule("prerequisite", requirement_kind=CV + "req_formal", requires=(at["statement"],),
               applies_to=applies),
        a_rule("completion", min_amount=Decimal(180), amount_unit=CV + "unit_ectsCredit", applies_to=applies),
        a_rule("recognition", max_share=Decimal("0.5"), applies_to=applies),
        a_rule("progression", applies_to=applies),
    )  # fmt: skip

    assert found(with_rules(rows, *rules)) == set()


def test_a_rule_states_its_wording_anchor_values_links_and_where_it_came_from() -> None:
    rows = a_document([CV + "addr_learner"])
    at = targets(rows)
    rule = a_rule(
        "selection", min_count=2, max_count=2, min_amount=Decimal("7.5"), amount_unit=CV + "unit_ectsCredit",
        option_texts=("Modul C",), options=(at["node"], at["statement"]), applies_to=(at["specification"],),
    )  # fmt: skip
    valued = with_rules(rows, rule)

    graph = kern_graph(valued)

    subject = uri(rule.id)
    [anchor] = graph.objects(subject, CUR.anchor)
    assert set(graph.predicate_objects(subject)) == {
        (RDF.type, CUR.SelectionRule), (CUR.verbatim, Literal("Eine Regel.", lang="de")),
        (CUR.anchor, anchor),
        (CUR.origin, URIRef(HUMAN)), (CUR.reviewStatus, URIRef(PROPOSED)),
        (CUR.minCount, Literal(2)), (CUR.maxCount, Literal(2)),
        (CUR.minAmount, Literal(Decimal("7.5"), datatype=XSD.decimal)),
        (CUR.amountUnit, URIRef(CV + "unit_ectsCredit")), (CUR.parsedExpression, Literal("Modul C")),
        (CUR.option, uri(at["node"].target)), (CUR.option, uri(at["statement"].target)),
        (CUR.ruleAppliesTo, uri(at["specification"].target)),
    }  # fmt: skip
    assert (anchor, RDF.type, CUR.SourceAnchor) in graph
    assert (anchor, CUR.blockId, Literal("p1-b1")) in graph


def test_a_value_out_of_its_kind_s_domain_is_not_stated() -> None:
    # cur:requirementKind is a prerequisite rule's, cur:maxShare a recognition rule's: at another kind, they
    # would make it one of those as well
    rows = a_document([CV + "addr_learner"])
    rule = a_rule("completion", requirement_kind=CV + "req_formal", max_share=Decimal("0.3"))

    graph = kern_graph(with_rules(rows, rule))

    assert list(graph.objects(uri(rule.id), CUR.requirementKind)) == []
    assert list(graph.objects(uri(rule.id), CUR.maxShare)) == []


def test_a_selection_of_one_linked_option_is_a_rule_of_no_kind_yet() -> None:
    # the shapes ask two options of a selection: until two are linked, it is cur:Rule (decision rule)
    rows = a_document([CV + "addr_learner"])
    at = targets(rows)
    one = a_rule("selection", options=(at["node"],), applies_to=(at["specification"],))

    graph = kern_graph(with_rules(rows, one))

    assert set(graph.objects(uri(one.id), RDF.type)) == {CUR.Rule}
    assert list(graph.objects(uri(one.id), CUR.option)) == [uri(at["node"].target)]
    assert found(with_rules(rows, one)) == set()


def test_a_selection_of_fewer_options_than_its_most_is_a_violation() -> None:
    rows = a_document([CV + "addr_learner"])
    at = targets(rows)
    fewer = a_rule(
        "selection", max_count=3, options=(at["node"], at["statement"]), applies_to=(at["specification"],)
    )

    assert found(with_rules(rows, fewer)) == {(str(uri(fewer.id)), "SelectionRuleShape", "violation")}


def test_a_selection_x3_read_with_its_options_as_text_alone_is_a_rule_of_no_kind() -> None:
    # no editor linked an option: the shapes ask two of a selection rule, which X3 cannot give (decision rule)
    rows = a_document([CV + "addr_learner"])
    read = a_rule(
        "selection", min_count=3, max_count=2, option_texts=("A", "B", "C"), origin=CV + "orig_model"
    )

    graph = kern_graph(with_rules(rows, read))

    assert set(graph.objects(uri(read.id), RDF.type)) == {CUR.Rule}
    assert set(graph.objects(uri(read.id), CUR.parsedExpression)) == {
        Literal("A"),
        Literal("B"),
        Literal("C"),
    }
    # the one result left is the warning of a rule without what it applies to
    assert found(with_rules(rows, read)) == {(str(uri(read.id)), "RuleShape", "warning")}


def test_a_recognition_over_half_is_a_warning_and_over_the_whole_a_violation() -> None:
    rows = a_document([CV + "addr_learner"])
    applies = (targets(rows)["specification"],)
    half, whole = Decimal("0.6"), Decimal("1.5")
    over_half = a_rule("recognition", max_share=half, applies_to=applies)
    over_whole = a_rule("recognition", max_share=whole, applies_to=applies)

    assert found(with_rules(rows, over_half, over_whole)) == {
        (str(uri(over_half.id)), "RecognitionRuleShape", "warning"),
        (str(uri(over_whole.id)), "RecognitionRuleShape", "warning"),
        (str(uri(over_whole.id)), "RecognitionRuleShape", "violation"),
    }


@pytest.mark.pg
async def test_the_rules_are_read_and_a_rejected_one_or_a_rejected_target_left_out(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    top = await ready(connection, document)
    [said] = await one(
        connection,
        "SELECT id FROM statement WHERE document_id = %s AND verbatim = 'Sie messen.'",
        document.id,
    )
    kept = await add_rule(connection, owner(document), document.id, "prerequisite", "Wer A hat.",
                          [HandAnchor(blocks=("p1-b1",))])  # fmt: skip
    dropped = await add_rule(connection, owner(document), document.id, "completion", "Alles.",
                             [HandAnchor(page=1)])  # fmt: skip
    assert kept is not None and dropped is not None
    await edit_rule(connection, owner(document), kept, 1, {"requires": [said], "applies_to": [top]})
    await connection.execute("UPDATE frame_part SET by_hand = false WHERE id = %s", (dropped,))
    await drop_or_reject_rule(connection, owner(document), dropped, 1)
    await connection.execute(
        "UPDATE statement SET review_status_iri = %s WHERE id = %s", (CV + "rev_rejected", said)
    )

    rows = await read_document(connection, document.id)
    graph = kern_graph(rows)

    assert [rule.id for rule in rows.rules] == [kept]
    assert (uri(kept), RDF.type, CUR.PrerequisiteRule) in graph
    assert list(graph.objects(uri(kept), CUR.requiresItem)) == []  # the statement rejected is no target
    assert list(graph.objects(uri(kept), CUR.ruleAppliesTo)) == [uri(top)]
    [anchor] = graph.objects(uri(kept), CUR.anchor)
    assert (anchor, CUR.blockId, Literal("p1-b1")) in graph
    assert (uri(dropped), None, None) not in graph


@pytest.mark.pg
async def test_a_frozen_rule_is_named_by_its_iri_and_the_graph_is_the_draft_s_under_other_names(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    from app.db.freezing import freeze
    from tests.db.test_freeze import checked

    await ready(connection, document)
    made = await add_rule(
        connection, owner(document), document.id, "completion", "Alles.", [HandAnchor(page=1)]
    )
    assert made is not None
    await checked(connection, document)
    await freeze(connection, document.id, BASE, accept_violations=True)
    rows = await read_document(connection, document.id)

    frozen = kern_graph(rows, frozen_naming())
    draft = kern_graph(rows, draft_naming())

    assert (URIRef(DOC + "/rule-1"), RDF.type, CUR.CompletionRule) in frozen
    [anchor] = frozen.objects(URIRef(DOC + "/rule-1"), CUR.anchor)
    assert isinstance(anchor, BNode)
    stamped = list(frozen.triples((URIRef(DOC), PROV.generatedAtTime, None)))
    frozen.remove(stamped[0])
    assert_isomorphic(frozen, under_frozen_names(draft, rows))
