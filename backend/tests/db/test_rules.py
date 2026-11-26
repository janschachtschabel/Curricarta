"""A document's rules as read (plan M3a I, E10; app/db/rule_rows.py): a rules frame part is the rule - X3's
reading, its parsed values in the schema's keys, its unit and kind of requirement named by their concepts -,
with its links by role and its anchors; and the rows the tests of an edit (test_rule_edits.py) and of a rule
added or taken away (test_rule_taking.py) share."""

from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.db.frame_parts import FramePartDraft, write_frame_parts
from app.db.nodes import write_subtree
from app.db.rules import rules_of
from app.domain.l1 import AnchorDraft
from tests.db.l1 import add_run
from tests.db.test_editing import document, one
from tests.db.test_nodes import CV, connection, node, statement, url

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
