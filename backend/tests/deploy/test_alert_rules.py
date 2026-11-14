"""deploy/alerts/curricarta.rules.yaml: the alert rules for the operators' Prometheus, read off the file.

No Prometheus runs here: the rules are held to what the service exports - the series, the label values
the code sets - and to how its gauges are meant to be read.
"""

import re
from pathlib import Path
from typing import Any, get_args

import yaml  # type: ignore[import-untyped]
from prometheus_client import REGISTRY

from app.core import metrics

ROOT = Path(__file__).resolve().parents[3]
RULES_FILE = "deploy/alerts/curricarta.rules.yaml"
RULES: list[dict[str, Any]] = [
    rule
    for group in yaml.safe_load((ROOT / RULES_FILE).read_text(encoding="utf-8"))["groups"]
    for rule in group["rules"]
]
HELM: dict[str, Any] = yaml.safe_load(
    (ROOT / "deploy" / "helm-values.example.yaml").read_text(encoding="utf-8")
)

METRIC = re.compile(r"\bcurricarta_[a-z0-9_]+")
SELECTOR = re.compile(r"\b(curricarta_[a-z0-9_]+)\{([^}]*)\}")
MATCHER = re.compile(r'([a-z_]+)\s*(=~|!~|!=|=)\s*"([^"]*)"')
SUFFIXES = {"counter": ("_total",), "histogram": ("_bucket", "_count", "_sum"), "gauge": ("",)}
# The values the code sets, per series and label (app/core/metrics.py)
SET_BY_THE_CODE = {
    ("curricarta_jobs_total", "outcome"): set(get_args(metrics.JobOutcome)),
    ("curricarta_llm_requests_total", "outcome"): set(get_args(metrics.LLMOutcome)),
    ("curricarta_http_requests_total", "status"): {str(code) for code in range(100, 600)},
    ("curricarta_queue_jobs", "status"): set(metrics.QUEUE_STATUSES),
}


def exported() -> dict[str, str]:
    """Each series the service exports, by its name in a query, with its metric's type."""
    series = {}
    for family in REGISTRY.collect():
        if family.name.startswith("curricarta_"):
            for suffix in SUFFIXES[family.type]:
                series[family.name + suffix] = family.type
    return series


def test_every_rule_reads_only_series_the_service_exports() -> None:
    series = exported()

    for rule in RULES:
        named = METRIC.findall(rule["expr"])
        assert named, rule["alert"]
        assert set(named) <= set(series), (rule["alert"], set(named) - set(series))


def test_every_label_value_a_rule_selects_is_one_the_code_sets() -> None:
    selected = 0
    for rule in RULES:
        for name, matchers in SELECTOR.findall(rule["expr"]):
            for label, _, value in MATCHER.findall(matchers):
                known = SET_BY_THE_CODE[name, label]
                # each alternative of a regular expression matches a value, a plain value is one
                for alternative in value.split("|"):
                    assert any(re.fullmatch(alternative, one) for one in known), (rule["alert"], label, value)
                selected += 1

    assert selected >= 4  # the matchers were found: a pattern that read none would pass any file


def test_every_alert_waits_before_it_fires_names_its_severity_and_says_what_to_do() -> None:
    for rule in RULES:
        assert re.fullmatch(r"[1-9][0-9]*[smh]", rule.get("for", "")), rule["alert"]
        assert rule["labels"]["severity"] in {"warning", "critical"}, rule["alert"]
        assert rule["annotations"]["summary"].strip(), rule["alert"]
        assert rule["annotations"]["description"].strip(), rule["alert"]


def test_a_gauge_every_replica_reports_is_read_as_one_value() -> None:
    # every API replica reads the queue from the same table: a sum would count it once per replica
    queue_gauges = {name for name, kind in exported().items() if kind == "gauge" and "_queue_" in name}
    assert queue_gauges == {"curricarta_queue_jobs", "curricarta_queue_oldest_waiting_seconds"}

    for rule in RULES:
        expr = rule["expr"]
        for found in METRIC.finditer(expr):
            if found.group(0) in queue_gauges:
                before = expr[: found.start()]
                assert re.search(r"\bmax(\s+by\s*\([^)]*\))?\s*\(\s*$", before), rule["alert"]


def test_the_helm_example_points_at_the_rules() -> None:
    assert HELM["monitoring"]["prometheusRule"] == {"enabled": True, "rulesFile": RULES_FILE}
    assert (ROOT / RULES_FILE).is_file()
