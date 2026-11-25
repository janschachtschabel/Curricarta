"""A document's values read back (app/db/value_rows.py, ``values_of``): in one snapshot, so that a set made
between its reads of the tables never shows a workload without the periods written with it."""

from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.db import value_rows
from app.db.values import replace_values, values_of
from app.domain.l2 import ValueDrafts, WorkloadDraft
from tests.db.test_editing import document
from tests.db.test_nodes import CV, connection, owner, url
from tests.db.test_values import GRADE, holders

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
