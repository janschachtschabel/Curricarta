""".github/workflows/release.yml: where the run's token goes and what the push steps do before they push.

These keep the credential of the one workflow that may write packages away from the dependencies' code and
the builds, and keep a version, once pushed, from being pushed again under the same name (test_release.py
guards the rest of the workflow).
"""

import re

from tests.deploy.test_release import TAG_RUN, _jobs, _run, _runs, _text, _workflow

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


NOT_FOUND = "no such manifest|manifest unknown|name unknown"


def test_a_version_is_pushed_once_and_a_registry_that_cannot_answer_stops_the_run() -> None:
    for job, names in (("images", "curricarta curricarta-web"), ("converter", "curricarta-convert")):
        run = _run(job, r"docker push")
        check = rf"if {re.escape(TAG_RUN)}; then\n\s*for name in {names}; do\n"

        # logged in, every name the job pushes asked for, and only then the first push; a tag's run alone
        assert run.index(LOGIN) < run.index("docker manifest inspect") < run.index("docker push")
        assert re.search(check, run), job
        assert run.count("docker manifest inspect") == 1
        # a name that answers stops the run; so does any answer but a clean not-found
        assert re.search(
            r'if answer="\$\(docker manifest inspect "\$REGISTRY/\$name:\$VERSION" 2>&1\)"; then\n'
            r'\s*echo "::error::\$REGISTRY/\$name:\$VERSION exists[^\n]*"\n\s*exit 1\n'
            rf"\s*elif ! grep -qiE '{re.escape(NOT_FOUND)}' <<<\"\$answer\"; then\n"
            r'\s*echo "::error::[^\n]*\$\{answer[^\n]*"\n\s*exit 1\n',
            run,
        ), job
    # a half release is completed by its failed jobs alone: a job run again finds its own images
    assert '"Re-run failed jobs"' in _text() and "Re-run all jobs" not in _text()
