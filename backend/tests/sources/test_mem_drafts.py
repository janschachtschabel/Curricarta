"""A MEM plan's tree as the core's drafts (app/sources/mem/drafts.py, Teilplan M2-5b): every part once, as a
node or a statement by the rules, imported and proposed, with what MEM says of it; its wordings in the
document's order for the anchor search; statements at the top under a node of the plan's title."""

import json
from pathlib import Path
from typing import Any

from app.domain.l1 import AnchorDraft, NodeDraft
from app.sources.mem.classes import typed
from app.sources.mem.drafts import drafts_from, rows_in_order, rule_counts
from app.sources.mem.tree import MemPart, MemTree, build_tree
from tests.sources.test_mem_classes import rules

CV = "https://w3id.org/wlo/curriculum/vocab#"
LP = "https://w3id.org/lehrplan/ontology/"
FIXTURES = Path(__file__).parent / "fixtures" / "mem"
PLAN, TITLE = "https://w3id.org/p/plan", "Informatik 5-6"


def frozen(land: str) -> MemTree:
    answers: dict[str, Any] = json.loads((FIXTURES / f"{land}.json").read_text(encoding="utf-8"))
    return build_tree(answers["closure"], answers["references"])


def found_everywhere(tree: MemTree) -> dict[str, AnchorDraft]:
    keys = [row.key for row in rows_in_order(tree, rules(), PLAN, TITLE)]
    return {key: AnchorDraft(("p1-b1",), page_start=1) for key in keys}


def walk(nodes: tuple[NodeDraft, ...] | list[NodeDraft]) -> list[Any]:
    found: list[Any] = []
    for node in nodes:
        found.append(node)
        found.extend(node.statements)
        found.extend(walk(node.children))
    return found


def test_every_part_is_one_row_imported_and_proposed_with_its_mem_iri() -> None:
    for land in ("rp", "sn", "by", "be"):
        tree = frozen(land)

        drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

        rows = walk(drafts)
        iris = [row.mem.iri for row in rows if row.mem is not None]
        assert sorted(iris) == sorted(tree.parts), land
        assert {(row.origin, row.review_status) for row in rows} == {
            (CV + "orig_import", CV + "rev_proposed")
        }


def test_rows_come_in_the_document_s_order_a_node_before_its_parts() -> None:
    tree = frozen("sn")

    keys = [row.key for row in rows_in_order(tree, rules(), PLAN, TITLE)]

    def preorder(parts: list[MemPart]) -> list[str]:
        return [key for part in parts for key in (part.iri, *preorder(part.children))]

    assert keys == preorder(tree.roots)


def test_a_statement_s_addressee_and_a_reference_under_its_holder() -> None:
    tree = frozen("sn")

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    rows = walk(drafts)
    statements = [row for row in rows if not isinstance(row, NodeDraft)]
    assert statements and all(statement.addressees for statement in statements)
    references = [statement for statement in statements if statement.kind == CV + "kind_reference"]
    assert len(references) == 20  # the fixture's references, each a statement
    assert all(statement.addressees == (CV + "addr_educator",) for statement in references)
    holders = {node.mem.iri for node in rows if isinstance(node, NodeDraft) and node.mem is not None and any(
        statement.kind == CV + "kind_reference" for statement in node.statements)}  # fmt: skip
    assert holders <= {part.parent for part in tree.parts.values() if part.reference}


def test_each_row_takes_the_anchor_found_for_it() -> None:
    tree = frozen("rp")
    anchors = {key: AnchorDraft((f"p{n + 1}-b1",), page_start=n + 1) for n, key in enumerate(
        row.key for row in rows_in_order(tree, rules(), PLAN, TITLE))}  # fmt: skip

    drafts = drafts_from(tree, rules(), PLAN, TITLE, anchors)

    for row in walk(drafts):
        assert row.mem is not None and row.anchors == (anchors[row.mem.iri],)


def part(name: str, *classes: str, children: tuple[MemPart, ...] = (), **values: Any) -> MemPart:
    made = MemPart(
        f"https://w3id.org/p/{name}", values.pop("label", name), tuple(LP + c for c in classes), **values
    )
    made.children.extend(children)
    return made


def test_statements_at_the_top_hang_under_a_node_of_the_plan_s_title_searched_first() -> None:
    area = part("area", "LP_0000349")
    told = part("told", "LP_0000263")
    tree = MemTree({p.iri: p for p in (area, told)}, [told, area])

    rows = rows_in_order(tree, rules(), PLAN, TITLE)
    drafts = drafts_from(
        tree, rules(), PLAN, TITLE, {row.key: AnchorDraft(("p1-b1",), page_start=1) for row in rows}
    )

    assert (rows[0].key, rows[0].wording) == (PLAN, TITLE)
    holder = drafts[0]
    assert (holder.original_title, holder.function, holder.mem) == (TITLE, CV + "fn_area", None)
    assert [statement.verbatim for statement in holder.statements] == ["told"]
    assert [draft.mem.iri for draft in drafts[1:] if draft.mem] == [area.iri]


def test_what_mem_says_of_a_part_beyond_the_core_is_kept_clean() -> None:
    told = part("told", "LP_0000263", description="Be\x00schreibung", number="1.2", position=3,
                grades=("5", "6"), hours="12", other_parents=("https://w3id.org/p/x",))  # fmt: skip
    area = part("area", "LP_0000349", children=(told,))
    told.parent = area.iri
    tree = MemTree({area.iri: area, told.iri: told}, [area])

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    [statement] = drafts[0].statements
    assert statement.mem is not None and statement.mem.properties == {
        "description": "Beschreibung", "number": "1.2", "position": 3, "grades": ["5", "6"], "hours": "12",
        "other_parents": ["https://w3id.org/p/x"],
    }  # fmt: skip
    assert statement.mem.classes == (LP + "LP_0000263",)
    assert drafts[0].mem is not None and drafts[0].mem.properties == {}


def test_a_node_title_is_cut_to_what_a_node_holds_and_a_part_of_no_storable_iri_keeps_no_mem() -> None:
    area = part("area", "LP_0000349", label="T" * 2500)
    odd = MemPart("https://w3id.org/p/a b", "Seltsam", (LP + "LP_0000349",))
    tree = MemTree({area.iri: area, odd.iri: odd}, [area, odd])

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    assert drafts[0].original_title == "T" * 2000
    assert (drafts[1].original_title, drafts[1].mem) == ("Seltsam", None)


def test_the_rules_are_counted_part_by_part() -> None:
    tree = frozen("sn")

    counts = rule_counts(tree, rules())

    assert sum(counts.values()) == len(tree.parts)
    assert counts["reference"] == 20 and counts["unknown"] == 0


def test_a_statement_typed_by_its_cue_keeps_its_subkind() -> None:
    tree = frozen("sn")

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    statements = [row for row in walk(drafts) if not isinstance(row, NodeDraft)]
    told = {row.mem.iri: row.subkind for row in statements if row.mem is not None}
    assert told == {iri: typed(tree.parts[iri], rules()).subkind for iri in told}
    assert any(told.values())  # some typed by a cue to a subkind


def test_a_reference_with_parts_below_keeps_them_all() -> None:
    told = part("told", "LP_0000263")
    held = part("held", "LP_0030065", children=(told,))
    area = part("area", "LP_0000349", children=(held,))
    told.parent, held.parent = held.iri, area.iri
    tree = MemTree({p.iri: p for p in (area, held, told)}, [area])

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    assert sorted(row.mem.iri for row in walk(drafts) if row.mem) == sorted(tree.parts)
    # a Verweis the closure holds is a part in MEM: not one held alone
    [node] = [row for row in walk(drafts) if row.mem and row.mem.iri == held.iri]
    assert node.mem is not None and "held_only" not in node.mem.properties


def test_every_value_of_mem_is_kept_clean_lists_classes_and_pages_too() -> None:
    held = part("held", "LP_0030065", targets=("https://w3id.org/z/\x00a",), holders=("https://w3id.org/h\ud800",),
                reference=True, page="https://land.example/\x00p")  # fmt: skip
    area = part("area", "LP_0000349", children=(held,), grades=("5\x00",))
    held.parent = area.iri
    tree = MemTree({area.iri: area, held.iri: held}, [area])

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    [reference] = drafts[0].statements
    assert reference.mem is not None and reference.mem.properties == {
        "page": "https://land.example/p", "holders": ["https://w3id.org/h"], "targets": ["https://w3id.org/z/a"],
        "held_only": True,
    }  # fmt: skip
    assert drafts[0].mem is not None and drafts[0].mem.properties == {"grades": ["5"]}


def test_a_part_s_classes_number_and_hours_are_kept_clean_too() -> None:
    told = MemPart("https://w3id.org/p/told", "told", (LP + "LP_0000263", LP + "LP_9\x00"), number="1\x00.2",
                   hours="1\ud8002")  # fmt: skip
    area = part("area", "LP_0000349", children=(told,))
    told.parent = area.iri
    tree = MemTree({area.iri: area, told.iri: told}, [area])

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    [statement] = drafts[0].statements
    assert statement.mem is not None
    assert statement.mem.classes == (LP + "LP_0000263", LP + "LP_9")
    assert statement.mem.properties == {"number": "1.2", "hours": "12"}


def test_a_wording_is_cut_to_what_a_statement_holds() -> None:
    told = part("told", "LP_0000263", label="W" * 20_001)
    area = part("area", "LP_0000349", children=(told,))
    told.parent = area.iri
    tree = MemTree({area.iri: area, told.iri: told}, [area])

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    assert drafts[0].statements[0].verbatim == "W" * 20_000


def test_a_node_typed_by_its_cue_keeps_its_node_type() -> None:
    tree = frozen("rp")

    drafts = drafts_from(tree, rules(), PLAN, TITLE, found_everywhere(tree))

    types = {row.mem.iri: row.node_type for row in walk(drafts) if isinstance(row, NodeDraft) and row.mem}
    assert types == {iri: typed(tree.parts[iri], rules()).node_type for iri in types}
    assert any(types.values())
