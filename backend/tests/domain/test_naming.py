"""The IRIs a document's nodes and statements get when it is frozen (plan M1 9.6, Paket 9b H6): nodes from
the top by the path of their codes, siblings in their order; statements numbered under their node, each
number given once. What a draft copy brought along keeps its IRI, what is new steps past it; a rejected
statement gets none."""

from uuid import uuid4

from app.domain.naming import GivenByKey, NodeRow, SpecificationRow, StatementRow, VariantRow, name_rows

DOC = "https://example.org/kk/doc/de/kmk/rlp/2018"


def node(code: str | None, position: int, parent: NodeRow | None = None, **changes: object) -> NodeRow:
    values: dict[str, object] = {
        "id": uuid4(), "parent_id": None if parent is None else parent.id, "position": position,
        "code": code, "code_assigned": False, "iri": None, "statement_serial": 0,
    } | changes  # fmt: skip
    return NodeRow(**values)  # type: ignore[arg-type]


def statement(at: NodeRow, position: int, **changes: object) -> StatementRow:
    values: dict[str, object] = {
        "id": uuid4(),
        "node_id": at.id,
        "position": position,
        "iri": None,
        "rejected": False,
    } | changes
    return StatementRow(**values)  # type: ignore[arg-type]


def specification(key: str, iri: str | None = None) -> SpecificationRow:
    return SpecificationRow(uuid4(), key, iri)


def variant(of: SpecificationRow, key: str, iri: str | None = None) -> VariantRow:
    return VariantRow(uuid4(), of.id, key, iri)


def test_a_document_s_specifications_and_variants_are_named_by_their_keys() -> None:
    lp = specification("lp")
    g8, g9 = variant(lp, "G8"), variant(lp, "G9")

    named = name_rows(DOC, [], [], specifications=[lp], variants=[g9, g8])

    assert named.specifications == {lp.id: f"{DOC}/spec/lp"}
    assert named.variants == {g8.id: f"{DOC}/spec/lp/variant/g8", g9.id: f"{DOC}/spec/lp/variant/g9"}


def test_two_keys_of_one_slug_get_two_iris() -> None:
    # in the order of their keys: "LP" before "lp"
    lower, upper = specification("lp"), specification("LP")
    first, second = variant(lower, "g-8"), variant(lower, "G 8")

    named = name_rows(DOC, [], [], specifications=[lower, upper], variants=[first, second])

    assert named.specifications == {upper.id: f"{DOC}/spec/lp", lower.id: f"{DOC}/spec/lp-2"}
    assert named.variants == {
        second.id: f"{DOC}/spec/lp-2/variant/g-8",
        first.id: f"{DOC}/spec/lp-2/variant/g-8-2",
    }


def test_a_key_without_a_letter_or_digit_is_named_by_its_place() -> None:
    # its place among the keys of its document, or of its specification
    lp, bullet = specification("lp"), specification("•")
    star = variant(lp, "*")

    named = name_rows(DOC, [], [], specifications=[lp, bullet], variants=[variant(lp, "a"), star])

    assert named.specifications[bullet.id] == f"{DOC}/spec/pos-2"
    assert named.variants[star.id] == f"{DOC}/spec/lp/variant/pos-1"


def test_a_specification_brought_along_keeps_its_iri_and_a_new_one_is_named_past_it() -> None:
    # recoded since it was named: its IRI stays, and a new key of its old slug counts on
    kept = specification("sek-1", iri=f"{DOC}/spec/lp")
    new = specification("lp")
    old_variant = variant(kept, "g8", iri=f"{DOC}/spec/lp/variant/g8")
    new_variant = variant(kept, "G8")

    named = name_rows(DOC, [], [], specifications=[kept, new], variants=[old_variant, new_variant])

    assert named.specifications == {new.id: f"{DOC}/spec/lp-2"}
    assert named.variants == {new_variant.id: f"{DOC}/spec/lp/variant/g8-2"}


def test_a_key_another_revision_named_takes_that_name() -> None:
    # revisions share the document's IRI: a key names in each what it named in the one that named it first
    lp = specification("lp")
    g8 = variant(lp, "g8")
    other = specification("lp-neu")
    given = GivenByKey(
        specifications={"lp": f"{DOC}/spec/lp-alt", "weg": f"{DOC}/spec/lp-neu"},
        variants={("lp", "g8"): f"{DOC}/spec/lp-alt/variant/g8"},
    )

    named = name_rows(DOC, [], [], specifications=[lp, other], variants=[g8], given=given)

    # a name another revision gave another key is none to give again
    assert named.specifications == {lp.id: f"{DOC}/spec/lp-alt", other.id: f"{DOC}/spec/lp-neu-2"}
    assert named.variants == {g8.id: f"{DOC}/spec/lp-alt/variant/g8"}


def test_a_node_and_a_specification_never_share_an_iri() -> None:
    # a node coded "Spec" with a child "LP" would sit where the specification "lp" is named
    top = node("Spec", 1)
    child = node("LP", 1, top)
    lp = specification("lp")

    named = name_rows(DOC, [top, child], [], specifications=[lp])

    assert named.specifications == {lp.id: f"{DOC}/spec/lp"}
    assert named.nodes == {top.id: f"{DOC}/spec", child.id: f"{DOC}/spec/lp-2"}


def test_a_node_moved_away_keeps_its_iri_from_a_new_sibling_of_its_old_place() -> None:
    # its IRI is of the path it was named at: no node made there since takes it
    first = node("LF 1", 1, iri=f"{DOC}/lf-1")
    second = node("LF 2", 2, iri=f"{DOC}/lf-2")
    moved = node("Pos", 1, second, iri=f"{DOC}/lf-1/pos")
    added = node("Pos", 1, first)

    named = name_rows(DOC, [first, second, moved, added], [])

    assert named.nodes == {added.id: f"{DOC}/lf-1/pos-2"}


def test_a_document_frozen_first_names_its_nodes_by_their_codes_and_numbers_its_statements() -> None:
    first = node("LF 1", 1)
    second = node("2", 2, code_assigned=True)
    under = node(None, 1, first)  # an editor's, without a code: its place names it
    beside = node(None, 2, first)
    said = [statement(first, 1), statement(first, 2, rejected=True), statement(first, 3)]

    # in any order: the positions decide
    named = name_rows(DOC, [second, beside, under, first], list(reversed(said)))

    assert named.nodes == {
        first.id: f"{DOC}/lf-1",
        second.id: f"{DOC}/pos-2",
        under.id: f"{DOC}/lf-1/pos-1",
        beside.id: f"{DOC}/lf-1/pos-2",
    }
    # a rejected statement is none of the curriculum's: it takes no number
    assert named.statements == {said[0].id: f"{DOC}/lf-1/s-1", said[2].id: f"{DOC}/lf-1/s-2"}
    assert named.serials == {first.id: 2}


def test_a_copy_keeps_what_it_brought_and_names_what_is_new_past_it() -> None:
    # copied: lf-1 with s-1 and s-3 (s-2 was an editor's, taken away in the copy); new: a second "LF 1"
    first = node("LF 1", 1, iri=f"{DOC}/lf-1", statement_serial=3)
    renamed = node("LF 7", 2, iri=f"{DOC}/lf-2")  # its code changed in the copy: its IRI stays
    added = node("LF 1", 3)
    kept = [statement(first, 1, iri=f"{DOC}/lf-1/s-1"), statement(first, 3, iri=f"{DOC}/lf-1/s-3")]
    new = statement(first, 4)
    taken_back = statement(first, 2, iri=f"{DOC}/lf-1/s-2", rejected=True)  # rejected since: it keeps it

    named = name_rows(DOC, [first, renamed, added], [*kept, new, taken_back])

    assert named.nodes == {added.id: f"{DOC}/lf-1-2"}
    assert named.statements == {new.id: f"{DOC}/lf-1/s-4"}
    assert named.serials == {first.id: 4}


def test_a_new_node_steps_past_a_segment_a_copied_sibling_holds_by_another_code() -> None:
    copied = node("LF 9", 1, iri=f"{DOC}/lf-3")  # once "LF 3", recoded in the copy
    added = node("LF 3", 2)

    named = name_rows(DOC, [copied, added], [])

    assert named.nodes == {added.id: f"{DOC}/lf-3-2"}


def test_a_new_node_steps_past_a_copied_sibling_s_segment_to_none_a_statement_holds() -> None:
    # counted on from "s", "s-2" would be the IRI of the parent's second statement
    copied = node("LF 1", 1, iri=f"{DOC}/s")  # once "S", recoded in the copy
    added = node("S", 2)

    named = name_rows(DOC, [copied, added], [])

    assert named.nodes == {added.id: f"{DOC}/s-1-2"}


def test_a_segment_counted_on_is_none_a_later_new_sibling_takes() -> None:
    copied = node("LF 9", 1, iri=f"{DOC}/lf-1")  # once "LF 1"
    counted = node("LF 1", 2)  # past the copied one's segment: lf-1-2
    printed = node("LF 1-2", 3)  # printed so: past the one counted on

    named = name_rows(DOC, [copied, counted, printed], [])

    assert named.nodes == {counted.id: f"{DOC}/lf-1-2", printed.id: f"{DOC}/lf-1-2-2"}


def test_nothing_new_is_nothing_named() -> None:
    first = node("LF 1", 1, iri=f"{DOC}/lf-1", statement_serial=1)

    named = name_rows(DOC, [first], [statement(first, 1, iri=f"{DOC}/lf-1/s-1")])

    assert (named.nodes, named.statements, named.serials) == ({}, {}, {})


def test_a_node_named_again_numbers_its_statements_past_all_an_earlier_revision_gave() -> None:
    # dropped in a draft copy and made anew at its code's path: its IRI comes back, no number does
    again = node("LF 1", 1)

    named = name_rows(DOC, [again], [statement(again, 1)], served={f"{DOC}/lf-1": 5})

    assert named.nodes == {again.id: f"{DOC}/lf-1"}
    assert list(named.statements.values()) == [f"{DOC}/lf-1/s-6"]
    assert named.serials == {again.id: 6}


def test_a_name_given_by_key_that_a_row_of_the_document_holds_is_counted_on() -> None:
    # recoded in the copy, "lp-alt" keeps .../spec/lp: a new "lp" takes no name a row holds, though revision 1
    # gave it to "lp"; so for a variant recoded beside a new one of its old key
    kept = specification("lp-alt", iri=f"{DOC}/spec/lp")
    new = specification("lp")
    stays = specification("sek", iri=f"{DOC}/spec/sek")
    recoded = variant(stays, "g8-alt", iri=f"{DOC}/spec/sek/variant/g8")
    added = variant(stays, "g8")
    given = GivenByKey(
        specifications={"lp": f"{DOC}/spec/lp", "sek": f"{DOC}/spec/sek"},
        variants={("sek", "g8"): f"{DOC}/spec/sek/variant/g8"},
    )

    named = name_rows(DOC, [], [], specifications=[kept, new, stays], variants=[recoded, added], given=given)

    assert named.specifications == {new.id: f"{DOC}/spec/lp-2"}
    assert named.variants == {added.id: f"{DOC}/spec/sek/variant/g8-2"}


def test_a_name_given_by_key_is_taken_once_and_a_variant_s_only_under_its_specification() -> None:
    # two keys a revision each named alike; a variant's name of another specification's IRI is none of its own
    first, second = specification("a"), specification("b")
    g8 = variant(second, "g8")
    given = GivenByKey(
        specifications={"a": f"{DOC}/spec/x", "b": f"{DOC}/spec/x"},
        variants={("b", "g8"): f"{DOC}/spec/x/variant/g8"},
    )

    named = name_rows(DOC, [], [], specifications=[first, second], variants=[g8], given=given)

    assert named.specifications == {first.id: f"{DOC}/spec/x", second.id: f"{DOC}/spec/b"}
    assert named.variants == {g8.id: f"{DOC}/spec/b/variant/g8"}
