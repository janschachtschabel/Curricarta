"""The synthetic document of the Kern measurement (app/exports/measure_kern.py) with the second layer: as many
level assignments, time spans and workloads as asked, spread over nodes and statements, and rules,
assessments and placements a tenth of the nodes each (plan M3a L1) - which X5 takes without a violation, so
that the measurement times a document as the editors could freeze it; and the measurement's numbers."""

from collections import Counter

import pytest
from rdflib import RDF

from app.domain.l2 import Holder
from app.exports.kern_naming import frozen_naming
from app.exports.kern_rdf import CUR, kern_graph
from app.exports.measure_kern import BASE, measure, synthetic_rows
from app.pipeline.shacl_child import validate_graph
from tests.pipeline.test_shacl import ONTOLOGY


def counted(nodes: int, statements: int, values: int) -> Counter[str]:
    rows = synthetic_rows(nodes, statements, values=values)
    held = Counter[str]()
    for holder, kinds in rows.values.items():
        held[f"{holder.kind}.levels"] += len(kinds.levels)
        held[f"{holder.kind}.time_spans"] += len(kinds.time_spans)
        held[f"{holder.kind}.workloads"] += len(kinds.workloads)
    held.update(rules=len(rows.rules), assessments=len(rows.assessments), placements=len(rows.placements))
    return +held  # the kinds of none left out


def test_the_values_are_spread_over_nodes_and_statements() -> None:
    assert counted(20, 60, values=40) == {
        "node.levels": 20, "statement.levels": 20, "node.time_spans": 40, "node.workloads": 40,
        "assessment.levels": 2, "placement.time_spans": 2, "rules": 2, "assessments": 2, "placements": 2,
    }  # fmt: skip
    assert counted(20, 60, values=0) == {}  # as the measurement was before: the first layer alone


def test_the_document_with_values_passes_x5_and_names_its_rows_as_frozen() -> None:
    rows = synthetic_rows(20, 60, values=40)

    found = Counter(result.severity for result in validate_graph(ONTOLOGY, kern_graph(rows)))
    frozen = kern_graph(rows, frozen_naming())

    assert found["violation"] == 0, found
    kinds = (CUR.CompletionRule, CUR.Assessment, CUR.Placement)
    named = {str(subject) for kind in kinds for subject in frozen.subjects(RDF.type, kind)}
    assert {f"{BASE}/{name}" for name in ("rule-1", "assessment-1", "assessment-2", "placement-1")} <= named
    assert all(Holder("node", node["id"]) in rows.values for node in rows.nodes)


@pytest.mark.anyio
async def test_the_measurement_times_the_graph_x5_and_the_export() -> None:
    measured = await measure(2, 4, values=2)

    assert measured.statements == 4 and measured.values == 2
    assert min(measured.graph_s, measured.x5_s, measured.export_s, measured.seconds) > 0
    assert measured.turtle_bytes > 0 and 0 < measured.export_peak_mib <= measured.peak_mib
    assert measured.violations == 0
