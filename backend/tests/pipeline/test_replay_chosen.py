"""Which kept answer is a unit's (app/pipeline/replay_answers.py ``chosen``), over the histories of more than
one X4 run: the answer in form naming the unit in the run that WROTE it; more than one there is ambiguous;
the last in form for a unit no X4 run wrote - never done, or written anew by a repair."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.db.units import UnitDone
from app.pipeline.replay_answers import Gathered, chosen

FIRST, LATER, REPAIR = UUID(int=1), UUID(int=2), UUID(int=6)  # two X4 runs, an X6 run
X4 = {FIRST, LATER}
NOW = datetime(2026, 11, 14, tzinfo=UTC)


def done(key: str, run: UUID | None, repairs: int = 0) -> UnitDone:
    return UnitDone(key, run, None, 1, (), NOW, repairs)


def answer(tag: str) -> dict[str, Any]:
    return {"tag": tag}


@pytest.mark.parametrize(
    ("done_units", "in_form", "answers", "ambiguous", "repaired"),
    [
        # in form in the first run, its write failed; asked again and written by the next job's run
        (
            {"E1": done("E1", LATER)},
            [(FIRST, "E1", answer("first, unwritten")), (LATER, "E1", answer("later, written"))],
            {"E1": "later, written"}, (), (),
        ),
        # the same, the unwritten answer kept after the written one: the run decides, not the order
        (
            {"E1": done("E1", FIRST)},
            [(FIRST, "E1", answer("first, written")), (LATER, "E1", answer("later, never written"))],
            {"E1": "first, written"}, (), (),
        ),
        # a stray naming E2 in the run that wrote E2 (another unit's answer, thrown away then): not guessed
        (
            {"E2": done("E2", FIRST)},
            [(FIRST, "E2", answer("own")), (FIRST, "E2", answer("stray")), (LATER, "E2", answer("later"))],
            {}, ("E2",), (),
        ),
        # written anew by a repair since: the last answer in form of the X4 runs, the unit told repaired
        (
            {"E1": done("E1", REPAIR, repairs=1)},
            [(FIRST, "E1", answer("first")), (LATER, "E1", answer("later"))],
            {"E1": "later"}, (), ("E1",),
        ),
        # never done: the last answer in form; none in form: no answer at all
        ({}, [(FIRST, "E1", answer("first")), (LATER, "E1", answer("later"))], {"E1": "later"}, (), ()),
        ({}, [], {}, (), ()),
    ],
    ids=["written-by-the-later-run", "written-by-the-first-run", "stray", "repaired", "never-done", "none"],
)  # fmt: skip
def test_a_unit_s_answer_is_the_one_in_the_run_that_wrote_it(
    done_units: dict[str, UnitDone],
    in_form: list[tuple[UUID, str, dict[str, Any]]],
    answers: dict[str, str],
    ambiguous: tuple[str, ...],
    repaired: tuple[str, ...],
) -> None:
    picked = chosen(["E1", "E2"], done_units, X4, Gathered(in_form=in_form))

    assert {key: found["tag"] for key, found in picked.answers.items()} == answers
    assert (picked.ambiguous, picked.repaired) == (ambiguous, repaired)
