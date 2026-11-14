"""``python -m app.quality.mem_report <document> --label <label> [--endpoint-counts]`` (plan H-3, A10): what
an import from the MEM endpoint found - its run's counts, the anchor search's hit rate by match kind, over all
rows and again without the title pages, its findings, the not-found wordings the fuzzy stage could not reach,
labels that are their IRI's tail and wordings cut. Imports are made as tests/jobs/test_mem_import.py makes
them, from the synthetic fixtures, against a stand-in endpoint. Never a title, a wording or a plan's IRI."""

import json
from typing import Any

import httpx2
import psycopg
import pytest

from app.conversion.base import Block
from app.db.mem_plans import record_import, replace_graph
from app.quality.closed import closed
from app.quality.mem_hits import hits
from app.quality.mem_report import Refused, mem_report
from tests.db.document_of import document_of
from tests.jobs.test_mem_import import (
    FROZEN,
    PLAN,
    Endpoint,
    a_job,
    an_import,
    answer,
    blocks,
    run,
    setup,
    with_contents,
)
from tests.quality.gold_documents import a_document

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, from test_mem_import

MARKER = "Kieselbachufer"  # the document's title: never in the report


def text_block(block: Block, text: str) -> Block:
    return block.model_copy(update={"text": text})


def at(made: list[Block], label: str) -> int:
    return next(n for n, block in enumerate(made) if block.text == label)


async def imported(
    context: Any, connection: psycopg.AsyncConnection, made: list[Block], frozen: Any = None
) -> Any:
    document = await document_of(connection, made)
    await replace_graph(connection, PLAN.graph, [PLAN])
    await record_import(connection, document.id, PLAN)
    await run(context, await a_job(connection, document), Endpoint(frozen=frozen))
    return document


async def report_of(context: Any, connection: psycopg.AsyncConnection, document: Any, **options: Any) -> Any:
    return await mem_report(
        connection, context.storage.sync, context.settings, document.id, "pilot-1", **options
    )


def test_hits_are_exact_to_normalized_and_the_title_pages_are_counted_apart() -> None:
    result = {
        "stages": {
            "node": {"exact": 5, "whitespace": 1, "elided": 1, "normalized": 1, "fuzzy": 2, "notFound": 1},
            "statement": {"exact": 3, "fuzzy": 1, "notFound": 2, "unsearched": 2},
        },
        "front": {"node": {"exact": 2}, "statement": {"exact": 1, "fuzzy": 1}},
    }

    made = hits(result)

    assert made["title_pages"] == "set_apart"
    assert made["strata"] == {
        "exact:node": 3, "whitespace:node": 1, "elided:node": 1, "normalized:node": 1, "fuzzy:node": 2,
        "notFound:node": 1, "front:node": 2,
        "exact:statement": 2, "notFound:statement": 2, "unsearched:statement": 2, "front:statement": 2,
    }  # fmt: skip
    assert made["all"]["node"] == {
        "rows": 11,
        "searched": 11,
        "hit": 8,
        "fuzzy": 2,
        "not_found": 1,
        "unsearched": 0,
        "hit_rate": 0.7273,
    }
    assert made["all"]["statement"] == {
        "rows": 8,
        "searched": 6,
        "hit": 3,
        "fuzzy": 1,
        "not_found": 2,
        "unsearched": 2,
        "hit_rate": 0.5,
    }
    assert made["all"]["rows"]["hit_rate"] == 0.6471  # 11 of 17 searched
    # without the title pages: their rows out of the numerator and the denominator alike
    assert made["without_front"]["node"] == {
        "rows": 9,
        "searched": 9,
        "hit": 6,
        "fuzzy": 2,
        "not_found": 1,
        "unsearched": 0,
        "hit_rate": 0.6667,
    }
    assert made["without_front"]["statement"] == {
        "rows": 6,
        "searched": 4,
        "hit": 2,
        "fuzzy": 0,
        "not_found": 2,
        "unsearched": 2,
        "hit_rate": 0.5,
    }
    assert made["without_front"]["rows"]["hit_rate"] == 0.6154  # 8 of 13


async def test_an_import_s_hit_rate_is_read_from_its_run(in_process_shacl: None, setup: Any) -> None:
    context, connection = setup
    made = with_contents()
    # the plan's statement on the cover alone, spaced apart; one node's title nowhere
    statement = 3 + next(n for n, row in enumerate(FROZEN["closure"]) if row["types"].endswith("/LP_0000432"))
    made[0] = text_block(made[0], made[statement].text.replace(" ", "  ", 1))
    made[statement] = text_block(made[statement], "Vorwort")
    made[at(made, "Reihe")] = text_block(made[at(made, "Reihe")], "Nachwort")
    document = await imported(context, connection, made)

    report = await report_of(context, connection, document)

    assert report["import"]["front"] == {"statement": {"whitespace": 1}}
    found = report["hits"]
    assert found["title_pages"] == "set_apart"
    assert found["strata"] == {"exact:node": 7, "notFound:node": 1, "front:statement": 1}
    assert (found["all"]["rows"]["searched"], found["all"]["rows"]["hit"]) == (9, 8)
    assert found["all"]["rows"]["hit_rate"] == 0.8889
    assert (found["without_front"]["rows"]["searched"], found["without_front"]["rows"]["hit"]) == (8, 7)
    assert found["without_front"]["rows"]["hit_rate"] == 0.875
    assert report["findings"]["x5.import_not_found"] == 1 and report["shacl"] == "done"
    assert report["run"]["search_budget_s"] == context.settings.mem_search_budget_s
    assert report["run"]["lease_s"] == context.settings.job_lease_s
    assert 0 <= report["run"]["duration_s"] < 60


async def test_an_import_whose_contents_were_not_found_says_so(in_process_shacl: None, setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())

    report = await report_of(context, connection, document)

    assert report["import"]["front"] is None
    assert report["hits"]["title_pages"] == "unknown"
    assert report["hits"]["without_front"] is None  # no figure without title pages: never the one over all
    assert report["hits"]["all"]["rows"]["hit_rate"] == 1.0
    assert not [stratum for stratum in report["hits"]["strata"] if stratum.startswith("front:")]


async def test_a_wording_whose_rarest_word_stands_too_often_is_counted(
    in_process_shacl: None, setup: Any
) -> None:
    context, connection = setup
    made = blocks()
    # "Vorgang Muster" nowhere as such, each word more often than the fuzzy stage tries places;
    # "Reihe" nowhere
    first = at(made, "Vorgang Muster")
    made[first] = text_block(made[first], " ".join(["Muster"] * 40))
    made[at(made, "Reihe")] = text_block(made[at(made, "Reihe")], " ".join(["Vorgang"] * 40))
    document = await imported(context, connection, made)

    report = await report_of(context, connection, document)

    assert report["hits"]["strata"]["notFound:node"] == 2
    assert report["rare_word_hidden"] == 1


async def test_the_report_names_no_plan_title_and_no_wording(in_process_shacl: None, setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)
    await connection.execute("UPDATE document SET title = %s WHERE id = %s", (MARKER, document.id))
    await run(context, await a_job(connection, document), Endpoint())

    report = await report_of(context, connection, document)

    printed = json.dumps(report, ensure_ascii=False)
    words = {word for row in FROZEN["closure"] for word in row["label"].split() if len(word) > 3}
    assert words and not [word for word in words if word in printed]
    assert MARKER not in printed and PLAN.title.split()[0] not in printed
    assert "example.org" not in printed and str(document.id) not in printed
    closed(report)  # counts, rates and codes alone


async def test_a_document_that_is_no_import_is_refused(setup: Any) -> None:
    context, connection = setup
    document = await a_document(connection)

    with pytest.raises(Refused) as refused:
        await report_of(context, connection, document)

    assert refused.value.code == "not_an_import"


def failing(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"the endpoint was asked: {request.url}")


async def test_without_the_switch_the_endpoint_is_never_asked(in_process_shacl: None, setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())

    report = await report_of(context, connection, document, transport=httpx2.MockTransport(failing))

    assert "endpoint" not in report


async def test_with_the_switch_the_endpoint_counts_the_label_shapes(
    in_process_shacl: None, setup: Any
) -> None:
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())
    asked: list[str] = []

    def counting(request: httpx2.Request) -> httpx2.Response:
        asked.append(request.content.decode())
        return answer([{"measure": "label_de", "count": "7"}, {"measure": "typed_hours", "count": "2"}])

    report = await report_of(
        context, connection, document, endpoint_counts=True, transport=httpx2.MockTransport(counting)
    )

    assert len(asked) == 1
    assert report["endpoint"] == {
        "label_de": 7, "label_untagged": 0, "label_other_language": 0, "pref_label_only": 0,
        "typed_number": 0, "typed_hours": 2, "typed_grade": 0,
    }  # fmt: skip


@pytest.mark.parametrize(("status", "code"), [(503, "mem_unavailable"), (400, "mem_refused")])
async def test_an_endpoint_away_or_refusing_is_refused(
    in_process_shacl: None, setup: Any, status: int, code: str
) -> None:
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())

    def answering(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status)

    with pytest.raises(Refused) as refused:
        await report_of(
            context, connection, document, endpoint_counts=True, transport=httpx2.MockTransport(answering)
        )

    assert refused.value.code == code
