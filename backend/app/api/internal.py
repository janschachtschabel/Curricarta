"""Paths for the cluster: probes and metrics, answered on the internal port only.

The ingress releases the public port; the internal one stays inside the cluster. On the public
port an internal path answers 404 as if it did not exist, also with a trailing slash (the
router's redirect would otherwise confirm it) and under a root path.
"""

import asyncio
import logging
import time

import psycopg
from fastapi import APIRouter, Request, Response
from psycopg_pool import AsyncConnectionPool, PoolTimeout
from starlette.datastructures import State
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.errors import error_response
from app.api.paths import route_path
from app.core import metrics
from app.db.migrate import applied_versions
from app.jobs.queue import queue_depth

METRICS_PATH = "/metrics"
INTERNAL_PATHS = frozenset({"/health", "/ready", METRICS_PATH})
READY_TIMEOUT_S = 2.0  # a probe has a short deadline of its own; waiting longer helps nobody
# The whole wait, bounded in the process as well: statement_timeout is the server's, and a peer
# gone silent (packets dropped) would hold a probe or a scrape until TCP gives up. The pool's wait
# and the statement's, each READY_TIMEOUT_S, fit in it
CLIENT_DEADLINE_S = 2 * READY_TIMEOUT_S
# Scrapes come every few seconds, from more than one Prometheus; the job table is asked at most this
# often per process, and a queue that stalls takes minutes to matter
QUEUE_READ_EVERY_S = 15.0

log = logging.getLogger(__name__)
# Set in the scope of a request refused here: the metrics count it unmatched, not as traffic of the path
REFUSED_INTERNAL = "curricarta.refused_internal"

router = APIRouter(include_in_schema=False)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process answers. The database is a matter for /ready."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: the database answers and has every migration this code expects.

    A database ahead of the code is ready: during a rolling update the new release has
    migrated while the old pods still serve (migrations add before they remove).
    """
    pool: AsyncConnectionPool = request.app.state.pool
    try:
        async with asyncio.timeout(CLIENT_DEADLINE_S), pool.connection(timeout=READY_TIMEOUT_S) as connection:
            await _with_deadline(connection)
            applied = await applied_versions(connection)
    except (PoolTimeout, psycopg.Error, TimeoutError):
        return _unavailable("database")
    if not request.app.state.expected_migrations <= applied:
        return _unavailable("migration")
    return JSONResponse({"status": "ready"})


async def _with_deadline(connection: psycopg.AsyncConnection) -> None:
    """The transaction's queries get the probe's deadline, local to it: a locked or busy database
    must not hold a probe or a scrape, nor a pool connection per waiting one."""
    deadline = f"{int(READY_TIMEOUT_S * 1000)}ms"
    await connection.execute("SELECT set_config('statement_timeout', %s, true)", (deadline,))


def _unavailable(reason: str) -> JSONResponse:
    return JSONResponse({"status": "unavailable", "reason": reason}, status_code=503)


@router.get(METRICS_PATH)
async def scrape(request: Request) -> Response:
    """The process's metrics; with them the pool as it is now and the queue as last read."""
    metrics.observe_pool(request.app.state.pool.get_stats())
    await _read_queue(request.app.state)
    content, content_type = metrics.render(request.headers.get("accept", ""))
    return Response(content=content, media_type=content_type)


async def _read_queue(state: State) -> None:
    """The queue's gauges, read anew at most every QUEUE_READ_EVERY_S. A failed read leaves the last
    values and counts the failure; the scrape answers all the same."""
    now = time.monotonic()
    if state.queue_read_at is not None and now - state.queue_read_at < QUEUE_READ_EVERY_S:
        return
    # stamped before the read: a scrape beside it does not ask as well, a failed one waits its turn
    state.queue_read_at = now
    pool: AsyncConnectionPool = state.pool
    try:
        async with asyncio.timeout(CLIENT_DEADLINE_S), pool.connection(timeout=READY_TIMEOUT_S) as connection:
            await _with_deadline(connection)
            depth = await queue_depth(connection)
    except (PoolTimeout, psycopg.Error, TimeoutError) as error:
        metrics.QUEUE_READS_FAILED.inc()
        log.warning("could not read the queue for the metrics: %s", type(error).__name__)
        return
    metrics.observe_queue(depth, state.job_kinds)


def is_internal(path: str) -> bool:
    return path.rstrip("/") in INTERNAL_PATHS


class InternalOnly:
    """ASGI middleware: 404 for an internal path asked on any port but ``port``."""

    def __init__(self, app: ASGIApp, port: int) -> None:
        self.app = app
        self.port = port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and is_internal(route_path(scope)) and _server_port(scope) != self.port:
            scope[REFUSED_INTERNAL] = True
            await error_response(404)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _server_port(scope: Scope) -> int | None:
    """The port of the socket the request came in on, not what a proxy or the Host header says.

    ``None`` without a server or on a unix socket, whose port ASGI leaves ``None``.
    """
    server = scope.get("server")
    return int(server[1]) if server and server[1] is not None else None
