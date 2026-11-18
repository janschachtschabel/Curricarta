"""One uvicorn process answers on two real sockets: the public port and the internal one."""

import gc
import io
import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from uvicorn.config import STARTUP_FAILURE

from app import serve
from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db.migrate import migrate
from app.serve import build_server, main
from tests.llm.test_client import llm_settings
from tests.support import FAKE_DATABASE_URL, FAKE_PEPPER, make_settings, without_settings_variables

START_TIMEOUT_S = 10.0


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def status_of(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - fixed local URL
            status: int = response.status
            return status
    except urllib.error.HTTPError as error:
        # an error's answer holds its connection open until it is closed
        with error:
            return error.code


@dataclass
class Running:
    settings: Settings
    log: io.StringIO


def two_free_ports() -> tuple[int, int]:
    public = free_port()
    internal = free_port()
    while internal == public:
        internal = free_port()
    return public, internal


def exclusive_socket_on(port: int) -> socket.socket:
    """Bound exclusively to ``port``: fails while any other socket holds it."""
    sock = socket.socket()
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", port))
    return sock


def exclusive_socket() -> socket.socket:
    """A listening socket no other socket may share - also not one with SO_REUSEADDR on Windows."""
    blocker = exclusive_socket_on(0)
    blocker.listen()
    return blocker


def close_uvicorn_s_unbound_socket(error: BaseException) -> None:
    """uvicorn's bind_socket ends the start with SystemExit and leaves the socket it could not bind
    open (uvicorn/config.py); closed here, or its ResourceWarning lands in whichever test runs when the
    traceback holding it is collected."""
    binds = [
        frame for frame, _ in traceback.walk_tb(error.__traceback__) if frame.f_code.co_name == "bind_socket"
    ]
    assert len(binds) == 1, "uvicorn's start no longer fails in bind_socket"
    unbound = binds[0].f_locals["sock"]
    assert isinstance(unbound, socket.socket)
    unbound.close()


@contextmanager
def serving(settings: Settings) -> Iterator[None]:
    """The real server of ``settings`` in a thread, stopped and checked afterwards."""
    server, sockets = build_server(settings)
    thread = threading.Thread(target=server.run, kwargs={"sockets": sockets}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + START_TIMEOUT_S
        while not server.started:
            assert time.monotonic() < deadline, "server did not start"
            time.sleep(0.02)
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=START_TIMEOUT_S)
    assert not thread.is_alive(), "server did not stop"


@pytest.fixture
def running(restore_logging: None) -> Iterator[Running]:
    log = io.StringIO()
    configure_logging("INFO", "json", stream=log)
    public_port, internal_port = two_free_ports()
    settings = make_settings(
        host="127.0.0.1", public_port=public_port, internal_port=internal_port, root_path="/curricarta"
    )
    with serving(settings):
        yield Running(settings, log)


@pytest.mark.pg
def test_the_real_server_reaches_a_migrated_database(database_url: str, restore_logging: None) -> None:
    # psycopg's async mode needs the selector loop the server sets; Windows' default refuses it
    migrate(database_url)
    configure_logging("INFO", "json", stream=io.StringIO())
    public_port, internal_port = two_free_ports()
    settings = make_settings(
        host="127.0.0.1", public_port=public_port, internal_port=internal_port, database_url=database_url
    )

    with serving(settings):
        assert status_of(f"http://127.0.0.1:{internal_port}/ready") == 200


def test_both_sockets_answer_and_only_the_internal_one_has_health(running: Running) -> None:
    public = f"http://127.0.0.1:{running.settings.public_port}"
    internal = f"http://127.0.0.1:{running.settings.internal_port}"

    assert status_of(f"{internal}/health") == 200
    assert status_of(f"{public}/health") == 404
    assert status_of(f"{public}/openapi.json") == 200


def test_uvicorn_logs_in_the_service_format(running: Running) -> None:
    lines = [json.loads(line) for line in running.log.getvalue().splitlines()]

    messages = [line["message"] for line in lines if line["logger"].startswith("uvicorn")]
    assert "Application startup complete." in messages
    assert sum("Uvicorn running on" in message for message in messages) == 2


def test_answers_do_not_name_the_server_software(running: Running) -> None:
    url = f"http://127.0.0.1:{running.settings.public_port}/api/v1/info"
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.headers.get("server") is None


def test_a_busy_internal_port_ends_the_start_and_closes_the_public_socket(restore_logging: None) -> None:
    configure_logging("INFO", "json", stream=io.StringIO())
    with exclusive_socket() as blocker:
        settings = make_settings(
            host="127.0.0.1", public_port=free_port(), internal_port=blocker.getsockname()[1]
        )

        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always", ResourceWarning)
            with pytest.raises(SystemExit) as caught:
                build_server(settings)
            close_uvicorn_s_unbound_socket(caught.value)
            gc.collect()

    assert caught.value.code == STARTUP_FAILURE
    assert [str(warning.message) for warning in seen if warning.category is ResourceWarning] == []


def test_main_ends_with_the_startup_failure_code(
    restore_logging: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with without_settings_variables(), exclusive_socket() as blocker:
        # set inside the hiding, undone with it: monkeypatch would restore "unset" afterwards
        # and so delete the process's own values
        invented = {
            "DATABASE_URL": FAKE_DATABASE_URL,
            "API_KEY_PEPPER": FAKE_PEPPER,
            "PUBLIC_PORT": str(free_port()),
            "INTERNAL_PORT": str(blocker.getsockname()[1]),
        }
        monkeypatch.setattr(sys, "stdout", io.StringIO())

        with mock.patch.dict(os.environ, invented), pytest.raises(SystemExit) as caught:
            main()
        close_uvicorn_s_unbound_socket(caught.value)

    assert caught.value.code == STARTUP_FAILURE


def test_the_server_trusts_forwarded_headers_from_the_configured_proxies_only(restore_logging: None) -> None:
    configure_logging("INFO", "json", stream=io.StringIO())
    public_port, internal_port = two_free_ports()
    settings = make_settings(
        host="127.0.0.1",
        public_port=public_port,
        internal_port=internal_port,
        forwarded_allow_ips="10.42.0.0/16",
    )

    server, sockets = build_server(settings)
    for sock in sockets:
        sock.close()

    assert server.config.forwarded_allow_ips == "10.42.0.0/16"
    assert server.config.proxy_headers is True


def cap_of(server: Any) -> int:
    """The cap on a model's answer the server's API holds the repair's offer to."""
    app = server.config.app
    assert isinstance(app, FastAPI)
    cap: int = app.state.output_cap
    return cap


def test_the_server_s_api_knows_the_cap_on_a_model_s_answer(restore_logging: None) -> None:
    # the repair's offer and start hold back what a repair under the workers' cap would not ask
    configure_logging("INFO", "json", stream=io.StringIO())
    public_port, internal_port = two_free_ports()
    settings = make_settings(host="127.0.0.1", public_port=public_port, internal_port=internal_port)

    server, sockets = build_server(settings, llm_settings(llm_max_output_tokens=32_000))
    for sock in sockets:
        sock.close()

    assert cap_of(server) == 32_000


def test_main_hands_the_environment_s_cap_on_to_the_api(
    restore_logging: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    caps: list[int] = []

    def built(settings: Settings, *args: Any, **kwargs: Any) -> Any:
        server, sockets = build_server(settings, *args, **kwargs)
        for sock in sockets:
            sock.close()
        caps.append(cap_of(server))
        raise SystemExit(STARTUP_FAILURE)  # not served: only what it was built with counts

    monkeypatch.setattr(serve, "build_server", built)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    with without_settings_variables():
        public_port, internal_port = two_free_ports()
        invented = {
            "DATABASE_URL": FAKE_DATABASE_URL,
            "API_KEY_PEPPER": FAKE_PEPPER,
            "PUBLIC_PORT": str(public_port),
            "INTERNAL_PORT": str(internal_port),
            "LLM_MAX_OUTPUT_TOKENS": "32000",
        }
        with mock.patch.dict(os.environ, invented), pytest.raises(SystemExit):
            main()

    assert caps == [32_000]
