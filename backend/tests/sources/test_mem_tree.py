"""The tree of a MEM plan (app/sources/mem/tree.py, plan M2 E8), built from answers of the form the
endpoint gives (tests/sources/fixtures/mem, synthetic plans of the shapes frozen 2026-11-09): every part
once under a real parent - a stated ancestor no other stated ancestor lies below -, the deepest of them
if there are more, the others kept; the references a part holds under it, after its parts; the parts in
the store's order."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.sources.mem.sparql import MemRefused
from app.sources.mem.tree import MemPart, build_tree

FIXTURES = Path(__file__).parent / "fixtures" / "mem"


def frozen(land: str) -> dict[str, Any]:
    answers: dict[str, Any] = json.loads((FIXTURES / f"{land}.json").read_text(encoding="utf-8"))
    return answers


def walk(parts: list[MemPart]) -> list[MemPart]:
    found: list[MemPart] = []
    for part in parts:
        found.append(part)
        found.extend(walk(part.children))
    return found


@pytest.mark.parametrize("land", ["rp", "sn", "by", "be", "kmk"])
def test_every_part_and_reference_hangs_once_in_the_tree(land: str) -> None:
    answers = frozen(land)

    tree = build_tree(answers["closure"], answers["references"])

    placed = walk(tree.roots)
    assert len(placed) == len({part.iri for part in placed})
    assert {part.iri for part in placed} >= {row["n"] for row in answers["closure"]}
    assert len(placed) == len(answers["closure"]) + len({row["v"] for row in answers["references"]})


@pytest.mark.parametrize("land", ["rp", "sn", "by", "be"])
def test_a_part_s_ancestors_are_its_parent_and_the_parent_s_ancestors(land: str) -> None:
    # the four Länder state the closure: a part's stated ancestors are the path from its root
    answers = frozen(land)
    tree = build_tree(answers["closure"], answers["references"])
    stated = {row["n"]: set(filter(None, row["ancestors"].split("|"))) & tree.parts.keys()
              for row in answers["closure"]}  # fmt: skip

    placed = [part for part in tree.parts.values() if part.iri in stated and part.parent is not None]

    assert placed
    assert all(stated[part.iri] == {part.parent} | stated[part.parent] for part in placed)
    assert all(not part.other_parents for part in placed)


def test_a_reference_hangs_under_the_part_that_holds_it_and_names_its_target() -> None:
    answers = frozen("sn")
    tree = build_tree(answers["closure"], answers["references"])
    row = answers["references"][0]

    reference = tree.parts[row["v"]]

    assert reference.parent == row["x"] and reference in tree.parts[row["x"]].children
    assert reference.targets == (row["target"],)
    assert (
        "https://w3id.org/lehrplan/ontology/LP_0030065" in reference.classes
    )  # a Verweis, as hat Verweis says


def test_berlin_s_parts_are_named_by_their_preferred_labels() -> None:
    answers = frozen("be")

    tree = build_tree(answers["closure"], answers["references"])

    labels = {row["n"]: row.get("label", "") for row in answers["closure"]}
    assert all(labels.values())  # Berlin's skos:prefLabel, read where it has no rdfs:label
    assert all(tree.parts[iri].label == " ".join(label.split()) for iri, label in labels.items())


def test_children_follow_the_store_s_position_then_their_number() -> None:
    rows = [
        {"n": "https://w3id.org/p/a", "label": "A", "ancestors": "", "types": ""},
        *({"n": f"https://w3id.org/p/{name}", "label": name, "ancestors": "https://w3id.org/p/a", "types": "",
           **extra} for name, extra in (
            ("third", {}), ("second", {"number": "2"}), ("first", {"position": "1"}),
        )),
    ]  # fmt: skip

    tree = build_tree(rows, [])

    assert [child.label for child in tree.roots[0].children] == ["first", "second", "third"]


def test_two_parents_equally_deep_keep_the_second_beside_the_first() -> None:
    rows = [
        {"n": "https://w3id.org/p/a", "label": "A", "ancestors": "", "types": ""},
        {"n": "https://w3id.org/p/b", "label": "B", "ancestors": "", "types": ""},
        {
            "n": "https://w3id.org/p/c",
            "label": "C",
            "ancestors": "https://w3id.org/p/a|https://w3id.org/p/b",
            "types": "",
        },
    ]

    part = build_tree(rows, []).parts["https://w3id.org/p/c"]

    assert (part.parent, part.other_parents) == ("https://w3id.org/p/a", ("https://w3id.org/p/b",))


def test_parts_joined_in_a_cycle_are_refused_rather_than_dropped() -> None:
    rows = [
        {"n": "https://w3id.org/p/a", "label": "A", "ancestors": "https://w3id.org/p/b", "types": ""},
        {"n": "https://w3id.org/p/b", "label": "B", "ancestors": "https://w3id.org/p/a", "types": ""},
    ]

    with pytest.raises(MemRefused, match="cycle"):
        build_tree(rows, [])


def test_a_part_keeps_its_description_number_grades_hours_and_page() -> None:
    answers = frozen("sn")
    rows = {row["n"]: row for row in answers["closure"]}
    with_hours = next(iri for iri, row in rows.items() if row.get("hours"))

    part = build_tree(answers["closure"], answers["references"]).parts[with_hours]

    assert part.hours == rows[with_hours]["hours"]
    assert part.page == rows[with_hours].get("page")
    assert part.grades == tuple(sorted(filter(None, rows[with_hours]["grades"].split("|"))))


def row(name: str, *ancestors: str, **extra: str) -> dict[str, str]:
    named = "|".join(f"https://w3id.org/p/{each}" for each in ancestors)
    label = extra.pop("label", name.upper())
    return {"n": f"https://w3id.org/p/{name}", "label": label, "ancestors": named, "types": "", **extra}


def test_a_part_of_two_parents_at_different_depths_hangs_under_the_deeper_and_keeps_the_other() -> None:
    # the closure stated: X lies in A (below R) and in B (a root); R is no parent of X, only an ancestor
    rows = [row("r"), row("a", "r", label="Z"), row("b", label="A"), row("x", "r", "a", "b")]

    part = build_tree(rows, []).parts["https://w3id.org/p/x"]

    assert (part.parent, part.other_parents) == ("https://w3id.org/p/a", ("https://w3id.org/p/b",))


def test_a_part_stated_under_a_parent_and_its_grandparent_hangs_under_the_parent() -> None:
    # part of the closure stated: P lies in G, G in R; X is stated under G and P. G is P's ancestor,
    # so X's one parent is P, whatever the labels say
    rows = [row("r"), row("g", "r", label="A"), row("p", "g", label="Z"), row("x", "g", "p")]

    part = build_tree(rows, []).parts["https://w3id.org/p/x"]

    assert (part.parent, part.other_parents) == ("https://w3id.org/p/p", ())


def test_a_part_stated_under_its_direct_parent_alone_hangs_under_it() -> None:
    rows = [row("r"), row("a", "r"), row("x", "a")]

    tree = build_tree(rows, [])

    assert tree.parts["https://w3id.org/p/x"].parent == "https://w3id.org/p/a"
    assert tree.parts["https://w3id.org/p/a"].parent == "https://w3id.org/p/r"


def test_rhineland_palatinate_s_parts_follow_the_numbers_in_their_iris() -> None:
    # its parts have neither position nor number; the rows come in any order
    answers = frozen("rp")

    tree = build_tree(list(reversed(answers["closure"])), [])

    numbers = [int(root.iri.rsplit("/t", 1)[1]) for root in tree.roots]
    assert len(numbers) == 8 and numbers == sorted(numbers)


def test_numbers_are_ordered_as_numbers() -> None:
    rows = [row("a"), row("ten", "a", number="10"), row("nine", "a", number="9")]

    tree = build_tree(rows, [])

    assert [child.number for child in tree.roots[0].children] == ["9", "10"]


def test_a_part_s_references_come_after_its_parts_with_or_without_a_target() -> None:
    rows = [row("a"), row("b9", "a")]  # no position, no number, a larger IRI number than v1
    references = [
        {"x": "https://w3id.org/p/a", "v": "https://w3id.org/p/v1", "label": "V1", "types": ""},
        {"x": "https://w3id.org/p/a", "v": "https://w3id.org/p/v2", "label": "V2", "types": "",
         "target": "https://w3id.org/z/2|https://w3id.org/z/1"},
    ]  # fmt: skip

    children = build_tree(rows, references).roots[0].children

    assert [child.iri.rsplit("/", 1)[1] for child in children] == ["b9", "v1", "v2"]
    assert all(child.reference for child in children[1:]) and not children[0].reference
    assert (children[1].targets, children[2].targets) == (
        (),
        ("https://w3id.org/z/1", "https://w3id.org/z/2"),
    )


def test_a_reference_two_parts_hold_hangs_once_and_names_both_holders() -> None:
    rows = [row("a"), row("b")]
    references = [
        {"x": "https://w3id.org/p/b", "v": "https://w3id.org/p/v", "label": "V", "types": ""},
        {"x": "https://w3id.org/p/a", "v": "https://w3id.org/p/v", "label": "V", "types": ""},
    ]

    tree = build_tree(rows, references)

    reference = tree.parts["https://w3id.org/p/v"]
    assert reference.parent == "https://w3id.org/p/a"
    assert reference.holders == ("https://w3id.org/p/a", "https://w3id.org/p/b")
    assert len(walk(tree.roots)) == 3


def test_a_reference_that_is_a_part_stays_a_part_and_names_its_holder() -> None:
    rows = [row("a"), row("v", "a")]
    references = [{"x": "https://w3id.org/p/a", "v": "https://w3id.org/p/v", "label": "V", "types": "",
                   "target": "https://w3id.org/z"}]  # fmt: skip

    part = build_tree(rows, references).parts["https://w3id.org/p/v"]
    assert part.targets == ("https://w3id.org/z",)

    assert (part.parent, part.reference, part.holders) == (
        "https://w3id.org/p/a",
        False,
        ("https://w3id.org/p/a",),
    )


@pytest.mark.parametrize(
    ("rows", "references"),
    [
        ([row("a"), row("a")], []),
        ([row("a")], [{"x": "https://w3id.org/p/a", "v": "https://w3id.org/p/v"}] * 2),
    ],
    ids=["part", "reference"],
)
def test_a_row_given_twice_is_refused(rows: list[dict[str, str]], references: list[dict[str, str]]) -> None:
    # the pages matched their count, so a row given twice stands for one that is missing
    with pytest.raises(MemRefused, match="twice"):
        build_tree(rows, references)


@pytest.mark.parametrize(
    ("extra", "position", "number"),
    [
        ({"position": "--3"}, None, None),
        ({"position": "\u00b2"}, None, None),
        ({"position": "9" * 40}, None, None),
        ({"position": "-3"}, -3, None),
        ({"number": "\u00b2"}, None, "\u00b2"),
        ({"number": "9" * 5000}, None, "9" * 5000),
    ],
    ids=[
        "two-signs",
        "superscript-position",
        "long-position",
        "negative",
        "superscript-number",
        "long-number",
    ],
)
def test_a_position_or_number_of_another_shape_is_kept_as_text_or_left(
    extra: dict[str, str], position: int | None, number: str | None
) -> None:
    rows = [row("a"), row("b", "a", **extra), row("c", "a", number="1")]

    tree = build_tree(rows, [])

    part = tree.parts["https://w3id.org/p/b"]
    assert (part.position, part.number) == (position, number)


@pytest.mark.parametrize(
    "rows",
    [
        [row("a", "b", "c"), row("b", "a", "c"), row("c", "a", "b")],
        [row("a", "c", "b"), row("b", "a"), row("c", "b")],
        [row("r"), row("a", "r", "b", "c"), row("b", "r", "a", "c"), row("c", "r", "a", "b"),
         row("x", "r", "a", "b", "c")],
    ],
    ids=["closure-stated", "one-more-edge", "under-a-root"],
)  # fmt: skip
def test_parts_in_a_cycle_are_refused_however_their_ancestors_are_stated(rows: list[dict[str, str]]) -> None:
    with pytest.raises(MemRefused, match="cycle"):
        build_tree(rows, [])


def test_a_number_with_a_sign_is_ordered_as_text_after_the_numbers() -> None:
    rows = [row("a"), row("minus", "a", number="-1"), row("two", "a", number="2")]

    tree = build_tree(rows, [])

    assert [child.number for child in tree.roots[0].children] == ["2", "-1"]


def test_a_label_holds_no_sign_the_database_cannot_hold() -> None:
    # a NUL and a lone surrogate (JSON may spell one): the database refuses both in text
    rows = [row("a", label="Op\x00tik\ud800 und Licht")]

    assert build_tree(rows, []).parts["https://w3id.org/p/a"].label == "Optik und Licht"
