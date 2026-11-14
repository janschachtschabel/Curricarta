"""The job source.mem_catalog (app/sources/mem/catalog.py, plan M2 E11): every allowed graph's plans read
in pages into mem_plan, graph by graph; an endpoint away for now is asked again by another attempt, an
answer it cannot take ends the job. A mock transport stands in for the endpoint; the database is real."""

import dataclasses
import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx2
import pytest
from psycopg_pool import AsyncConnectionPool

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.db.mem_plans import find_plans
from app.db.migrate import migrate
from app.jobs.context import JobContext
from app.jobs.handlers import make_handlers
from app.jobs.outcome import PermanentError
from app.jobs.queue import Job, claim, enqueue
from app.sources.mem import catalog
from app.sources.mem.catalog import KIND, read_catalog
from app.sources.mem.sparql import GRAPHS, MemUnavailable
from tests.support import make_settings

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

LP = "https://w3id.org/lehrplan/ontology/"
RP, BISTA = "https://w3id.org/lehrplan/rp", "https://w3id.org/lehrplan/graph/bista"
ENDPOINT = "https://sparql.example.invalid/sparql"


def plan_row(name: str, **values: str) -> dict[str, str]:
    return {"p": f"https://w3id.org/p/{name}", "label": name, "classes": LP + "LP_0000438", **values}


def answer(rows: list[dict[str, str]], status: int = 200) -> httpx2.Response:
    bindings = [{key: {"type": "literal", "value": value} for key, value in row.items()} for row in rows]
    return httpx2.Response(status, json={"head": {"vars": []}, "results": {"bindings": bindings}})


class Endpoint:
    """The plans of each graph, answered as the endpoint would: a count, then pages by LIMIT/OFFSET."""

    def __init__(
        self, plans: Mapping[str, list[dict[str, str]]], status: int = 200, refused: str = ""
    ) -> None:
        self.plans = plans
        self.status = status
        self.refused = refused
        self.asked: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        query = parse_qs(request.content.decode())["query"][0]
        graph = [line[6:-1] for line in query.splitlines() if line.startswith("FROM <")][-1]
        self.asked.append(graph)
        if self.status != 200 or graph == self.refused:
            return answer([], self.status if self.status != 200 else 400)
        rows = sorted(self.plans.get(graph, []), key=lambda row: row["p"])
        if "COUNT" in query:
            return answer([{"count": str(len(rows))}])
        limit = int(query.rsplit("LIMIT ", 1)[1].split()[0])
        offset = int(query.rsplit("OFFSET ", 1)[1].split()[0])
        return answer(rows[offset : offset + limit])


@pytest.fixture
async def context(database_url: str, tmp_path: Path) -> AsyncIterator[JobContext]:
    migrate(database_url)
    async with AsyncConnectionPool(database_url, min_size=1, max_size=4, open=False) as pool:
        storage = AsyncStorage(FileSystemStorage(tmp_path / "store"))
        settings = make_settings(database_url=database_url, mem_sparql_url=ENDPOINT)
        yield JobContext(pool=pool, storage=storage, settings=settings)


async def a_job(context: JobContext) -> Job:
    async with context.pool.connection() as connection:
        await enqueue(connection, KIND, "admin", {})
        job = await claim(connection, "w1", [KIND], 60)
    assert job is not None
    return job


async def run(context: JobContext, endpoint: Endpoint) -> dict[str, Any]:
    return await read_catalog(context, await a_job(context), transport=httpx2.MockTransport(endpoint))


async def test_every_allowed_graph_s_plans_are_read_into_the_catalogue(context: JobContext) -> None:
    endpoint = Endpoint(
        {
            RP: [plan_row("Deutsch", land=LP + "LP_3000046")],
            BISTA: [plan_row("Mathe", classes=LP + "LP_0000571")],
        }
    )

    result = await run(context, endpoint)

    assert sorted(set(endpoint.asked)) == sorted(GRAPHS)
    async with context.pool.connection() as connection:
        found, total = await find_plans(connection)
    assert total == 2
    assert {(plan.graph, plan.title, plan.class_iri) for plan in found} == {
        (RP, "Deutsch", LP + "LP_0000438"),
        (BISTA, "Mathe", LP + "LP_0000571"),
    }
    assert all(ENDPOINT in (plan.attribution or "") for plan in found)
    assert result["graphs"][RP] == {"plans": 1, "removed": 0, "skipped": 0, "kept": 0, "mismatched": 0}
    assert json.loads(json.dumps(result)) == result  # the job's result is stored as JSON


async def test_a_graph_s_plans_are_read_in_pages(context: JobContext) -> None:
    endpoint = Endpoint({RP: [plan_row(f"{n:04}") for n in range(1203)]})

    await run(context, endpoint)

    async with context.pool.connection() as connection:
        _, total = await find_plans(connection)
    assert total == 1203
    assert endpoint.asked.count(RP) == 1 + 3  # the count, then three pages of 500


async def test_a_catalogue_read_again_drops_what_the_endpoint_holds_no_more(context: JobContext) -> None:
    await run(context, Endpoint({RP: [plan_row("Deutsch"), plan_row("Alt")]}))

    result = await run(context, Endpoint({RP: [plan_row("Deutsch")]}))

    async with context.pool.connection() as connection:
        found, _ = await find_plans(connection)
    assert [plan.title for plan in found] == ["Deutsch"]
    assert result["graphs"][RP]["removed"] == 1


async def test_a_plan_whose_iri_the_table_cannot_take_is_skipped_and_counted(context: JobContext) -> None:
    result = await run(
        context, Endpoint({RP: [plan_row("Deutsch"), {"p": "urn:x:1", "label": "x", "classes": ""}]})
    )

    assert result["graphs"][RP] == {"plans": 1, "removed": 0, "skipped": 1, "kept": 0, "mismatched": 0}


@pytest.mark.parametrize("before_last", [2, 1], ids=["first", "second"])
async def test_an_endpoint_busy_for_now_leaves_the_job_to_another_attempt(
    context: JobContext, before_last: int
) -> None:
    job = await a_job(context)
    attempt = dataclasses.replace(job, attempts=job.max_attempts - before_last)

    with pytest.raises(MemUnavailable):
        await read_catalog(context, attempt, transport=httpx2.MockTransport(Endpoint({}, status=503)))


async def test_an_endpoint_away_at_the_last_attempt_ends_the_job_unavailable(context: JobContext) -> None:
    # the interface words it, not "an unknown failure" (plan M2-8, A3)
    job = await a_job(context)
    last = dataclasses.replace(job, attempts=job.max_attempts)

    with pytest.raises(PermanentError) as ended:
        await read_catalog(context, last, transport=httpx2.MockTransport(Endpoint({}, status=503)))

    assert ended.value.code == "mem_unavailable"
    assert GRAPHS[0] in ended.value.message


async def test_an_answer_the_client_cannot_take_ends_the_job(context: JobContext) -> None:
    with pytest.raises(PermanentError) as ended:
        await run(context, Endpoint({}, status=400))

    assert ended.value.code == "mem_refused"


async def test_the_worker_s_handlers_take_the_catalogue(context: JobContext) -> None:
    assert KIND == "source.mem_catalog"
    assert KIND in make_handlers(context)


async def test_a_graph_that_answers_with_no_plans_keeps_the_ones_it_had(context: JobContext) -> None:
    # a store reloading a graph answers with none for a while: the catalogue keeps what it had and says so
    await run(context, Endpoint({RP: [plan_row("Deutsch")]}))

    result = await run(context, Endpoint({}))

    async with context.pool.connection() as connection:
        found, _ = await find_plans(connection)
    assert [plan.title for plan in found] == ["Deutsch"]
    assert result["graphs"][RP] == {"plans": 0, "removed": 0, "skipped": 0, "kept": 1, "mismatched": 0}


async def test_a_refused_graph_ends_the_job_after_the_others_are_read(context: JobContext) -> None:
    endpoint = Endpoint({RP: [plan_row("Deutsch")]}, refused=GRAPHS[0])

    with pytest.raises(PermanentError) as ended:
        await run(context, endpoint)

    assert ended.value.code == "mem_refused"
    assert f"{GRAPHS[0]}: the endpoint answered 400" in ended.value.message
    async with context.pool.connection() as connection:
        found, _ = await find_plans(connection)
    assert [plan.title for plan in found] == ["Deutsch"]  # RP comes after the refused BY


async def test_a_graph_whose_every_plan_is_skipped_keeps_the_ones_it_had(context: JobContext) -> None:
    await run(context, Endpoint({RP: [plan_row("Deutsch")]}))

    result = await run(context, Endpoint({RP: [{"p": "urn:x:1", "label": "x", "classes": ""}]}))

    async with context.pool.connection() as connection:
        found, _ = await find_plans(connection)
    assert [plan.title for plan in found] == ["Deutsch"]
    assert result["graphs"][RP] == {"plans": 0, "removed": 0, "skipped": 1, "kept": 1, "mismatched": 0}


async def test_a_plan_whose_graph_and_class_disagree_on_the_kmk_is_counted_and_logged(
    context: JobContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a Land's graph holding a Bildungsstandard: imported as a Lehrplan, exported as a standard (plan M2-7)
    warned: list[tuple[Any, ...]] = []
    monkeypatch.setattr(catalog.log, "warning", lambda *args: warned.append(args))

    result = await run(
        context, Endpoint({RP: [plan_row("Deutsch"), plan_row("Mathe", classes=LP + "LP_0000571")]})
    )

    assert result["graphs"][RP]["mismatched"] == 1
    assert [(args[1], args[2]) for args in warned] == [(1, RP)]


async def test_an_endpoint_away_at_the_last_attempt_names_the_graphs_refused_before(
    context: JobContext,
) -> None:
    class AwayAfterTheFirst(Endpoint):
        def __call__(self, request: httpx2.Request) -> httpx2.Response:
            first = f"FROM <{GRAPHS[0]}>" in parse_qs(request.content.decode())["query"][0]
            return answer([], 400 if first else 503)

    job = await a_job(context)
    last = dataclasses.replace(job, attempts=job.max_attempts)

    with pytest.raises(PermanentError) as ended:
        await read_catalog(context, last, transport=httpx2.MockTransport(AwayAfterTheFirst({})))

    assert ended.value.code == "mem_unavailable"
    assert f"{GRAPHS[1]}:" in ended.value.message and f"refused before - {GRAPHS[0]}" in ended.value.message
