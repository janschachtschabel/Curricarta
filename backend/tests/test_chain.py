"""The whole way of a curriculum through the service, as one test: an account uploads a PDF, asks for its
conversion, makes a document of it and has it extracted, an editor sets values, a rule, an assessment and
a placement of the second layer (plan M3a), X5 checks it, the editor freezes it and downloads its Kern
export, which holds each of them under its frozen IRI - each step through the public API, each job run by
the worker's own step with the real handlers, against the PostgreSQL and S3 test services. A model stands
in (FunctionModel, as the pipeline's tests use it): it answers each unit with the wording of its longest
block, word for word, so that X5 finds it where it stands. The PDF is one of the conversion tests'
synthetic files (tools/make_conversion_fixtures.py)."""

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import FunctionModel
from rdflib import RDF, Graph, URIRef

from app.api.app import create_app
from app.core.settings import Settings
from app.core.storage import open_storage
from app.core.storage_async import AsyncStorage
from app.core.storage_s3 import s3_client
from app.db.migrate import migrate
from app.domain.iris import slug
from app.exports.kern_rdf import CUR
from app.jobs.context import JobContext
from app.jobs.handlers import make_handlers
from app.jobs.queue import Job
from app.jobs.worker import Handler, Worker
from app.vocab.store import load_vocabulary
from tests.api.upload_stores import s3_settings
from tests.llm.test_client import llm_settings
from tests.pipeline.test_run import Model, a_statement
from tests.support import make_settings, ontology_vocabulary, seed_admin, selector_client

pytestmark = [pytest.mark.pg, pytest.mark.s3]

PUBLIC = "http://testserver:8000"
PDF = (Path(__file__).resolve().parent / "conversion" / "fixtures" / "prose.pdf").read_bytes()
BASE = "https://example.org/kk/"
WORK = {"title": "Lehrplan Technik", "region": "DE-NW", "short_title": "lp-technik"}
CV, LVL = "https://w3id.org/wlo/curriculum/vocab#", "https://w3id.org/wlo/curriculum/level/"
_BLOCK = re.compile(r"^\[(p\d+-b\d+)\] (.+)$", re.M)


class Quoting(Model):
    """The pipeline's stand-in; a unit is answered by one statement, the wording of the longest block in
    its span as the document in the prompt shows it (``quoted``: those wordings)."""

    def __init__(self) -> None:
        super().__init__()
        self.quoted: list[str] = []
        self.document = ""

    def __call__(self, messages: list[ModelMessage], info: Any) -> Any:
        # the document stands in the prefix every question about it shares
        self.document = "\n".join(
            str(getattr(part, "content", "")) for message in messages for part in message.parts
        )
        return super().__call__(messages, info)

    def unit(self, prompt: str) -> dict[str, Any]:
        found = re.search(r"^=== EINHEIT ===\n(E\d+) \| .* \| Blöcke (\S+) bis (\S+)$", prompt, re.M)
        assert found is not None
        key, first, last = found.groups()
        self.units.append(key)
        blocks = dict(_BLOCK.findall(self.document))
        order = list(blocks)
        span = order[order.index(first) : order.index(last) + 1]
        chosen = max(span, key=lambda block: len(blocks[block]))
        self.quoted.append(blocks[chosen])
        return {"unitKey": key, "statements": [a_statement(chosen, blocks[chosen])], "checkedAbsent": []}


@pytest.fixture
def chain_settings(database_url: str, preloaded_vocabulary: None) -> Iterator[Settings]:
    """The service's settings on the test database, its vocabulary loaded, and a bucket of its own on
    the S3 test service, emptied and removed after."""
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    settings = make_settings(database_url=database_url, iri_base=BASE, **s3_settings())
    assert settings.s3_bucket is not None
    client = s3_client(settings)
    client.create_bucket(Bucket=settings.s3_bucket)
    try:
        yield settings
    finally:
        listed = client.get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket)
        for item in [item for page in listed for item in page.get("Contents", [])]:
            client.delete_object(Bucket=settings.s3_bucket, Key=item["Key"])
        client.delete_bucket(Bucket=settings.s3_bucket)


def work_off(settings: Settings, model: Quoting) -> list[str]:
    """What a worker does with every job waiting now, one after the other, with the handlers it starts
    with: the kinds of the jobs it ran, in their order."""
    function_model = FunctionModel(model, settings={"max_tokens": 4_000})
    ran: list[str] = []

    def noting(kind: str, handler: Handler) -> Handler:
        async def run(job: Job) -> Any:
            ran.append(kind)
            return await handler(job)

        return run

    async def work() -> None:
        url = settings.database_url.get_secret_value()
        async with AsyncConnectionPool(url, min_size=1, max_size=6, open=False) as pool:
            storage = AsyncStorage(await asyncio.to_thread(open_storage, settings))
            context = JobContext(pool, storage, settings, llm=llm_settings(), model=lambda: function_model)
            handlers = {kind: noting(kind, handler) for kind, handler in make_handlers(context).items()}
            worker = Worker(pool, handlers, owner="chain-worker")
            while await worker.run_once():
                pass

    asyncio.run(work(), loop_factory=asyncio.SelectorEventLoop)
    return ran


def job_of(client: TestClient, header: dict[str, str], job_id: str) -> dict[str, Any]:
    answer = client.get(f"/api/v1/jobs/{job_id}", headers=header)
    assert answer.status_code == 200, answer.text
    return dict(answer.json())


def statements_of(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [found for node in nodes for found in [*node["statements"], *statements_of(node["children"])]]


def test_a_pdf_goes_from_its_upload_to_a_frozen_document(chain_settings: Settings) -> None:
    settings, model = chain_settings, Quoting()
    with selector_client(create_app(settings), base_url=PUBLIC) as client:
        # 0. an admin makes an editor's account, its token and its budget
        admin = seed_admin(settings.database_url.get_secret_value())
        made = client.post(
            "/api/v1/accounts", headers=admin, json={"name": "Redaktion", "roles": ["redaktion"]}
        )
        assert made.status_code == 201, made.text
        account = made.json()["id"]
        key = client.post(f"/api/v1/accounts/{account}/keys", headers=admin, json={"label": "chain"})
        assert key.status_code == 201, key.text
        editor = {"Authorization": f"Bearer {key.json()['token']}"}
        quota = {"token_limit": None, "page_limit": None}
        assert client.put(f"/api/v1/accounts/{account}/quota", headers=admin, json=quota).status_code == 200

        # 1. the upload
        uploaded = client.post("/api/v1/sources", headers=editor, files={"file": ("lehrplan.pdf", PDF)})
        assert uploaded.status_code == 201, uploaded.text
        source = uploaded.json()["id"]

        # 2. its conversion by pdfplumber, run by the worker
        asked = client.post(f"/api/v1/sources/{source}/conversions", headers=editor)
        assert asked.status_code == 202, asked.text
        assert (asked.json()["status"], asked.json()["engine"]) == ("pending", "pdfplumber")
        assert work_off(settings, model) == ["source.convert"]
        converted = client.get(f"/api/v1/sources/{source}/conversion", headers=editor).json()
        assert (converted["id"], converted["status"], converted["pages"]) == (asked.json()["id"], "done", 2)

        # 3. a document of it, its extraction run with the model standing in: X1 to X5
        started = client.post(
            "/api/v1/documents",
            headers=editor,
            json={
                "source_id": source,
                "conversion_id": converted["id"],
                "sector": "school",
                "regions": ["DE-NW"],
            },
        )
        assert started.status_code == 202, started.text
        document, extraction = started.json()["document"]["id"], started.json()["job"]["id"]
        assert work_off(settings, model) == ["extract.run"]
        assert job_of(client, editor, extraction)["status"] == "done"
        runs = client.get(f"/api/v1/documents/{document}/runs", headers=editor).json()
        assert {run["stage"] for run in runs if run["state"] == "done"} >= {"X1", "X2", "X3", "X4", "X5"}
        assert model.asked == ["profile", "outline", "frame"] and model.quoted

        # 4. the second layer set by the editor (plan M3a): a workload at a node and a level at a statement,
        # a rule on a block of the document, a graded exam of its specification, the node placed there
        edited = second_layer(client, editor, document, block=_BLOCK.findall(model.document)[0][0])

        # 5. its work, issuer and edition set, X5 checks it again: no violation, nothing owed
        assert (
            client.patch(f"/api/v1/documents/{document}/work", headers=editor, json=WORK).status_code == 200
        )
        metadata = {"issuer": "Ministerium", "edition": "2024"}
        assert client.patch(f"/api/v1/documents/{document}", headers=editor, json=metadata).status_code == 200
        checked = client.post(f"/api/v1/documents/{document}/check", headers=editor)
        assert checked.status_code == 202, checked.text
        assert work_off(settings, model) == ["extract.check"]
        assert job_of(client, editor, checked.json()["id"])["status"] == "done"
        findings = client.get(f"/api/v1/documents/{document}/findings", headers=editor).json()
        assert findings["counts"]["violation"] == 0, findings["findings"]

        # 6. frozen
        frozen = client.post(f"/api/v1/documents/{document}/freeze", headers=editor)
        assert frozen.status_code == 200, frozen.text
        assert frozen.json()["frozen_at"] is not None and frozen.json()["iri"].startswith(BASE)

        # 7. what it says, as the frozen document reads: the statements the model answered, with their IRIs
        tree = client.get(f"/api/v1/documents/{document}/tree", headers=editor).json()
        assert tree["closed"] == "frozen"
        said = statements_of(tree["nodes"])
        assert sorted(found["fields"]["verbatim"] for found in said) == sorted(model.quoted)
        assert all(found["iri"].startswith(frozen.json()["iri"]) for found in said)

        # 8. exported: its Kern Turtle, every row under the IRI the document was frozen with, none by its id
        exported = client.get(f"/api/v1/documents/{document}/kern.ttl", headers=editor)
        assert exported.status_code == 200, exported.text
        graph = Graph().parse(data=exported.content, format="turtle")
        named = {str(term) for triple in graph for term in (triple[0], triple[2]) if isinstance(term, URIRef)}
        assert not [term for term in named if term.startswith("urn:uuid:")]
        rows = {*graph.subjects(RDF.type, CUR.CurriculumNode), *graph.subjects(RDF.type, CUR.Statement)}
        assert rows and all(str(row).startswith(frozen.json()["iri"] + "/") for row in rows)
        assert {found["iri"] for found in said} <= {str(row) for row in rows}
        holders = {found["id"]: found["iri"] for found in [*nodes_of(tree["nodes"]), *said]}
        specs = client.get(f"/api/v1/documents/{document}/specifications", headers=editor).json()
        holders |= {  # the frozen name of its key (app/domain/naming.py)
            spec["id"]: f"{frozen.json()['iri']}/spec/{slug(spec['key'])}" for spec in specs["specifications"]
        }
        second_layer_exported(graph, frozen.json()["iri"], holders, edited)

        # 9. MEM's own export is of an import from MEM-Schule alone: this document is none
        mem = client.get(f"/api/v1/documents/{document}/export.ttl", headers=editor)
        assert (mem.status_code, mem.json()["code"]) == (409, "not_mem_import")


def nodes_of(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [found for node in nodes for found in [node, *nodes_of(node["children"])]]


def values(revision: int, **kinds: list[dict[str, Any]]) -> dict[str, Any]:
    return {"expected_revision": revision, "level_assignments": [], "time_spans": [], "workloads": []} | kinds


def second_layer(client: TestClient, editor: dict[str, str], document: str, block: str) -> dict[str, str]:
    """What an editor sets of the second layer, each through its route: a workload at a node with a
    statement, a level at that statement, a completion rule anchored at ``block`` that applies to the node,
    a graded exam of the document's specification and the node placed in that specification for a grade
    level - the ids of the node, the statement and the specification."""

    def ok(answer: Any, status: int = 200) -> dict[str, Any]:
        assert answer.status_code == status, answer.text
        return dict(answer.json())

    tree = ok(client.get(f"/api/v1/documents/{document}/tree", headers=editor))
    node = next(found for found in nodes_of(tree["nodes"]) if found["statements"])
    said, [specification] = node["statements"][0], tree["specifications"]
    node_path, said_path = f"/api/v1/nodes/{node['id']}", f"/api/v1/statements/{said['id']}"
    at_node = ok(client.put(f"{node_path}/values", headers=editor, json=values(node["revision"], workloads=[
        {"amount": 40, "unit": CV + "unit_lesson"}])))  # fmt: skip
    ok(client.put(f"{said_path}/values", headers=editor, json=values(said["revision"], level_assignments=[
        {"level": LVL + "cefr-B1"}])))  # fmt: skip
    new_rule = {"kind": "completion", "verbatim": "Alle Bereiche.", "anchors": [{"blocks": [block]}]}
    rule = ok(client.post(f"/api/v1/documents/{document}/rules", headers=editor, json=new_rule), 201)
    ok(client.patch(f"/api/v1/rules/{rule['id']}", headers=editor, json={
        "expected_revision": rule["revision"], "min_count": 2, "applies_to": [node["id"]]}))  # fmt: skip
    exam = {"parent_id": specification["id"], "assessment_kind": CV + "ak_exam", "graded": True,
            "duration_minutes": 90, "targets": [node["id"]]}  # fmt: skip
    made = ok(client.post(f"/api/v1/documents/{document}/assessments", headers=editor, json=exam), 201)
    ok(client.put(f"/api/v1/assessments/{made['id']}/values", headers=editor, json=values(made["revision"],
        level_assignments=[{"level": LVL + "grade-2"}])))  # fmt: skip
    there = {"specification_id": specification["id"], "obligation": CV + "obl_binding"}
    placed = ok(client.put(f"{node_path}/placements", headers=editor, json={
        "expected_revision": at_node["revision"], "placements": [there]}))  # fmt: skip
    [placement] = placed["placements"]
    grade = {"time_kind": CV + "time_gradeLevel", "span_from": 7}
    ok(client.put(f"/api/v1/placements/{placement['id']}/values", headers=editor, json=values(
        placement["revision"], time_spans=[grade])))  # fmt: skip
    return {"node": node["id"], "statement": said["id"], "specification": specification["id"]}


def second_layer_exported(graph: Graph, iri: str, holders: dict[str, str], edited: dict[str, str]) -> None:
    """What ``second_layer`` set, in the Turtle: each row under its frozen IRI, each value at its holder."""
    node, said, specification = (URIRef(holders[edited[k]]) for k in ("node", "statement", "specification"))
    rule, exam, placement = (URIRef(f"{iri}/{name}-1") for name in ("rule", "assessment", "placement"))

    def one(subject: Any, predicate: URIRef) -> Any:
        [found] = graph.objects(subject, predicate)
        return found

    workload = one(node, CUR.workload)
    assert (one(workload, CUR.amount).toPython(), one(workload, CUR.unit)) == (40, URIRef(CV + "unit_lesson"))
    assert one(one(said, CUR.levelAssignment), CUR.level) == URIRef(LVL + "cefr-B1")
    assert (rule, RDF.type, CUR.CompletionRule) in graph
    assert (one(rule, CUR.minCount).toPython(), one(rule, CUR.ruleAppliesTo)) == (2, node)
    assert (exam, RDF.type, CUR.Assessment) in graph and one(exam, CUR.assesses) == node
    assert one(exam, CUR.partOf) == specification == one(placement, CUR.inSpecification)
    assert one(one(exam, CUR.levelAssignment), CUR.level) == URIRef(LVL + "grade-2")
    assert one(placement, CUR.placedUnit) == node
    assert one(placement, CUR.obligation) == URIRef(CV + "obl_binding")
    span = one(placement, CUR.timeSpan)
    assert one(span, CUR.timeKind) == URIRef(CV + "time_gradeLevel")
    assert one(span, CUR["from"]).toPython() == 7
