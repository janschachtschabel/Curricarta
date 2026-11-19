"""The bounds of the Compose files (deploy/docker-compose.yml, deploy/docker-compose.converter.yml) and the
rate limit at their edge: each service's memory, processes, /tmp and logs, read off the files.

A tmpfs counts against its container's memory limit: what lies in /tmp is memory, so a /tmp that holds
the uploads needs a limit above it.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from app.exports.mem_export import REQUEST_S
from tests.support import make_settings

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
BASE: dict[str, Any] = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
CONVERTER: dict[str, Any] = yaml.safe_load(
    (DEPLOY / "docker-compose.converter.yml").read_text(encoding="utf-8")
)
HELM: dict[str, Any] = yaml.safe_load((DEPLOY / "helm-values.example.yaml").read_text(encoding="utf-8"))
# Every service of both files; the converter file's api only adds to the base file's
SERVICES: dict[str, Any] = {
    **BASE["services"],
    **{name: service for name, service in CONVERTER["services"].items() if name != "api"},
}
MEMORY = {
    "postgres": "1g",
    "minio": "512m",
    "bucket": "512m",
    "migrate": "512m",
    "vocab": "512m",
    "retention": "512m",
    "api": "768m",
    "worker": "1g",
    "web": "256m",
    "converter": "6g",
    "models": "1g",
}
TMP = "/tmp"  # noqa: S108 - a path in the container, read off the file: no temporary file is made
TMP_SIZE = {"api": "256m", "worker": "256m", "web": "192m", "converter": "1g"}


def mebibytes(size: str) -> int:
    match = re.fullmatch(r"(\d+)(m|g)", size)
    assert match, size
    return int(match.group(1)) * (1024 if match.group(2) == "g" else 1)


def tmp_size(service: dict[str, Any]) -> str:
    [entry] = [entry for entry in service["tmpfs"] if entry.split(":", 1)[0] == TMP]
    match = re.fullmatch(rf"{TMP}:size=(\d+[mg])", entry)
    assert match, entry
    return match.group(1)


def uploads_at_once_mib() -> int:
    settings = make_settings()
    return settings.max_concurrent_uploads * (settings.max_upload_mb + 1)


def test_the_limits_name_every_service() -> None:
    assert set(MEMORY) == set(SERVICES)


@pytest.mark.parametrize("name", SERVICES)
def test_every_service_has_a_memory_limit_a_bounded_tmp_and_rotated_logs(name: str) -> None:
    service = SERVICES[name]

    assert service["mem_limit"] == MEMORY[name]
    assert service["pids_limit"] == (512 if name == "converter" else 256)
    assert tmp_size(service) == TMP_SIZE.get(name, "64m")
    assert mebibytes(tmp_size(service)) < mebibytes(service["mem_limit"])
    assert service["logging"] == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}


def test_the_api_s_tmp_holds_the_uploads_it_takes_at_once() -> None:
    # each upload's form lies in /tmp up to MAX_UPLOAD_MB and 1 MiB, MAX_CONCURRENT_UPLOADS at once
    assert mebibytes(tmp_size(SERVICES["api"])) >= uploads_at_once_mib()


def test_the_web_server_s_tmp_holds_the_bodies_it_buffers_within_its_memory() -> None:
    # the edge buffers each body whole in its /tmp before the API reads it (test_upload_edge.py); the
    # tmpfs counts against its memory limit, so the limit stands above it
    web = SERVICES["web"]

    assert mebibytes(tmp_size(web)) >= uploads_at_once_mib()
    assert mebibytes(web["mem_limit"]) > mebibytes(tmp_size(web))


def directives(nginx: str) -> list[str]:
    """The directives of an nginx file, comments taken out, each with its words joined by one space."""
    text = "\n".join(line.split("#", 1)[0] for line in nginx.splitlines())
    return [" ".join(part.split()) for part in re.split(r"[;{}]", text) if part.strip()]


def test_the_edge_limits_requests_per_address_and_answers_429() -> None:
    server = (DEPLOY / "nginx.conf").read_text(encoding="utf-8")
    api = (DEPLOY / "nginx-api.conf").read_text(encoding="utf-8")
    # the zone at the level of http: the file is included there, before its server block
    before_server = server.split("server {", 1)[0]
    location = api.split("location /api/ {", 1)[1].split("}", 1)[0]

    assert "limit_req_zone $binary_remote_addr zone=api:10m rate=50r/s" in directives(before_server)
    assert {"limit_req zone=api burst=100 nodelay", "limit_req_status 429"} <= set(directives(location))
    # the spec and the SPA's files are not counted: the API's location holds every limit_req
    assert len([line for line in directives(api) if line.startswith("limit_req")]) == 2
    assert HELM["ingress"]["annotations"]["nginx.ingress.kubernetes.io/limit-rps"] == "50"


# What the edge waits beyond the API's longest own deadline: the answer's way back, a slow pool connection
EDGE_MARGIN_S = 10


def edge_read_timeouts_s() -> tuple[int, int]:
    """The read deadline towards the API of Compose's edge (deploy/nginx-api.conf) and of the Helm example's
    ingress (its annotation, set or left as a comment for the operator to set)."""
    api = (DEPLOY / "nginx-api.conf").read_text(encoding="utf-8")
    location = api.split("location /api/ {", 1)[1].split("}", 1)[0]
    [compose] = [line for line in directives(location) if line.startswith("proxy_read_timeout ")]
    compose_match = re.fullmatch(r"proxy_read_timeout (\d+)s", compose)
    assert compose_match, compose
    helm_text = (DEPLOY / "helm-values.example.yaml").read_text(encoding="utf-8")
    [helm] = re.findall(
        r'^\s*#?\s*nginx\.ingress\.kubernetes\.io/proxy-read-timeout: "(\d+)"', helm_text, re.M
    )
    return int(compose_match.group(1)), int(helm)


def test_the_edges_wait_for_the_api_past_its_statement_deadline() -> None:
    # One rule at both edges: past the API's DB_STATEMENT_TIMEOUT_S (and the MEM export's wait in its
    # request) by a margin, so that the API's own answer - a 500 for a cancelled statement - reaches the
    # client rather than the edge's 504
    compose, helm = edge_read_timeouts_s()
    statement_s = {
        int(BASE["services"]["api"]["environment"]["DB_STATEMENT_TIMEOUT_S"]),
        int(HELM["api"]["env"]["DB_STATEMENT_TIMEOUT_S"]),
    }

    assert compose == helm
    assert compose >= max(*statement_s, REQUEST_S) + EDGE_MARGIN_S
