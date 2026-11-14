"""What the MEM import writes beside its tree (plan M2, E1; Teilplan M2-5a): the document names its plan,
title, subjects, school types, licence and attribution as they stood at the import; one conversion takes a
plan once; a specification is added on its own; a Land is a region of the vocabulary; a plan is read from
the catalogue by its IRI."""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest

from app.core.ids import new_id
from app.db.documents import DocumentError, create_document, document_for_job, imported_document
from app.db.mem_plans import MemPlan, amend_licence, plan_by_iri, record_import, replace_graph
from app.db.migrate import migrate
from app.db.profile import add_specification
from app.db.source_queries import Reader
from app.domain.l1 import SpecificationDraft
from app.vocab.lookup import region_of_land
from app.vocab.store import load_vocabulary
from tests.db.l1 import add_conversion
from tests.support import ontology_vocabulary

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

LP = "https://w3id.org/lehrplan/ontology/"
PLAN = MemPlan(
    iri="https://w3id.org/lehrplan/instances/rp/resource/lehrplan-134-1",
    graph="https://w3id.org/lehrplan/rp",
    land_iri=LP + "LP_3000046",
    title="Informatik 5-6",
    class_iri=LP + "LP_0000433",
    subjects=("https://w3id.org/schulfach/RP_1",),
    school_types=("https://w3id.org/schulart/RP_9",),
    licence="CC BY-SA 4.0",
    attribution="MEM-Schule",
)


@pytest.fixture
def url(database_url: str, preloaded_vocabulary: None) -> str:
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    return database_url


@pytest.fixture
async def connection(url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as opened:
        yield opened


async def a_document(
    url: str, connection: psycopg.AsyncConnection, made: dict[str, Any] | None = None
) -> Any:
    if made is None:
        with psycopg.connect(url, autocommit=True) as sync:
            made = add_conversion(sync)
    return await create_document(
        connection, Reader(made["owner"], sees_all=False), third_party_content=False,
        source_id=made["source"], conversion_id=made["conversion"], sector="school",
    )  # fmt: skip


async def test_a_document_names_the_plan_it_was_imported_from_with_its_licence_as_it_stood(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    document = await a_document(url, connection)
    assert document.mem_iri is None

    await record_import(connection, document.id, PLAN)

    found = await document_for_job(connection, document.id)
    assert found is not None and (found.mem_iri, found.title) == (PLAN.iri, PLAN.title)
    cursor = await connection.execute(
        "SELECT mem_subjects, mem_school_types, mem_licence, mem_attribution, mem_land_iri, mem_class_iri"
        " FROM document WHERE id = %s",
        (document.id,),
    )
    assert await cursor.fetchone() == (
        list(PLAN.subjects),
        list(PLAN.school_types),
        "CC BY-SA 4.0",
        "MEM-Schule",
        PLAN.land_iri,
        PLAN.class_iri,
    )


async def test_a_title_longer_than_a_document_s_is_cut_to_it(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    document = await a_document(url, connection)
    long = MemPlan(**{**PLAN.__dict__, "title": "x" * 1500})

    await record_import(connection, document.id, long)

    found = await document_for_job(connection, document.id)
    assert found is not None and found.title == "x" * 1000


async def test_one_conversion_takes_a_plan_once(url: str, connection: psycopg.AsyncConnection) -> None:
    with psycopg.connect(url, autocommit=True) as sync:
        made = add_conversion(sync)
    first, second = await a_document(url, connection, made), await a_document(url, connection, made)
    await record_import(connection, first.id, PLAN)

    with pytest.raises(psycopg.errors.UniqueViolation):
        await record_import(connection, second.id, PLAN)


async def test_a_specification_is_added_to_a_document_on_its_own(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    document = await a_document(url, connection)

    made = await add_specification(
        connection, document.id, SpecificationDraft("S1", "curriculum", "Informatik 5-6", None, {}, ())
    )

    cursor = await connection.execute(
        "SELECT id, key, spec_kind, title, field_text FROM specification WHERE document_id = %s",
        (document.id,),
    )
    assert await cursor.fetchall() == [(made, "S1", "curriculum", "Informatik 5-6", None)]


async def test_a_land_of_mem_is_the_region_the_vocabulary_matches_it_with(
    connection: psycopg.AsyncConnection,
) -> None:
    assert await region_of_land(connection, LP + "LP_3000046") == "DE-RP"
    assert await region_of_land(connection, LP + "LP_3000048") == "DE-BE"
    assert await region_of_land(connection, LP + "LP_0000000") is None
    await connection.execute(
        "UPDATE vocab_concept SET retired_in = (SELECT max(id) FROM vocab_release) WHERE notation = 'DE-RP'"
    )
    assert await region_of_land(connection, LP + "LP_3000046") is None  # a Land the vocabulary retired


async def test_a_region_without_notation_is_no_region(connection: psycopg.AsyncConnection) -> None:
    await connection.execute("UPDATE vocab_concept SET notation = NULL WHERE notation = 'DE-RP'")

    assert await region_of_land(connection, LP + "LP_3000046") is None


async def test_a_plan_is_read_from_the_catalogue_by_its_iri(connection: psycopg.AsyncConnection) -> None:
    await replace_graph(connection, PLAN.graph, [PLAN])

    found = await plan_by_iri(connection, PLAN.iri)

    assert found is not None and found.__dict__ | {"read_at": None} == PLAN.__dict__
    assert found.read_at is not None
    assert await plan_by_iri(connection, PLAN.iri + "-2") is None


async def test_a_specification_names_no_evidence_and_a_document_that_is_none_is_refused(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    document = await a_document(url, connection)

    with pytest.raises(ValueError, match="evidence"):
        await add_specification(
            connection, document.id, SpecificationDraft("S1", "curriculum", "T", None, {}, ("p1-b1",))
        )
    with pytest.raises(DocumentError):
        await add_specification(
            connection, new_id(), SpecificationDraft("S1", "curriculum", "T", None, {}, ())
        )
    with pytest.raises(DocumentError):
        await record_import(connection, new_id(), PLAN)
    cursor = await connection.execute("SELECT count(*) FROM entity WHERE kind = 'specification'")
    assert await cursor.fetchone() == (0,)


async def test_a_conversion_s_import_of_a_plan_is_found_and_no_draft_copy_of_it(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    with psycopg.connect(url, autocommit=True) as sync:
        made = add_conversion(sync)
    first, copy = await a_document(url, connection, made), await a_document(url, connection, made)
    await record_import(connection, first.id, PLAN)
    await connection.execute(
        "UPDATE document SET copy_of = %s, iri = %s, mem_iri = %s WHERE id = %s",
        (first.id, "https://example.org/curriculum/1", PLAN.iri, copy.id),
    )

    found = await imported_document(connection, made["conversion"], PLAN.iri)

    assert found is not None and found.id == first.id
    assert await imported_document(connection, made["conversion"], PLAN.iri + "-2") is None
    assert await imported_document(connection, new_id(), PLAN.iri) is None
    await connection.execute("UPDATE document SET mem_iri = NULL WHERE id = %s", (first.id,))
    assert await imported_document(connection, made["conversion"], PLAN.iri) is None  # the copy's alone


async def test_a_land_or_class_the_tables_do_not_take_is_recorded_as_none(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    document = await a_document(url, connection)
    odd = MemPlan(**{**PLAN.__dict__, "land_iri": "Sachsen", "class_iri": "https://w3id.org/a b"})

    await record_import(connection, document.id, odd)

    cursor = await connection.execute(
        "SELECT mem_iri, mem_land_iri, mem_class_iri FROM document WHERE id = %s", (document.id,)
    )
    assert await cursor.fetchone() == (PLAN.iri, None, None)


async def test_imports_without_a_licence_take_the_one_checked_frozen_ones_too(
    url: str, connection: psycopg.AsyncConnection
) -> None:
    # the data's licence is checked after the first imports (E14): it goes into theirs, frozen or not
    with psycopg.connect(url, autocommit=True) as sync:
        made = [add_conversion(sync, bytes([n]) * 32) for n in range(1, 5)]
    draft, frozen, own, other = [await a_document(url, connection, each) for each in made]
    unlicensed = MemPlan(**{**PLAN.__dict__, "licence": None})
    await record_import(connection, draft.id, unlicensed)
    await record_import(connection, frozen.id, MemPlan(**{**unlicensed.__dict__, "iri": PLAN.iri + "-2"}))
    await record_import(connection, own.id, MemPlan(**{**PLAN.__dict__, "iri": PLAN.iri + "-3"}))
    await connection.execute(
        "UPDATE document SET iri = 'https://example.org/lp/1', frozen_at = now() WHERE id = %s", (frozen.id,)
    )
    licence = "https://creativecommons.org/licenses/by-sa/4.0/"

    await replace_graph(
        connection, PLAN.graph, [unlicensed, MemPlan(**{**PLAN.__dict__, "iri": PLAN.iri + "-9"})]
    )

    amended = await amend_licence(connection, licence)

    assert amended == (2, 1)  # two imports, one plan of the catalogue: one plan held its own
    cursor = await connection.execute("SELECT iri, licence FROM mem_plan ORDER BY iri")
    assert await cursor.fetchall() == [(PLAN.iri, licence), (PLAN.iri + "-9", "CC BY-SA 4.0")]
    cursor = await connection.execute(
        "SELECT id, mem_licence FROM document WHERE id = ANY(%s)", ([draft.id, frozen.id, own.id, other.id],)
    )
    assert dict(await cursor.fetchall()) == {
        draft.id: licence, frozen.id: licence, own.id: "CC BY-SA 4.0", other.id: None,
    }  # fmt: skip
