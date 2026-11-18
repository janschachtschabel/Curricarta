"""A warning fails the test it shows in: pytest's configuration turns every warning into an error,
and what it ignores it ignores narrowly, each with its reason.

The CI runs pytest with pyproject.toml's settings, so this holds there as well as locally.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
TEXT = (BACKEND / "pyproject.toml").read_text(encoding="utf-8")
PYTEST: dict[str, Any] = tomllib.loads(TEXT)["tool"]["pytest"]["ini_options"]


def test_every_warning_is_an_error_first() -> None:
    assert PYTEST["filterwarnings"][0] == "error"
    assert "-W" not in PYTEST.get("addopts", "")


def test_each_exception_names_its_category_and_its_message_or_module() -> None:
    for entry in PYTEST["filterwarnings"][1:]:
        action, message, category, module = ([*entry.split(":"), "", "", ""])[:4]
        assert action in {"ignore", "default"}, entry
        assert category.strip(), entry
        assert message.strip() or module.strip(), f"too wide: {entry}"


def test_each_exception_says_why() -> None:
    block = re.search(r"(?ms)^filterwarnings = \[\n(.*?)^\]", TEXT)
    assert block is not None
    lines = block.group(1).splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith('"') and line.strip() != '"error",':
            assert lines[index - 1].strip().startswith("#"), line
