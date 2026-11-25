"""A specification edited (plan M3a H1; app/db/specifications.py, app/db/values.py): its title and field set
on its revision, its applicability contexts set with its values as a whole - each context with its sector,
formality, institution and target group as written, and time spans and levels of its own -, and read back
by document with its variants. Under the tree's lock, as every edit; the key, which its IRI is made of,
stays."""

import asyncio
import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.db.anchors import new_entity
from app.db.editing import DocumentFrozen, StaleRevision
from app.db.findings import findings_of
from app.db.review import ReviewItem, set_review
from app.db.runs import x5_owed
from app.db.source_queries import Reader
from app.db.specifications import edit_specification, specifications_of
from app.db.values import UnknownValue, ValueRefused, replace_values, values_of
from app.domain.l2 import ContextDraft, Holder, LevelDraft, TimeSpanDraft, ValueDrafts
from app.vocab.form_values import FieldError
from tests.db.test_editing import a_finding, document, edited_at, one
from tests.db.test_nodes import CV, connection, owner, url, waiting_for_a_lock
from tests.db.test_values import holders, revision_of

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

LVL = "https://w3id.org/wlo/curriculum/level/"
HUMAN, PROPOSED, CONFIRMED = CV + "orig_human", CV + "rev_proposed", CV + "rev_confirmed"
SCHOOL, FORMAL = CV + "sec_school", CV + "form_formal"
GRADE = TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=Decimal(5), span_to=Decimal(6))
EQF4 = LevelDraft(level=LVL + "EQF-4")
CONTEXT = ContextDraft(
    sector=SCHOOL, formality=FORMAL, institution_text="Gymnasium", target_group_text="Erwachsene",
    levels=(EQF4,), time_spans=(GRADE,),
)  # fmt: skip


async def specification(connection: psycopg.AsyncConnection, document: Any) -> Holder:
    return (await holders(connection, document))["specification"]


async def test_a_specification_s_title_and_field_are_set_on_its_revision(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await specification(connection, document)

    revision = await edit_specification(
        connection, owner(document), made.id, 1, {"title": "Physik", "field_text": "Naturwissenschaften"}
    )

    assert revision == 2 == await revision_of(connection, made)
    assert await one(
        connection, "SELECT key, title, field_text FROM specification WHERE id = %s", made.id
    ) == ("lp", "Physik", "Naturwissenschaften")
    assert await edited_at(connection, document) is not None
    assert await x5_owed(connection, document.id)
    # a blank field empties it; one left out stays; the same again changes nothing
    assert await edit_specification(connection, owner(document), made.id, 2, {"field_text": " "}) == 3
    assert await edit_specification(connection, owner(document), made.id, 3, {"title": "Physik"}) == 3
    assert await one(connection, "SELECT title, field_text FROM specification WHERE id = %s", made.id) == (
        "Physik",
        None,
    )


async def test_a_specification_edit_is_refused_and_changes_nothing(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await specification(connection, document)
    refused = [
        ({"title": " "}, ("title", "required")),
        ({"title": "x" * 1001}, ("title", "too_long")),
        ({"field_text": "x" * 2001}, ("field_text", "too_long")),
        ({"field_text": "a\x00"}, ("field_text", "not_storable")),
        ({"key": "neu"}, ("key", "unknown")),  # its IRI is made of it
    ]

    for given, problem in refused:
        with pytest.raises(FieldError) as error:
            await edit_specification(connection, owner(document), made.id, 1, given)
        assert (error.value.key, error.value.problem) == problem
    with pytest.raises(StaleRevision) as stale:
        await edit_specification(connection, owner(document), made.id, 2, {"title": "Physik"})
    assert stale.value.current == 1
    await connection.execute(
        "UPDATE document SET iri = 'https://example.org/curriculum/1', frozen_at = now() WHERE id = %s",
        (document.id,),
    )
    with pytest.raises(DocumentFrozen):
        await edit_specification(connection, owner(document), made.id, 1, {"title": "Physik"})
    assert await one(connection, "SELECT title, revision FROM specification WHERE id = %s", made.id) == (
        "LP",
        1,
    )


async def test_a_specification_is_none_to_who_sees_not_its_document(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await specification(connection, document)
    stranger = Reader(uuid.uuid4(), sees_all=False)

    assert await edit_specification(connection, stranger, made.id, 1, {"title": "Physik"}) is None
    assert await edit_specification(connection, owner(document), uuid.uuid4(), 1, {"title": "P"}) is None


async def test_a_context_holds_sector_formality_time_and_level(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await specification(connection, document)

    revision = await replace_values(connection, owner(document), made, 1, ValueDrafts(contexts=(CONTEXT,)))

    assert revision == 2
    [context] = (await values_of(connection, document.id))[made].contexts
    value = context.value
    assert (value.sector, value.formality, value.institution_text, value.target_group_text) == (
        SCHOOL, FORMAL, "Gymnasium", "Erwachsene",
    )  # fmt: skip
    assert (value.levels, value.time_spans) == ((), ())  # they stand beside, with their own statement
    assert [level.value.level for level in context.levels] == [LVL + "EQF-4"]
    assert [span.value.span_from for span in context.time_spans] == [Decimal(5)]
    stated = [context.stated, *(each.stated for each in context.levels)]
    stated += [each.stated for each in context.time_spans]
    assert {(each.origin, each.review_status, each.revision) for each in stated} == {(HUMAN, PROPOSED, 1)}
    assert await one(
        connection,
        "SELECT (SELECT count(*) FROM level_assignment WHERE specification_id IS NULL),"
        " (SELECT count(*) FROM time_span WHERE specification_id IS NULL)",
    ) == (1, 1)


async def test_a_context_kept_by_its_id_keeps_its_values_and_one_left_out_goes_with_them(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await specification(connection, document)
    second = ContextDraft(sector=SCHOOL)
    await replace_values(connection, owner(document), made, 1, ValueDrafts(contexts=(CONTEXT, second)))
    first, dropped = (await values_of(connection, document.id))[made].contexts
    level = first.levels[0]
    # a finding on a value of the context that goes, which goes with it
    await connection.execute(
        "INSERT INTO validation_finding (id, document_id, rule, severity, focus_id, message)"
        " VALUES (gen_random_uuid(), %s, 'shacl.X', 'warning', %s, 'm')",
        (document.id, dropped.value.id),
    )

    changed = replace(
        CONTEXT, formality=None, id=first.value.id, time_spans=(),
        levels=(replace(EQF4, id=level.value.id), LevelDraft(level=LVL + "EQF-5")),
    )  # fmt: skip
    revision = await replace_values(connection, owner(document), made, 2, ValueDrafts(contexts=(changed,)))

    assert revision == 3
    [context] = (await values_of(connection, document.id))[made].contexts
    assert (context.value.id, context.value.formality, context.stated.revision) == (first.value.id, None, 2)
    assert (context.levels[0].value.id, context.levels[0].stated.revision) == (level.value.id, 1)
    assert [each.value.level for each in context.levels] == [LVL + "EQF-4", LVL + "EQF-5"]
    assert context.time_spans == ()
    assert await one(
        connection,
        "SELECT (SELECT count(*) FROM applicability_context), (SELECT count(*) FROM validation_finding)",
    ) == (1, 0)


async def test_a_context_is_a_specification_s_alone_and_its_values_its_own(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await holders(connection, document)
    await replace_values(
        connection,
        owner(document),
        made["specification"],
        1,
        ValueDrafts(levels=(EQF4,), contexts=(CONTEXT,)),
    )
    held = (await values_of(connection, document.id))[made["specification"]]
    own_level, context = held.levels[0], held.contexts[0]
    before = await values_of(connection, document.id)

    with pytest.raises(ValueRefused) as at_node:
        await replace_values(connection, owner(document), made["node"], 1, ValueDrafts(contexts=(CONTEXT,)))
    assert at_node.value.check == "not_held"
    unknown = [
        # the specification's own level is none of the context's, the context's none of the specification's
        ValueDrafts(
            levels=(EQF4,),
            contexts=(replace(CONTEXT, id=context.value.id, levels=(replace(EQF4, id=own_level.value.id),)),),
        ),
        ValueDrafts(levels=(replace(EQF4, id=context.levels[0].value.id),)),
        # a new context's values are new as it is
        ValueDrafts(contexts=(replace(CONTEXT, levels=(replace(EQF4, id=context.levels[0].value.id),)),)),
    ]
    for drafts in unknown:
        with pytest.raises(UnknownValue):
            await replace_values(connection, owner(document), made["specification"], 2, drafts)
    assert await values_of(connection, document.id) == before


async def test_a_document_s_specifications_are_read_with_their_variants_contexts_and_values(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await specification(connection, document)
    variant = await new_entity(connection, "variant")
    await connection.execute(
        "INSERT INTO variant (id, specification_id, key, label, variant_kind_scheme, variant_kind_iri)"
        " VALUES (%s, %s, 'g8', 'G8', %s, %s)",
        (variant, made.id, CV + "VariantKinds", CV + "var_track"),
    )
    await replace_values(
        connection, owner(document), made, 1, ValueDrafts(levels=(EQF4,), contexts=(CONTEXT,))
    )

    [read] = await specifications_of(connection, document.id)

    assert (read.id, read.key, read.spec_kind, read.title, read.field_text, read.revision) == (
        made.id, "lp", "curriculum", "LP", None, 2,
    )  # fmt: skip
    assert [(each.key, each.label, each.variant_kind) for each in read.variants] == [
        ("g8", "G8", CV + "var_track")
    ]
    assert [level.value.level for level in read.values.levels] == [LVL + "EQF-4"]
    assert [context.value.institution_text for context in read.values.contexts] == ["Gymnasium"]


async def test_a_review_of_a_context_or_its_value_counts_its_specification_s_revision(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the specification's revision is the token its set is made on: a set read before the review is stale
    made = await specification(connection, document)
    await replace_values(connection, owner(document), made, 1, ValueDrafts(contexts=(CONTEXT,)))
    [context] = (await values_of(connection, document.id))[made].contexts
    level = context.levels[0]
    assert context.value.id is not None and level.value.id is not None  # stored rows

    items = [
        ReviewItem("applicability_context", context.value.id, 1),
        ReviewItem("level_assignment", level.value.id, 1),
    ]
    revisions = await set_review(connection, document.id, CONFIRMED, items)

    assert revisions == {context.value.id: 2, level.value.id: 2}
    assert await revision_of(connection, made) == 3
    [reviewed] = (await values_of(connection, document.id))[made].contexts
    assert {reviewed.stated.review_status, reviewed.levels[0].stated.review_status} == {CONFIRMED}


async def test_a_finding_on_a_context_or_its_value_names_the_specification(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await specification(connection, document)
    await replace_values(connection, owner(document), made, 1, ValueDrafts(contexts=(CONTEXT,)))
    [context] = (await values_of(connection, document.id))[made].contexts
    focus = [context.value.id, context.levels[0].value.id, context.time_spans[0].value.id]
    for each in focus:
        await a_finding(connection, document, each)

    rows = (await findings_of(connection, document.id)).rows

    assert {(row.focus_id, row.holder_kind, row.holder_id, row.focus_label) for row in rows} == {
        (each, "specification", made.id, "LP") for each in focus
    }


@pytest.mark.parametrize("second", ["edit", "values"])
async def test_two_editors_of_a_specification_at_once_one_wins(
    url: str, connection: psycopg.AsyncConnection, document: Any, second: str
) -> None:
    # both on revision 1: the second waits for the tree's lock, then finds the revision the first wrote - an
    # edit of its title against an edit, or against a set of its values
    made = await specification(connection, document)
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[int | None] | None = None
        try:
            async with other.transaction():
                assert await edit_specification(other, owner(document), made.id, 1, {"title": "Physik"}) == 2
                waiting = asyncio.create_task(
                    edit_specification(connection, owner(document), made.id, 1, {"title": "Chemie"})
                    if second == "edit"
                    else replace_values(
                        connection, owner(document), made, 1, ValueDrafts(contexts=(CONTEXT,))
                    )
                )
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            with pytest.raises(StaleRevision) as lost:
                if waiting is not None:
                    await waiting

    assert lost.value.current == 2
    assert await one(connection, "SELECT title, revision FROM specification WHERE id = %s", made.id) == (
        "Physik",
        2,
    )
    assert await one(connection, "SELECT count(*) FROM applicability_context") == (0,)
