"""The rehearsal's runner (tests/quality/handout_runner.py): the processes it starts, several at once, see
no settings variable of the real environment but the test values it sets, it leaves the test's own
environment as it was, and a failing command's words reach an assertion cut short, never an input value."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from tests.quality.handout_runner import Operator, told
from tests.support import hidden_settings_variables

pytestmark = pytest.mark.anyio

# the child tells the settings variables it has, by the names given it, and whether the system's root is
# there - never the rest of its environment, which an assertion would print
SEEN = (
    "import json, os, sys; names = set(sys.argv[1:]);"
    " sys.stdout.write(json.dumps({'settings': {k: v for k, v in os.environ.items() if k.upper() in names},"
    " 'root': os.environ.get('SYSTEMROOT')}))"
)


async def test_the_processes_see_no_real_settings_and_the_test_s_environment_stays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("OPENAI_API_KEY", "MISTRAL_API_KEY", "API_KEY_PEPPER", "STORAGE_BACKEND", "DATABASE_URL"):
        monkeypatch.setenv(name, "invented-real-value")  # as though the machine had them set
    before = dict(os.environ)
    operator = Operator("postgresql://nobody@127.0.0.1:1/none", tmp_path / "store", tmp_path / "gold", {})
    asked = ["-c", SEEN, *sorted(hidden_settings_variables())]

    seen = await asyncio.gather(*(operator.process(asked) for _ in range(6)))

    assert dict(os.environ) == before
    for done in seen:
        assert done.returncode == 0, told(done.stderr)
        child = json.loads(done.stdout)
        # by name first: a failure names the variables, never shows a value of the machine's
        assert sorted(child["settings"]) == sorted(operator.settings)
        assert child["settings"] == operator.settings  # its own test values alone
        assert child["root"] == os.environ.get("SYSTEMROOT")  # the rest of the environment whole


def test_a_failing_command_s_words_are_told_cut_short_without_an_input_value() -> None:
    stderr = b"\n".join(
        [b"line %d" % n for n in range(20)]
        + [b"  Value error [type=value_error, input_value='sk-invented', input_type=str]", b"last"]
    )

    words = told(stderr)

    assert "sk-invented" not in words and "input_value" not in words
    assert words.endswith("last") and "line 0" not in words
