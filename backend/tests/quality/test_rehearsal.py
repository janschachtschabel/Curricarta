"""The acceptance runs rehearsed without money (plan H-3, A9): a model stands in (FunctionModel, as the
pipeline's own tests use it), the document's wordings are made by the MEM fixtures' tool, the SHACL check
runs in the test's process - and every command of the operator's handout (tests/quality/handout.py) runs
word for word, as a process of its own, in the order an operator runs them: the estimate, the budget's two
steps, the usage report, the draws, the sheets, the judgements read in, the reports, the replay, the MEM
import's report with the switch and without. The sheets go to a temporary folder, never into the tree."""

import asyncio
import csv
import io
import re
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.conversion.base import Block
from app.db.gold import items_of
from app.db.runs import done_stages
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from app.pipeline.run import extract_document
from app.quality.sheet import encoded
from app.usage.ledger import usage_of
from tests.db.document_of import document_of
from tests.jobs.test_mem_import import ENDPOINT, Endpoint, an_import, run
from tests.jobs.test_mem_import import a_job as an_import_job
from tests.pipeline.test_run import Model, a_job, a_statement, block, context_of, rows, setup
from tests.quality.gold_documents import owner
from tests.quality.handout import COMMANDS
from tests.quality.handout_runner import Operator
from tests.sources.test_mem_fixtures import mem_synth
from tests.support import make_settings

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the fixture, shared with test_run

LABEL, MEM_LABEL = "pilot-1", "mem-1"
BASE = "https://curricarta.example.org"
BODY = "Die Lernenden beschreiben, wie das Wasser am Ufer fließt, und erklären die Kiesel im Bach."


def made(form: str, seed: int) -> str:
    return str(mem_synth.wording(form, seed))


HEADINGS = ("Kompetenzen", "Am Ufer", "Im Wasser", "Unter den Steinen", "Bewertung")
DOCUMENT = [
    block("p1-b1", made("Ein Plan für das Lernen am Bach", 0), size=24),
    block("p1-b2", made("Dieser Plan gilt ab dem 1. August 2019.", 1)),
] + [
    made_block
    for page, heading in enumerate(HEADINGS, start=2)
    for made_block in (
        block(f"p{page}-b1", made(heading, 10 * page), size=16),
        block(f"p{page}-b2", made(BODY, 10 * page + 1)),
        block(f"p{page}-b3", made(BODY, 10 * page + 2)),
    )
]
_ORDER = [b.id for b in DOCUMENT]


class Standing(Model):
    """The pipeline's stand-in, each heading an area - a unit of X4 each -, a unit answered by one
    statement: the wording of the first text block in its span, word for word, so that X5 finds it where it
    stands (``chosen``: those blocks)."""

    def __init__(self) -> None:
        super().__init__()
        self.chosen: list[str] = []

    def outline(self, prompt: str) -> dict[str, Any]:
        found = super().outline(prompt)
        area = found["headings"][0]["nodeType"]
        for heading in found["headings"]:
            heading |= {"nodeType": area, "nodeFunction": "area"}
        return found

    def unit(self, prompt: str) -> dict[str, Any]:
        found = re.search(r"^=== EINHEIT ===\n(E\d+) \| .* \| Blöcke (\S+) bis (\S+)$", prompt, re.M)
        assert found is not None
        key, first, last = found.groups()
        self.units.append(key)
        span = _ORDER[_ORDER.index(first) : _ORDER.index(last) + 1]
        text: Block = next(b for b in DOCUMENT if b.id in span and b.font_size == 10)
        self.chosen.append(text.id)
        return {"unitKey": key, "statements": [a_statement(text.id, text.text)], "checkedAbsent": []}


async def a_plan(connection: psycopg.AsyncConnection) -> Any:
    """The document, converted, its owner's limit at 1: the operator's to set."""
    document = await document_of(connection, DOCUMENT)
    await connection.execute(
        "INSERT INTO quota (account_id, token_limit) VALUES (%s, 1)", (document.owner_id,)
    )
    return document


async def extract(context: JobContext, connection: psycopg.AsyncConnection, document: Any) -> dict[str, Any]:
    return await extract_document(context, await a_job(connection, document.id, document.owner_id))


async def limit(connection: psycopg.AsyncConnection, document: Any, tokens: int) -> None:
    """What an admin sets with PUT /api/v1/accounts/{id}/quota."""
    await connection.execute(
        "UPDATE quota SET token_limit = %s WHERE account_id = %s", (tokens, document.owner_id)
    )


def judged(sheet: Path, fill: Any) -> None:
    """The sheet as its judge saves it: each row's judging cells filled by ``fill(n, row)``, the rest as
    the command wrote it - marks and shown marks among them."""
    text = sheet.read_bytes().decode("utf-8-sig")
    written = list(csv.DictReader(io.StringIO(text, newline=""), delimiter=";"))
    sheet.write_bytes(encoded([row | fill(n, row) for n, row in enumerate(written)]))


async def test_the_acceptance_runs_end_to_end_with_a_model_standing_in(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    pool, connection = setup
    document = await a_plan(connection)
    model = Standing()
    context = context_of(pool, tmp_path, model, database_url)
    account = await owner(connection, document)
    values = {"Dokument-ID": str(document.id), "Kennung": LABEL, "Konto": account, "Adresse": BASE}
    operator = Operator(database_url, tmp_path / "store", tmp_path / "gold-local", values)

    # 1. a limit of 1: the document stands converted, the job ends on its budget before it asks
    with pytest.raises(PermanentError) as ended:
        await extract(context, connection, document)
    assert ended.value.code == "budget_exhausted"
    assert (model.asked, model.units) == ([], [])
    assert await done_stages(connection, document.id) == set()
    assert await rows(
        connection, "SELECT count(*) FROM document_block WHERE conversion_id = %s", document.conversion_id
    ) == [(len(DOCUMENT),)]

    # 2. the limit at what is spent and X1's charged_at_most: the run ends after X2, nothing of X3 booked
    before = await operator.json("estimate")
    assert before["unreckoned"] == {"X3": "before_x2", "X4": "before_x2"}
    spent = (await usage_of(connection, document.owner_id)).tokens_spent
    await limit(connection, document, spent + before["charged_at_most"])
    with pytest.raises(PermanentError) as ended:
        await extract(context, connection, document)
    assert ended.value.code == "run_over_budget"
    assert (model.asked, model.units) == (["profile", "outline"], [])
    assert await rows(
        connection,
        "SELECT count(*) FROM llm_usage WHERE account_id = %s AND purpose IN ('x3.frame', 'x4.unit')",
        document.owner_id,
    ) == [(0,)]
    after = await operator.json("estimate")
    assert after["unreckoned"] == {}
    assert after["charged_expected"] > 0 and after["room"] > 0
    usage = await usage_of(connection, document.owner_id)
    assert usage.token_limit is not None
    left = usage.token_limit - usage.tokens_spent
    assert after["charged_expected"] + after["room"] > left  # the estimate tells why the run stopped

    # 3. the limit raised by charged_expected and room: X3 to X5 run to the end
    await limit(connection, document, usage.token_limit + after["charged_expected"] + after["room"])
    await extract(context, connection, document)
    assert await done_stages(connection, document.id) == {"X1", "X2", "X3", "X4", "X5"}
    assert model.asked == ["profile", "outline", "frame"] and len(model.units) == len(after["requests"]) - 1

    # an import from MEM-Schule beside it, its endpoint standing in
    imported = await an_import(connection)
    mem_context = JobContext(
        pool=pool,
        storage=context.storage,
        settings=make_settings(database_url=database_url, mem_sparql_url=ENDPOINT),
    )
    await run(mem_context, await an_import_job(connection, imported), Endpoint())
    mem = {"Dokument-ID": str(imported.id), "Kennung": MEM_LABEL}

    # 4. the usage report, the draws, the replay and the MEM report, side by side
    usage_report, statements, blocks, replayed, mem_plain, mem_switch = await asyncio.gather(
        operator.json("usage"),
        operator.json("draw_statements"),
        operator.json("draw_blocks"),
        operator.json("replay"),
        operator.json("mem_report", **mem),
        operator.run("mem_report_endpoint", **mem),
    )
    assert usage_report["raw"]["ledger_equals_raw"] is True
    assert replayed["units_differing"] == [] and replayed["missing"] == 0
    assert "endpoint" not in mem_plain and mem_plain["hits"]["all"]["rows"]["searched"] == 9
    assert (mem_switch.returncode, mem_switch.stdout) == (1, b"")
    assert b"mem_refused" in mem_switch.stderr  # the switch asks the endpoint; without it nothing did

    # 5. the sheets, judged and read in, and the reports
    samples = {"Aussagen-Stichprobe": str(statements["sample"]), "Block-Stichprobe": str(blocks["sample"])}
    operator.values |= samples
    for done in await asyncio.gather(operator.run("sheet_statements"), operator.run("sheet_blocks")):
        assert done.returncode == 0, done.stderr
    statement_items = await items_of(connection, statements["sample"])
    block_items = await items_of(connection, blocks["sample"])
    last = len(statement_items) - 1
    assert last >= 1  # a correct statement and a wrong one at least
    judged(
        operator.folder / f"{LABEL}-aussagen.csv",
        lambda n, _: (
            {"verdict": "wrong", "reasons": "not_a_statement"} if n == last else {"verdict": "correct"}
        ),
    )
    judged(operator.folder / f"{LABEL}-bloecke.csv", lambda n, _: {"expected": "1"})
    taken = await asyncio.gather(operator.json("judge_statements"), operator.json("judge_blocks"))
    assert [(done["judged"], done["refused"]) for done in taken] == [
        (len(statement_items), 0),
        (len(block_items), 0),
    ]
    printed, again = await asyncio.gather(operator.json("report"), operator.json("report_replayed"))
    [entry] = printed["documents"]
    assert entry["label"] == LABEL
    statement = entry["statement"]
    assert (statement["judged"], statement["open"], statement["reasons"]["not_a_statement"]) == (
        len(statement_items),
        0,
        1,
    )
    assert statement["pooled"]["precision_strict"] == round(last / len(statement_items), 4)
    # every drawn item judged, one stratum: the weighted rate is said, and is the pooled one
    assert statement["weighted"]["precision_strict"] == statement["pooled"]["precision_strict"]
    sampled = {item.block_id for item in block_items}
    found = len(sampled & set(model.chosen))
    assert 0 < found < len(block_items)  # blocks holding a statement and blocks holding none
    assert (entry["block"]["judged"], entry["block"]["expected"], entry["block"]["found"]) == (
        len(block_items),
        len(block_items),
        found,
    )
    assert entry["block"]["recall"] == round(found / len(block_items), 4)
    kept = again["documents"][0]["statement"]["replayed"]
    assert (kept["judged"], kept["kept_correct"], kept["kept_wrong"]) == (len(statement_items), last, 1)
    assert kept["new_unjudged"] == 0  # the reader unchanged: the replay reads what was judged, no more

    # 6. every command of the handout was run
    assert sorted(set(operator.ran)) == sorted(COMMANDS)
