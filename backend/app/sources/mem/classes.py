"""How a part of a MEM plan is typed in the core (plan M2, E2/E8): the rules ``mem-rules/2``.

In this order:
1. a reference - pointed at by ``hat Verweis`` - is a statement of kind reference, or with parts below it a
   subunit node, its parts kept;
1a. in the KMK's graph (E13, plan M2-7) its own table (``kmk``), for the lexicon's cues type its classes as a
   Land's: a Kompetenzbereich (Bista) is an area of the Kompetenzbereich type, a Standard (Bistas) a
   statement of kind standard, subkind Regelstandard, for the learner;
2. a state class the lexicon names (a cue's ``skos:exactMatch``) takes the cue's target: a node type with
   its function, a statement subkind with its kind, or a kind itself - six classes of Brandenburg the
   lexicon leaves ``kind_unclassified``, their kind to be decided at the document;
3. else its base class - among its own classes (the endpoint's graph holds the inferred ones), up the
   ontology's chain (mem/lp-klassen.ttl), or by the state classes' table (mem/grundtypen.json) where the
   base type follows from the class's function value - in the order BASE_ORDER;
4. else an area of an unknown class (``unknown``), never a frame part - in the KMK's graph an Element (Bista)
   is an area without a type (``kmk_element``): every Bista part is one, so it is the catch-all, not a rule
   before the cues, and counted apart, so that a class new to the rules still shows in the run.

A part of a statement's base class that has parts below it is a node (``fn_subunit``): a statement has
no children. The addressee is the subkind's ``cur:defaultAddressee``, else the kind's in KIND_ADDRESSEE.
What the rules found per part goes into the import's run, with their version.

The export goes the other way (plan M2-6, E8/E9): a row's classes as MEM gave them, and where none of them
reaches a base class through the chain the MEM shapes read, the first base class the table gives them as a
further type (``base_to_add``); a row the editors made or changed takes the base class of its core typing
(``generic_class``).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from rdflib import RDFS, Graph, URIRef

from app.sources.mem.queries import LP
from app.sources.mem.tree import VERWEIS, MemPart

RULES = "mem-rules/2"
CV = "https://w3id.org/wlo/curriculum/vocab#"
SCHUL = "https://w3id.org/wlo/curriculum/profile/school#"
# the seven base classes of a curricular element, first the one a part of two takes
BASE_ORDER = (
    LP + "LP_0000263",  # Kompetenzspezifikation
    LP + "LP_0000332",  # Lerninhalt
    LP + "LP_0000852",  # Hinweis
    VERWEIS,  # LP_0030065
    LP + "LP_0000349",  # Bereich
    LP + "LP_0030325",  # Leitperspektive
    LP + "LP_0001015",  # Fragment
)
# a base class's statement kind, or its node (function, type)
_KINDS = {
    LP + "LP_0000263": CV + "kind_learningOutcome",
    LP + "LP_0000332": CV + "kind_content",
    LP + "LP_0000852": CV + "kind_guidance",
    VERWEIS: CV + "kind_reference",
}
_NODES = {
    LP + "LP_0000349": (CV + "fn_area", SCHUL + "Kompetenzbereich"),
    LP + "LP_0030325": (CV + "fn_crossCutting", SCHUL + "Querschnittsbereich"),
    LP + "LP_0001015": (CV + "fn_area", None),
}
KIND_ADDRESSEE = {
    CV + "kind_learningOutcome": CV + "addr_learner",
    CV + "kind_content": CV + "addr_learner",
    CV + "kind_guidance": CV + "addr_educator",
    CV + "kind_reference": CV + "addr_educator",
    CV + "kind_standard": CV + "addr_learner",  # what learners can at the end of a stage
    # the kind is open, so is its addressee: the review list decides
    CV + "kind_unclassified": CV + "addr_other",
}
_FUNCTION = CV + "fn_"
_KIND = CV + "kind_"
_SUBUNIT = CV + "fn_subunit"
_AREA = CV + "fn_area"
_ELEMENT = LP + "LP_0000536"  # Element (Bista)
# the KMK's table: a class -> a node (function, type), or a statement (kind, subkind)
_KMK_NODES = {LP + "LP_0030263": (_AREA, SCHUL + "Kompetenzbereich")}  # Kompetenzbereich (Bista)
_KMK_STATEMENTS = {LP + "LP_0030266": (CV + "kind_standard", SCHUL + "Regelstandard")}  # Standard (Bistas)


@dataclass(frozen=True)
class MemRules:
    targets: Mapping[str, str]  # a state class -> the profile's target its cue names
    broader: Mapping[str, str]  # a node type -> its function, a subkind -> its kind
    addressees: Mapping[str, str]  # a subkind -> its default addressee
    bases: Mapping[str, frozenset[str]]  # a class -> the base classes above it
    version: str = RULES
    kmk: bool = False  # the plan is of the KMK's graph: its table before the cues


@dataclass(frozen=True)
class Typed:
    node: bool
    function: str | None = None  # a node's
    node_type: str | None = None
    kind: str | None = None  # a statement's
    subkind: str | None = None
    addressee: str | None = None
    rule: str = "base"  # reference, kmk, cue, base, kmk_element, unknown


def rules_from(
    cues: Iterable[tuple[str, str]],
    concepts: Iterable[tuple[str, str | None, str | None]],
    chain: Graph,
    base_types: Mapping[str, Iterable[str]],
    *,
    kmk: bool = False,
) -> MemRules:
    """The rules from the lexicon's cues (state class, target), the concepts (IRI, first broader, default
    addressee), the ontology's chain and the base-type table; with the KMK's table for a plan of its
    graph."""
    targets: dict[str, str] = {}
    for klass, target in sorted(cues):
        targets.setdefault(klass, target)  # a class two cues name: the first target by IRI
    broader = {iri: up for iri, up, _ in concepts if up is not None}
    addressees = {iri: addressee for iri, _, addressee in concepts if addressee is not None}
    bases: dict[str, set[str]] = {}
    for klass in {str(subject) for subject in chain.subjects(RDFS.subClassOf, None)}:
        bases[klass] = {str(up) for up in chain.transitive_objects(URIRef(klass), RDFS.subClassOf)} & set(
            BASE_ORDER
        )
    for klass, types in base_types.items():
        bases.setdefault(klass, set()).update(set(types) & set(BASE_ORDER))
    return MemRules(
        targets,
        broader,
        addressees,
        {klass: frozenset(found) for klass, found in bases.items() if found},
        kmk=kmk,
    )


def typed(part: MemPart, rules: MemRules) -> Typed:
    """The part's place in the core by the rules, as the module says."""
    if part.reference or VERWEIS in part.classes:
        if part.children:  # a Verweis the closure holds as a part, with parts of its own: they stay
            return Typed(True, function=_SUBUNIT, rule="reference")
        return Typed(False, kind=_KINDS[VERWEIS], addressee=KIND_ADDRESSEE[_KINDS[VERWEIS]], rule="reference")
    if rules.kmk and (found := _kmk_typed(part, rules)) is not None:
        return found
    for klass in sorted(part.classes):
        target = rules.targets.get(klass)
        if target is None:
            continue
        if target.startswith(_KIND):  # the lexicon names the kind itself (kind_unclassified)
            kind, subkind = target, None
        elif (up := rules.broader.get(target)) is None:
            continue
        elif up.startswith(_FUNCTION):
            return Typed(True, function=up, node_type=target, rule="cue")
        else:
            kind, subkind = up, target
        if part.children:
            return Typed(True, function=_SUBUNIT, rule="cue")
        addressee = rules.addressees.get(target) or KIND_ADDRESSEE.get(kind, CV + "addr_learner")
        return Typed(False, kind=kind, subkind=subkind, addressee=addressee, rule="cue")
    bases = set(part.classes) & set(BASE_ORDER)
    for klass in part.classes:
        bases |= rules.bases.get(klass, frozenset())
    base = next((each for each in BASE_ORDER if each in bases), None)
    if base is None:
        if rules.kmk and _ELEMENT in part.classes:
            return Typed(True, function=_AREA, rule="kmk_element")
        return Typed(True, function=_AREA, rule="unknown")
    if base in _NODES:
        function, node_type = _NODES[base]
        return Typed(True, function=function, node_type=node_type)
    if part.children:
        return Typed(True, function=_SUBUNIT)
    return Typed(False, kind=_KINDS[base], addressee=KIND_ADDRESSEE[_KINDS[base]])


def _kmk_typed(part: MemPart, rules: MemRules) -> Typed | None:
    """A part of the KMK's graph by its table, an area before a standard; none where it names neither. The
    addressee as the cues give it: the subkind's own, else the kind's."""
    for klass, (function, node_type) in _KMK_NODES.items():
        if klass in part.classes:
            return Typed(True, function=function, node_type=node_type, rule="kmk")
    for klass, (kind, subkind) in _KMK_STATEMENTS.items():
        if klass in part.classes:
            if part.children:
                return Typed(True, function=_SUBUNIT, rule="kmk")
            addressee = rules.addressees.get(subkind) or KIND_ADDRESSEE[kind]
            return Typed(False, kind=kind, subkind=subkind, addressee=addressee, rule="kmk")
    return None


@dataclass(frozen=True)
class MemModel:
    """The base classes a class reaches: through the chain alone, and by the table."""

    chain_bases: Mapping[str, frozenset[str]]
    table_bases: Mapping[str, frozenset[str]]


def model_from(chain: Graph, base_types: Mapping[str, Iterable[str]]) -> MemModel:
    """The model of the ontology's chain and base-type table."""
    chain_bases = {
        klass: frozenset(
            {str(up) for up in chain.transitive_objects(URIRef(klass), RDFS.subClassOf)} & set(BASE_ORDER)
        )
        for klass in {str(subject) for subject in chain.subjects(RDFS.subClassOf, None)}
    }
    table_bases = {klass: frozenset(types) & frozenset(BASE_ORDER) for klass, types in base_types.items()}
    return MemModel(
        {klass: bases for klass, bases in chain_bases.items() if bases},
        {klass: bases for klass, bases in table_bases.items() if bases},
    )


def base_to_add(classes: Sequence[str], model: MemModel) -> str | None:
    """The base class to type a row with beside its classes: none where one of them is a base class or the
    chain carries one there; else the first, in BASE_ORDER, the table gives them; else none."""
    if set(classes) & set(BASE_ORDER) or any(model.chain_bases.get(klass) for klass in classes):
        return None
    found = set().union(*(model.table_bases.get(klass, frozenset()) for klass in classes))
    return next((base for base in BASE_ORDER if base in found), None)


# a statement kind -> its base class; a KMK standard says what learners can, as a Kompetenzspezifikation
_GENERIC_KINDS = {kind: base for base, kind in _KINDS.items()} | {CV + "kind_standard": LP + "LP_0000263"}
_GENERIC_NODES = {typing: base for base, typing in _NODES.items()}  # (function, node type) -> base class
_FRAGMENT = LP + "LP_0001015"
_CROSS_CUTTING = CV + "fn_crossCutting"


def generic_class(*, function: str | None, node_type: str | None, kind: str | None) -> str:
    """The base class of a core typing - a node's function and type, a statement's kind: the rules
    backwards (an area of the type a Bereich makes is one, a cross-cutting node a Leitperspektive), a
    Fragment where they give none (another area, a subunit, an unclassified kind)."""
    if function is not None:
        found = _GENERIC_NODES.get((function, node_type))
        return found or (LP + "LP_0030325" if function == _CROSS_CUTTING else _FRAGMENT)
    return _GENERIC_KINDS.get(kind or "", _FRAGMENT)
