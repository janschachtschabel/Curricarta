"""X6 where a repair's answer is cut at the output cap (audit 2026-11-14): the package stays as it was,
a finding names it with the cap and counts no repair; no repair under a cap no higher asks it again,
one under a higher cap does, and the cut is no defect told to the model. A model stands in."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.function import FunctionModel

from app.db.findings import add_findings
from app.pipeline import x6_repair
from tests.pipeline.provider_support import usage_rows
from tests.pipeline.test_run import CV, context_of, rows, setup
from tests.pipeline.test_x4_cut import cutting
from tests.pipeline.test_x6_repair import Quoting, a_repair, extracted, runs_of, wordings

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run


async def test_a_repair_s_answer_cut_at_the_cap_leaves_its_package_and_says_so(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E3",))
    job = await a_repair(connection, document)
    fixer = Quoting()

    await x6_repair.repair_document(context_of(pool, tmp_path, cutting(fixer, "E3"), database_url), job)

    assert fixer.units == ["E3"]  # asked once
    assert "Aussage E3" in await wordings(connection, document)
    runs = await runs_of(connection, document)
    assert [stage + outcome for stage, outcome, _ in runs] == ["X5done", "X6done", "X5done"]
    assert runs[1][2]["unanswered"] == ["E3"]
    assert await rows(
        connection,
        "SELECT f.rule, f.severity, f.details FROM validation_finding f"
        " JOIN extraction_run r ON r.id = f.run_id WHERE r.stage_iri = %s",
        CV + "stage_X6",
    ) == [("x6.answer_cut", "warning", {"unit": "E3", "cap": 4_000})]
    # no repair made: it changed nothing, and no repair under this cap asks it again
    assert await rows(connection, "SELECT repairs FROM extraction_unit WHERE unit_key = 'E3'") == [(0,)]
    assert await usage_rows(connection, job, "x6.unit") == [(1, 5_000, False), ("held", 0)]


async def test_a_second_repair_under_the_same_cap_asks_the_cut_package_not_and_books_nothing(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E3",))
    first = Quoting()
    await x6_repair.repair_document(
        context_of(pool, tmp_path, cutting(first, "E3"), database_url), await a_repair(connection, document)
    )
    again, fixer = await a_repair(connection, document), Quoting()

    made = await x6_repair.repair_document(context_of(pool, tmp_path, fixer, database_url), again)

    assert (fixer.units, made["units"]) == ([], 0)
    assert await usage_rows(connection, again, "x6.unit") == [("held", 0)]
    assert "Aussage E3" in await wordings(connection, document)


async def test_a_repair_under_a_higher_cap_asks_the_cut_package_without_the_cut_as_a_defect(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E3",))
    first = Quoting()
    context = context_of(pool, tmp_path, cutting(first, "E3"), database_url)
    await x6_repair.repair_document(context, await a_repair(connection, document))
    fixer = Quoting()
    higher = FunctionModel(fixer, settings={"max_tokens": 8_000})

    await x6_repair.repair_document(
        replace(context, model=lambda: higher),
        await a_repair(connection, document),
    )

    assert fixer.units == ["E3"]
    [asked] = fixer.prompts
    assert "output cap" not in asked and "Längengrenze" not in asked
    assert "„Aussage E3“ steht nicht wörtlich" in asked  # the defect that is the document's
    assert "Aussage E3" not in await wordings(connection, document)
    assert await rows(connection, "SELECT rule FROM validation_finding WHERE rule = 'x6.answer_cut'") == []


async def x6_cuts(connection: Any) -> list[tuple[Any, ...]]:
    return await rows(connection, "SELECT details FROM validation_finding WHERE rule = 'x6.answer_cut'")


async def test_a_package_cut_again_under_a_higher_cap_has_one_finding_with_the_higher_cap(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E3",))
    fixer = Quoting()
    context = context_of(pool, tmp_path, cutting(fixer, "E3"), database_url)
    await x6_repair.repair_document(context, await a_repair(connection, document))
    higher = FunctionModel(cutting(fixer, "E3"), settings={"max_tokens": 8_000})

    await x6_repair.repair_document(
        replace(context, model=lambda: higher), await a_repair(connection, document)
    )

    assert fixer.units == ["E3", "E3"]
    assert await x6_cuts(connection) == [({"unit": "E3", "cap": 8_000},)]


async def test_a_repair_s_cut_is_named_though_a_cancel_comes_as_its_finding_is_written(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E3",))
    writing, written = asyncio.Event(), asyncio.Event()

    async def slow(connection: Any, document_id: Any, run_id: Any, findings: Any) -> None:
        if any(found.rule == "x6.answer_cut" for found in findings):
            writing.set()
            await asyncio.wait_for(written.wait(), 10)
        await add_findings(connection, document_id, run_id, findings)

    monkeypatch.setattr(x6_repair, "add_findings", slow)
    context = context_of(pool, tmp_path, cutting(Quoting(), "E3"), database_url)
    job = asyncio.create_task(x6_repair.repair_document(context, await a_repair(connection, document)))
    await asyncio.wait_for(writing.wait(), 10)
    job.cancel()
    await asyncio.sleep(0)
    written.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    for _ in range(200):
        if await x6_cuts(connection):
            break
        await asyncio.sleep(0.01)

    assert await x6_cuts(connection) == [({"unit": "E3", "cap": 4_000},)]


async def test_a_package_cut_under_a_higher_cap_is_not_asked_under_a_lower_one(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await extracted(setup, tmp_path, database_url, invent=("E3",))
    first = Quoting()
    context = context_of(pool, tmp_path, cutting(first, "E3"), database_url)
    higher = FunctionModel(cutting(first, "E3"), settings={"max_tokens": 8_000})
    await x6_repair.repair_document(
        replace(context, model=lambda: higher), await a_repair(connection, document)
    )
    fixer = Quoting()

    made = await x6_repair.repair_document(
        context_of(pool, tmp_path, fixer, database_url), await a_repair(connection, document)
    )

    assert (fixer.units, made["units"]) == ([], 0)  # 4 000 is no higher than 8 000
