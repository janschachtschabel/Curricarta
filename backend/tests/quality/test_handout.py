"""The README's section "Güte messen" holds the operator's commands as the rehearsal runs them
(tests/quality/handout.py, tests/quality/test_rehearsal.py): its fenced command lines are the handout's, in
its order, word for word - a command changed in one place and not in the other is told here."""

from pathlib import Path

from app.quality.sheet import LOCAL_FOLDER
from tests.quality.handout import COMMANDS

README = Path(__file__).resolve().parents[3] / "README.md"
SECTION = "### Güte messen"


def section_lines() -> list[str]:
    """The lines of the section, from its heading to the next heading."""
    lines = README.read_text(encoding="utf-8").splitlines()
    start = lines.index(SECTION) + 1
    end = next((n for n in range(start, len(lines)) if lines[n].startswith("#")), len(lines))
    return lines[start:end]


def fenced(lines: list[str]) -> list[str]:
    """The lines inside the section's fenced blocks, each a command."""
    inside, found = False, []
    for line in lines:
        if line.strip().startswith("```"):  # indented under a step of the list too
            inside = not inside
        elif inside and line.strip():
            found.append(line.strip())
    assert not inside, "a fenced block is not closed"
    return found


def test_the_readme_s_commands_are_the_handout_s_in_its_order() -> None:
    assert fenced(section_lines()) == list(COMMANDS.values())


def test_the_readme_says_where_the_sheets_lie() -> None:
    text = "\n".join(section_lines())

    assert f"`{LOCAL_FOLDER.as_posix()}/`" in text
    assert "--endpoint-counts" in text
