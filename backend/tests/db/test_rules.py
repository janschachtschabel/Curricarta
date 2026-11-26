"""A document's rules as the editors read and set them (plan M3a I, E10; app/db/rules.py): a rules frame part
is the rule - X3's reading, its parsed values in the schema's keys, its units and kinds of requirement named
by their concepts -, with what it applies to, its options and what it requires as links to rows of its
document. An edit sets them on the rule's revision and makes it an editor's proposal; a rule added by hand
stands on blocks chosen as a statement does; one taken away is deleted where an editor made it, else
rejected."""

import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.db.editing import DocumentFrozen, JobOpen, StaleRevision
from app.db.frame_parts import FramePartDraft, write_frame_parts
from app.db.nodes import write_subtree
from app.db.rules import Link, add_rule, drop_or_reject_rule, edit_rule, rules_of
from app.db.source_queries import Reader
from app.db.statement_editing import HandAnchor, Taken
from app.domain.l1 import AnchorDraft
from app.vocab.form_values import FieldError
from tests.db.l1 import add_conversion, add_run
from tests.db.test_editing import a_finding, an_open_job, document, edited_at, one
from tests.db.test_nodes import CV, connection, node, owner, statement, url, waiting_for_a_lock

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_nodes

HUMAN, MODEL = CV + "orig_human", CV + "orig_model"
PROPOSED, CONFIRMED, REJECTED = CV + "rev_proposed", CV + "rev_confirmed", CV + "rev_rejected"
RULE: dict[str, Any] = {
    "verbatim": "Zwei aus vier Wahlmodulen im Umfang von mindestens 10 LP.", "ruleKind": "selection",
    "minCount": 2, "maxCount": 2, "minAmount": 10, "maxAmount": None, "amountUnit": "ectsCredit",
    "requirementKind": None, "maxShare": None, "optionTexts": ["Modul A", "Modul B"],
}  # fmt: skip


async def a_run_s_rule(url: str, connection: psycopg.AsyncConnection, document: Any, **content: Any) -> UUID:
    """A rule X3 read, on block p1-b1, after the document's other frame parts."""
    with psycopg.connect(url, autocommit=True) as sync:
        run = add_run(sync, document.id, "stage_X3")
    draft = FramePartDraft("rules", RULE | content, AnchorDraft(("p1-b1",), 1), MODEL, PROPOSED)
    [made] = await write_frame_parts(connection, document.id, document.conversion_id, [draft], run_id=run)
    return made


async def rows(connection: psycopg.AsyncConnection, document: Any) -> tuple[UUID, UUID, UUID]:
    """A node with a child and the child's statement, written by a run: the top, the child, the statement."""
    top = await write_subtree(
        connection, document.id, node(children=(node("fn_unit", statements=(statement("Sie messen."),)),))
    )
    child, said = await one(
        connection,
        "SELECT n.id, s.id FROM node n JOIN statement s ON s.node_id = n.id WHERE n.parent_id = %s",
        top,
    )
    return top, child, said


async def test_a_run_s_rule_is_read_with_its_values_named_by_their_concepts(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document, requirementKind="formal", maxShare=0.25)
    operators = FramePartDraft("operators", {"lemma": "nennen"}, AnchorDraft(("p1-b1",), 1), MODEL, PROPOSED)
    with psycopg.connect(url, autocommit=True) as sync:
        run = add_run(sync, document.id, "stage_X3")
    await write_frame_parts(connection, document.id, document.conversion_id, [operators], run_id=run)

    [rule] = await rules_of(connection, document.id)

    assert (rule.id, rule.kind, rule.verbatim, rule.origin, rule.review_status) == (
        made, "selection", RULE["verbatim"], MODEL, PROPOSED,
    )  # fmt: skip
    assert (rule.revision, rule.by_hand) == (1, False)
    assert (rule.min_count, rule.max_count, rule.min_amount, rule.max_amount, rule.max_share) == (
        2, 2, Decimal(10), None, Decimal("0.25"),
    )  # fmt: skip
    assert (rule.amount_unit, rule.requirement_kind) == (CV + "unit_ectsCredit", CV + "req_formal")
    assert rule.option_texts == ("Modul A", "Modul B")
    assert (rule.applies_to, rule.options, rule.requires) == ((), (), ())
    assert [(anchor.page_start, anchor.blocks) for anchor in rule.anchors] == [(1, ("p1-b1",))]


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


async def a_specification(connection: psycopg.AsyncConnection, document: Any) -> tuple[UUID, UUID]:
    specification, variant = (await one(connection, "SELECT gen_random_uuid(), gen_random_uuid()"))[:2]
    await connection.execute("INSERT INTO entity (id, kind) VALUES (%s, 'specification'), (%s, 'variant')",
                             (specification, variant))  # fmt: skip
    await connection.execute(
        "INSERT INTO specification (id, document_id, key, spec_kind, title)"
        " VALUES (%s, %s, 'lp', 'curriculum', 'LP')",
        (specification, document.id),
    )
    await connection.execute(
        "INSERT INTO variant (id, specification_id, key, label, variant_kind_scheme, variant_kind_iri)"
        " VALUES (%s, %s, 'g8', 'G8', %s, %s)",
        (variant, specification, CV + "VariantKinds", CV + "var_track"),
    )
    return specification, variant


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


async def test_a_confirmed_rule_an_editor_changes_is_proposed_again(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await a_run_s_rule(url, connection, document)
    await connection.execute("UPDATE frame_part SET review_status_iri = %s WHERE id = %s", (CONFIRMED, made))

    await edit_rule(connection, owner(document), made, 1, {"verbatim": "Drei aus vier."})

    [rule] = await rules_of(connection, document.id)
    assert (rule.verbatim, rule.review_status, rule.origin) == ("Drei aus vier.", PROPOSED, HUMAN)
