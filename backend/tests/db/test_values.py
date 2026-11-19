"""A holder's values set as a whole (plan M3a D2, app/db/values.py): a node's, a statement's or a
specification's levels, time spans and workloads with their periods, on the holder's revision, under the
tree's lock. A value named by its id stays that row, one left out goes, a new one is an editor's proposal;
the holder's revision counts one up and X5 owes the document a check. Nothing is written to a frozen
document, beside its open job, or at a value of another holder."""

import asyncio
import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.db.anchors import new_entity
from app.db.editing import DocumentFrozen, JobOpen, StaleRevision
from app.db.nodes import write_subtree
from app.db.runs import x5_owed
from app.db.source_queries import Reader
from app.db.values import UnknownValue, ValueRefused, replace_values, values_of
from app.domain.l2 import Holder, HolderKind, LevelDraft, TimeSpanDraft, ValueDrafts, WorkloadDraft
from tests.db.test_editing import a_rule_s_node, an_open_job, document, edited_at, one
from tests.db.test_nodes import CV, connection, node, owner, statement, url, waiting_for_a_lock

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

LVL = "https://w3id.org/wlo/curriculum/level/"
HUMAN, PROPOSED = CV + "orig_human", CV + "rev_proposed"
GRADE = TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=Decimal(5), span_to=Decimal(6))
LESSONS = WorkloadDraft(amount=Decimal(40), amount_to=Decimal(50), unit=CV + "unit_lesson")
EQF4 = LevelDraft(level=LVL + "EQF-4")


async def holders(connection: psycopg.AsyncConnection, document: Any) -> dict[HolderKind, Holder]:
    """A node with a statement and a specification of the document, each a holder of values."""
    made = await write_subtree(
        connection, document.id, node("fn_unit", statements=(statement("Sie messen."),))
    )
    [(said,)] = await (
        await connection.execute("SELECT id FROM statement WHERE node_id = %s", (made,))
    ).fetchall()
    specification = await new_entity(connection, "specification")
    await connection.execute(
        "INSERT INTO specification (id, document_id, key, spec_kind, title)"
        " VALUES (%s, %s, 'lp', 'curriculum', 'LP')",
        (specification, document.id),
    )
    return {
        "node": Holder("node", made),
        "statement": Holder("statement", said),
        "specification": Holder("specification", specification),
    }


async def revision_of(connection: psycopg.AsyncConnection, holder: Holder) -> int:
    return int((await one(connection, f"SELECT revision FROM {holder.kind} WHERE id = %s", holder.id))[0])  # noqa: S608


async def count_values(connection: psycopg.AsyncConnection) -> tuple[Any, ...]:
    return await one(
        connection,
        "SELECT (SELECT count(*) FROM level_assignment), (SELECT count(*) FROM time_span),"
        " (SELECT count(*) FROM workload)",
    )


@pytest.mark.parametrize("kind", ["node", "statement", "specification"])
async def test_a_set_is_written_at_each_kind_of_holder_on_its_revision(
    connection: psycopg.AsyncConnection, document: Any, kind: HolderKind
) -> None:
    holder = (await holders(connection, document))[kind]
    drafts = ValueDrafts(levels=(EQF4,)) if kind == "statement" else ValueDrafts(
        levels=(EQF4,), time_spans=(GRADE,), workloads=(LESSONS,)
    )  # fmt: skip

    revision = await replace_values(connection, owner(document), holder, 1, drafts)

    assert revision == 2 == await revision_of(connection, holder)
    held = (await values_of(connection, document.id))[holder]
    assert [level.value.level for level in held.levels] == [LVL + "EQF-4"]
    stated = [each.stated for each in held.levels] + [each.stated for each in held.time_spans]
    stated += [each.stated for each in held.workloads]
    assert {(each.origin, each.review_status, each.revision, each.rule_id) for each in stated} == {
        (HUMAN, PROPOSED, 1, None)
    }


async def test_a_set_replaces_the_holder_s_values_and_keeps_those_it_names(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await holders(connection, document)
    holder, beside = made["node"], made["specification"]
    first = ValueDrafts(
        levels=(EQF4, LevelDraft(level=LVL + "EQF-5")),
        time_spans=(GRADE,),
        workloads=(WorkloadDraft(amount=Decimal(40), unit=CV + "unit_lesson", total=True, periods=(GRADE,)),),
    )
    await replace_values(connection, owner(document), holder, 1, first)
    await replace_values(connection, owner(document), beside, 1, ValueDrafts(levels=(EQF4,)))
    before = await values_of(connection, document.id)
    kept, dropped = before[holder].levels
    workload = before[holder].workloads[0]
    period = workload.periods[0]

    second = ValueDrafts(
        # the second level first, the first one changed, a new one; the time span left out
        levels=(LevelDraft(level=LVL + "EQF-5", id=dropped.value.id),
                LevelDraft(level=LVL + "EQF-4", level_to=LVL + "EQF-5", id=kept.value.id), EQF4),
        workloads=(WorkloadDraft(
            amount=Decimal(40), unit=CV + "unit_lesson", total=True, id=workload.value.id,
            periods=(replace(GRADE, id=period.value.id), TimeSpanDraft(CV + "time_gradeLevel", Decimal(7))),
        ),),
    )  # fmt: skip
    revision = await replace_values(connection, owner(document), holder, 2, second)

    after = await values_of(connection, document.id)
    levels = after[holder].levels
    assert revision == 3
    assert [
        (each.value.id, each.value.level, each.value.level_to, each.stated.revision) for each in levels[:2]
    ] == [
        (dropped.value.id, LVL + "EQF-5", None, 1),  # moved, not changed
        (kept.value.id, LVL + "EQF-4", LVL + "EQF-5", 2),
    ]
    assert levels[2].value.id not in (kept.value.id, dropped.value.id)
    assert after[holder].time_spans == ()
    [kept_workload] = after[holder].workloads
    assert (kept_workload.value.id, kept_workload.stated.revision) == (workload.value.id, 1)
    assert [(each.value.id, each.value.span_from) for each in kept_workload.periods] == [
        (period.value.id, Decimal(5)),
        (kept_workload.periods[1].value.id, Decimal(7)),
    ]
    assert after[beside] == before[beside]  # another holder's stay
    assert await count_values(connection) == (4, 2, 1)


async def test_a_set_that_changes_nothing_leaves_all_as_it_was(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    holder = (await holders(connection, document))["node"]
    await replace_values(connection, owner(document), holder, 1, ValueDrafts(levels=(EQF4,)))
    before = await values_of(connection, document.id)
    [level] = before[holder].levels

    revision = await replace_values(
        connection,
        owner(document),
        holder,
        2,
        ValueDrafts(levels=(LevelDraft(level=LVL + "EQF-4", id=level.value.id),)),
    )

    assert revision == 2 == await revision_of(connection, holder)
    assert await values_of(connection, document.id) == before


async def test_a_stale_revision_changes_nothing(connection: psycopg.AsyncConnection, document: Any) -> None:
    holder = (await holders(connection, document))["specification"]
    await replace_values(connection, owner(document), holder, 1, ValueDrafts(levels=(EQF4,)))

    with pytest.raises(StaleRevision) as stale:
        await replace_values(connection, owner(document), holder, 1, ValueDrafts())

    assert stale.value.current == 2
    assert await count_values(connection) == (1, 0, 0)


async def test_two_writers_at_once_one_wins(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    # both on revision 1: the second waits for the tree's lock, then finds the revision the first wrote
    holder = (await holders(connection, document))["node"]
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[int | None] | None = None
        try:
            async with other.transaction():
                assert (
                    await replace_values(other, owner(document), holder, 1, ValueDrafts(levels=(EQF4,))) == 2
                )
                waiting = asyncio.create_task(
                    replace_values(connection, owner(document), holder, 1, ValueDrafts(time_spans=(GRADE,)))
                )
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            with pytest.raises(StaleRevision) as lost:
                if waiting is not None:
                    await waiting

    assert lost.value.current == 2
    assert await count_values(connection) == (1, 0, 0)


async def test_a_frozen_document_and_one_beside_its_job_refuse(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    holder = (await holders(connection, document))["node"]
    await an_open_job(connection, document)
    with pytest.raises(JobOpen):
        await replace_values(connection, owner(document), holder, 1, ValueDrafts(levels=(EQF4,)))
    await connection.execute("DELETE FROM job")
    await connection.execute(
        "UPDATE document SET iri = 'https://example.org/curriculum/1', frozen_at = now() WHERE id = %s",
        (document.id,),
    )

    with pytest.raises(DocumentFrozen):
        await replace_values(connection, owner(document), holder, 1, ValueDrafts(levels=(EQF4,)))
    assert await count_values(connection) == (0, 0, 0)
    assert await revision_of(connection, holder) == 1


async def test_a_value_of_another_holder_named_by_id_is_refused(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await holders(connection, document)
    one_set = ValueDrafts(levels=(EQF4,), workloads=(WorkloadDraft(amount=Decimal(1), unit=CV + "unit_lesson",
                                                                   periods=(GRADE,)),))  # fmt: skip
    await replace_values(connection, owner(document), made["node"], 1, one_set)
    await replace_values(
        connection, owner(document), made["specification"], 1, ValueDrafts(workloads=(LESSONS,))
    )
    held = (await values_of(connection, document.id))[made["node"]]
    level, workload = held.levels[0], held.workloads[0]
    period = workload.periods[0]
    other_workload = (await values_of(connection, document.id))[made["specification"]].workloads[0]
    before = await values_of(connection, document.id)

    foreign = [
        (made["statement"], ValueDrafts(levels=(LevelDraft(level=LVL + "EQF-5", id=level.value.id),))),
        # a period is its workload's: neither a time span of the holder nor one under another workload
        (made["node"], ValueDrafts(time_spans=(replace(GRADE, id=period.value.id),))),
        (made["specification"], ValueDrafts(workloads=(
            WorkloadDraft(amount=Decimal(1), unit=CV + "unit_lesson", id=other_workload.value.id,
                          periods=(TimeSpanDraft(time_kind=CV + "time_gradeLevel", id=period.value.id),)),))),
        # a level's id is no workload's
        (made["node"], ValueDrafts(workloads=(WorkloadDraft(amount=Decimal(1), unit=CV + "unit_lesson",
                                                            id=level.value.id),))),
    ]  # fmt: skip
    for holder, drafts in foreign:
        revision = await revision_of(connection, holder)
        with pytest.raises(UnknownValue):
            await replace_values(connection, owner(document), holder, revision, drafts)

    assert await values_of(connection, document.id) == before


async def test_a_value_the_store_refuses_names_its_check_and_changes_nothing(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await holders(connection, document)
    holder = made["node"]

    with pytest.raises(ValueRefused) as refused:
        await replace_values(
            connection,
            owner(document),
            holder,
            1,
            ValueDrafts(levels=(LevelDraft(level=CV + "unit_lesson"),)),
        )
    with pytest.raises(ValueRefused) as reversed_:
        await replace_values(connection, owner(document), holder, 1, ValueDrafts(
            workloads=(replace(LESSONS, amount=Decimal(5), amount_to=Decimal(4)),)))  # fmt: skip

    # beyond what the column's type holds: the store's data error, refused as the checks are
    with pytest.raises(ValueRefused) as too_long:
        await replace_values(connection, owner(document), holder, 1, ValueDrafts(
            workloads=(replace(LESSONS, minutes_per_unit=2**40),)))  # fmt: skip
    assert too_long.value.check is None
    with pytest.raises(ValueRefused) as at_statement:
        await replace_values(connection, owner(document), made["statement"], 1, ValueDrafts((), (GRADE,)))
    assert at_statement.value.check == "not_held"
    assert (refused.value.check, reversed_.value.check) == (
        "level_assignment_level_fits",
        "workload_amount_order",
    )
    assert await count_values(connection) == (0, 0, 0)
    assert await revision_of(connection, holder) == 1


async def test_a_change_owes_x5_a_check(connection: psycopg.AsyncConnection, document: Any) -> None:
    holder = (await holders(connection, document))["statement"]
    assert await edited_at(connection, document) is None

    await replace_values(connection, owner(document), holder, 1, ValueDrafts(levels=(EQF4,)))

    assert await edited_at(connection, document) is not None
    assert await x5_owed(connection, document.id)


async def test_a_holder_is_none_to_who_sees_not_its_document(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await holders(connection, document)
    stranger = Reader(uuid.uuid4(), sees_all=False)

    for holder in made.values():
        assert await replace_values(connection, stranger, holder, 1, ValueDrafts(levels=(EQF4,))) is None
    assert (
        await replace_values(connection, owner(document), Holder("node", uuid.uuid4()), 1, ValueDrafts())
        is None
    )
    assert await count_values(connection) == (0, 0, 0)


async def test_a_rule_s_node_takes_values_as_any(connection: psycopg.AsyncConnection, document: Any) -> None:
    made = Holder("node", await a_rule_s_node(connection, document))

    assert await replace_values(connection, owner(document), made, 1, ValueDrafts(levels=(EQF4,))) == 2
