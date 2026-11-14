""".github/workflows/release.yml publishes the images to GitHub's container registry, for a version tag
and by hand: tagged by their commit, a tag's also by its version, and started from the registry by their
digests.

These keep the one workflow that may write anywhere from writing more than it must, from running for code
that is not the repository's own, and from publishing an image under a name someone can move
(test_ci.py guards what every workflow shares: pins, permissions, deadlines, no persisted token).
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from tests.deploy.test_ci import EVERY

ROOT = Path(__file__).resolve().parents[3]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
VERSION: str = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))["project"][
    "version"
]
PUSH = {"contents": "read", "packages": "write"}
# the shell's test for a run of a version tag: a run by hand gets the commit's tag alone
TAG_RUN = '[ "$GITHUB_EVENT_NAME" = push ] && [ "$GITHUB_REF_TYPE" = tag ]'


def _text() -> str:
    return RELEASE.read_text(encoding="utf-8")


def _code() -> str:
    """The workflow without its comment lines, which may name what the code must not do."""
    return "\n".join(line for line in _text().splitlines() if not line.lstrip().startswith("#"))


def _workflow() -> dict[Any, Any]:
    workflow: dict[Any, Any] = yaml.safe_load(_text())
    return workflow


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = _workflow()["jobs"]
    return jobs


def _runs(job: str) -> list[str]:
    return [str(step.get("run", "")) for step in _jobs()[job]["steps"]]


def _run(job: str, pattern: str) -> str:
    return next(run for run in _runs(job) if re.search(pattern, run))


def _docker_builds(job: str) -> list[str]:
    """Each docker build of the job's steps, its continued lines joined."""
    joined = "\n".join(_runs(job)).replace("\\\n", " ")
    return re.findall(r"docker build [^\n]*", joined)


def test_test_ci_guards_the_release_like_every_workflow() -> None:
    assert RELEASE in EVERY


def test_it_runs_for_version_tags_and_by_hand_never_for_a_pull_request() -> None:
    workflow = _workflow()
    # PyYAML reads the key "on" as YAML 1.1 does: as True
    triggers = workflow["on"] if "on" in workflow else workflow[True]

    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v*.*.*"]}
    # nothing of a pull request reaches it, not even its branch's name or title; the one mention is the
    # concurrency expression every workflow shares (test_ci.py), false for each of its runs
    for untrusted in ("workflow_run", "head_ref", "github.event."):
        assert untrusted not in _code(), untrusted
    assert re.findall(r"[^\n]*pull_request[^\n]*", _code()) == [
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}"
    ]


def test_only_the_jobs_that_push_may_write_packages() -> None:
    permissions = {name: job.get("permissions", _workflow()["permissions"]) for name, job in _jobs().items()}

    assert _workflow()["permissions"] == {"contents": "read"}
    assert permissions == {"images": PUSH, "converter": PUSH, "start": {"contents": "read"}}


LOGIN = """printf '%s' "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin"""
TOKEN = {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}


def test_the_only_secret_it_reads_is_the_run_s_own_token() -> None:
    text = _text()

    # (not the name of deploy/make-secrets.py)
    assert set(re.findall(r"(?<![\w/-])secrets\.(\w+)", text)) == {"GITHUB_TOKEN"}
    assert "github.token" not in text
    # to GitHub's registry, on stdin: never on the command line, where the process list and the log show it
    assert re.findall(r"[^\n]*docker login[^\n]*", text) == [f"          {LOGIN}"] * 2
    assert not any("docker login" in run for run in _runs("start"))


def test_the_token_reaches_the_two_push_steps_alone_and_only_after_every_build() -> None:
    # no env for a whole workflow or job: each step names what it gets
    assert "env" not in _workflow()
    assert not any("env" in job for job in _jobs().values())
    envs = {
        (name, step["name"]): step["env"]
        for name, job in _jobs().items()
        for step in job["steps"]
        if "env" in step
    }
    assert envs == {
        ("images", "Push the images"): TOKEN,
        ("converter", "Push the converter's image"): TOKEN,
        ("start", "Pull the pushed images by their digests"): {
            "API": "${{ needs.images.outputs.api }}",
            "WEB": "${{ needs.images.outputs.web }}",
        },
    }
    for name in ("images", "converter"):
        steps = _jobs()[name]["steps"]
        [login] = [index for index, step in enumerate(steps) if LOGIN in str(step.get("run", ""))]
        builds = [
            index
            for index, step in enumerate(steps)
            if re.search(r"npm|docker build", str(step.get("run", "")))
        ]
        # the dependencies' code and the builds run before the credential is stored, and it is removed
        # however the push ends
        assert builds and max(builds) < login, name
        assert steps[login + 1 :] == [
            {"name": "Log out of the registry", "if": "always()", "run": "docker logout ghcr.io"}
        ]


def test_no_run_step_expands_an_expression_into_the_shell() -> None:
    # A value the run gets goes through env: an expression in the script would be pasted into it as code
    for name in _jobs():
        assert not any("${{" in run for run in _runs(name)), name


def test_an_image_carries_its_commit_s_tag_and_a_version_tag_only_from_a_git_tag() -> None:
    for job in ("images", "converter"):
        names = _run(job, r"GITHUB_ENV")

        assert 'version="sha-${GITHUB_SHA::12}"' in names
        assert 'tags="$version"' in names
        version_tag = r'version="\$\{GITHUB_REF_NAME#v\}"\n\s*tags="\$tags \$version"'
        assert re.search(rf"if {re.escape(TAG_RUN)}; then\n\s*{version_tag}", names), job
        # every image is built and pushed under each tag
        assert 'for tag in $TAGS; do tags+=(-t "$image:$tag"); done' in _run(job, r"docker build")
        assert 'for tag in $TAGS; do docker push "$REGISTRY/$1:$tag"; done' in _run(job, r"docker push")
    # a name someone can move to another image is no release
    assert "latest" not in _code()


def test_a_tag_that_is_not_the_package_s_version_stops_the_release() -> None:
    steps = _jobs()["images"]["steps"]
    [check] = [
        index for index, step in enumerate(steps) if "backend/pyproject.toml" in str(step.get("run", ""))
    ]
    builds = [index for index, step in enumerate(steps) if re.search(r"npm|docker", str(step.get("run", "")))]
    run = str(steps[check]["run"])

    # before anything is built, for a tag's run; the converter and the start wait for it
    assert steps[check]["if"] == "github.event_name == 'push' && github.ref_type == 'tag'"
    assert check < min(builds)
    assert re.search(r'if \[ "\$GITHUB_REF_NAME" != "v\$version" \]; then\n[^\n]*\n\s*exit 1', run)
    assert _jobs()["converter"]["needs"] == "images"
    assert _jobs()["start"]["needs"] == "images"
    # the version it compares is the package's
    [reader] = re.findall(r"python3 -c '([^']*)'", run)
    read = subprocess.run(  # noqa: S603 - the workflow's own line
        [sys.executable, "-c", reader], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert read.stdout.strip() == VERSION


def test_the_images_say_where_they_come_from() -> None:
    labels = [
        '--label "org.opencontainers.image.source=$GITHUB_SERVER_URL/$GITHUB_REPOSITORY"',
        '--label "org.opencontainers.image.revision=$GITHUB_SHA"',
        '--label "org.opencontainers.image.version=$VERSION"',
        '--label "org.opencontainers.image.licenses=Apache-2.0"',
    ]

    for job in ("images", "converter"):
        builds = _docker_builds(job)
        assert builds, job
        for build in builds:
            assert all(label in build for label in labels), build
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").split()[:4] == [
        "Apache",
        "License",
        "Version",
        "2.0,",
    ]


def test_the_revision_is_passed_where_the_dockerfile_takes_it() -> None:
    # The image reports its build where its Dockerfile declares the argument; until then the build passes
    # none, rather than one docker build warns it never used
    for job in ("images", "converter"):
        build = _run(job, r"docker build")
        [pattern] = re.findall(r"grep -Eq '([^']*)' \"\$dockerfile\"", build)
        assert 'then revision=(--build-arg "REVISION=$GITHUB_SHA"); fi' in build
        # set empty, then filled once: nothing empties it again before the build
        assert re.findall(r"(?<![\w.])revision=\S*", build) == ["revision=()", "revision=(--build-arg"]
        assert all('"${revision[@]}"' in command for command in _docker_builds(job))

        # GNU grep -E reads these escapes as Python does
        for line in ("ARG REVISION", "ARG REVISION=unknown", "  ARG REVISION"):
            assert re.search(pattern, line), line
        for line in ("ARG REVISIONS", "# ARG REVISION", "ARG VENV=api"):
            assert not re.search(pattern, line), line


def test_the_converter_s_image_is_built_only_for_a_tag_or_when_asked() -> None:
    converter = _jobs()["converter"]
    asked = _workflow()[True]["workflow_dispatch"]["inputs"]["converter"]
    [build] = _docker_builds("converter")

    assert converter["if"] == "github.event_name == 'push' || inputs.converter"
    assert asked["type"] == "boolean" and asked["default"] is False
    assert converter["timeout-minutes"] == 60
    assert "--build-arg VENV=convert" in build
    assert '"$REGISTRY/curricarta-convert"' in _run("converter", r"docker build")
    assert re.findall(r"^\s*push (\S+ \w+)$", _run("converter", r"docker push"), re.M) == [
        "curricarta-convert convert"
    ]


def test_the_pushed_image_is_started_by_its_digest_not_built_again() -> None:
    images, start = _jobs()["images"], _jobs()["start"]
    pull = _run("start", r"docker pull")
    up = _run("start", r"compose -f deploy/docker-compose.yml up")
    down = next(step for step in start["steps"] if "down -v" in str(step.get("run", "")))

    # the digests the push recorded, as the job's outputs and in the run's summary
    assert images["outputs"] == {
        "api": "${{ steps.push.outputs.api }}",
        "web": "${{ steps.push.outputs.web }}",
    }
    push = _run("images", r"docker push")
    assert 'echo "$2=$digest" >> "$GITHUB_OUTPUT"' in push
    assert "$GITHUB_STEP_SUMMARY" in push
    assert re.findall(r"^\s*push (\S+ \w+)$", push, re.M) == ["curricarta api", "curricarta-web web"]
    assert start["timeout-minutes"] == 15
    # each by its digest, checked as one before it is pulled, under the name Compose runs
    pulling = next(step for step in start["steps"] if "docker pull" in str(step.get("run", "")))
    assert pulling["env"] == {
        "API": "${{ needs.images.outputs.api }}",
        "WEB": "${{ needs.images.outputs.web }}",
    }
    for digest, image, local in (
        ("API", "curricarta", "curricarta-api"),
        ("WEB", "curricarta-web", "curricarta-web"),
    ):
        assert f'[[ "${digest}" =~ ^sha256:[0-9a-f]{{64}}$ ]]' in pull
        assert f'docker pull "$registry/{image}@${digest}"' in pull
        assert f'docker tag "$registry/{image}@${digest}" {local}:local' in pull
    assert not any("docker build" in run for run in _runs("start"))
    assert "up -d --no-build" in up
    assert re.search(r"curl -sf --max-time \d+ http://127\.0\.0\.1:18080/api/v1/info", up)
    assert '--index 1 api python -c "$ready"' in up and '--index 2 api python -c "$ready"' in up
    assert down["if"] == "always()"
