""".github/workflows/ci.yml runs every check of the repository, with pinned tools; every workflow reads
the repository and nothing more, but for the two jobs of release.yml that push its images, and takes its
actions by their commits.

These keep a workflow from losing a check or taking an action by a tag someone could move.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
EVERY = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
TEXT = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
WORKFLOW: dict[Any, Any] = yaml.safe_load(TEXT)
JOBS: dict[str, Any] = WORKFLOW["jobs"]
COMPOSE: dict[str, Any] = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
PYPROJECT: dict[str, Any] = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))


def _commands() -> str:
    return "\n".join(str(step.get("run", "")) for job in JOBS.values() for step in job.get("steps", []))


def _smoke_test() -> str:
    steps = JOBS["images"]["steps"]
    return next(str(step["run"]) for step in steps if step.get("name") == "Smoke test of the whole service")


def _command(job: str, pattern: str) -> str:
    runs = [str(step.get("run", "")) for step in JOBS[job]["steps"]]
    return next(run for run in runs if re.search(pattern, run))


def test_there_are_the_workflows_these_guard() -> None:
    assert [path.name for path in EVERY] == ["audit.yml", "ci.yml", "converter.yml", "release.yml"]


# the jobs that push the release's images to the registry (tests/deploy/test_release.py)
PUSHING = {("release.yml", "images"), ("release.yml", "converter")}


@pytest.mark.parametrize("path", EVERY, ids=lambda path: path.name)
def test_every_action_is_pinned_by_its_commit(path: Path) -> None:
    uses = re.findall(r"uses: (\S+)", path.read_text(encoding="utf-8"))

    assert uses
    assert all(re.search(r"@[0-9a-f]{40}$", action) for action in uses), uses


@pytest.mark.parametrize("path", EVERY, ids=lambda path: path.name)
def test_it_reads_the_repository_and_nothing_more(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert workflow["permissions"] == {"contents": "read"}
    # a job may widen them for itself only to push the images it built
    for name, job in workflow["jobs"].items():
        allowed = (
            {"contents": "read", "packages": "write"}
            if (path.name, name) in PUSHING
            else {"contents": "read"}
        )
        assert job.get("permissions", {"contents": "read"}) == allowed, name


@pytest.mark.parametrize("path", EVERY, ids=lambda path: path.name)
def test_no_later_step_can_read_the_checkout_s_token(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    checkouts = [step for step in steps if "actions/checkout@" in step.get("uses", "")]

    assert checkouts
    assert all(step.get("with", {}).get("persist-credentials") is False for step in checkouts)


@pytest.mark.parametrize("path", EVERY, ids=lambda path: path.name)
def test_a_branch_can_be_checked_by_hand_and_main_is_never_cut_short(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML reads the key "on" as YAML 1.1 does: as True
    triggers = workflow["on"] if "on" in workflow else workflow[True]

    # A green run on a test branch is the milestone's proof; a push alone starts nothing there
    assert "workflow_dispatch" in triggers
    assert workflow["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


@pytest.mark.parametrize("path", EVERY, ids=lambda path: path.name)
def test_every_job_and_every_request_has_a_deadline(path: Path) -> None:
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].values()
    runs = "\n".join(str(step.get("run", "")) for job in jobs for step in job["steps"])

    assert all(job.get("timeout-minutes", 0) > 0 for job in jobs)
    curls = re.findall(r"curl [^\n]*", runs)
    assert all("--max-time" in curl for curl in curls), curls


def test_every_check_of_the_repository_runs() -> None:
    commands = _commands()

    for check in [
        "pruefung/pruefe.py",
        "ruff check",
        "ruff format --check",
        "mypy",
        "pytest",
        "npm ci",
        "npm test",
        "npm run lint",
        "npm run build",
        "deploy/api.Dockerfile",
        "deploy/web.Dockerfile",
    ]:
        assert check in commands, check


def test_the_script_ci_runs_is_linted_and_typed_as_well() -> None:
    for tool in (r"ruff check", r"ruff format --check", r"mypy"):
        assert "make-secrets.py" in _command("backend", tool), tool


def _test_parts() -> list[list[str]]:
    return [str(part["paths"]).split() for part in JOBS["backend-tests"]["strategy"]["matrix"]["include"]]


def _holding_tests(tests: Path) -> set[str]:
    """The top-level entries under ``tests`` that pytest collects from: its folders with a test file
    anywhere below, and its own test files."""
    patterns = ("test_*.py", "*_test.py")

    def holds(path: Path) -> bool:
        if path.is_dir():
            return any(next(path.rglob(pattern), None) for pattern in patterns)
        return any(path.match(pattern) for pattern in patterns)

    return {f"tests/{path.name}" for path in tests.iterdir() if holds(path)}


def test_the_backend_tests_run_in_parts_that_leave_no_test_out_and_none_twice() -> None:
    parts = _test_parts()
    every = [path for part in parts for path in part]

    assert len(parts) >= 2
    assert len(every) == len(set(every)), every
    assert set(every) == _holding_tests(ROOT / "backend" / "tests")
    assert "${{ matrix.paths }}" in _command("backend-tests", r"-m pytest")
    # its checks are named by the part, not by the paths, which change with each rebalancing
    assert JOBS["backend-tests"]["name"] == "backend-tests (${{ matrix.part }})"


def test_the_checks_beside_the_tests_run_once() -> None:
    for check in ("pruefung/pruefe.py", "ruff check", "ruff format --check", "-m mypy"):
        running = [
            name
            for name, job in JOBS.items()
            if any(check in str(step.get("run", "")) for step in job["steps"])
        ]
        assert running == ["backend"], check


def test_the_entries_holding_tests_are_found_however_deep_their_files_lie(tmp_path: Path) -> None:
    for folder in ("flat", "deep/er", "helpers"):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "flat" / "test_a.py").touch()
    (tmp_path / "deep" / "er" / "b_test.py").touch()
    (tmp_path / "helpers" / "support.py").touch()
    (tmp_path / "test_top.py").touch()
    (tmp_path / "conftest.py").touch()

    assert _holding_tests(tmp_path) == {"tests/flat", "tests/deep", "tests/test_top.py"}


def test_the_tests_keep_their_coverage() -> None:
    floor = PYPROJECT["tool"]["coverage"]["report"]["fail_under"]
    run = PYPROJECT["tool"]["coverage"]["run"]

    pytest = _command("backend-tests", r"-m pytest")
    combine = _command("backend-coverage", r"coverage combine")
    report = _command("backend-coverage", r"coverage report")

    # each part measures the application and keeps its data under a name of its own; the floor holds
    # for all of them together, in the job that combines them, never per part
    assert "-m coverage run --parallel-mode --source=app -m pytest" in pytest
    assert "fail-under" not in pytest and "--cov" not in pytest
    # a floor given on the command line would override pyproject's
    assert "fail-under" not in combine + report
    assert floor >= 90
    # the parts' data meet from two machines; the processes the tests start are measured too
    assert run["relative_files"] is True
    assert run["patch"] == ["subprocess"]


def test_each_part_hands_its_coverage_on_and_the_floor_holds_before_the_images_are_built() -> None:
    upload = next(
        step for step in JOBS["backend-tests"]["steps"] if "upload-artifact@" in step.get("uses", "")
    )
    download = next(
        step for step in JOBS["backend-coverage"]["steps"] if "download-artifact@" in step.get("uses", "")
    )

    # coverage's data files begin with a dot, which the upload leaves out unless told
    assert upload["with"]["include-hidden-files"] is True
    assert upload["with"]["retention-days"] == 1
    assert upload["with"]["if-no-files-found"] == "error"
    assert JOBS["backend-coverage"]["needs"] == "backend-tests"
    assert download["with"]["merge-multiple"] is True
    assert set(JOBS["images"]["needs"]) >= {"backend", "backend-tests", "backend-coverage", "frontend"}


def test_the_database_and_object_store_tests_are_required_not_skipped() -> None:
    environment = JOBS["backend-tests"]["env"]

    # GitHub sets CI=true, which turns a missing test service into a failure (tests/conftest.py)
    assert environment["CURRICARTA_TEST_DATABASE_URL"].startswith("postgresql://")
    assert environment["CURRICARTA_TEST_S3_URL"].startswith("http://127.0.0.1:")


def test_ci_tests_against_the_database_image_compose_runs() -> None:
    service = JOBS["backend-tests"]["services"]["postgres"]

    assert service["image"] == COMPOSE["services"]["postgres"]["image"]
    # healthy once it listens on TCP, not while the first start's socket-only server runs
    assert "pg_isready -h 127.0.0.1" in service["options"]


def test_the_lock_is_installed_as_it_is() -> None:
    assert "uv sync --frozen" in _commands()


def test_the_smoke_test_starts_the_whole_service_and_asks_through_the_web_server() -> None:
    smoke = _smoke_test()

    assert "docker compose -f deploy/docker-compose.yml up" in smoke
    assert "127.0.0.1:18080/api/v1/info" in smoke


@pytest.mark.parametrize(
    ("what", "pattern"),
    [
        # no service waits for the vocabulary load: up -d stays green when it fails; docker wait on its
        # container, as the runner's compose wait found none once the load had ended
        (
            "the vocabulary load ended well",
            r"test \"\$\(docker wait \"\$\(docker compose -f deploy/docker-compose\.yml"
            r" ps -aq vocab\)\"\)\" = 0",
        ),
        ("both workers run", r"ps -q --status running worker \| wc -l\)\" = 2"),
        # restart: unless-stopped brings a crashing worker back, running again for a while
        (
            "no worker was restarted",
            r"docker inspect -f '\{\{\.State\.Status\}\} \{\{\.RestartCount\}\}' \"\$worker\"\)\""
            r" = \"running 0\"",
        ),
        (
            "each API replica is ready",
            r"ready=\"[^\"]*:9000/ready'[\s\S]*"
            r"--index 1 api python -c \"\$ready\"\n.*--index 2 api python -c \"\$ready\"",
        ),
        # a trace id the client sends appears in the API's log line of the request
        (
            "the trace id reaches the log",
            r"x-client-trace-id: \$trace[\s\S]*logs api[^\n]*grep -\w*F \"\$trace\"",
        ),
    ],
)
def test_the_smoke_test_checks(what: str, pattern: str) -> None:
    assert re.search(pattern, _smoke_test()), what
