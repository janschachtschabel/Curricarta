"""The worker's internal port: /health for the liveness probe, /metrics for Prometheus.

Served on the worker's own event loop, so /health answers only while the loop turns - a loop
held by a handler is what the probe is for. Nothing else is answered (404); the port is the
pod's INTERNAL_PORT, never released by the ingress.
"""

import asyncio
import contextlib
from collections.abc import Iterator

import uvicorn
from psycopg_pool import AsyncConnectionPool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.core import metrics


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _metrics(request: Request) -> Response:
    pool: AsyncConnectionPool | None = request.app.state.pool
    if pool is not None:  # the worker's own pool, as this scrape finds it
        metrics.observe_pool(pool.get_stats())
    content, content_type = metrics.render(request.headers.get("accept", ""))
    return Response(content=content, media_type=content_type)


class ProbeServer(uvicorn.Server):
    """uvicorn as the worker runs it: SIGTERM is the worker's, which first lets its job finish.
    uvicorn's own capture would take the signal and raise it again once it had stopped."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def start_serving(server: ProbeServer) -> asyncio.Task[None]:
    """Serve ``server``'s port and return once it answers; the task ends after
    ``server.should_exit``. A port in use ends the start (uvicorn's SystemExit)."""
    serving = asyncio.create_task(server.serve(sockets=[server.config.bind_socket()]))
    while not server.started:
        if serving.done():
            serving.result()  # its error
            raise RuntimeError("the probe server ended before it answered")
        await asyncio.sleep(0.01)
    return serving


def probe_server(
    host: str = "127.0.0.1", port: int = 0, *, pool: AsyncConnectionPool | None = None
) -> ProbeServer:
    """The server for ``host:port``; bind with ``server.config.bind_socket()`` and pass the
    socket to ``serve``, or pass one bound elsewhere. /metrics says ``pool``'s state, if given."""
    app = Starlette(routes=[Route("/health", _health), Route("/metrics", _metrics)])
    app.state.pool = pool
    # log_config=None: uvicorn's lines go through the service's handler (app.core.logging)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        http="h11",
        lifespan="off",
        access_log=False,
        log_config=None,
        server_header=False,
    )
    return ProbeServer(config)
