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
        assert 'echo "REGISTRY=ghcr.io/${GITHUB_REPOSITORY_OWNER,,}"' in names
        # every image is built under each tag, and pushed by that loop alone
        assert 'for tag in $TAGS; do tags+=(-t "$image:$tag"); done' in _run(job, r"docker build")
    loop = 'for tag in $TAGS; do docker push "$REGISTRY/$1:$tag"; done'
    assert [line.strip() for line in re.findall(r"[^\n]*docker push[^\n]*", _code())] == [loop, loop]
    assert re.findall(r"^\s*build (\S+) (\S+)$", _run("images", r"docker build"), re.M) == [
        ("deploy/api.Dockerfile", '"$REGISTRY/curricarta"'),
        ("deploy/web.Dockerfile", '"$REGISTRY/curricarta-web"'),
    ]
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


def test_the_job_that_may_write_packages_runs_no_install_script_and_takes_no_cache() -> None:
    node = next(step for step in _jobs()["images"]["steps"] if "setup-node@" in step.get("uses", ""))

    # the SPA builds the same without its dependencies' install scripts; a cache other runs wrote stays out
    assert re.findall(r"npm ci[^\n&]*", _code()) == ["npm ci --ignore-scripts "]
    assert node["with"] == {"node-version": "22"}


def test_a_tag_s_run_releases_only_a_commit_of_main() -> None:
    steps = _jobs()["images"]["steps"]
    [on_main] = [index for index, step in enumerate(steps) if "merge-base" in str(step.get("run", ""))]
    builds = [index for index, step in enumerate(steps) if re.search(r"npm|docker", str(step.get("run", "")))]
    run = str(steps[on_main]["run"])

    assert steps[on_main]["if"] == "github.event_name == 'push' && github.ref_type == 'tag'"
    assert on_main < min(builds)
    # the checkout holds the tagged commit alone: main's history is fetched for the check, without a token
    assert "git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main" in run
    assert re.search(
        r'if ! git merge-base --is-ancestor "\$GITHUB_SHA" origin/main; then\n'
        r"[^\n]*::error::[^\n]*\n\s*exit 1",
        run,
    )
    # a run by hand may be of any branch, and says of which
    assert re.search(
        r'else\n\s*echo "::notice::[^\n]*\$GITHUB_REF_NAME[^\n]*"\n\s*fi', _run("images", r"GITHUB_ENV")
    )


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
    assert re.findall(r"^\s*push (.+)$", _run("converter", r"docker push"), re.M) == ["curricarta-convert"]


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
    assert re.findall(r"^\s*push (.+)$", push, re.M) == ["curricarta api", "curricarta-web web"]
    assert start["timeout-minutes"] == 15
    # each by its digest, checked as one before it is pulled, under the name Compose runs
    pulling = next(step for step in start["steps"] if "docker pull" in str(step.get("run", "")))
    assert pulling["env"] == {
        "API": "${{ needs.images.outputs.api }}",
        "WEB": "${{ needs.images.outputs.web }}",
    }
    assert 'registry="ghcr.io/${GITHUB_REPOSITORY_OWNER,,}"' in pull
    for digest, image, local in (
        ("API", "curricarta", "curricarta-api"),
        ("WEB", "curricarta-web", "curricarta-web"),
    ):
        assert re.search(
            rf'\[\[ "\${digest}" =~ \^sha256:\[0-9a-f\]\{{64\}}\$ \]\] \|\| \{{\n'
            rf'\s*echo "::error::job images handed over no digest for {re.escape(image)}"; exit 1; \}}',
            pull,
        ), digest
        assert f'docker pull "$registry/{image}@${digest}"' in pull
        assert f'docker tag "$registry/{image}@${digest}" {local}:local' in pull
    assert not any("docker build" in run for run in _runs("start"))
    assert "up -d --no-build" in up
    assert re.search(r"curl -sf --max-time \d+ http://127\.0\.0\.1:18080/api/v1/info", up)
    assert '--index 1 api python -c "$ready"' in up and '--index 2 api python -c "$ready"' in up
    assert down["if"] == "always()"
