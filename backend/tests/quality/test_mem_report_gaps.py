"""What the MEM import's report counts from the plan's answers kept under the run (app/quality/
mem_report.py): labels that are their IRI's tail and wordings cut - unknown where the answers are gone
from the store, and the cuts where the catalogue names the plan no more, which the endpoint is then not
asked for."""

from pathlib import Path
from typing import Any

import pytest

from app.db.mem_plans import replace_graph
from app.quality.mem_report import Refused
from app.sources.mem.drafts import MAX_TITLE, MAX_WORDING
from tests.jobs.test_mem_import import FROZEN, PLAN, Endpoint, a_job, an_import, blocks, run, setup
from tests.quality.test_mem_report import imported, report_of

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, from test_mem_import


async def test_labels_that_are_their_iri_s_tail_and_wordings_cut_are_counted(
    in_process_shacl: None, setup: Any
) -> None:
    context, connection = setup
    closure = [dict(row) for row in FROZEN["closure"]]
    closure[0]["label"] = ""  # a node of no label: titled by its IRI's tail
    closure[1]["label"] = " ".join(["Muster"] * (MAX_TITLE // 6))  # a node's title past its bound
    closure[8]["label"] = " ".join(["Muster"] * (MAX_WORDING // 6))  # the statement's wording past its own
    document = await imported(context, connection, blocks(), {**FROZEN, "closure": closure})

    report = await report_of(context, connection, document)

    assert report["label_is_iri_tail"] == 1
    assert report["cut"] == {"titles": 1, "wordings": 1}


async def test_the_plan_s_answers_gone_from_the_store_leave_their_counts_unknown(
    in_process_shacl: None, setup: Any, tmp_path: Path
) -> None:
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())
    for kept in (tmp_path / "store" / "runs").glob("*/im/1.json"):
        kept.unlink()

    report = await report_of(context, connection, document)

    assert (report["label_is_iri_tail"], report["cut"]) == (None, None)
    assert report["hits"]["all"]["rows"]["searched"] == 9  # the run's result is in the database


async def test_a_plan_gone_from_the_catalogue_is_not_asked_for(in_process_shacl: None, setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())
    await replace_graph(connection, PLAN.graph, [])

    report = await report_of(context, connection, document)
    with pytest.raises(Refused) as refused:
        await report_of(context, connection, document, endpoint_counts=True)

    assert report["cut"] is None and refused.value.code == "unknown_plan"
