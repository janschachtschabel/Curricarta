"""Which not-found wordings the MEM import's report holds against the fuzzy stage's limit on places
(app/quality/mem_rare.py): only those the fuzzy stage looked for - not one longer than it takes
(``MAX_FUZZY``), counted apart, and not one past the search's time, which was never looked for at all."""

from collections.abc import Callable, Sequence
from functools import partial
from typing import Any

import pytest

from app.sources.mem import anchoring, import_job
from app.sources.mem.drafts import rows_in_order
from app.sources.mem.rules_db import load_rules
from app.sources.mem.tree import build_tree
from tests.jobs.test_mem_import import FROZEN, PLAN, blocks, setup
from tests.quality.test_mem_report import STATEMENT, at, frequent, imported, report_of, text_block

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, from test_mem_import


async def test_a_wording_longer_than_the_fuzzy_stage_takes_is_counted_apart(
    in_process_shacl: None, setup: Any
) -> None:
    context, connection = setup
    closure = [dict(row) for row in FROZEN["closure"]]
    statement = next(n for n, row in enumerate(closure) if row["label"] == STATEMENT)
    closure[statement]["label"] = " ".join(["Muster Vorgang"] * 200)  # past MAX_FUZZY, nowhere as such
    made = blocks()
    made[at(made, "Vorgang Muster")] = text_block(made[at(made, "Vorgang Muster")], frequent("Muster"))
    made[at(made, STATEMENT)] = text_block(made[at(made, STATEMENT)], frequent("Vorgang"))
    document = await imported(context, connection, made, {**FROZEN, "closure": closure})

    report = await report_of(context, connection, document)

    assert report["hits"]["strata"]["notFound:statement"] == 1
    assert (report["rare_word_hidden"], report["too_long_for_fuzzy"]) == (1, 1)  # the node's title alone


def stopping_after(searched: int) -> Callable[[], float]:
    """A clock that stands still for the search's start and its first ``searched`` rows, then leaps."""
    calls = 0

    def clock() -> float:
        nonlocal calls
        calls += 1
        return 0.0 if calls <= searched + 1 else 1e9

    return clock


async def test_a_row_past_the_search_s_time_is_not_counted(
    in_process_shacl: None, setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, connection = setup
    made = blocks()
    made[at(made, "Vorgang Muster")] = text_block(made[at(made, "Vorgang Muster")], frequent("Muster"))
    made[at(made, "Reihe")] = text_block(made[at(made, "Reihe")], frequent("Vorgang"))
    # "ihre Folge" hidden alike, and the last row the search looks for: past its time
    made[at(made, "Grundlage")] = text_block(made[at(made, "Grundlage")], frequent("ihre"))
    made[at(made, "ihre Folge")] = text_block(made[at(made, "ihre Folge")], frequent("Folge"))
    rules = await load_rules(connection, context.settings.ontology_dir)
    order = [row.key for row in rows_in_order(build_tree(FROZEN["closure"], []), rules, PLAN.iri, PLAN.title)]
    left = next(row["n"] for row in FROZEN["closure"] if row["label"] == "ihre Folge")
    assert order[-1] == left
    searched = len(order) - 1
    original = anchoring.anchor_rows

    async def timed(rows: Sequence[Any], text: Any, budget_s: float) -> Any:
        return await partial(original, clock=stopping_after(searched))(rows, text, budget_s)

    monkeypatch.setattr(import_job, "anchor_rows", timed)
    document = await imported(context, connection, made)

    report = await report_of(context, connection, document)

    assert report["import"]["unsearched"] == 1
    assert report["hits"]["strata"]["notFound:node"] == 3  # "Vorgang Muster", "Reihe", "Grundlage"
    assert report["rare_word_hidden"] == 1  # "Vorgang Muster": "ihre Folge" was never looked for
    assert report["too_long_for_fuzzy"] == 0
