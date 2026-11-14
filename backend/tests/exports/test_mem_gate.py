"""The gate of a MEM export (app/exports/mem_gate.py, plan M2-6, E10): the MEM shapes' violations of the
export's graph, each naming its row; a document of no class known refused, as no shape would target it.
Saxony's frozen plan, imported as the import's drafts make it, meets the shapes; each shape has rows to
check there. The KMK's frozen plan (plan M2-7) meets them too, though none targets a row of it; a
competence area made up beside it shows the Bereich shape at work. The shapes run in this process, as the
child runs them (app/pipeline/shacl_child.py)."""

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from rdflib import RDF, RDFS, URIRef

from app.domain.l1 import AnchorDraft, NodeDraft
from app.exports.mem_gate import Violation, violations
from app.exports.mem_rows import MemRows
from app.exports.mem_ttl import MemExport, mem_graph
from app.pipeline.shacl_child import ShaclResult, validate_graph
from app.sources.mem.classes import MemModel, MemRules, model_from
from app.sources.mem.drafts import drafts_from, rows_in_order
from app.sources.mem.rules_db import mem_files
from app.sources.mem.tree import build_tree
from tests.sources.test_mem_classes import kmk_rules, rules
from tests.support import ONTOLOGY

LP = "https://w3id.org/lehrplan/ontology/"
CV = "https://w3id.org/wlo/curriculum/vocab#"
DOC = "https://example.org/kk/doc/de-sn/lp/1"
SAXONY: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "sources" / "fixtures" / "mem" / "sn.json").read_text(encoding="utf-8")
)


@cache
def model() -> MemModel:
    return model_from(*mem_files(ONTOLOGY))


def document(**columns: Any) -> dict[str, Any]:
    return {
        "id": uuid4(), "iri": DOC, "title": "Lehrplan Informatik", "rights_status": "unklar",
        "frozen_at": datetime(2026, 11, 1, tzinfo=UTC), "mem_iri": SAXONY["plan"],
        "mem_land_iri": LP + "LP_3000014", "mem_class_iri": LP + "LP_0000438", "mem_subjects": [],
        "mem_school_types": [], "mem_licence": None, "mem_attribution": "MEM-Schule",
    } | columns  # fmt: skip


def imported(frozen: dict[str, Any] | None = None, typing: MemRules | None = None, **columns: Any) -> MemRows:
    """A plan - Saxony's - as the import writes it and a freeze names it: every row an IRI of its own."""
    frozen = SAXONY if frozen is None else frozen
    typing = rules() if typing is None else typing
    tree = build_tree(frozen["closure"], frozen["references"])
    keys = [row.key for row in rows_in_order(tree, typing, frozen["plan"], "Lehrplan Informatik")]
    drafts = drafts_from(tree, typing, frozen["plan"], "Lehrplan Informatik",
                         {key: AnchorDraft(("p1-b1",), page_start=1) for key in keys})  # fmt: skip
    nodes: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []

    def walk(node: NodeDraft, parent: Any, position: int) -> None:
        made = uuid4()
        nodes.append({
            "id": made, "parent_id": parent, "position": position, "iri": f"{DOC}/n{len(nodes)}",
            "origin_iri": node.origin, "review_status_iri": node.review_status, "function_iri": node.function,
            "node_type_iri": node.node_type, "original_title": node.original_title,
            "title_language": node.title_language, "code": node.code,
            "mem_iri": node.mem.iri if node.mem else None,
            "mem_classes": list(node.mem.classes) if node.mem else [],
            "mem_properties": dict(node.mem.properties) if node.mem else {},
        })  # fmt: skip
        for at, statement in enumerate(node.statements, start=1):
            statements.append({
                "id": uuid4(), "node_id": made, "position": at, "iri": f"{DOC}/s{len(statements)}",
                "origin_iri": statement.origin, "verbatim": statement.verbatim,
                "language": statement.language,
                "statement_kind_iri": statement.kind, "subkind_iri": statement.subkind,
                "mem_iri": statement.mem.iri if statement.mem else None,
                "mem_classes": list(statement.mem.classes) if statement.mem else [],
                "mem_properties": dict(statement.mem.properties) if statement.mem else {},
            })  # fmt: skip
        for at, child in enumerate(node.children, start=1):
            walk(child, made, at)

    for at, root in enumerate(drafts, start=1):
        walk(root, None, at)
    return MemRows(document(**columns), nodes, statements)


def gated(rows: MemRows) -> tuple[MemExport, list[Violation]]:
    export = mem_graph(rows, model())
    return export, violations(validate_graph(ONTOLOGY, export.graph, shapes="mem"), export)


def targets(export: MemExport, base: str) -> int:
    """How many subjects a shape of ``base`` targets: their types reach it through the chain."""
    chain = model()
    return sum(
        any(klass == base or base in chain.chain_bases.get(klass, frozenset()) for klass in
            {str(found) for found in export.graph.objects(subject, RDF.type)})
        for subject in set(export.graph.subjects(RDF.type, None))
    )  # fmt: skip


def test_saxony_s_plan_as_exported_meets_the_mem_shapes() -> None:
    export, found = gated(imported())

    assert found == []
    assert len(set(export.graph.subjects(RDFS.label, None))) == len(SAXONY["closure"]) + 20 + 1


def test_each_shape_has_rows_to_check_and_the_textual_entity_none() -> None:
    export, _ = gated(imported())

    assert targets(export, LP + "LP_0000349") > 0  # Bereich
    assert targets(export, LP + "LP_0000438") == 1  # Lehrplan: the document
    assert targets(export, LP + "LP_0030065") == 20  # Verweis: the fixture's references
    assert targets(export, "http://purl.obolibrary.org/obo/IAO_0000300") == 0  # known empty: lp: classes only


def test_a_reference_mem_names_no_target_of_breaks_its_shape_at_its_row() -> None:
    rows = imported()
    reference = next(row for row in rows.statements if row["statement_kind_iri"] == CV + "kind_reference")
    reference["mem_properties"] = {key: value for key, value in reference["mem_properties"].items()
                                   if key != "targets"}  # fmt: skip

    _, found = gated(rows)

    assert [(each.focus, each.row_kind, each.row_id, each.shape) for each in found] == [
        (reference["mem_iri"], "statement", reference["id"], "VerweisShape")
    ]
    assert found[0].path is not None and found[0].message


def test_a_plan_without_its_land_breaks_the_lehrplan_shape_at_the_document() -> None:
    rows = imported(mem_land_iri=None)

    _, found = gated(rows)

    assert [(each.focus, each.row_kind, each.shape) for each in found] == [
        (DOC, "document", "LPBundeslandShape")
    ]


def test_a_document_of_no_class_known_is_refused_rather_than_checked_by_no_shape() -> None:
    rows = imported(mem_class_iri=None)

    _, found = gated(rows)

    assert [(each.focus, each.row_kind, each.shape) for each in found] == [(DOC, "document", "DocumentClass")]


def test_a_warning_is_no_violation() -> None:
    export = mem_graph(imported(), model())
    warning = validate_graph(ONTOLOGY, export.graph, shapes="mem")  # none: the shapes know violations alone
    fake = [result._replace(severity="warning") for result in validate_graph(
        ONTOLOGY, mem_graph(imported(mem_land_iri=None), model()).graph, shapes="mem")]  # fmt: skip

    assert warning == [] and fake and violations(fake, export) == []


def test_violations_of_one_shape_with_a_path_and_without_one_are_ordered() -> None:
    export = mem_graph(imported(), model())
    results = [
        ShaclResult(DOC, "XShape", "violation", "lp:LP_0000029", "fehlt", None, "MinCount"),
        ShaclResult(DOC, "XShape", "violation", None, "Knoten", None, "Node"),
    ]

    found = violations(results, export)

    assert [each.path for each in found] == [None, "lp:LP_0000029"]


def test_a_reference_the_editors_made_does_not_lock_the_export() -> None:
    rows = imported()
    node = rows.nodes[0]
    rows.statements.append({
        "id": uuid4(), "node_id": node["id"], "position": 999, "iri": f"{DOC}/neu",
        "origin_iri": CV + "orig_human",
        "verbatim": "Siehe Kapitel 3.", "language": "de", "statement_kind_iri": CV + "kind_reference",
        "subkind_iri": None, "mem_iri": None, "mem_classes": [], "mem_properties": {},
    })  # fmt: skip

    _, found = gated(rows)

    assert found == []


KMK: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "sources" / "fixtures" / "mem" / "kmk.json").read_text(encoding="utf-8")
)
STANDARDS = LP + "LP_0000571"  # Bildungsstandard


def kmk_imported(frozen: dict[str, Any] = KMK, **columns: Any) -> MemRows:
    kmk = {"mem_iri": frozen["plan"], "mem_class_iri": STANDARDS, "mem_land_iri": None}
    return imported(frozen, kmk_rules(), **(kmk | columns))


def with_area(*classes: str) -> dict[str, Any]:
    """The KMK's plan with a competence area MADE UP for the test (the frozen plan has none) above three of
    its standards."""
    area = KMK["plan"] + "made-up-area"
    closure = [dict(row) for row in KMK["closure"]]
    for row in closure[:3]:
        row["ancestors"] = f"{KMK['plan']}|{area}"
    made = {"ancestors": KMK["plan"], "grades": "", "label": "Kompetenzbereich (erfunden)", "n": area,
            "types": "|".join(LP + klass for klass in classes)}  # fmt: skip
    return KMK | {"closure": [made, *closure]}


def test_the_kmk_s_plan_as_exported_meets_the_mem_shapes_as_a_standard_of_no_land() -> None:
    export, found = gated(kmk_imported())

    assert found == []
    assert {str(klass) for klass in export.graph.objects(URIRef(DOC), RDF.type)} == {STANDARDS}


def test_no_shape_targets_a_row_of_the_kmk_s_plan() -> None:
    # known: a flat plan of standards, no area, no reference; the document is no Lehrplan
    export, _ = gated(kmk_imported())

    for base in ("LP_0000349", "LP_0000438", "LP_0030065"):
        assert targets(export, LP + base) == 0, base
    assert targets(export, "http://purl.obolibrary.org/obo/IAO_0000300") == 0


def test_a_kmk_competence_area_is_checked_by_the_bereich_shape() -> None:
    rows = kmk_imported(with_area("LP_0000261", "LP_0000349", "LP_0000536", "LP_0030263"))

    export, found = gated(rows)

    assert found == []
    assert targets(export, LP + "LP_0000349") == 1


def test_a_kmk_competence_area_part_of_nothing_breaks_the_bereich_shape_at_its_row() -> None:
    rows = kmk_imported(with_area("LP_0000261", "LP_0000349", "LP_0000536", "LP_0030263"))
    area = next(row for row in rows.nodes if row["mem_iri"] == KMK["plan"] + "made-up-area")
    area["mem_properties"] = {**area["mem_properties"], "held_only": True}

    _, found = gated(rows)

    assert [(each.focus, each.row_kind, each.row_id, each.shape) for each in found] == [
        (area["mem_iri"], "node", area["id"], "BereichShape")
    ]


def test_a_bista_area_of_no_superclass_gets_the_bereich_class_beside() -> None:
    # LP_0030264 has none in lp.ttl: the table's base class makes it a Bereich the shape checks
    rows = kmk_imported(with_area("LP_0030264"))

    export, found = gated(rows)

    assert found == []
    assert LP + "LP_0000349" in {
        str(klass) for klass in export.graph.objects(URIRef(KMK["plan"] + "made-up-area"), RDF.type)
    }
    assert targets(export, LP + "LP_0000349") == 1


def test_a_kmk_plan_typed_a_lehrplan_needs_its_land() -> None:
    # the control: as a Lehrplan the document of no land breaks the Lehrplan shape
    _, found = gated(kmk_imported(mem_class_iri=LP + "LP_0000438"))

    assert [(each.row_kind, each.shape) for each in found] == [("document", "LPBundeslandShape")]
