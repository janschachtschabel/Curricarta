"""The edge in front of the API buffers request bodies (docs/uebergabe/konfiguration.md, "Uploads").

An upload holds one of its replica's few slots from before its form is read (app/api/sources.py):
an edge that streamed bodies would let a client that sends slowly hold a slot at its own pace. nginx
and ingress-nginx buffer a body whole before they pass it on, unless told not to; neither the
Compose proxy nor the Helm example may tell them so.
"""

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
NGINX_FILES = ("nginx.conf", "nginx-api.conf", "nginx-api-off.conf")


def streams_bodies(nginx: str) -> bool:
    """Whether an nginx configuration turns request buffering off anywhere (comments aside)."""
    lines = (line.split("#", 1)[0] for line in nginx.splitlines())
    return any(
        re.search(r"\bproxy_request_buffering\s+([\"']?)off\1\s*;", line, re.IGNORECASE) for line in lines
    )


def test_the_compose_web_server_buffers_request_bodies() -> None:
    for name in NGINX_FILES:
        assert not streams_bodies((DEPLOY / name).read_text(encoding="utf-8")), name


def test_the_helm_example_s_ingress_buffers_request_bodies() -> None:
    values: dict[str, Any] = yaml.safe_load((DEPLOY / "helm-values.example.yaml").read_text(encoding="utf-8"))
    annotations = {key.lower(): str(value).lower() for key, value in values["ingress"]["annotations"].items()}

    assert annotations.get("nginx.ingress.kubernetes.io/proxy-request-buffering", "on") == "on"


def test_a_server_that_streams_bodies_is_told_apart() -> None:
    assert streams_bodies("location /api/ {\n    proxy_request_buffering  off;\n}")
    # nginx reads on and off in any case, and a value may be quoted
    for written in ("OFF", "Off", '"off"', "'OFF'"):
        assert streams_bodies(f"Proxy_Request_Buffering {written};"), written
    assert not streams_bodies("# proxy_request_buffering off;\nproxy_request_buffering on;")
    assert not streams_bodies('proxy_request_buffering "on";')
