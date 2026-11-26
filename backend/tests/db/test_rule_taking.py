"""A rule added by hand and a rule taken away (plan M3a I; app/db/rules.py add_rule, drop_or_reject_rule):
added after the document's frame parts on the blocks chosen, an editor's from the first; taken away, an
editor's deleted with the findings on it, a run's rejected and kept; never beside an open job, of a frozen
document or of one the reader does not see."""

import asyncio
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.db.editing import DocumentFrozen, JobOpen, StaleRevision
from app.db.rules import add_rule, drop_or_reject_rule, edit_rule, rules_of
from app.db.source_queries import Reader
from app.db.statement_editing import HandAnchor, Taken
from app.vocab.form_values import FieldError
from tests.db.test_editing import a_finding, an_open_job, document, edited_at, one
from tests.db.test_nodes import connection, owner, url, waiting_for_a_lock
from tests.db.test_rules import HUMAN, PROPOSED, REJECTED, a_run_s_rule

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_nodes


async def test_a_rule_added_by_hand_stands_after_the_others_on_the_blocks_chosen(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    first = await a_run_s_rule(url, connection, document)
    before = await edited_at(connection, document)

    made = await add_rule(
        connection, owner(document), document.id, "completion", "Bestanden ist, wer alle Module besteht.",
        [HandAnchor(blocks=("p2-b1", "p1-b1"))],
    )  # fmt: skip

    assert made is not None
    found = await rules_of(connection, document.id)
    assert [rule.id for rule in found] == [first, made]
    rule = found[1]
    assert (rule.kind, rule.verbatim, rule.origin, rule.review_status, rule.by_hand, rule.revision) == (
        "completion", "Bestanden ist, wer alle Module besteht.", HUMAN, PROPOSED, True, 1,
    )  # fmt: skip
    assert (rule.min_count, rule.amount_unit, rule.option_texts) == (None, None, ())
    assert [(anchor.page_start, anchor.page_end, anchor.blocks) for anchor in rule.anchors] == [
        (1, 2, ("p1-b1", "p2-b1"))
    ]
    assert await edited_at(connection, document) not in (None, before)


async def test_a_rule_added_by_hand_stands_somewhere(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    with pytest.raises(FieldError) as nowhere:
        await add_rule(connection, owner(document), document.id, "completion", "Bestanden.", [])
    with pytest.raises(FieldError) as blank:
        await add_rule(connection, owner(document), document.id, "completion", " ", [HandAnchor(page=1)])

    assert (nowhere.value.key, nowhere.value.problem) == ("anchors", "required")
    assert (blank.value.key, blank.value.problem) == ("verbatim", "required")
    assert await rules_of(connection, document.id) == []


async def test_a_run_s_rule_is_rejected_and_an_editor_s_deleted_with_the_findings_on_it(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    run_s = await a_run_s_rule(url, connection, document)
    by_hand = await add_rule(
        connection, owner(document), document.id, "completion", "Alle.", [HandAnchor(page=1)]
    )
    assert by_hand is not None
    await a_finding(connection, document, by_hand)

    rejected = await drop_or_reject_rule(connection, owner(document), run_s, 1)
    again = await drop_or_reject_rule(connection, owner(document), run_s, 2)
    deleted = await drop_or_reject_rule(connection, owner(document), by_hand, 1)

    assert (rejected, again, deleted) == (Taken("rejected", 2), Taken("rejected", 2), Taken("deleted", None))
    # a second rejection changes nothing, and says so
    assert (rejected is not None and rejected.changed, again is not None and again.changed) == (True, False)
    [rule] = await rules_of(connection, document.id)
    assert (rule.id, rule.review_status) == (run_s, REJECTED)
    assert await one(
        connection,
        "SELECT (SELECT count(*) FROM validation_finding),"
        " (SELECT count(*) FROM anchor WHERE frame_part_id = %s)",
        by_hand,
    ) == (0, 0)


async def test_a_rule_taken_away_on_another_revision_stays(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)

    with pytest.raises(StaleRevision):
        await drop_or_reject_rule(connection, owner(document), made, 2)


async def test_no_rule_is_changed_beside_an_open_job_or_of_a_frozen_document(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)
    job = await an_open_job(connection, document)

    with pytest.raises(JobOpen):
        await edit_rule(connection, owner(document), made, 1, {"max_count": 3})
    with pytest.raises(JobOpen):
        await add_rule(connection, owner(document), document.id, "completion", "Alle.", [HandAnchor(page=1)])
    with pytest.raises(JobOpen):
        await drop_or_reject_rule(connection, owner(document), made, 1)
    await connection.execute("DELETE FROM job WHERE id = %s", (job,))
    await connection.execute(
        "UPDATE document SET iri = 'https://example.org/d', frozen_at = now() WHERE id = %s", (document.id,)
    )
    with pytest.raises(DocumentFrozen):
        await edit_rule(connection, owner(document), made, 1, {"max_count": 3})


async def test_a_rule_is_none_to_who_sees_not_its_document(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)
    stranger = Reader(UUID(int=7), sees_all=False)

    assert await edit_rule(connection, stranger, made, 1, {"max_count": 3}) is None
    assert await drop_or_reject_rule(connection, stranger, made, 1) is None
    assert (
        await add_rule(connection, stranger, document.id, "completion", "Alle.", [HandAnchor(page=1)]) is None
    )
    [rule] = await rules_of(connection, document.id)
    assert rule.revision == 1


async def _second_waits(url: str, connection: psycopg.AsyncConnection, first: Any, second: Any) -> Any:
    """``first(other)`` in a transaction of another connection, ``second(connection)`` started meanwhile and
    seen waiting for the tree's lock; the second's outcome - or what it raised - once the first committed."""
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[Any] | None = None
        try:
            async with other.transaction():
                await first(other)
                waiting = asyncio.create_task(second(connection))
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            assert waiting is not None
            done, _ = await asyncio.wait([waiting])
    return done.pop()


async def test_two_editors_taking_a_rule_away_at_once_one_wins(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)

    lost = await _second_waits(
        url, connection,
        lambda other: drop_or_reject_rule(other, owner(document), made, 1),
        lambda mine: drop_or_reject_rule(mine, owner(document), made, 1),
    )  # fmt: skip

    assert isinstance(lost.exception(), StaleRevision)
    assert lost.exception().current == 2
    [rule] = await rules_of(connection, document.id)
    assert (rule.review_status, rule.revision) == (REJECTED, 2)


async def test_an_edit_behind_the_deletion_of_an_editor_s_rule_finds_none(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await add_rule(
        connection, owner(document), document.id, "completion", "Alle.", [HandAnchor(page=1)]
    )
    assert made is not None

    edited = await _second_waits(
        url, connection,
        lambda other: drop_or_reject_rule(other, owner(document), made, 1),
        lambda mine: edit_rule(mine, owner(document), made, 1, {"max_count": 3}),
    )  # fmt: skip

    assert edited.result() is None
    assert await rules_of(connection, document.id) == []


async def test_two_rules_added_at_once_take_a_place_each(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    def adding(wording: str) -> Any:
        return lambda on: add_rule(
            on, owner(document), document.id, "completion", wording, [HandAnchor(page=1)]
        )

    second = await _second_waits(url, connection, adding("Erste."), adding("Zweite."))

    assert second.result() is not None
    positions = await one(
        connection,
        "SELECT array_agg(position ORDER BY position), count(DISTINCT position) FROM frame_part"
        " WHERE document_id = %s",
        document.id,
    )
    assert positions == ([1, 2], 2)
    assert [rule.verbatim for rule in await rules_of(connection, document.id)] == ["Erste.", "Zweite."]
