"""An edit of a rule (plan M3a I; app/db/rules.py edit_rule): its fields and links set on its revision under
the tree's lock, the rule an editor's proposal after; what it may not take refused with the field and why,
nothing changed; a stale revision and two editors at once."""

import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.db.editing import StaleRevision
from app.db.nodes import write_subtree
from app.db.rules import Link, edit_rule, rules_of
from app.vocab.form_values import FieldError
from tests.db.l1 import add_conversion
from tests.db.test_editing import document, edited_at, one
from tests.db.test_nodes import CV, connection, node, owner, url, waiting_for_a_lock
from tests.db.test_rules import (
    CONFIRMED,
    HUMAN,
    MODEL,
    PROPOSED,
    REJECTED,
    a_run_s_rule,
    a_specification,
    rows,
)

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_nodes


async def test_an_edit_sets_values_and_links_and_makes_the_rule_an_editor_s_proposal(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)
    top, child, said = await rows(connection, document)
    before = await edited_at(connection, document)
    given = {
        "max_count": 3, "max_amount": Decimal("12.5"), "amount_unit": CV + "unit_hour",
        "option_texts": ["Modul C"], "options": [child, top, child], "applies_to": [top],
    }  # fmt: skip

    revision = await edit_rule(connection, owner(document), made, 1, given)

    [rule] = await rules_of(connection, document.id)
    assert revision == rule.revision == 2
    assert (rule.origin, rule.review_status, rule.max_count, rule.max_amount, rule.amount_unit) == (
        HUMAN, PROPOSED, 3, Decimal("12.5"), CV + "unit_hour",
    )  # fmt: skip
    assert rule.option_texts == ("Modul C",)
    # in the order given, each once
    assert rule.options == (Link(child, "node"), Link(top, "node"))
    assert rule.applies_to == (Link(top, "node"),)
    # stored in the schema's keys, as X3 writes them and X5's checks read them
    content = (await one(connection, "SELECT content FROM frame_part WHERE id = %s", made))[0]
    assert (content["maxCount"], content["maxAmount"], content["amountUnit"], content["minCount"]) == (
        3, 12.5, "hour", 2,
    )  # fmt: skip
    assert await edited_at(connection, document) not in (None, before)
    assert said  # a statement stands to be linked; the next test links one


async def test_a_prerequisite_rule_requires_a_statement_a_specification_and_a_variant(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document, ruleKind="prerequisite", optionTexts=[])
    _, _, said = await rows(connection, document)
    specification, variant = await a_specification(connection, document)

    await edit_rule(connection, owner(document), made, 1, {
        "requirement_kind": CV + "req_recommended", "requires": [said, variant],
        "applies_to": [specification],
    })  # fmt: skip

    [rule] = await rules_of(connection, document.id)
    assert rule.requires == (Link(said, "statement"), Link(variant, "variant"))
    assert rule.applies_to == (Link(specification, "specification"),)
    assert rule.requirement_kind == CV + "req_recommended"


async def test_an_edit_that_changes_nothing_leaves_the_rule_as_it_was(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)
    before = await edited_at(connection, document)

    revision = await edit_rule(connection, owner(document), made, 1, {
        "min_count": 2, "amount_unit": CV + "unit_ectsCredit", "options": [], "kind": "selection",
    })  # fmt: skip

    [rule] = await rules_of(connection, document.id)
    assert (revision, rule.revision, rule.origin) == (1, 1, MODEL)
    assert await edited_at(connection, document) == before


# each an edit the rule may not take: the field and the problem it is refused with
REFUSED: dict[str, tuple[dict[str, Any], str, str]] = {
    "a kind its options leave no room for": (
        {"kind": "completion", "options": ["top"]}, "options", "not_held"
    ),
    "a required item of a selection": ({"requires": ["top"]}, "requires", "not_held"),
    "a unit of another list": ({"amount_unit": CV + "req_formal"}, "amount_unit", "not_offered"),
    "a kind of requirement of another list": (
        {"requirement_kind": CV + "unit_hour"}, "requirement_kind", "not_offered"
    ),
    "a row of no document's": ({"applies_to": ["unknown"]}, "applies_to", "unknown_value"),
    "a field the rule has not": ({"title": "Neu"}, "title", "unknown"),
    "a blank wording": ({"verbatim": " "}, "verbatim", "required"),
    "an overlong wording": ({"verbatim": "x" * 20_001}, "verbatim", "too_long"),
}  # fmt: skip


@pytest.mark.parametrize("name", list(REFUSED))
async def test_an_edit_the_rule_may_not_take_changes_nothing(
    url: str, connection: psycopg.AsyncConnection, document: Any, name: str
) -> None:
    made = await a_run_s_rule(url, connection, document)
    top, _, _ = await rows(connection, document)
    given, field, problem = REFUSED[name]
    ids = {"top": top, "unknown": UUID(int=1)}
    given = {key: [ids[each] for each in value] if key in ("options", "requires", "applies_to") else value
             for key, value in given.items()}  # fmt: skip

    with pytest.raises(FieldError) as refused:
        await edit_rule(connection, owner(document), made, 1, given)

    assert (refused.value.key, refused.value.problem) == (field, problem)
    [rule] = await rules_of(connection, document.id)
    assert (rule.revision, rule.options, rule.kind) == (1, (), "selection")


async def test_a_row_of_another_document_is_no_target(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)
    with psycopg.connect(url, autocommit=True) as sync:
        other = add_conversion(sync, b"\x05" * 32, owner=document.owner_id)
    from app.db.documents import create_document  # the other document of the same owner

    elsewhere = await create_document(
        connection, owner(document), third_party_content=False, source_id=other["source"],
        conversion_id=other["conversion"], sector="school",
    )  # fmt: skip
    foreign = await write_subtree(connection, elsewhere.id, node())

    with pytest.raises(FieldError) as refused:
        await edit_rule(connection, owner(document), made, 1, {"applies_to": [foreign]})

    assert (refused.value.key, refused.value.problem) == ("applies_to", "unknown_value")


async def test_a_rejected_statement_is_no_target(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document, ruleKind="prerequisite")
    _, _, said = await rows(connection, document)
    await connection.execute("UPDATE statement SET review_status_iri = %s WHERE id = %s", (REJECTED, said))

    with pytest.raises(FieldError) as refused:
        await edit_rule(connection, owner(document), made, 1, {"requires": [said]})

    assert (refused.value.key, refused.value.problem) == ("requires", "unknown_value")


async def test_an_edit_on_another_revision_is_stale(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)
    await edit_rule(connection, owner(document), made, 1, {"max_count": 4})

    with pytest.raises(StaleRevision) as stale:
        await edit_rule(connection, owner(document), made, 1, {"max_count": 3})

    assert stale.value.current == 2


async def test_two_editors_of_a_rule_at_once_one_wins(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    # both on revision 1: the second waits for the tree's lock, then finds the revision the first wrote
    made = await a_run_s_rule(url, connection, document)
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[int | None] | None = None
        try:
            async with other.transaction():
                assert await edit_rule(other, owner(document), made, 1, {"max_count": 3}) == 2
                waiting = asyncio.create_task(
                    edit_rule(connection, owner(document), made, 1, {"max_count": 4})
                )
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            with pytest.raises(StaleRevision) as lost:
                if waiting is not None:
                    await waiting

    assert lost.value.current == 2
    [rule] = await rules_of(connection, document.id)
    assert (rule.max_count, rule.revision) == (3, 2)


async def test_a_confirmed_rule_an_editor_changes_is_proposed_again(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)
    await connection.execute("UPDATE frame_part SET review_status_iri = %s WHERE id = %s", (CONFIRMED, made))

    await edit_rule(connection, owner(document), made, 1, {"verbatim": "Drei aus vier."})

    [rule] = await rules_of(connection, document.id)
    assert (rule.verbatim, rule.review_status, rule.origin) == ("Drei aus vier.", PROPOSED, HUMAN)
