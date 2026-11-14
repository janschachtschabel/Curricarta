"""The catalogue of MEM's plans in the database (app/db/mem_plans.py, plan M2 E11): a graph's plans replaced
as one, the others left; found by Land, subject and title, a page at a time, with their number."""

from collections.abc import AsyncIterator
from dataclasses import replace

import psycopg
import pytest

from app.db.mem_plans import MemPlan, find_plans, graph_size, replace_graph
from app.db.migrate import migrate

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

LP = "https://w3id.org/lehrplan/ontology/"
RP, SN = "https://w3id.org/lehrplan/rp", "https://w3id.org/lehrplan/sn"
RLP, SAX = LP + "LP_3000046", LP + "LP_3000047"


def plan(name: str, graph: str = RP, **values: object) -> MemPlan:
    fields: dict[str, object] = {
        "iri": f"https://w3id.org/p/{name}",
        "graph": graph,
        "land_iri": RLP if graph == RP else SAX,
        "title": name,
        "class_iri": LP + "LP_0000438",
        "subjects": (),
        "school_types": (),
        "licence": None,
        "attribution": "MEM-Schule",
        **values,
    }
    return MemPlan(**fields)  # type: ignore[arg-type]


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    migrate(database_url)
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as connection:
        yield connection


async def test_a_graph_s_plans_are_written_and_found_with_when_they_were_read(
    db: psycopg.AsyncConnection,
) -> None:
    written = plan("Deutsch", subjects=("https://w3id.org/s/1",), school_types=("https://w3id.org/a/1",))

    assert await replace_graph(db, RP, [written]) == (1, 0)
    found, total = await find_plans(db)

    assert total == 1
    assert replace(found[0], read_at=None) == written
    assert found[0].read_at is not None


async def test_a_graph_read_again_drops_the_plans_it_holds_no_more_and_leaves_other_graphs(
    db: psycopg.AsyncConnection,
) -> None:
    await replace_graph(db, RP, [plan("Deutsch"), plan("Mathe")])
    await replace_graph(db, SN, [plan("Physik", SN)])

    assert await replace_graph(db, RP, [plan("Mathe", title="Mathematik")]) == (1, 1)

    found, _ = await find_plans(db)
    assert sorted((each.graph, each.title) for each in found) == [(RP, "Mathematik"), (SN, "Physik")]


async def test_a_plan_read_again_says_when(db: psycopg.AsyncConnection) -> None:
    await replace_graph(db, RP, [plan("Deutsch")])
    (first,), _ = await find_plans(db)

    await replace_graph(db, RP, [plan("Deutsch")])

    (again,), _ = await find_plans(db)
    assert first.read_at is not None and again.read_at is not None
    assert again.read_at > first.read_at


async def test_a_plan_another_graph_held_moves_to_the_graph_that_holds_it_now(
    db: psycopg.AsyncConnection,
) -> None:
    await replace_graph(db, RP, [plan("Deutsch")])

    await replace_graph(db, SN, [plan("Deutsch", SN)])

    found, _ = await find_plans(db)
    assert [(each.iri, each.graph) for each in found] == [("https://w3id.org/p/Deutsch", SN)]


async def test_an_empty_answer_empties_the_graph(db: psycopg.AsyncConnection) -> None:
    await replace_graph(db, RP, [plan("Deutsch")])

    assert await replace_graph(db, RP, []) == (0, 1)
    assert await find_plans(db) == ([], 0)


async def test_plans_are_found_by_land_subject_and_title_in_title_order(db: psycopg.AsyncConnection) -> None:
    await replace_graph(
        db,
        RP,
        [
            plan("b", title="Deutsch 7-8", subjects=("https://w3id.org/s/de",)),
            plan("a", title="Deutsch 5-6", subjects=("https://w3id.org/s/de",)),
            plan("c", title="Mathematik", subjects=("https://w3id.org/s/ma",)),
        ],
    )
    await replace_graph(db, SN, [plan("d", SN, title="Deutsch", subjects=("https://w3id.org/s/de",))])

    by_land, lands = await find_plans(db, land=RLP)
    by_subject, subjects = await find_plans(db, subject="https://w3id.org/s/de", land=RLP)
    by_title, titles = await find_plans(db, title="DEUTSCH", limit=2)

    assert [each.title for each in by_land] == ["Deutsch 5-6", "Deutsch 7-8", "Mathematik"]
    assert [each.title for each in by_subject] == ["Deutsch 5-6", "Deutsch 7-8"]
    assert [each.title for each in by_title] == ["Deutsch", "Deutsch 5-6"]
    assert (lands, subjects, titles) == (3, 2, 3)  # the number of all found, not of the page


async def test_a_title_search_takes_its_signs_as_they_are(db: psycopg.AsyncConnection) -> None:
    # LIKE's own signs match themselves, not any sign
    await replace_graph(
        db, RP, [plan("a", title="Deutsch 5_6"), plan("b", title="Deutsch 5x6"), plan("c", title="100%")]
    )

    underscore, _ = await find_plans(db, title="5_6")
    percent, _ = await find_plans(db, title="%")

    assert [each.title for each in underscore] == ["Deutsch 5_6"]
    assert [each.title for each in percent] == ["100%"]


async def test_a_page_of_plans_and_the_number_of_all(db: psycopg.AsyncConnection) -> None:
    await replace_graph(db, RP, [plan(f"{n:02}") for n in range(12)])

    page, total = await find_plans(db, limit=5, offset=10)

    assert total == 12
    assert [each.title for each in page] == ["10", "11"]


async def test_a_graph_s_plans_are_replaced_as_one_or_not_at_all(db: psycopg.AsyncConnection) -> None:
    await replace_graph(db, RP, [plan("Deutsch"), plan("Mathe")])

    with pytest.raises(psycopg.errors.CheckViolation):
        await replace_graph(db, RP, [plan("Physik"), plan("Leer", title="")])

    found, _ = await find_plans(db)
    assert sorted(each.title for each in found) == ["Deutsch", "Mathe"]


async def test_the_number_of_plans_of_a_graph(db: psycopg.AsyncConnection) -> None:
    await replace_graph(db, RP, [plan("Deutsch"), plan("Mathe")])

    assert (await graph_size(db, RP), await graph_size(db, SN)) == (2, 0)


async def test_a_page_past_the_last_is_empty_and_still_counts_all(db: psycopg.AsyncConnection) -> None:
    await replace_graph(db, RP, [plan(f"{n:02}") for n in range(12)])

    assert await find_plans(db, limit=5, offset=20) == ([], 12)
