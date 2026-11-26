"""A document's rules in the Kern graph (plan M3a I, E10; cur-kern.ttl cur:Rule, cur-shapes.ttl RuleShape):
each rules frame part the rows hold (app/db/rule_rows.py; a rejected one left out) as a rule of its kind's
class, its wording in German (cur:verbatim), its anchors (cur:anchor, written with the others in
app/exports/kern_rdf.py), where it came from and how far it is reviewed, its counts as integers, its amounts
and its share as decimals, its unit and kind of requirement, what it applies to (cur:ruleAppliesTo), its
options (cur:option) and what it requires (cur:requiresItem) - a target the graph does not state, a rejected
statement, left out -, and each option text no link names yet as written (cur:parsedExpression). It is named
as a statement is (app/exports/kern_naming.py): its urn:uuid in a draft, its stored IRI once frozen.

A value of another kind's domain is not stated - a kind of requirement is a prerequisite rule's, a share a
recognition rule's -, as it would make the rule one of that kind too. A selection rule of fewer than two
linked options - X3 reads them all as text - is a rule of no kind (cur:Rule) until the editors link two: the
selection's shape asks two linked options of it, a violation no editor brought about (plan M3a I, decision
rule). X3 reads a German plan's rules: their language is German, as a statement's is by default (migration
l1_nodes) - a known limit: a plan in another language would be tagged German as well."""

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from rdflib import RDF, XSD, BNode, Graph, Literal, Namespace, URIRef

from app.db.rule_rows import Rule
from app.exports.kern_naming import Naming
from app.exports.kern_rows import KernRows

CUR = Namespace("https://w3id.org/wlo/curriculum/core#")  # as app/exports/kern_rdf.py, which calls here
Name = URIRef | BNode
LANGUAGE = "de"  # a known limit: every rule's wording is tagged German (see above)
_CLASSES = {
    "selection": CUR.SelectionRule, "prerequisite": CUR.PrerequisiteRule, "completion": CUR.CompletionRule,
    "recognition": CUR.RecognitionRule, "progression": CUR.ProgressionRule,
}  # fmt: skip
LINKED_OPTIONS = 2  # a selection rule's options the editors linked before it is stated as one


def rule_names(rows: KernRows, naming: Naming) -> dict[UUID, Name]:
    """Each rule's name by its id, so that its anchors name it too."""
    return {rule.id: naming.of("rule", {"id": rule.id, "iri": rule.iri}) for rule in rows.rules}


def add_rules(graph: Graph, rows: KernRows, names: Mapping[UUID, Name]) -> None:
    """The rows' rules, each named as ``names`` says, as the module says."""
    for rule in rows.rules:
        subject = names[rule.id]
        graph.add((subject, RDF.type, _class(rule)))
        graph.add((subject, CUR.verbatim, Literal(rule.verbatim, lang=LANGUAGE)))
        graph.add((subject, CUR.origin, URIRef(rule.origin)))
        graph.add((subject, CUR.reviewStatus, URIRef(rule.review_status)))
        for predicate, number in ((CUR.minCount, rule.min_count), (CUR.maxCount, rule.max_count)):
            if number is not None:
                graph.add((subject, predicate, Literal(number)))
        amounts = [(CUR.minAmount, rule.min_amount), (CUR.maxAmount, rule.max_amount)]
        if rule.kind == "recognition":
            amounts.append((CUR.maxShare, rule.max_share))
        for predicate, amount in amounts:
            _decimal(graph, subject, predicate, amount)
        if rule.amount_unit is not None:
            graph.add((subject, CUR.amountUnit, URIRef(rule.amount_unit)))
        if rule.kind == "prerequisite" and rule.requirement_kind is not None:
            graph.add((subject, CUR.requirementKind, URIRef(rule.requirement_kind)))
        for text in rule.option_texts:
            graph.add((subject, CUR.parsedExpression, Literal(text)))
        linked = ((CUR.ruleAppliesTo, rule.applies_to), (CUR.option, rule.options),
                  (CUR.requiresItem, rule.requires))  # fmt: skip
        for predicate, links in linked:
            for link in links:
                if (target := names.get(link.target)) is not None:
                    graph.add((subject, predicate, target))


def _class(rule: Rule) -> URIRef:
    if rule.kind == "selection" and len(rule.options) < LINKED_OPTIONS:
        return CUR.Rule
    return _CLASSES.get(rule.kind, CUR.Rule)


def _decimal(graph: Graph, subject: Name, predicate: URIRef, value: Decimal | None) -> None:
    if value is not None:
        graph.add((subject, predicate, Literal(value, datatype=XSD.decimal)))
