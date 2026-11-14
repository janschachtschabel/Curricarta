"""The MEM fixtures are synthetic (tests/sources/fixtures/mem/HERKUNFT.md, audit 2026-11-14): MEM-Schule's
data - a Land's wordings - are not ours to hand on, so the repository holds none. A fixture frozen from
the endpoint and committed as it came fails here."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "mem"


def tool() -> Any:
    """backend/tools/mem_synth.py, which is no package: loaded by its path."""
    spec = importlib.util.spec_from_file_location(
        "mem_synth", Path(__file__).parents[2] / "tools" / "mem_synth.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mem_synth = tool()

NAMES = sorted(path.stem for path in FIXTURES.glob("*.json"))
IRI_FIELDS = ("n", "v", "x", "target")


def fixture(name: str) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return found


def test_there_are_fixtures_to_guard() -> None:
    assert NAMES == ["be", "by", "kmk", "rp", "sn"]


@pytest.mark.parametrize("name", NAMES)
def test_a_fixture_names_no_part_of_a_real_plan(name: str) -> None:
    made = fixture(name)
    base = f"{mem_synth.BASE}/{name}/"

    assert made["synthetic"] is True
    assert made["plan"].startswith(base)
    for row in [*made["closure"], *made["references"]]:
        named = [row[field] for field in IRI_FIELDS if row.get(field)]
        named += [part for part in row.get("ancestors", "").split("|") if part]
        assert all(iri.startswith(base) for iri in named), row


@pytest.mark.parametrize("name", NAMES)
def test_a_fixture_s_wordings_are_made_of_the_tool_s_words(name: str) -> None:
    known = {*mem_synth.NOUNS, *mem_synth.WORDS}

    for row in [*fixture(name)["closure"], *fixture(name)["references"]]:
        for field in ("label", "description"):
            for piece in (row.get(field) or "").split():
                word = "".join(sign for sign in piece if sign.isalpha())
                # a word of the list, or what the tool leaves as it stands: a number, a mark, a formula's sign
                assert word in known or not word or any(sign.isdigit() for sign in piece) or len(word) == 1, (
                    row["n"],
                    piece,
                )


def test_a_wording_keeps_its_form_and_none_of_its_words() -> None:
    made = mem_synth.wording("Die Lernenden untersuchen 3 Texte (Klasse 5/6).", 4)

    assert [piece[0].isupper() for piece in made.split()] == [True, True, False, False, True, False, False]
    assert made.endswith("5/6).") and " 3 " in made and "(" in made
    assert not {"Lernenden", "untersuchen", "Texte", "Klasse"} & set(made.replace("(", " ").split())
