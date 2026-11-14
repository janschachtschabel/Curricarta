""".github/workflows/audit.yml checks the locked dependencies against the advisory databases, weekly, by
hand and wherever a lock changes; .github/dependabot.yml proposes the updates. Known advisories that cannot
be lifted yet stand in deploy/audit-allowlist.toml, each with a reason and a date to look again.

These keep the audit from losing a file it reads, a trigger or its strictness, and keep an ignored
advisory from being forgotten (test_ci.py guards what every workflow shares: pins, permissions, deadlines).
"""

import datetime
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from tests.deploy.test_ci import EVERY

ROOT = Path(__file__).resolve().parents[3]
AUDIT = ROOT / ".github" / "workflows" / "audit.yml"
ALLOWLIST = ROOT / "deploy" / "audit-allowlist.toml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
PYPROJECT: dict[str, Any] = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
EXPORTS = ["deploy/requirements-api.txt", "deploy/requirements-convert.txt"]
# an entry is looked at again within a quarter
LONGEST_DEFERRAL = datetime.timedelta(days=90)


def _workflow() -> dict[Any, Any]:
    workflow: dict[Any, Any] = yaml.safe_load(AUDIT.read_text(encoding="utf-8"))
    return workflow


def _triggers() -> dict[str, Any]:
    workflow = _workflow()
    # PyYAML reads the key "on" as YAML 1.1 does: as True
    triggers: dict[str, Any] = workflow["on"] if "on" in workflow else workflow[True]
    return triggers


def _runs(job: str) -> list[str]:
    return [str(step.get("run", "")) for step in _workflow()["jobs"][job]["steps"]]


def _entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = tomllib.loads(ALLOWLIST.read_text(encoding="utf-8")).get("advisory", [])
    return entries


def _as_date(value: Any) -> datetime.date | None:
    # TOML has dates of its own; a quoted ISO date is taken as well
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def allowlist_errors(entries: list[dict[str, Any]]) -> list[str]:
    """What is wrong with the entries of the allowlist, one line each; empty where nothing is."""
    errors: list[str] = []
    for number, entry in enumerate(entries):
        name = f"entry {number} ({entry.get('id', '?')})"
        for key in ("id", "package"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                errors.append(f"{name}: no {key}")
        reason = entry.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            errors.append(f"{name}: no reason of at least 20 characters")
        added, review = _as_date(entry.get("added")), _as_date(entry.get("review"))
        if added is None:
            errors.append(f"{name}: no added date")
        if review is None:
            errors.append(f"{name}: no review date")
        if added and review and not added <= review <= added + LONGEST_DEFERRAL:
            errors.append(f"{name}: review more than 90 days after added, or before it")
    return errors


def overdue(entries: list[dict[str, Any]], today: datetime.date) -> list[str]:
    """The ids whose review date has passed; on the review day itself an entry still holds."""
    return [entry["id"] for entry in entries if (_as_date(entry.get("review")) or today) < today]


def test_test_ci_guards_the_audit_like_every_workflow() -> None:
    # pinned actions, contents: read, no persisted token, a deadline per job, a concurrency group
    assert AUDIT in EVERY


def test_it_runs_weekly_by_hand_and_where_a_lock_changes() -> None:
    triggers = _triggers()

    # Monday 05:17 UTC, off the hour when scheduled runs crowd
    assert triggers["schedule"] == [{"cron": "17 5 * * 1"}]
    assert "workflow_dispatch" in triggers
    paths = triggers["pull_request"]["paths"]
    for path in [
        "backend/uv.lock",
        "backend/pyproject.toml",
        "deploy/requirements-*.txt",
        "frontend/package-lock.json",
        "frontend/package.json",
        ".github/workflows/audit.yml",
        "deploy/audit-allowlist.toml",
    ]:
        assert path in paths, path


def test_the_audit_tool_comes_from_the_lock() -> None:
    dev = PYPROJECT["dependency-groups"]["dev"]
    lock = tomllib.loads((ROOT / "backend" / "uv.lock").read_text(encoding="utf-8"))

    assert any(re.match(r"pip-audit>=\d", requirement) for requirement in dev), dev
    assert "pip-audit" in {package["name"] for package in lock["package"]}
    assert any(run.startswith("uv sync --frozen") for run in _runs("python"))
    # a dev tool: never in an image
    for export in EXPORTS:
        assert not re.search(r"^pip-audit==", (ROOT / export).read_text(encoding="utf-8"), re.M), export


@pytest.mark.parametrize("export", EXPORTS)
def test_each_hash_pinned_export_is_audited_without_installing_it(export: str) -> None:
    audits = [run for run in _runs("python") if "pip-audit" in run and f"../{export}" in run]

    assert len(audits) == 1, audits
    # --require-hashes takes the export as pinned; --disable-pip reads it without resolving or installing
    assert "--require-hashes" in audits[0]
    assert "--disable-pip" in audits[0]
    assert not any("pip install" in run for run in _runs("python"))


def test_both_npm_audits_run_at_their_levels() -> None:
    runs = _runs("npm")

    # what ships fails at moderate, the development tools at high
    assert "npm audit --omit=dev --audit-level=moderate" in runs
    assert "npm audit --audit-level=high" in runs


def test_every_ignored_advisory_stands_in_the_allowlist_and_the_other_way_round() -> None:
    ignored = re.findall(r"--ignore-vuln[ =](\S+)", AUDIT.read_text(encoding="utf-8"))

    assert sorted(ignored) == sorted(entry["id"] for entry in _entries())


def test_every_allowlist_entry_is_complete() -> None:
    assert allowlist_errors(_entries()) == []


GOOD = {
    "id": "GHSA-xxxx-xxxx-xxxx",
    "package": "example",
    "reason": "the vulnerable function is never called",
    "added": datetime.date(2026, 11, 14),
    "review": datetime.date(2027, 2, 12),
}


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"id": ""}, "no id"),
        ({"package": None}, "no package"),
        ({"reason": "not used"}, "no reason"),
        ({"added": "14.11.2026"}, "no added date"),
        ({"review": "soon"}, "no review date"),
        ({"review": datetime.date(2027, 2, 13)}, "more than 90 days"),
        ({"review": "2026-11-13"}, "before it"),
    ],
)
def test_the_allowlist_check_refuses_each_kind_of_bad_entry(change: dict[str, Any], error: str) -> None:
    assert allowlist_errors([GOOD]) == []

    errors = allowlist_errors([GOOD | change])

    assert len(errors) == 1 and error in errors[0], errors


def test_no_allowlist_entry_is_past_its_review_date() -> None:
    # Meant to turn red by itself: on the day an entry's review date passes, someone looks at the advisory
    # again and lifts the package, or writes a new reason with a new date.
    assert overdue(_entries(), datetime.date.today()) == []


def test_an_entry_is_overdue_from_the_day_after_its_review_date() -> None:
    today = datetime.date(2027, 2, 12)

    assert overdue([GOOD | {"review": today - datetime.timedelta(days=1)}], today) == [GOOD["id"]]
    assert overdue([GOOD | {"review": today}], today) == []


def test_dependabot_watches_each_ecosystem_in_its_directory() -> None:
    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    updates = {(update["package-ecosystem"], update["directory"]): update for update in config["updates"]}

    assert config["version"] == 2
    assert set(updates) == {
        ("github-actions", "/"),
        ("npm", "/frontend"),
        ("uv", "/backend"),
        ("docker", "/deploy"),
    }
    for update in updates.values():
        assert update["schedule"]["interval"] == "weekly"
    # the backend gets security updates alone: a lock change needs both exports written again
    assert updates[("uv", "/backend")]["open-pull-requests-limit"] == 0
    assert updates[("npm", "/frontend")]["open-pull-requests-limit"] == 5
    npm_groups = updates[("npm", "/frontend")]["groups"].values()
    assert [group["update-types"] for group in npm_groups] == [["minor", "patch"]]
    assert len(updates[("github-actions", "/")]["groups"]) == 1
