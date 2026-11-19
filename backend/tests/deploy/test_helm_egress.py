"""deploy/helm-values.example.yaml: the network policy lets every part out to what it reaches.

networkPolicy.egress holds one entry per part. With the policy enabled, a part without an entry is let out
to nothing the chart names (or to what the chart's own default gives it): a CronJob without one ends with
exit 1 every night, or runs its database steps and never reaches the store.
"""

from typing import Any

import pytest

from tests.deploy.test_helm_values import VALUES

EGRESS: dict[str, list[Any]] = VALUES["networkPolicy"]["egress"]
# The destinations whose selectors the chart fills in for the cluster
SHARED = {"dns", "postgresql", "object-store"}
# Every part that runs a process of the service: a command of its own, or the secrets it reads
RUNNING = [
    part
    for part, values in VALUES.items()
    if isinstance(values, dict) and ("command" in values or "secrets" in values)
]
# What a secret is for: a part that reads it reaches that destination
REACHED_WITH = {
    "DATABASE_URL": "postgresql",
    "S3_ACCESS_KEY": "object-store",
    "S3_SECRET_KEY": "object-store",
}


def _named(rules: list[Any]) -> set[str]:
    return {rule["name"] for rule in rules if isinstance(rule, dict)}


def test_the_parts_that_run_are_found() -> None:
    # the jobs and the CronJob among them, the web server not (it reaches nothing)
    assert {"api", "worker", "converter", "modelsFetch", "migrate", "vocab", "retention"} <= set(RUNNING)
    assert "web" not in RUNNING


@pytest.mark.parametrize("part", RUNNING)
def test_every_part_that_runs_has_an_egress_entry(part: str) -> None:
    assert part in EGRESS, f"{part} has no way out once the policy is enabled"
    assert "dns" in EGRESS[part]


@pytest.mark.parametrize("part", [part for part in RUNNING if "secrets" in VALUES[part]])
def test_a_part_reaches_what_its_secrets_are_for(part: str) -> None:
    keys = VALUES[part]["secrets"]["keys"]

    reached = {rule for rule in EGRESS[part] if isinstance(rule, str)}

    assert {REACHED_WITH[key] for key in keys if key in REACHED_WITH} <= reached


def test_the_sweep_reaches_the_database_and_the_store() -> None:
    # without the store it takes the jobs and audit rows, notes the raw answers and never empties the notes
    assert EGRESS["retention"] == ["dns", "postgresql", "object-store"]


@pytest.mark.parametrize("part", ["migrate", "vocab"])
def test_the_release_s_jobs_reach_the_database_alone(part: str) -> None:
    # python -m app.db.migrate and python -m app.vocab.load read and write the database, never the store
    assert EGRESS[part] == ["dns", "postgresql"]


def test_every_entry_names_a_part_of_the_values() -> None:
    assert set(EGRESS) <= set(RUNNING)


def defined(rule: Any, named: set[str]) -> bool:
    """Whether an entry's rule is a destination the map defines: a shared selector, a rule written out with
    its name, ports and targets (under this part, or under another and named here by its name first), or a
    destination outside the cluster with the place its address comes from in parentheses."""
    if isinstance(rule, dict):
        return bool(rule.get("name") and rule.get("ports") and rule.get("to"))
    described = rule.endswith(")") and "(" in rule and bool(rule.split("(", 1)[0].strip())
    return rule in SHARED or rule.split(" ", 1)[0] in named or described


@pytest.mark.parametrize("part", list(EGRESS))
def test_each_entry_names_only_destinations_the_map_defines(part: str) -> None:
    named = set().union(*(_named(rules) for rules in EGRESS.values()))

    assert [rule for rule in EGRESS[part] if not defined(rule, named)] == []


def test_a_destination_the_map_does_not_define_is_told_apart() -> None:
    named = {"public-web"}

    assert defined("public-web as the worker's below", named)
    assert defined("language model (OPENAI_BASE_URL)", named)
    for rule in ("postgres", "objectstore", "object store", "public web", "(OPENAI_BASE_URL)", {"name": "x"}):
        assert not defined(rule, named), rule
