"""A node's placements over time and beside another editor (plan M3a K; app/db/placements.py): named when the
document is frozen and kept by its draft copy, which counts on; two sets at once, a set beside a set of a
placement's values, and what a set of values or a node taken away counts on the nodes' revisions."""

import asyncio
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.db.draft_copy import copy_document
from app.db.editing import DocumentFrozen, StaleRevision
from app.db.freezing import freeze
from app.db.node_drop import drop_node
from app.db.placement_rows import placements_of
from app.db.placements import replace_placements
from app.db.values import replace_values
from app.domain.l2 import Holder, ValueDrafts, WorkloadDraft
from app.domain.placements import PlacementDraft
from tests.db.test_editing import document, one
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_nodes import CV, connection, owner, url, waiting_for_a_lock
from tests.db.test_placements import BINDING, ELECTIVE, SEMESTER, placed, rows

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing


async def test_a_frozen_document_s_placements_are_named_and_its_draft_copy_keeps_them_and_counts_on(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    await ready(connection, document)
    drafts = [PlacementDraft(BINDING, specification_id=made["specification"]),
              PlacementDraft(ELECTIVE, variant_id=made["variant"])]  # fmt: skip
    await replace_placements(connection, owner(document), made["module"], 1, drafts)
    first = (await placements_of(connection, document.id))[0].id
    workload = WorkloadDraft(Decimal(5), CV + "unit_ectsCredit", periods=(SEMESTER,))
    await replace_values(connection, owner(document), Holder("placement", first), 1,
                         ValueDrafts(time_spans=(SEMESTER,), workloads=(workload,)))  # fmt: skip
    await checked(connection, document)

    await freeze(connection, document.id, BASE, accept_violations=False)
    with pytest.raises(DocumentFrozen):
        await replace_placements(connection, owner(document), made["module"], 2, [])
    copy_id = await copy_document(connection, document.id)
    copy = await one(connection, "SELECT id, owner_id FROM document WHERE id = %s", copy_id)
    copied = type("Copy", (), {"id": copy[0], "owner_id": copy[1]})
    module, revision = await one(
        connection, "SELECT n.id, n.revision FROM node n JOIN node o ON o.iri = n.iri AND o.id = %s"
        " WHERE n.document_id = %s", made["module"], copy_id,
    )  # fmt: skip
    kept = [PlacementDraft(row.obligation, row.specification_id, row.variant_id, id=row.id)
            for row in await placements_of(connection, copy_id)]  # fmt: skip
    specification = kept[0].specification_id
    [copied_first] = [row for row in await placements_of(connection, copy_id) if row.position == 1]
    assert [(len(row.periods), row.value.amount) for row in copied_first.values.workloads] == [
        (1, Decimal(5))
    ]
    assert [span.value.span_from for span in copied_first.values.time_spans] == [Decimal(3)]
    await replace_placements(
        connection,
        owner(copied),
        module,
        revision,
        [*kept, PlacementDraft(BINDING, specification_id=specification)],
    )
    await checked(connection, copied)
    await freeze(connection, copy_id, BASE, accept_violations=False)

    named = "SELECT array_agg(iri ORDER BY iri) FROM placement WHERE document_id = %s"
    assert await one(connection, named, document.id) == ([f"{DOC}/placement-1", f"{DOC}/placement-2"],)
    assert await one(connection, named, copy_id) == (
        [f"{DOC}/placement-1", f"{DOC}/placement-2", f"{DOC}/placement-3"],
    )
    assert (await one(connection, "SELECT serials FROM document WHERE id = %s", copy_id))[0]["placement"] == 3


@pytest.mark.parametrize("second", ["set", "values"])
async def test_two_editors_of_a_node_s_placements_at_once_one_wins(
    url: str, connection: psycopg.AsyncConnection, document: Any, second: str
) -> None:
    # the second waits for the tree's lock: a set on the node's revision 1 finds 2; a set of the values of a
    # placement the first took away finds none
    made = await placed(connection, document)
    await replace_placements(
        connection,
        owner(document),
        made["module"],
        1,
        [PlacementDraft(BINDING, specification_id=made["specification"])],
    )
    [placement] = await rows(connection, document)
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[int | None] | None = None
        try:
            async with other.transaction():
                assert await replace_placements(other, owner(document), made["module"], 2, []) == 3
                waiting = asyncio.create_task(
                    replace_placements(
                        connection,
                        owner(document),
                        made["module"],
                        2,
                        [PlacementDraft(ELECTIVE, specification_id=made["specification"], id=placement.id)],
                    )
                    if second == "set"
                    else replace_values(
                        connection,
                        owner(document),
                        Holder("placement", placement.id),
                        1,
                        ValueDrafts(time_spans=(SEMESTER,)),
                    )
                )
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            if second == "set":
                with pytest.raises(StaleRevision) as lost:
                    if waiting is not None:
                        await waiting
                assert lost.value.current == 3
            else:
                assert waiting is not None
                assert await waiting is None

    assert await one(connection, "SELECT count(*) FROM placement") == (0,)
    assert await one(connection, "SELECT count(*) FROM time_span") == (0,)


async def test_a_set_of_a_placement_s_values_counts_its_node_s_revision_so_a_removal_read_before_is_stale(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the node holds its placements: one taken away on the node's revision may not take values set meanwhile
    made = await placed(connection, document)
    draft = PlacementDraft(BINDING, specification_id=made["specification"])
    assert await replace_placements(connection, owner(document), made["module"], 1, [draft]) == 2
    [placement] = await rows(connection, document)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as other:
        values = ValueDrafts(time_spans=(SEMESTER,))
        assert await replace_values(other, owner(document), Holder("placement", placement.id), 1, values) == 2

    with pytest.raises(StaleRevision) as stale:
        await replace_placements(connection, owner(document), made["module"], 2, [])

    assert stale.value.current == 3
    assert await one(connection, "SELECT count(*) FROM time_span WHERE placement_id = %s", placement.id) == (
        1,
    )


async def test_a_node_taken_away_counts_the_revision_of_each_node_placed_at_it(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the placements at it go with it: the panel of a node placed there sees its view stale, not a
    # placement gone
    made = await placed(connection, document)
    draft = PlacementDraft(BINDING, specification_id=made["specification"], in_node_id=made["area"])
    assert await replace_placements(connection, owner(document), made["module"], 1, [draft]) == 2
    [placement] = await rows(connection, document)

    await drop_node(connection, owner(document), made["area"], 1)

    assert await one(connection, "SELECT revision FROM node WHERE id = %s", made["module"]) == (3,)
    with pytest.raises(StaleRevision) as stale:
        kept = PlacementDraft(BINDING, specification_id=made["specification"], id=placement.id)
        await replace_placements(connection, owner(document), made["module"], 2, [kept])
    assert stale.value.current == 3
