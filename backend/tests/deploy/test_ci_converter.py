""".github/workflows/converter.yml builds the converter's image (plan M1 3b), fetches its models and starts
the service with it as the README has them, and runs Docling's tests in the image: the one place they are
not skipped, and there they may not be. A workflow of its own, started where what the converter is built
of or runs changes (test_ci.py guards what every workflow shares)."""

import os
import re
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from app.conversion.models import MODELS_DIR, missing

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
TEXT = (ROOT / ".github" / "workflows" / "converter.yml").read_text(encoding="utf-8")
WORKFLOW: dict[Any, Any] = yaml.safe_load(TEXT)
# PyYAML reads the key "on" as YAML 1.1 does: as True
TRIGGERS: dict[str, Any] = WORKFLOW["on"] if "on" in WORKFLOW else WORKFLOW[True]
STEPS: list[dict[str, Any]] = [step for job in WORKFLOW["jobs"].values() for step in job["steps"]]
BASE: dict[str, Any] = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
CONVERTER: dict[str, Any] = yaml.safe_load(
    (ROOT / "deploy" / "docker-compose.converter.yml").read_text(encoding="utf-8")
)["services"]["converter"]
README = (ROOT / "README.md").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "deploy" / "api.Dockerfile").read_text(encoding="utf-8")
E2E = "tests/conversion/test_docling_e2e.py"


def _commands() -> str:
    return "\n".join(str(step.get("run", "")) for step in STEPS)


def _command(pattern: str) -> str:
    return next(str(step["run"]) for step in STEPS if re.search(pattern, str(step.get("run", ""))))


def _readme_block() -> list[str]:
    """The commands of the README's block that builds the converter, fetches its models and starts it."""
    after = README[README.index("Einmalig bauen und die Modelle holen") :]
    block = re.search(r"```bash\n(.*?)```", after, re.DOTALL)
    assert block
    return [line for line in block.group(1).splitlines() if line.strip()]


def test_it_runs_where_what_the_converter_is_built_of_or_runs_changes() -> None:
    assert TRIGGERS["push"]["branches"] == ["main"]
    paths = TRIGGERS["push"]["paths"]
    assert TRIGGERS["pull_request"]["paths"] == paths
    for path in [
        ".github/workflows/converter.yml",
        ".dockerignore",  # the image's build context
        "backend/app/conversion/**",
        "backend/app/jobs/**",
        "backend/tests/conversion/**",
        "backend/tests/conftest.py",  # loaded by the tests in the image, without the net
        "backend/tests/support.py",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "deploy/api.Dockerfile",
        "deploy/requirements-convert.txt",
        "deploy/docker-compose.yml",
        "deploy/docker-compose.converter.yml",
    ]:
        assert path in paths, path


def test_the_readme_s_steps_run_word_for_word() -> None:
    commands = _commands()
    block = _readme_block()

    assert len(block) == 3  # build, fetch the models, start
    for line in block:
        assert line in commands, line


def test_docling_s_tests_run_in_the_image_as_the_converter_runs_and_may_not_be_skipped() -> None:
    run = _command(re.escape(E2E))

    assert "curricarta-convert:local" in run
    for flag in [
        "--network none",  # Hugging Face is never asked
        "--read-only",
        "--tmpfs /tmp",
        "--cap-drop ALL",
        f"{BASE['name']}_models:/models:ro",  # the models the README's fetch wrote
        "CURRICARTA_REQUIRE_DOCLING=1",
    ]:
        assert flag in run, flag


def test_docling_s_tests_show_the_child_s_peak_memory_they_print() -> None:
    # the numbers CHILD_MEMORY_LIMIT_MB is sized by stand in the workflow's log (audit 2026-11-14)
    assert re.search(r"test_docling_e2e\.py -p no:cacheprovider -rA$", _command(re.escape(E2E)).strip())


def test_docling_s_tests_run_the_image_s_code_in_the_converter_s_environment() -> None:
    run = _command(re.escape(E2E))

    # the tests beside the image's code, not a checkout's code in its stead: what the build leaves out shows
    assert '"$PWD/backend/tests:/srv/backend/tests:ro"' in run
    assert '"$PWD/backend/pyproject.toml:/srv/backend/pyproject.toml:ro"' in run
    assert "/work" not in run and " -w " not in run
    # no variable the converter lacks - a HOME of its own would hide a write to the service's missing one
    given = dict(re.findall(r"-e (\w+)=(\S+)", run))
    ours = {"PYTHONPATH", "CURRICARTA_REQUIRE_DOCLING"}
    assert {name: value for name, value in given.items() if name not in ours}.items() <= CONVERTER[
        "environment"
    ].items()


def test_pytest_comes_from_the_lock_for_the_image_s_python() -> None:
    # pytest is no part of the image: the development's group of uv.lock, at the image's Python
    python = re.search(r"FROM python:(\d+\.\d+)-slim", DOCKERFILE)
    assert python
    setup = next(step for step in STEPS if "astral-sh/setup-uv@" in step.get("uses", ""))

    assert "uv sync --frozen --only-group dev" in _commands()
    assert setup["with"]["python-version"] == python.group(1)
    assert f"python{python.group(1)}/site-packages:/testlibs:ro" in _command(re.escape(E2E))


@pytest.mark.parametrize(
    ("what", "pattern"),
    [
        (
            "the API answers through the web server",
            r"curl -sf --max-time \d+ http://127\.0\.0\.1:18080/api/v1/info",
        ),
        # restart: unless-stopped brings a converter back that ended at its start, running again for a while
        (
            "the converter is healthy and was not restarted",
            r"docker inspect -f '\{\{\.State\.Health\.Status\}\} \{\{\.RestartCount\}\}' \"\$converter\"\)\""
            r" = \"healthy 0\"",
        ),
        # the worker names the kinds it takes at its start: Docling installed, its models there
        (
            "the converter takes Docling's jobs",
            r"logs converter \| grep -F \"takes \['source\.convert_docling'\]\"",
        ),
    ],
)
def test_the_service_starts_with_the_converter(what: str, pattern: str) -> None:
    assert re.search(pattern, _command(r"up -d")), what


def test_the_service_is_stopped_and_its_volumes_removed_whatever_happened() -> None:
    down = next(step for step in STEPS if "down -v" in str(step.get("run", "")))

    assert down["if"] == "always()"
    assert "deploy/docker-compose.converter.yml" in down["run"]


@pytest.mark.skipif(
    find_spec("docling") is not None and not missing(MODELS_DIR), reason="Docling and its models are here"
)
def test_docling_s_tests_fail_where_they_are_required_and_docling_is_missing() -> None:
    environment = {**os.environ, "CURRICARTA_REQUIRE_DOCLING": "1"}

    ran = subprocess.run(  # noqa: S603 - this interpreter, a test module of the repository
        [sys.executable, "-m", "pytest", E2E, "-p", "no:cacheprovider", "-q"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert ran.returncode != 0, ran.stdout
    assert "Docling's tests are required" in ran.stdout
