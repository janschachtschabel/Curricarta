"""A node's placements as the editors write them (plan M3a K; app/db/placements.py, app/db/placement_rows.py):
set as the node's whole on its revision - one named by its id kept, one left out gone with its values and the
findings on them, a new or changed one an editor's proposal -, each in a specification or a variant of the
document, at a node of it or nowhere in particular, with an obligation of the list. Under the tree's lock, as
every edit."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from app.db.anchors import new_entity
from app.db.editing import StaleRevision, drop_node
from app.db.placement_rows import placements_of
from app.db.placements import replace_placements
from app.db.source_queries import Reader
from app.db.values import replace_values
from app.domain.l2 import Holder, LevelDraft, TimeSpanDraft, ValueDrafts, ValueRefused
from app.domain.placements import PlacementDraft
from app.vocab.form_values import FieldError
from tests.db.test_editing import a_finding, document, edited_at, one
from tests.db.test_nodes import CV, connection, owner, url
from tests.db.test_values import holders

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

BINDING, ELECTIVE = CV + "obl_binding", CV + "obl_elective"
HUMAN, PROPOSED = CV + "orig_human", CV + "rev_proposed"
SEMESTER = TimeSpanDraft(time_kind=CV + "time_semester", span_from=Decimal(3))
LEVEL = LevelDraft(level="https://w3id.org/wlo/curriculum/level/EQF-4")


async def placed(connection: psycopg.AsyncConnection, document: Any) -> dict[str, UUID]:
    """A module and an area of the document, its specification and a variant of it."""
    held = await holders(connection, document)
    variant = await new_entity(connection, "variant")
    await connection.execute(
        "INSERT INTO variant (id, specification_id, key, label, variant_kind_scheme, variant_kind_iri)"
        " VALUES (%s, %s, 'v', 'Schwerpunkt', %s, %s)",
        (variant, held["specification"].id, CV + "VariantKinds", CV + "var_track"),
    )
    area = await new_entity(connection, "node")
    await connection.execute(
        "INSERT INTO node (id, document_id, position, function_scheme, function_iri, origin_scheme,"
        " origin_iri, review_status_scheme, review_status_iri) SELECT %s, document_id, 2, function_scheme,"
        " function_iri, origin_scheme, origin_iri, review_status_scheme, review_status_iri"
        " FROM node WHERE id = %s",
        (area, held["node"].id),
    )
    return {
        "module": held["node"].id,
        "area": area,
        "specification": held["specification"].id,
        "variant": variant,
    }


async def rows(connection: psycopg.AsyncConnection, document: Any) -> list[Any]:
    return await placements_of(connection, document.id)


async def test_a_set_places_the_node_each_placement_an_editor_s_proposal_in_its_order(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    drafts = [
        PlacementDraft(BINDING, specification_id=made["specification"], in_node_id=made["area"],
                       grade_weight=Decimal("1.5")),
        PlacementDraft(ELECTIVE, variant_id=made["variant"]),
        PlacementDraft(ELECTIVE, specification_id=made["specification"], variant_id=made["variant"]),
    ]  # fmt: skip

    revision = await replace_placements(connection, owner(document), made["module"], 1, drafts)

    found = await rows(connection, document)
    assert revision == 2
    assert [(row.node_id, row.position, row.specification_id, row.variant_id, row.in_node_id, row.obligation,
             row.grade_weight) for row in found] == [
        (made["module"], 1, made["specification"], None, made["area"], BINDING, Decimal("1.5")),
        (made["module"], 2, None, made["variant"], None, ELECTIVE, None),
        (made["module"], 3, made["specification"], made["variant"], None, ELECTIVE, None),
    ]  # fmt: skip
    assert {(row.stated.origin, row.stated.review_status, row.stated.revision, row.iri) for row in found} == {
        (HUMAN, PROPOSED, 1, None)
    }
    assert await one(connection, "SELECT revision FROM node WHERE id = %s", made["module"]) == (2,)
    assert await edited_at(connection, document) is not None


async def test_a_set_keeps_what_it_names_changes_moves_and_takes_away_the_rest(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    first, second, third = (
        PlacementDraft(BINDING, specification_id=made["specification"]),
        PlacementDraft(ELECTIVE, variant_id=made["variant"]),
        PlacementDraft(BINDING, specification_id=made["specification"], in_node_id=made["area"]),
    )
    await replace_placements(connection, owner(document), made["module"], 1, [first, second, third])
    kept, moved, gone = (row.id for row in await rows(connection, document))
    await replace_values(
        connection, owner(document), Holder("placement", gone), 1, ValueDrafts(time_spans=(SEMESTER,))
    )
    [span] = await one(connection, "SELECT array_agg(id) FROM time_span WHERE placement_id = %s", gone)
    finding_at_span = await a_finding(connection, document, span[0])
    finding_at_gone = await a_finding(connection, document, gone)

    revision = await replace_placements(  # on the node's revision 3: the values' set counted it
        connection, owner(document), made["module"], 3,
        [PlacementDraft(BINDING, made["specification"], made["variant"], id=moved),
         PlacementDraft(ELECTIVE, specification_id=made["specification"], id=kept, grade_weight=Decimal(2))],
    )  # fmt: skip

    found = {row.id: row for row in await rows(connection, document)}
    assert revision == 4
    assert set(found) == {kept, moved}
    assert (found[moved].position, found[moved].obligation, found[moved].stated.revision) == (1, BINDING, 2)
    assert (found[kept].position, found[kept].grade_weight, found[kept].stated.revision) == (2, Decimal(2), 2)
    assert await one(connection, "SELECT count(*) FROM time_span") == (0,)
    assert await one(
        connection,
        "SELECT count(*) FROM validation_finding WHERE id = ANY(%s)",
        [finding_at_span, finding_at_gone],
    ) == (0,)


async def test_a_placement_moved_alone_keeps_its_revision_and_a_set_changing_nothing_the_node_s(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    one_, two = (
        PlacementDraft(BINDING, specification_id=made["specification"]),
        PlacementDraft(ELECTIVE, variant_id=made["variant"]),
    )
    await replace_placements(connection, owner(document), made["module"], 1, [one_, two])
    first, second = (row.id for row in await rows(connection, document))
    named = [PlacementDraft(BINDING, specification_id=made["specification"], id=first),
             PlacementDraft(ELECTIVE, variant_id=made["variant"], id=second)]  # fmt: skip

    same = await replace_placements(connection, owner(document), made["module"], 2, named)
    swapped = await replace_placements(connection, owner(document), made["module"], 2, named[::-1])

    found = {row.id: (row.position, row.stated.revision) for row in await rows(connection, document)}
    assert (same, swapped) == (2, 3)
    assert found == {second: (1, 1), first: (2, 1)}


@pytest.mark.parametrize(
    ("draft", "field", "problem"),
    [
        ({"obligation": CV + "form_formal"}, "placements[0].obligation", "not_offered"),
        ({"specification_id": None}, "placements[0].specification_id", "required"),
        ({"specification_id": "foreign"}, "placements[0].specification_id", "not_offered"),
        ({"variant_id": "other"}, "placements[0].variant_id", "not_offered"),
        ({"in_node_id": "module"}, "placements[0].in_node_id", "not_offered"),
        ({"in_node_id": "foreign"}, "placements[0].in_node_id", "not_offered"),
        ({"id": "foreign"}, "placements[0]", "unknown_value"),
    ],
    ids=["obligation-of-another-list", "nowhere", "foreign-specification", "variant-of-another", "in-itself",
         "foreign-place", "unknown-id"],
)  # fmt: skip
async def test_a_placement_the_store_does_not_take_refuses_the_set_and_nothing_is_written(
    connection: psycopg.AsyncConnection, document: Any, draft: dict[str, Any], field: str, problem: str
) -> None:
    made = await placed(connection, document)
    other = await new_entity(connection, "specification")
    await connection.execute(
        "INSERT INTO specification (id, document_id, key, spec_kind, title)"
        " VALUES (%s, %s, 'b', 'curriculum', 'B')",
        (other, document.id),
    )
    named = made | {"foreign": uuid4(), "other": made["variant"]}
    given = {
        key: named.get(value, value) if isinstance(value, str) else value for key, value in draft.items()
    }
    if draft.get("variant_id") == "other":
        given["specification_id"] = other
    fields: dict[str, Any] = {"obligation": BINDING, "specification_id": made["specification"]} | given

    with pytest.raises(FieldError) as refused:
        await replace_placements(connection, owner(document), made["module"], 1, [PlacementDraft(**fields)])

    assert (refused.value.key, refused.value.problem) == (field, problem)
    assert await one(connection, "SELECT count(*) FROM placement") == (0,)
    assert await one(connection, "SELECT revision FROM node WHERE id = %s", made["module"]) == (1,)


async def test_a_set_on_another_revision_is_stale_and_one_the_reader_does_not_see_none(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    draft = [PlacementDraft(BINDING, specification_id=made["specification"])]

    with pytest.raises(StaleRevision) as stale:
        await replace_placements(connection, owner(document), made["module"], 2, draft)
    stranger = await replace_placements(connection, Reader(uuid4(), sees_all=False), made["module"], 1, draft)

    assert (stale.value.current, stranger) == (1, None)
    assert await one(connection, "SELECT count(*) FROM placement") == (0,)


async def test_a_placement_holds_time_spans_and_workloads_and_no_levels(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    await replace_placements(
        connection,
        owner(document),
        made["module"],
        1,
        [PlacementDraft(BINDING, specification_id=made["specification"])],
    )
    [placement] = await rows(connection, document)
    holder = Holder("placement", placement.id)

    revision = await replace_values(
        connection, owner(document), holder, 1, ValueDrafts(time_spans=(SEMESTER,))
    )
    with pytest.raises(ValueRefused) as refused:
        await replace_values(connection, owner(document), holder, 2, ValueDrafts(levels=(LEVEL,)))

    [read] = await rows(connection, document)
    assert revision == 2
    assert refused.value.check == "not_held"
    assert [span.value.time_kind for span in read.values.time_spans] == [CV + "time_semester"]


async def test_a_node_taken_away_takes_its_placements_and_those_at_it_with_the_findings_on_them(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    await replace_placements(
        connection, owner(document), made["module"], 1,
        [PlacementDraft(BINDING, specification_id=made["specification"], in_node_id=made["area"])],
    )  # fmt: skip
    [placement] = await rows(connection, document)
    await replace_values(connection, owner(document), Holder("placement", placement.id), 1,
                         ValueDrafts(time_spans=(SEMESTER,)))  # fmt: skip
    [span] = await one(
        connection, "SELECT array_agg(id) FROM time_span WHERE placement_id = %s", placement.id
    )
    findings = [
        await a_finding(connection, document, placement.id),
        await a_finding(connection, document, span[0]),
    ]

    await drop_node(connection, owner(document), made["area"], 1)

    assert await one(connection, "SELECT count(*) FROM placement") == (0,)
    assert await one(connection, "SELECT count(*) FROM validation_finding WHERE id = ANY(%s)", findings) == (
        0,
    )


async def test_a_placement_keeps_an_obligation_retired_since_until_it_is_changed(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await placed(connection, document)
    in_specification: dict[str, Any] = {"specification_id": made["specification"]}
    await replace_placements(
        connection, owner(document), made["module"], 1, [PlacementDraft(ELECTIVE, **in_specification)]
    )
    [placement] = await rows(connection, document)
    await connection.execute("UPDATE vocab_concept SET retired_in = 1 WHERE iri = %s", (ELECTIVE,))

    kept = await replace_placements(
        connection, owner(document), made["module"], 2,
        [PlacementDraft(ELECTIVE, **in_specification, grade_weight=Decimal(1), id=placement.id)],
    )  # fmt: skip
    with pytest.raises(FieldError) as refused:
        await replace_placements(connection, owner(document), made["module"], 3,
                                 [PlacementDraft(ELECTIVE, **in_specification)])  # fmt: skip

    assert kept == 3
    assert (refused.value.key, refused.value.problem) == ("placements[0].obligation", "not_offered")
