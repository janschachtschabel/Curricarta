"""A document's values read back (app/db/value_rows.py, ``values_of``): in one snapshot, so that a set made
between its reads of the tables never shows a workload without the periods written with it; and one
holder's (``held_values_of``), as the document's read gives them, without reading another holder's rows -
what a set checks its values against (app/api/values.py)."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.db import value_rows
from app.db.value_rows import held_values_of
from app.db.values import replace_values, values_of
from app.domain.l2 import HeldValues, HolderKind, LevelDraft, ValueDrafts, WorkloadDraft
from tests.db.test_editing import document
from tests.db.test_nodes import CV, connection, owner, url
from tests.db.test_specifications import CONTEXT
from tests.db.test_values import EQF4, GRADE, LESSONS, LVL, holders

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing


async def test_a_document_s_values_are_read_in_one_snapshot(
    url: str, connection: psycopg.AsyncConnection, document: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder = (await holders(connection, document))["node"]
    read = value_rows.read_rows
    tables: list[str] = []

    async def read_and_meanwhile_set(
        reading: psycopg.AsyncConnection, table: str, *args: Any, **kwargs: Any
    ) -> Any:
        found = await read(reading, table, *args, **kwargs)
        tables.append(table)
        if table == "time_span":  # read; the workloads not yet: another sets one with its period
            async with await psycopg.AsyncConnection.connect(url, autocommit=True) as other:
                drafts = ValueDrafts(
                    workloads=(WorkloadDraft(Decimal(40), CV + "unit_lesson", periods=(GRADE,)),)
                )
                await replace_values(other, owner(document), holder, 1, drafts)
        return found

    monkeypatch.setattr(value_rows, "read_rows", read_and_meanwhile_set)
    seen = await values_of(connection, document.id)

    # the set came between two reads
    assert tables == ["level_assignment", "time_span", "workload", "applicability_context"]
    assert seen == {}  # read before the set, all of it
    monkeypatch.undo()
    [workload] = (await values_of(connection, document.id))[holder].workloads
    assert len(workload.periods) == 1


def counted(held: HeldValues) -> int:
    """The rows the values are: each value, a workload's periods, a context's values."""
    return (
        len(held.levels) + len(held.time_spans) + len(held.workloads) + len(held.contexts)
        + sum(len(workload.periods) for workload in held.workloads)
        + sum(len(context.levels) + len(context.time_spans) for context in held.contexts)
    )  # fmt: skip


async def test_one_holder_s_values_are_read_as_the_document_s_read_gives_them_and_no_other_row(
    connection: psycopg.AsyncConnection, document: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = await holders(connection, document)
    sets: dict[HolderKind, ValueDrafts] = {
        "node": ValueDrafts(
            levels=(EQF4,), time_spans=(GRADE,), workloads=(replace(LESSONS, periods=(GRADE,)),)
        ),
        "statement": ValueDrafts(levels=(LevelDraft(level=LVL + "cefr-B1"),)),
        "specification": ValueDrafts(workloads=(LESSONS,), contexts=(CONTEXT,)),
    }
    for kind, drafts in sets.items():
        await replace_values(connection, owner(document), held[kind], 1, drafts)
    whole = await values_of(connection, document.id)
    read = value_rows.read_rows
    rows: list[dict[str, Any]] = []

    async def counting(*args: Any, **kwargs: Any) -> Any:
        found = await read(*args, **kwargs)
        rows.extend(found)
        return found

    monkeypatch.setattr(value_rows, "read_rows", counting)
    for holder in held.values():
        rows.clear()

        assert await held_values_of(connection, holder) == whole[holder]
        assert len(rows) == counted(whole[holder])  # its own rows, no other holder's
