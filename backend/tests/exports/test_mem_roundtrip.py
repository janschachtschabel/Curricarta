"""A MEM plan imported, frozen and exported (plan M2-6, the package's acceptance): Saxony's frozen plan
through the import job (a mock endpoint, as tests/jobs/test_mem_import.py has it), its document given its
work, issuer and edition and frozen, then exported - it meets the MEM shapes, and every part MEM gave goes
out under its MEM IRI. The KMK's frozen plan the same way, as a framework of all of Germany (plan M2-7): a
Bildungsstandard of no land, its standards Regelstandards the profile's shape does not warn of - which it
does where the same import is typed a Lehrplan. The database, the store and the shapes' child are real."""

from dataclasses import dataclass
from typing import Any

import httpx2
import psycopg
import pytest
from rdflib import RDF, RDFS, Graph, URIRef

from app.conversion.base import Block
from app.db.documents import set_document_type
from app.db.freezing import freeze
from app.db.mem_plans import MemPlan, record_import, replace_graph
from app.db.profile import add_specification
from app.domain.l1 import SpecificationDraft, SpecificationKind
from app.exports.mem_export import Exported, MemExporter
from app.exports.mem_rows import read_mem_document
from app.sources.mem.import_job import import_document
from tests.db.document_of import document_of
from tests.db.l1 import add_entity
from tests.jobs.test_mem_import import PLAN, Endpoint, a_job, frozen_of, setup

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_mem_import

LP = "https://w3id.org/lehrplan/ontology/"
SCHUL = "https://w3id.org/wlo/curriculum/profile/school#"
BASE = "https://example.org/kk/"


@dataclass(frozen=True)
class Kind:
    """A plan of a fixture as the route imports it: its catalogue's land and class, the document's region,
    type and specification (app/api/mem.py), its work."""

    fixture: str
    land_iri: str | None
    class_iri: str
    region: str
    document_type: str
    spec_kind: SpecificationKind
    issuer: str
    work: tuple[str, str]  # its title and short title


SAXONY = Kind(
    "sn",
    LP + "LP_3000014",
    LP + "LP_0000438",
    "DE-SN",
    "dt-Lehrplan",
    "curriculum",
    "Kultusministerium",
    ("Lehrplan Informatik", "lp-inf"),
)
KMK = Kind(
    "kmk",
    None,
    LP + "LP_0000571",
    "DE",
    "dt-Bildungsstandards",
    "competencyFramework",
    "KMK",
    ("Bildungsstandards Französisch", "bista-f"),
)


async def imported(context: Any, connection: psycopg.AsyncConnection, kind: Kind) -> Any:
    frozen = frozen_of(kind.fixture)
    labels = [" ".join(row["label"].split()) for row in frozen["closure"]]
    blocks = [
        Block(id=f"p{page}-b1", page=page, kind="text", text=label, bbox=None, font_size=None, bold=False,
              italic=False)
        for page, label in enumerate(labels, start=1)
    ]  # fmt: skip
    document = await document_of(connection, blocks, regions=(kind.region,))
    plan = MemPlan(**{**PLAN.__dict__, "iri": frozen["plan"], "graph": frozen["graph"],
                      "land_iri": kind.land_iri, "class_iri": kind.class_iri})  # fmt: skip
    await replace_graph(connection, plan.graph, [plan])
    await record_import(connection, document.id, plan)
    # as the route writes it (app/api/mem.py): the document's type and its specification
    await set_document_type(connection, document.id, SCHUL + kind.document_type)
    await add_specification(
        connection, document.id, SpecificationDraft("S1", kind.spec_kind, plan.title, None, {}, ())
    )
    await import_document(
        context, await a_job(connection, document), transport=httpx2.MockTransport(Endpoint(frozen=frozen))
    )
    return document, frozen


async def frozen_import(
    context: Any, connection: psycopg.AsyncConnection, database_url: str, kind: Kind = SAXONY
) -> Any:
    document, frozen = await imported(context, connection, kind)
    with psycopg.connect(database_url, autocommit=True) as sync:
        work = add_entity(sync, "work")
        sync.execute(
            "INSERT INTO work (id, title, region, short_title, owner_id) VALUES (%s, %s, %s, %s, %s)",
            (work, kind.work[0], kind.region, kind.work[1], document.owner_id),
        )
        sync.execute(
            "UPDATE document SET work_id = %s, issuer = %s, edition = '2019' WHERE id = %s",
            (work, kind.issuer, document.id),
        )
    await freeze(connection, document.id, BASE, accept_violations=False)  # an import meets the Kern's shapes
    return document, frozen


async def test_saxony_s_plan_imported_frozen_and_exported_meets_the_mem_shapes(
    setup: Any, database_url: str
) -> None:
    context, connection = setup
    document, saxony = await frozen_import(context, connection, database_url)

    rows = await read_mem_document(connection, document.id)
    made = await MemExporter(context.storage, context.settings).export(rows)

    assert isinstance(made, Exported), made
    graph = Graph().parse(data=await context.storage.get(made.key), format="turtle")
    labelled = {str(subject) for subject in graph.subjects(RDFS.label, None)}
    assert {row["n"] for row in saxony["closure"]} <= labelled  # every part under its MEM IRI
    assert {row["v"] for row in saxony["references"]} <= labelled
    assert (URIRef(rows.document["iri"]), None, None) in graph


REGELSTANDARD_WARNING = "shacl.SchulRegelstandardShape"
HAS_LAND = LP + "LP_0000029"  # hat Bundesland


async def warnings_of(connection: psycopg.AsyncConnection, document: Any, rule: str) -> int:
    cursor = await connection.execute(
        "SELECT count(*) FROM validation_finding WHERE document_id = %s AND rule = %s", (document.id, rule)
    )
    found = await cursor.fetchone()
    assert found is not None
    return int(found[0])


async def test_the_kmk_s_plan_imported_frozen_and_exported_is_a_bildungsstandard_meeting_the_mem_shapes(
    setup: Any, database_url: str
) -> None:
    context, connection = setup
    document, kmk = await frozen_import(context, connection, database_url, KMK)

    rows = await read_mem_document(connection, document.id)
    made = await MemExporter(context.storage, context.settings).export(rows)

    assert isinstance(made, Exported), made
    graph = Graph().parse(data=await context.storage.get(made.key), format="turtle")
    labelled = {str(subject) for subject in graph.subjects(RDFS.label, None)}
    assert {row["n"] for row in kmk["closure"]} <= labelled
    the_document = URIRef(rows.document["iri"])
    assert {str(klass) for klass in graph.objects(the_document, RDF.type)} == {LP + "LP_0000571"}
    assert not list(graph.triples((the_document, URIRef(HAS_LAND), None)))
    assert await warnings_of(connection, document, REGELSTANDARD_WARNING) == 0


async def test_the_kmk_s_standards_typed_a_lehrplan_are_warned_of(setup: Any) -> None:
    # the control: the profile's shape warns of a Regelstandard outside the KMK's standards
    context, connection = setup
    as_lehrplan = Kind("kmk", None, LP + "LP_0000571", "DE", "dt-Lehrplan", "curriculum", "KMK", KMK.work)

    document, _ = await imported(context, connection, as_lehrplan)

    assert await warnings_of(connection, document, REGELSTANDARD_WARNING) == 10
