"""HTTP metrics by route template, scraped on the internal port only."""

import threading
import time
from collections.abc import Iterator

import anyio
import psycopg
import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from psycopg_pool import AsyncConnectionPool
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app import __revision__, __version__
from app.api import internal as internal_api
from app.api.app import create_app
from app.api.internal import READY_TIMEOUT_S
from app.core.ids import new_id
from app.db.migrate import migrate
from tests.support import FAKE_DATABASE_URL, lock_held, make_settings, selector_client

PUBLIC = "http://testserver:8000"
INTERNAL = "http://testserver:9000"
REQUESTS = "curricarta_http_requests_total"
DURATION_COUNT = "curricarta_http_request_duration_seconds_count"


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def app() -> FastAPI:
    application = create_app(make_settings())
    # its database is unreachable: read just now, so a scrape here does not wait out the pool
    # (test_an_unreachable_database_leaves_the_scrape_answering_in_time does)
    application.state.queue_read_at = time.monotonic()

    async def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    application.add_api_route("/api/v1/items/{item_id}", item, tags=["system"])
    return application


@pytest.fixture
def public(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=PUBLIC) as client:
        yield client


@pytest.fixture
def internal(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=INTERNAL) as client:
        yield client


def test_metrics_answer_on_the_internal_port_in_the_text_format(internal: TestClient) -> None:
    response = internal.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert f"# TYPE {REQUESTS} counter" in response.text


def test_metrics_follow_the_scrapers_accept_header(internal: TestClient) -> None:
    response = internal.get("/metrics", headers={"Accept": "application/openmetrics-text; version=1.0.0"})

    assert response.headers["content-type"].startswith("application/openmetrics-text")
    assert response.text.endswith("# EOF\n")


def test_metrics_do_not_exist_on_the_public_port(public: TestClient) -> None:
    assert public.get("/metrics").status_code == 404


def test_a_request_is_counted_by_its_route_template(public: TestClient) -> None:
    labels = {"method": "GET", "route": "/api/v1/items/{item_id}"}
    before = sample(REQUESTS, status="200", **labels)
    durations = sample(DURATION_COUNT, **labels)

    public.get("/api/v1/items/42")
    public.get("/api/v1/items/43")

    assert sample(REQUESTS, status="200", **labels) == before + 2
    assert sample(DURATION_COUNT, **labels) == durations + 2
    assert sample(REQUESTS, method="GET", route="/api/v1/items/42", status="200") == 0


def test_a_path_no_route_takes_shares_one_label(public: TestClient) -> None:
    before = sample(REQUESTS, method="GET", route="unmatched", status="404")

    public.get("/api/v1/random-1")
    public.get("/api/v1/random-2")

    assert sample(REQUESTS, method="GET", route="unmatched", status="404") == before + 2


def test_an_invented_method_shares_one_label(public: TestClient) -> None:
    before = sample(REQUESTS, method="other", route="/api/v1/info", status="405")

    public.request("FOO", "/api/v1/info")

    assert sample(REQUESTS, method="other", route="/api/v1/info", status="405") == before + 1


def test_a_refused_internal_path_is_no_traffic_of_that_path(public: TestClient) -> None:
    before = sample(REQUESTS, method="GET", route="/health", status="404")
    unmatched = sample(REQUESTS, method="GET", route="unmatched", status="404")

    public.get("/health")

    assert sample(REQUESTS, method="GET", route="/health", status="404") == before
    assert sample(REQUESTS, method="GET", route="unmatched", status="404") == unmatched + 1


def test_a_scrape_is_not_counted(internal: TestClient) -> None:
    internal.get("/metrics")
    internal.get("/metrics")

    assert sample(REQUESTS, method="GET", route="/metrics", status="200") == 0


@pytest.fixture
def routed() -> Iterator[TestClient]:
    """Routers included the usual FastAPI ways: with a prefix, nested, and a mounted app."""
    application = create_app(make_settings())
    items = APIRouter()

    @items.get("/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    application.include_router(items, prefix="/api/v1/a", tags=["system"])
    application.include_router(items, prefix="/api/v1/b", tags=["system"])
    inner = APIRouter(prefix="/inner")

    @inner.get("/deep/{x}")
    async def deep(x: str) -> dict[str, str]:
        return {"x": x}

    outer = APIRouter(prefix="/api/v1/outer")
    outer.include_router(inner)
    application.include_router(outer, tags=["system"])

    async def hello(request: Request) -> PlainTextResponse:
        return PlainTextResponse(request.path_params["name"])

    application.mount("/files", Starlette(routes=[Route("/hello/{name}", hello)]))
    with TestClient(application, base_url=PUBLIC) as client:
        yield client


@pytest.mark.parametrize(
    ("path", "status", "route"),
    [
        ("/api/v1/a/items/1", "200", "/api/v1/a/items/{item_id}"),
        ("/api/v1/b/items/2", "200", "/api/v1/b/items/{item_id}"),
        ("/api/v1/outer/inner/deep/abc", "200", "/api/v1/outer/inner/deep/{x}"),
        ("/files/hello/bob", "200", "/files"),
        ("/files/nothing-here", "404", "/files"),
    ],
)
def test_the_label_is_the_full_template_of_the_route(
    routed: TestClient, path: str, status: str, route: str
) -> None:
    before = sample(REQUESTS, method="GET", route=route, status=status)

    routed.get(path)

    assert sample(REQUESTS, method="GET", route=route, status=status) == before + 1


def test_a_refused_metrics_path_counts_as_unmatched(public: TestClient) -> None:
    before = sample(REQUESTS, method="GET", route="unmatched", status="404")

    public.get("/metrics")

    assert sample(REQUESTS, method="GET", route="unmatched", status="404") == before + 1


def test_the_build_says_its_version_and_revision(internal: TestClient) -> None:
    text = internal.get("/metrics").text

    assert f'curricarta_build_info{{revision="{__revision__}",version="{__version__}"}} 1.0' in text


# The queue as the API reads it at a scrape: every replica says the same, the rules take the max
JOBS = "curricarta_queue_jobs"
READS_FAILED = "curricarta_queue_reads_failed_total"
READ_AT = "curricarta_queue_read_timestamp_seconds"


@pytest.fixture
def queue_url(database_url: str) -> str:
    migrate(database_url)
    return database_url


def add_job(url: str, kind: str) -> None:
    with psycopg.connect(url) as connection:
        connection.execute("INSERT INTO job_lane (lane) VALUES ('system') ON CONFLICT DO NOTHING")
        connection.execute("INSERT INTO job (id, kind, lane) VALUES (%s, %s, 'system')", (new_id(), kind))


def remove_jobs(url: str) -> None:
    with psycopg.connect(url) as connection:
        connection.execute("DELETE FROM job")


def scraping(url: str, **settings: object) -> TestClient:
    return selector_client(create_app(make_settings(database_url=url, **settings)), base_url=INTERNAL)


@pytest.fixture
def every_scrape_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(internal_api, "QUEUE_READ_EVERY_S", 0)


@pytest.mark.pg
@pytest.mark.usefixtures("every_scrape_reads")
def test_a_kind_without_jobs_reads_zero_not_its_last_value(queue_url: str) -> None:
    add_job(queue_url, "source.fetch")
    with scraping(queue_url) as client:
        client.get("/metrics")
        assert sample(JOBS, kind="source.fetch", status="queued") == 1
        remove_jobs(queue_url)

        client.get("/metrics")

    assert REGISTRY.get_sample_value(JOBS, {"kind": "source.fetch", "status": "queued"}) == 0
    assert REGISTRY.get_sample_value(JOBS, {"kind": "extract.run", "status": "running"}) == 0


@pytest.mark.pg
@pytest.mark.usefixtures("every_scrape_reads")
def test_a_kind_the_service_does_not_know_shares_one_label(queue_url: str) -> None:
    add_job(queue_url, "made.up")
    add_job(queue_url, "made.up_too")

    with scraping(queue_url) as client:
        client.get("/metrics")

    assert sample(JOBS, kind="other", status="queued") == 2
    assert REGISTRY.get_sample_value(JOBS, {"kind": "made.up", "status": "queued"}) is None


@pytest.mark.pg
@pytest.mark.usefixtures("every_scrape_reads")
def test_a_database_away_leaves_the_scrape_answering_with_the_last_values(queue_url: str) -> None:
    add_job(queue_url, "source.fetch")
    with scraping(queue_url) as client:
        client.get("/metrics")
        remove_jobs(queue_url)  # read now, it would say 0
        failed = sample(READS_FAILED)
        # another session holds the table: the read waits out its deadline, the scrape does not
        with lock_held(queue_url, "LOCK TABLE job IN ACCESS EXCLUSIVE MODE", at_most_s=READY_TIMEOUT_S + 3):
            started = time.monotonic()
            response = client.get("/metrics")
            elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < 3
    assert sample(JOBS, kind="source.fetch", status="queued") == 1
    assert sample(READS_FAILED) == failed + 1


@pytest.mark.pg
@pytest.mark.usefixtures("every_scrape_reads")
def test_the_time_of_the_last_read_moves_only_when_a_read_succeeds(
    queue_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the rules leave out a replica whose values are stale (deploy/alerts/curricarta.rules.yaml)
    monkeypatch.setattr(internal_api, "CLIENT_DEADLINE_S", 0.3)  # the failed read need not wait long
    with scraping(queue_url) as client:
        before = time.time()
        client.get("/metrics")
        read_at = sample(READ_AT)
        with lock_held(queue_url, "LOCK TABLE job IN ACCESS EXCLUSIVE MODE", at_most_s=READY_TIMEOUT_S + 3):
            client.get("/metrics")

    assert before <= read_at <= time.time()
    assert sample(READ_AT) == read_at


@pytest.mark.pg
@pytest.mark.usefixtures("every_scrape_reads")
def test_a_read_the_database_does_not_end_is_ended_by_the_scrape(
    queue_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a peer gone silent never answers, and the server's statement_timeout cannot reach the
    # client: the scrape bounds the read itself. A short bound stands in for it here, under the
    # server's own deadline, so the client's is the one that ends the read
    monkeypatch.setattr(internal_api, "CLIENT_DEADLINE_S", 0.3)
    with scraping(queue_url) as client:
        client.get("/metrics")  # the pool's connection is open
        failed = sample(READS_FAILED)
        with lock_held(queue_url, "LOCK TABLE job IN ACCESS EXCLUSIVE MODE", at_most_s=READY_TIMEOUT_S + 3):
            started = time.monotonic()
            response = client.get("/metrics")
            elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < 1
    assert sample(READS_FAILED) == failed + 1


def test_an_unreachable_database_leaves_the_scrape_answering_in_time() -> None:
    failed = sample(READS_FAILED)
    with scraping(FAKE_DATABASE_URL) as client:
        started = time.monotonic()
        response = client.get("/metrics")
        elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < 3
    assert sample(READS_FAILED) == failed + 1


@pytest.mark.pg
def test_scrapes_in_quick_succession_ask_the_database_once(queue_url: str) -> None:
    add_job(queue_url, "source.fetch")
    with scraping(queue_url) as client:
        client.get("/metrics")
        add_job(queue_url, "source.fetch")

        client.get("/metrics")

    assert sample(JOBS, kind="source.fetch", status="queued") == 1


@pytest.mark.pg
def test_the_pool_says_its_size_what_is_free_and_who_waits(queue_url: str) -> None:
    taken, release = threading.Event(), threading.Event()
    with scraping(queue_url, db_pool_max_size=1) as client:
        client.get("/metrics")  # its read of the queue opened the one connection, and gave it back
        client.get("/metrics")  # the pool as this scrape finds it
        assert (sample("curricarta_db_pool_size"), sample("curricarta_db_pool_available")) == (1, 1)
        assert sample("curricarta_db_pool_requests_waiting") == 0
        pool: AsyncConnectionPool = client.app.state.pool  # type: ignore[attr-defined]

        async def hold() -> None:
            async with pool.connection():
                taken.set()
                await anyio.to_thread.run_sync(release.wait)

        async def wait() -> None:
            async with pool.connection(timeout=10):
                pass

        holding = client.portal.start_task_soon(hold)  # type: ignore[union-attr]
        assert taken.wait(5)
        waiting = client.portal.start_task_soon(wait)  # type: ignore[union-attr]
        deadline = time.monotonic() + 5
        while pool.get_stats()["requests_waiting"] < 1 and time.monotonic() < deadline:
            time.sleep(0.01)

        client.get("/metrics")  # within the read's interval: no connection asked for
        seen = [sample(f"curricarta_db_pool_{name}") for name in ("size", "available", "requests_waiting")]
        release.set()
        holding.result(10)
        waiting.result(10)

    assert seen == [1, 0, 1]
