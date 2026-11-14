"""The job extract.mem_import (app/sources/mem/import_job.py, Teilplan M2-5b): the plan asked for at the
endpoint, its tree read and kept raw, typed, anchored in the document and written as imported rows in one
run IM, then X5. A plan gone is mem_unknown_plan, an answer refused mem_refused, an endpoint away for now
asks again; a document imported before is not written twice. A mock transport stands in for the endpoint;
the database and the store are real. Rheinland-Pfalz's frozen plan (9 parts) is the import."""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx2
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from app.conversion.base import Block
from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.db.documents import DocumentError
from app.db.mem_plans import MemPlan, record_import, replace_graph
from app.db.migrate import migrate
from app.jobs.context import JobContext
from app.jobs.handlers import make_handlers
from app.jobs.outcome import PermanentError
from app.jobs.queue import Job, LeaseLost, claim, enqueue
from app.pipeline import x5_stage
from app.pipeline.progress import ProgressCode, report
from app.sources.mem import import_job
from app.sources.mem.import_job import KIND, import_document
from app.sources.mem.sparql import MemUnavailable
from app.vocab.store import load_vocabulary
from tests.db.document_of import document_of
from tests.support import make_settings, ontology_vocabulary

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

CV = "https://w3id.org/wlo/curriculum/vocab#"
LP = "https://w3id.org/lehrplan/ontology/"
SCHUL = "https://w3id.org/wlo/curriculum/profile/school#"
ENDPOINT = "https://sparql.example.invalid/sparql"
FROZEN: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "sources" / "fixtures" / "mem" / "rp.json").read_text(encoding="utf-8")
)
PLAN = MemPlan(
    iri=FROZEN["plan"], graph=FROZEN["graph"], land_iri=None, title="Informatik Grundschule",
    class_iri="https://w3id.org/lehrplan/ontology/LP_0000433", subjects=(), school_types=(), licence=None,
    attribution="MEM-Schule",
)  # fmt: skip


def answer(rows: list[dict[str, str]], status: int = 200) -> httpx2.Response:
    bindings = [{key: {"type": "literal", "value": value} for key, value in row.items()} for row in rows]
    return httpx2.Response(status, json={"head": {"vars": []}, "results": {"bindings": bindings}})


class Endpoint:
    """A frozen plan as the endpoint answers it: the plan's count, its closure and references in pages."""

    def __init__(
        self,
        *,
        held: bool = True,
        status: int = 200,
        frozen: dict[str, Any] | None = None,
        counted: list[dict[str, str]] | None = None,
    ) -> None:
        self.held, self.status = held, status
        self.frozen = FROZEN if frozen is None else frozen
        self.counted = [{"count": "1" if held else "0"}] if counted is None else counted

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if self.status != 200:
            return answer([], self.status)
        query = parse_qs(request.content.decode())["query"][0]
        if "VALUES ?base" in query:
            return answer(self.counted)
        rows: list[dict[str, str]] = self.frozen["references" if "LP_0030071" in query else "closure"]
        if "COUNT" in query:
            return answer([{"count": str(len(rows))}])
        limit = int(query.rsplit("LIMIT ", 1)[1].split()[0])
        offset = int(query.rsplit("OFFSET ", 1)[1].split()[0])
        return answer(rows[offset : offset + limit])


def blocks(frozen: dict[str, Any] = FROZEN) -> list[Block]:
    """A page per part of the plan, its label as the text: every wording stands word for word."""
    labels = [" ".join(row["label"].split()) for row in frozen["closure"]]
    return [
        Block(id=f"p{page}-b1", page=page, kind="text", text=label, bbox=None, font_size=None, bold=False,
              italic=False)
        for page, label in enumerate(labels, start=1)
    ]  # fmt: skip


@pytest.fixture
async def setup(
    database_url: str, preloaded_vocabulary: None, tmp_path: Path
) -> AsyncIterator[tuple[JobContext, psycopg.AsyncConnection]]:
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    async with (
        AsyncConnectionPool(database_url, min_size=1, max_size=4, open=False) as pool,
        await psycopg.AsyncConnection.connect(database_url, autocommit=True) as connection,
    ):
        settings = make_settings(database_url=database_url, mem_sparql_url=ENDPOINT)
        yield (
            JobContext(
                pool=pool, storage=AsyncStorage(FileSystemStorage(tmp_path / "store")), settings=settings
            ),
            connection,
        )


async def an_import(connection: psycopg.AsyncConnection, *, in_catalogue: bool = True) -> Any:
    document = await document_of(connection, blocks())
    if in_catalogue:
        await replace_graph(connection, PLAN.graph, [PLAN])
    await record_import(connection, document.id, PLAN)
    return document


async def a_job(connection: psycopg.AsyncConnection, document: Any) -> Job:
    await enqueue(connection, KIND, "admin", {"document_id": str(document.id)})
    job = await claim(connection, "w1", [KIND], 60)
    assert job is not None
    return job


async def run(context: JobContext, job: Job, endpoint: Endpoint) -> dict[str, Any]:
    return await import_document(context, job, transport=httpx2.MockTransport(endpoint))


async def rows(connection: psycopg.AsyncConnection, query: str, *values: Any) -> list[tuple[Any, ...]]:
    cursor = await connection.execute(query, values)
    return await cursor.fetchall()


async def runs(connection: psycopg.AsyncConnection, document: Any) -> Mapping[str, tuple[Any, Any]]:
    found = await rows(
        connection,
        "SELECT replace(stage_iri, %s, ''), outcome, result FROM extraction_run WHERE document_id = %s"
        " ORDER BY started_at",
        CV + "stage_",
        document.id,
    )
    return {stage: (outcome, result) for stage, outcome, result in found}


async def test_an_import_writes_the_plan_s_tree_as_imported_rows_then_checks_it(setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)

    made = await run(context, await a_job(connection, document), Endpoint())

    assert made["stages"] == ["IM", "X5"]
    written = await rows(
        connection,
        "SELECT mem_iri, replace(origin_iri, %s, ''), replace(review_status_iri, %s, '') FROM node"
        " WHERE document_id = %s"
        " UNION ALL SELECT mem_iri, replace(origin_iri, %s, ''), replace(review_status_iri, %s, '')"
        " FROM statement WHERE document_id = %s",
        CV, CV, document.id, CV, CV, document.id,
    )  # fmt: skip
    assert sorted(iri for iri, _, _ in written) == sorted(row["n"] for row in FROZEN["closure"])
    assert {(origin, status) for _, origin, status in written} == {("orig_import", "rev_proposed")}
    done = await runs(connection, document)
    assert (done["IM"][0], done["X5"][0]) == ("done", "done")
    result = done["IM"][1]
    assert result["rules"] == "mem-rules/2" and result["parts"] == 9 and result["references"] == 0
    assert sum(result["stages"]["node"].values()) + sum(result["stages"].get("statement", {}).values()) == 9
    assert result["unsearched"] == 0
    assert result["front"] is None  # the document has no contents: no title pages to count apart
    # X5 reckoned the anchors the import found: every one of them stands word for word
    kinds = await rows(
        connection,
        "SELECT DISTINCT replace(match_kind_iri, %s, '') FROM anchor WHERE document_id = %s"
        " AND (node_id IS NOT NULL OR statement_id IS NOT NULL)",
        CV, document.id,
    )  # fmt: skip
    assert kinds == [("match_exact",)]


async def test_the_plan_s_answers_are_kept_raw_under_the_run(setup: Any, tmp_path: Path) -> None:
    context, connection = setup
    document = await an_import(connection)

    await run(context, await a_job(connection, document), Endpoint())

    [(run_id,)] = await rows(
        connection,
        "SELECT id FROM extraction_run WHERE document_id = %s AND stage_iri = %s",
        document.id,
        CV + "stage_IM",
    )
    kept = json.loads(
        (tmp_path / "store" / "runs" / str(run_id) / "im" / "1.json").read_text(encoding="utf-8")
    )
    assert (len(kept["closure"]), kept["plan"]) == (9, PLAN.iri)


async def test_an_import_done_is_not_written_twice(setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())
    count = (
        "SELECT (SELECT count(*) FROM node WHERE document_id = %s),"
        " (SELECT count(*) FROM statement WHERE document_id = %s)"
    )
    before = await rows(connection, count, document.id, document.id)

    again = await run(context, await a_job(connection, document), Endpoint())

    assert again["stages"] == ["IM", "X5"]
    assert await rows(connection, count, document.id, document.id) == before
    [(runs_im,)] = await rows(
        connection,
        "SELECT count(*) FROM extraction_run WHERE document_id = %s AND stage_iri = %s",
        document.id,
        CV + "stage_IM",
    )
    assert runs_im == 1


@pytest.mark.parametrize(
    ("endpoint", "in_catalogue", "code"),
    [(Endpoint(held=False), True, "mem_unknown_plan"), (Endpoint(counted=[{}]), True, "mem_unknown_plan"),
     (Endpoint(counted=[]), True, "mem_unknown_plan"), (Endpoint(), False, "mem_unknown_plan"),
     (Endpoint(status=400), True, "mem_refused")],
    ids=["gone-at-the-endpoint", "no-count", "no-row", "gone-from-the-catalogue", "refused"],
)  # fmt: skip
async def test_a_plan_gone_or_an_answer_refused_ends_the_job_and_writes_nothing(
    setup: Any, endpoint: Endpoint, in_catalogue: bool, code: str
) -> None:
    context, connection = setup
    document = await an_import(connection, in_catalogue=in_catalogue)

    with pytest.raises(PermanentError) as ended:
        await run(context, await a_job(connection, document), endpoint)

    assert ended.value.code == code
    assert await rows(connection, "SELECT id FROM node WHERE document_id = %s", document.id) == []


@pytest.mark.parametrize("before_last", [2, 1], ids=["first", "second"])
async def test_an_endpoint_away_for_now_leaves_the_import_to_another_attempt(
    setup: Any, before_last: int
) -> None:
    context, connection = setup
    document = await an_import(connection)
    job = await a_job(connection, document)

    with pytest.raises(MemUnavailable):
        await run(
            context, dataclasses.replace(job, attempts=job.max_attempts - before_last), Endpoint(status=503)
        )

    assert (await runs(connection, document))["IM"][0] == "failed"
    assert await rows(connection, "SELECT id FROM node WHERE document_id = %s", document.id) == []


async def test_an_endpoint_away_at_the_last_attempt_ends_the_import_unavailable(setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)
    job = await a_job(connection, document)

    with pytest.raises(PermanentError) as ended:
        await run(context, dataclasses.replace(job, attempts=job.max_attempts), Endpoint(status=503))

    assert ended.value.code == "mem_unavailable"
    assert (await runs(connection, document))["IM"] == ("failed", {"failure": "mem_unavailable"})


@pytest.mark.parametrize("broke", [asyncio.CancelledError, LeaseLost], ids=["cancel", "lease"])
async def test_a_cancel_or_a_lost_lease_at_the_last_attempt_is_no_endpoint_away(
    setup: Any, monkeypatch: pytest.MonkeyPatch, broke: type[BaseException]
) -> None:
    context, connection = setup
    document = await an_import(connection)
    job = await a_job(connection, document)

    async def broken(*_: Any) -> Any:
        raise broke("x")

    monkeypatch.setattr(import_job, "_read", broken)

    with pytest.raises(broke):
        await run(context, dataclasses.replace(job, attempts=job.max_attempts), Endpoint())


async def test_an_import_reports_reading_then_anchoring_then_checking(
    setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, connection = setup
    document = await an_import(connection)
    reported: list[str] = []

    async def noting(connection: Any, job: Any, code: ProgressCode, **params: int) -> None:
        reported.append(code)
        await report(connection, job, code, **params)

    monkeypatch.setattr(import_job, "report", noting)
    monkeypatch.setattr(x5_stage, "report", noting)

    await run(context, await a_job(connection, document), Endpoint())

    assert reported == ["mem_read", "mem_anchor", "check_document"]


async def test_the_worker_takes_the_import(setup: Any) -> None:
    context, _ = setup

    assert KIND == "extract.mem_import" and KIND in make_handlers(context)


def with_contents() -> list[Block]:
    """A cover, the contents on page 2 naming every part, then a page per part: the contents hold every
    wording too, and are no part of the text the import looks in."""
    labels = [" ".join(row["label"].split()) for row in FROZEN["closure"]]
    lines = "\n".join(f"{n} {label} {'.' * 20} {n + 2}" for n, label in enumerate(labels, start=1))
    made = [
        Block(id="p1-b1", page=1, kind="text", text="Lehrplan Informatik", bbox=None, font_size=20, bold=True,
              italic=False),
        Block(id="p2-b1", page=2, kind="text", text="Inhalt", bbox=None, font_size=16, bold=True,
              italic=False),
        Block(id="p2-b2", page=2, kind="text", text=lines, bbox=None, font_size=11, bold=False, italic=False),
    ]  # fmt: skip
    made += [
        Block(id=f"p{page}-b1", page=page, kind="text", text=label, bbox=None, font_size=11, bold=False,
              italic=False)
        for page, label in enumerate(labels, start=3)
    ]  # fmt: skip
    return made


async def test_the_contents_are_no_place_a_wording_is_anchored_at(setup: Any) -> None:
    context, connection = setup
    document = await document_of(connection, with_contents())
    await replace_graph(connection, PLAN.graph, [PLAN])
    await record_import(connection, document.id, PLAN)

    await run(context, await a_job(connection, document), Endpoint())

    pages = await rows(
        connection,
        "SELECT DISTINCT ab.block_id FROM anchor a JOIN anchor_block ab ON ab.anchor_id = a.id"
        " WHERE a.document_id = %s AND (a.node_id IS NOT NULL OR a.statement_id IS NOT NULL)",
        document.id,
    )
    assert pages and not [block for (block,) in pages if block.startswith(("p1-", "p2-"))]


async def test_an_import_another_job_wrote_meanwhile_is_not_written_again(
    setup: Any, monkeypatch: Any
) -> None:
    # this attempt looked before the other's run was done: the stage's lock tells it, and it writes nothing
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())
    count = "SELECT count(*) FROM node WHERE document_id = %s"
    before = await rows(connection, count, document.id)

    async def nothing_done(*_: Any) -> set[str]:
        return set()

    monkeypatch.setattr(import_job, "done_stages", nothing_done)
    await run(context, await a_job(connection, document), Endpoint())

    assert await rows(connection, count, document.id) == before
    outcomes = await rows(
        connection,
        "SELECT outcome FROM extraction_run WHERE document_id = %s AND stage_iri = %s ORDER BY started_at",
        document.id,
        CV + "stage_IM",
    )
    assert outcomes == [("done",), ("failed",)]


def frozen_of(land: str) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(
        (Path(__file__).parents[1] / "sources" / "fixtures" / "mem" / f"{land}.json").read_text(
            encoding="utf-8"
        )
    )
    return found


async def anchor_of(
    connection: psycopg.AsyncConnection, document: Any, mem_iri: str
) -> list[tuple[Any, ...]]:
    """The match kind of the anchor of the row of ``mem_iri``."""
    return await rows(
        connection,
        "SELECT replace(a.match_kind_iri, %s, '') FROM anchor a LEFT JOIN node n ON n.id = a.node_id"
        " LEFT JOIN statement s ON s.id = a.statement_id"
        " WHERE a.document_id = %s AND coalesce(n.mem_iri, s.mem_iri) = %s",
        CV, document.id, mem_iri,
    )  # fmt: skip


async def test_a_wording_the_document_does_not_hold_is_a_warning_and_the_references_are_counted(
    setup: Any,
) -> None:
    # Saxony's frozen plan: parts at every depth, 20 references
    context, connection = setup
    saxony = frozen_of("sn")
    labels = [" ".join(row["label"].split()) for row in saxony["closure"]]
    missing = max(labels, key=len)  # the longest wording: no other holds it, and the document shall not
    lost = saxony["closure"][labels.index(missing)]["n"]
    labels.remove(missing)
    assert missing not in labels
    made = [
        Block(id=f"p{page}-b1", page=page, kind="text", text=label, bbox=None, font_size=None, bold=False,
              italic=False)
        for page, label in enumerate(labels, start=1)
    ]  # fmt: skip
    document = await document_of(connection, made)
    plan = MemPlan(**{**PLAN.__dict__, "iri": saxony["plan"], "graph": saxony["graph"]})
    await replace_graph(connection, plan.graph, [plan])
    await record_import(connection, document.id, plan)

    await run(context, await a_job(connection, document), Endpoint(frozen=saxony))

    result = (await runs(connection, document))["IM"][1]
    assert result["references"] == len({row["v"] for row in saxony["references"]})
    assert sum(result["typed"].values()) == len(saxony["closure"]) + result["references"]
    assert await anchor_of(connection, document, lost) == [("match_notFound",)]
    warned = await rows(
        connection,
        "SELECT count(*) FROM validation_finding WHERE document_id = %s AND rule = 'x5.import_not_found'",
        document.id,
    )
    assert warned[0][0] >= 1


async def test_a_wording_found_on_the_title_pages_is_counted_apart(setup: Any) -> None:
    context, connection = setup
    made = with_contents()
    # a Kompetenzspezifikation's wording - a statement's -: on the cover, spaced apart, nowhere in the body
    at = 3 + next(n for n, row in enumerate(FROZEN["closure"]) if row["types"].endswith("/LP_0000432"))
    made[0] = Block(
        id="p1-b1", page=1, kind="text", text=made[at].text.replace(" ", "  ", 1), bbox=None, font_size=20,
        bold=True, italic=False,
    )  # fmt: skip
    made[at] = Block(
        id=made[at].id, page=made[at].page, kind="text", text="Vorwort", bbox=None, font_size=11, bold=False,
        italic=False,
    )  # fmt: skip
    document = await document_of(connection, made)
    await replace_graph(connection, PLAN.graph, [PLAN])
    await record_import(connection, document.id, PLAN)

    await run(context, await a_job(connection, document), Endpoint())

    result = (await runs(connection, document))["IM"][1]
    # a statement, found once its spacing is set aside
    assert result["front"] == {"statement": {"whitespace": 1}}
    assert result["untraced"] == 0


async def test_a_tree_the_document_s_profile_does_not_hold_ends_the_job(setup: Any) -> None:
    # the rules type by the school's lexicon: a document of another sector does not take its node types
    context, connection = setup
    document = await document_of(connection, blocks(), sector="vocational")
    await replace_graph(connection, PLAN.graph, [PLAN])
    await record_import(connection, document.id, PLAN)

    with pytest.raises(PermanentError) as ended:
        await run(context, await a_job(connection, document), Endpoint())

    assert ended.value.code == "mem_unwritable"
    assert (await runs(connection, document))["IM"][0] == "failed"


async def test_a_document_gone_at_the_write_ends_the_job(setup: Any, monkeypatch: Any) -> None:
    context, connection = setup
    document = await an_import(connection)

    async def gone(*_: Any, **__: Any) -> None:
        raise DocumentError("no document")

    monkeypatch.setattr(import_job, "write_subtree", gone)
    with pytest.raises(PermanentError) as ended:
        await run(context, await a_job(connection, document), Endpoint())

    assert ended.value.code == "mem_unwritable"


async def test_an_import_checked_and_then_edited_is_checked_again(setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)
    await run(context, await a_job(connection, document), Endpoint())
    await connection.execute("UPDATE document SET edited_at = now() WHERE id = %s", (document.id,))

    await run(context, await a_job(connection, document), Endpoint())

    checks = await rows(
        connection,
        "SELECT outcome FROM extraction_run WHERE document_id = %s AND stage_iri = %s ORDER BY started_at",
        document.id,
        CV + "stage_X5",
    )
    assert checks == [("done",), ("done",)]


EXPIRED = "UPDATE job SET lease_expires_at = now() - interval '1 minute' WHERE id = %s"


async def test_an_attempt_that_lost_its_lease_starts_no_run(setup: Any) -> None:
    context, connection = setup
    document = await an_import(connection)
    job = await a_job(connection, document)
    await connection.execute(EXPIRED, (job.id,))

    with pytest.raises(LeaseLost):
        await run(context, job, Endpoint())

    assert await runs(connection, document) == {}


class Expiring(Endpoint):
    """The endpoint, asked for the plan, while the attempt's lease runs out."""

    def __init__(self, database_url: str, job: Job) -> None:
        super().__init__()
        self.database_url, self.job = database_url, job

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if "VALUES ?base" in parse_qs(request.content.decode())["query"][0]:
            with psycopg.connect(self.database_url, autocommit=True) as connection:
                connection.execute(EXPIRED, (self.job.id,))
        return super().__call__(request)


async def test_an_attempt_that_lost_its_lease_meanwhile_writes_nothing(setup: Any, database_url: str) -> None:
    context, connection = setup
    document = await an_import(connection)
    job = await a_job(connection, document)

    with pytest.raises(LeaseLost):
        await run(context, job, Expiring(database_url, job))

    assert await rows(connection, "SELECT id FROM node WHERE document_id = %s", document.id) == []


LOOSE: dict[str, Any] = {
    **FROZEN,
    "closure": [
        {"ancestors": FROZEN["plan"], "grades": "", "label": "Die Lernenden sitzen richtig.",
         "n": "https://w3id.org/p/lose aussage", "types": LP + "LP_0000263"},
        {"ancestors": FROZEN["plan"], "grades": "", "label": "Geordneter Beginn", "n": "https://w3id.org/p/start",
         "types": LP + "LP_0000349"},
    ],
    "references": [],
}  # fmt: skip


async def test_statements_at_the_top_hang_under_the_plan_s_title_and_a_part_of_no_storable_iri_is_counted(
    setup: Any,
) -> None:
    context, connection = setup
    made = [
        Block(id=f"p{page}-b1", page=page, kind="text", text=text, bbox=None, font_size=None, bold=False,
              italic=False)
        for page, text in enumerate([PLAN.title, "Die Lernenden sitzen richtig.", "Geordneter Beginn"], 1)
    ]  # fmt: skip
    document = await document_of(connection, made)
    await replace_graph(connection, PLAN.graph, [PLAN])
    await record_import(connection, document.id, PLAN)
    await connection.execute("UPDATE document SET title = 'Ein anderer Titel' WHERE id = %s", (document.id,))

    await run(context, await a_job(connection, document), Endpoint(frozen=LOOSE))

    holders = await rows(
        connection, "SELECT original_title FROM node WHERE document_id = %s AND mem_iri IS NULL", document.id
    )
    assert holders == [(PLAN.title,)]
    assert (await runs(connection, document))["IM"][1]["untraced"] == 1


KMK: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "sources" / "fixtures" / "mem" / "kmk.json").read_text(encoding="utf-8")
)
KMK_PLAN = MemPlan(
    iri=KMK["plan"], graph=KMK["graph"], land_iri=None, title="Bildungsstandards Französisch",
    class_iri=LP + "LP_0000571", subjects=(), school_types=(), licence=None, attribution="MEM-Schule",
)  # fmt: skip


async def test_a_plan_of_the_kmk_s_graph_is_typed_by_its_table(setup: Any) -> None:
    # its ten standards: Regelstandards for the learner, at the plan's own area (plan M2-7, E13)
    context, connection = setup
    document = await document_of(connection, blocks(KMK), regions=("DE",))
    await replace_graph(connection, KMK_PLAN.graph, [KMK_PLAN])
    await record_import(connection, document.id, KMK_PLAN)

    await run(context, await a_job(connection, document), Endpoint(frozen=KMK))

    done = await runs(connection, document)
    assert done["IM"][0] == "done" and done["IM"][1]["typed"] == {"kmk": 10}
    written = await rows(
        connection,
        "SELECT replace(s.statement_kind_iri, %s, ''), replace(s.subkind_iri, %s, ''),"
        " replace(a.addressee_iri, %s, '') FROM statement s"
        " JOIN statement_addressee a ON a.statement_id = s.id WHERE s.document_id = %s",
        CV, SCHUL, CV, document.id,
    )  # fmt: skip
    assert written == [("kind_standard", "Regelstandard", "addr_learner")] * 10
