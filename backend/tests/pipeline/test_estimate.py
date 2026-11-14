"""The reckoning of an extraction run before it asks (plan M1 11.2): every request the stages owe a
document, counted as the meter reckons it when the stage sends it - the meter's reservations are
watched, not changed -, and the stages it cannot count named with why; a model stands in
(FunctionModel), never a provider."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.profiles.openai import OpenAIModelProfile

from app.db.documents import Document, document_for_job, set_document_type
from app.db.nodes import write_subtree
from app.db.runs import RunStart, finish_run, stage_result, start_run
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from app.pipeline import run
from app.pipeline.estimate import Reckoning, _guessed_units, reckon
from app.pipeline.run import extract_document
from app.pipeline.skeleton import Heading, Skeleton
from app.pipeline.toc import Contents
from app.usage.ledger import Reservation
from app.usage.meter import LedgerMeter
from tests.db.document_of import document_of
from tests.llm.test_client import llm_settings
from tests.pipeline.test_run import (
    BODY,
    Model,
    a_document,
    a_job,
    block,
    by_hand,
    context_of,
    is_profile,
    setup,
    unwatched,
)
from tests.pipeline.test_x4_statements import with_concurrency

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["setup"]  # the database with the ontology's vocabularies and a pool, shared with test_run

SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"
VOCATIONAL = "https://w3id.org/wlo/curriculum/profile/vocational#"
BEFORE_X2 = {"X3": "before_x2", "X4": "before_x2"}
Reserved = list[tuple[str, int, int]]


@pytest.fixture
def reserved(monkeypatch: pytest.MonkeyPatch) -> Reserved:
    """Each request's reservation as the meter is asked for it: purpose, input, output."""
    seen: Reserved = []
    original = LedgerMeter.reserve

    async def watching(meter: LedgerMeter, input_tokens: int, output_tokens: int) -> Reservation:
        seen.append((meter._charge.purpose, input_tokens, output_tokens))
        return await original(meter, input_tokens, output_tokens)

    monkeypatch.setattr(LedgerMeter, "reserve", watching)
    return seen


async def reckoned(connection: psycopg.AsyncConnection, context: JobContext, document: Document) -> Reckoning:
    current = await document_for_job(connection, document.id)  # as the stages before left it
    assert current is not None and context.llm is not None and context.model is not None
    return await reckon(connection, context.llm, current, context.model(), context.settings.ontology_dir)


def requests_of(reckoning: Reckoning) -> Reserved:
    return [(request.purpose, request.input_tokens, request.output_tokens) for request in reckoning.requests]


async def after_x2(
    setup: tuple[AsyncConnectionPool, psycopg.AsyncConnection],
    tmp_path: Path,
    database_url: str,
) -> tuple[Document, JobContext]:
    """A document whose first job ended after X2, its budget spent: the outline's answer leaves the
    account too little for X3's request - the watch after X2 off, which would end it before."""
    pool, connection = setup
    document = await a_document(connection)
    model = Model()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not is_profile(messages):
            await connection.execute(
                "UPDATE quota SET token_limit = 3000 WHERE account_id = %s", (document.owner_id,)
            )
        return model(messages, info)

    with pytest.raises(PermanentError) as ended:
        await extract_document(
            unwatched(context_of(pool, tmp_path, answer, database_url), database_url),
            await a_job(connection, document.id, document.owner_id),
        )
    assert ended.value.code == "budget_exhausted"
    await connection.execute(
        "UPDATE quota SET token_limit = NULL WHERE account_id = %s", (document.owner_id,)
    )
    return document, context_of(pool, tmp_path, Model(), database_url)


def flattened(model: Model) -> Callable[[list[ModelMessage], AgentInfo], ModelResponse]:
    """``model`` reading a prompt sent in parts - a cache breakpoint between them - as its text."""

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        first = messages[0]
        assert isinstance(first, ModelRequest)
        part = first.parts[-1]
        if isinstance(part, UserPromptPart) and not isinstance(part.content, str):
            text = "".join(item for item in part.content if isinstance(item, str))
            first = replace(first, parts=[*first.parts[:-1], replace(part, content=text)])
        return model([first, *messages[1:]], info)

    return answer


async def test_x1_is_reckoned_as_its_requests_are_reserved(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str, reserved: Reserved
) -> None:
    # the type set by the editors: X1 reads the headings by it, the reckoning too
    pool, connection = setup
    document = await a_document(connection)
    await set_document_type(connection, document.id, SCHOOL + "dt-Lehrplan")
    context = context_of(pool, tmp_path, Model(specifications=False), database_url)

    reckoning = await reckoned(connection, context, document)
    await extract_document(context, await a_job(connection, document.id, document.owner_id))

    assert reckoning.owed == ("X1", "X2", "X3", "X4", "X5")
    assert reckoning.units is None  # X2 has not cut them yet
    assert reckoning.unreckoned == BEFORE_X2
    assert [entry[0] for entry in requests_of(reckoning)] == ["x1.profile", "x1.outline"]
    assert requests_of(reckoning) == [entry for entry in reserved if entry[0].startswith("x1.")]
    # guessed from the skeleton as X1 reads it - Kompetenzen, Inhaltsfeld 1, Leistungsbewertung -, cut
    # as X2 cuts a tree; X1 made Leistungsbewertung a frame part, which X2 reads for the frame alone
    kept = await stage_result(connection, document.id, "X2")
    assert kept is not None
    cut = [package["path"][-1] for package in kept["packages"] if package["job"] == "statements"]
    assert (reckoning.guessed_units, cut) == (3, ["Kompetenzen", "Inhaltsfeld 1: Optik"])


async def test_the_outline_is_reckoned_by_the_type_the_editors_set(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str, reserved: Reserved
) -> None:
    # "CE 01" is a Curriculare Einheit in a Pflege-Rahmenplan alone (vocational#c-ce-1): read without
    # a type, its pattern types the heading and leaves no outline to ask; read as an Ausbildungsordnung,
    # the heading is asked
    pool, connection = setup
    blocks = [
        block("p1-b1", "Rahmenplan der Fachkommission", size=24),
        block("p2-b1", "CE 01 Ausbildungsstart", size=16),
        block("p2-b2", BODY),
        block("p3-b1", BODY),
    ]
    document = await document_of(connection, blocks, sector="vocational", regions=())
    await connection.execute(
        "INSERT INTO quota (account_id, token_limit) VALUES (%s, NULL)", (document.owner_id,)
    )
    # without specifications: before X1 the reckoning knows none for the outline to name
    model = Model(document_type="Ausbildungsordnung", specifications=False)
    context = context_of(pool, tmp_path, model, database_url)
    untyped = await reckoned(connection, context, document)
    await set_document_type(connection, document.id, VOCATIONAL + "dt-Ausbildungsordnung")

    reckoning = await reckoned(connection, context, document)
    await extract_document(context, await a_job(connection, document.id, document.owner_id))

    assert [entry[0] for entry in requests_of(untyped)] == ["x1.profile"]
    assert [entry[0] for entry in requests_of(reckoning)] == ["x1.profile", "x1.outline"]
    assert requests_of(reckoning) == [entry for entry in reserved if entry[0].startswith("x1.")]


async def test_a_tree_set_up_by_hand_leaves_x1_unreckoned(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # X1 ends the job at once on it (document_has_tree) and asks nothing
    pool, connection = setup
    document = await a_document(connection)
    await write_subtree(connection, document.id, by_hand())

    reckoning = await reckoned(connection, context_of(pool, tmp_path, Model(), database_url), document)

    assert (reckoning.requests, reckoning.unreckoned) == ((), {"X1": "document_has_tree", **BEFORE_X2})
    assert reckoning.prefix_tokens is not None


async def test_an_imported_document_owes_no_request_of_the_model(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # its job reads the plan's tree from MEM-Schule and checks it (app/sources/mem/import_job.py)
    pool, connection = setup
    document = await a_document(connection)
    await connection.execute(
        "UPDATE document SET mem_iri = 'https://w3id.org/lehrplan/instances/rp/resource/lehrplan-134-1'"
        " WHERE id = %s",
        (document.id,),
    )
    context = context_of(pool, tmp_path, Model(), database_url)

    owing = await reckoned(connection, context, document)
    for stage in ("IM", "X5"):
        run_id = await start_run(connection, RunStart(document.id, None, None, stage, None, None, None, None))
        await finish_run(connection, run_id, "done")
    done = await reckoned(connection, context, document)

    assert owing == Reckoning(("IM", "X5"), None, None, None, (), {})
    assert done.owed == ()


async def test_after_x1_alone_the_units_are_counted_and_x3_and_x4_left_unreckoned(
    setup: Any, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # X2 broke after X1 (the next job cuts the units, without the model): they are counted, not asked
    pool, connection = setup
    document = await a_document(connection)
    context = context_of(pool, tmp_path, Model(), database_url)

    async def broken(*_: Any) -> Any:
        raise RuntimeError("the database went away")

    with monkeypatch.context() as patched:
        patched.setattr(run, "work_packages", broken)
        with pytest.raises(RuntimeError):
            await extract_document(context, await a_job(connection, document.id, document.owner_id))

    reckoning = await reckoned(connection, context, document)

    assert reckoning.owed == ("X2", "X3", "X4", "X5")
    assert (reckoning.units, reckoning.requests, reckoning.unreckoned) == (2, (), BEFORE_X2)
    assert reckoning.guessed_units is None  # counted, not guessed


async def test_x3_and_x4_are_reckoned_once_x2_is_done_as_the_next_job_reserves_them(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str, reserved: Reserved
) -> None:
    _, connection = setup
    document, context = await after_x2(setup, tmp_path, database_url)
    reserved.clear()

    reckoning = await reckoned(connection, context, document)
    await extract_document(context, await a_job(connection, document.id, document.owner_id))

    assert reckoning.owed == ("X3", "X4", "X5")
    assert (reckoning.units, reckoning.unreckoned) == (2, {})
    assert sorted(entry[0] for entry in requests_of(reckoning)) == ["x3.frame", "x4.unit", "x4.unit"]
    assert sorted(requests_of(reckoning)) == sorted(reserved)  # the units are asked side by side
    assert all(request.shared_tokens == 0 for request in reckoning.requests)  # the model takes no breakpoint


async def test_a_unit_done_is_not_reckoned_again(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str, reserved: Reserved
) -> None:
    # a job ended at the quota midway through X4, one unit at a time: E1 written, E2 open
    pool, connection = setup
    document = await a_document(connection)
    model = Model()

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        made = model(messages, info)
        if model.units == ["E1"]:  # booked, 4,400 spent: the next unit's request finds too little left
            await connection.execute(
                "UPDATE quota SET token_limit = 4500 WHERE account_id = %s", (document.owner_id,)
            )
        return made

    first = with_concurrency(context_of(pool, tmp_path, answer, database_url), database_url, 1)
    with pytest.raises(PermanentError) as ended:
        await extract_document(first, await a_job(connection, document.id, document.owner_id))
    assert ended.value.code == "budget_exhausted"
    await connection.execute(
        "UPDATE quota SET token_limit = NULL WHERE account_id = %s", (document.owner_id,)
    )
    context = context_of(pool, tmp_path, Model(), database_url)
    reserved.clear()

    reckoning = await reckoned(connection, context, document)
    await extract_document(context, await a_job(connection, document.id, document.owner_id))

    assert (reckoning.owed, reckoning.units) == (("X4", "X5"), 1)
    assert [entry[0] for entry in reserved] == ["x4.unit"]  # E2 alone
    assert requests_of(reckoning) == reserved


async def test_a_stage_no_window_fits_is_left_unreckoned(
    setup: Any, tmp_path: Path, database_url: str
) -> None:
    # the stage ends the job before it asks (prefix_too_long): the reckoning says so, counts nothing
    _, connection = setup
    document, context = await after_x2(setup, tmp_path, database_url)
    current = await document_for_job(connection, document.id)
    assert current is not None and context.model is not None
    narrow = llm_settings(llm_context_tokens=20_000)  # no room for a prefix beside a request's rest

    reckoning = await reckon(connection, narrow, current, context.model(), context.settings.ontology_dir)

    assert reckoning.requests == ()
    assert reckoning.unreckoned == {"X3": "prefix_too_long", "X4": "prefix_too_long"}
    assert reckoning.prefix_tokens is None


async def test_what_a_cache_breakpoint_keeps_before_it_is_the_prefix_counted(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str, reserved: Reserved
) -> None:
    # a model that takes one, as gpt-6-luna does: the prefix, the breakpoint, the task
    # (app/llm/calls.py, cached_up_to) - reckoned as the stages then reserve it
    _, connection = setup
    document, context = await after_x2(setup, tmp_path, database_url)
    model = FunctionModel(
        flattened(Model()),
        profile=OpenAIModelProfile(openai_supports_prompt_cache_breakpoints=True),
        settings={"max_tokens": 4_000},
    )
    breaking = replace(context, model=lambda: model)
    reserved.clear()

    reckoning = await reckoned(connection, breaking, document)
    await extract_document(breaking, await a_job(connection, document.id, document.owner_id))

    [frame] = [request for request in reckoning.requests if request.purpose == "x3.frame"]
    assert frame.shared_tokens == reckoning.prefix_tokens  # X3's: the document whole, no lists behind it
    units = [request for request in reckoning.requests if request.purpose == "x4.unit"]
    # X4's: the same document with X4's lists behind it, alike for both units (the whole fits)
    assert len(units) == 2 and units[0].shared_tokens == units[1].shared_tokens
    assert all(frame.shared_tokens < unit.shared_tokens < unit.input_tokens for unit in units)
    assert sorted(requests_of(reckoning)) == sorted(reserved)


async def test_a_document_done_owes_no_request(
    in_process_shacl: None, setup: Any, tmp_path: Path, database_url: str
) -> None:
    _, connection = setup
    document, context = await after_x2(setup, tmp_path, database_url)
    await extract_document(context, await a_job(connection, document.id, document.owner_id))

    reckoning = await reckoned(connection, context, document)

    assert (reckoning.owed, reckoning.units, reckoning.requests, reckoning.unreckoned) == ((), 0, (), {})


def a_heading(key: str, position: int, title: str, parent: str | None, node_type: str | None) -> Heading:
    return Heading(key, position, f"p1-b{position + 1}", 1, 1 if parent is None else 2, parent, title, "",
                   False, node_type, None)  # fmt: skip


async def test_the_units_are_guessed_by_the_depth_of_the_headings_types(setup: Any) -> None:
    # a register skips itself and what lies under it, an ordinance's part is read for the frame alone
    _, connection = setup
    blocks = [block(f"p1-b{at + 1}", BODY) for at in range(8)]
    headings = (
        a_heading("H1", 0, "Lernfeld 1", None, None),
        a_heading("H2", 2, "Verzeichnis", None, VOCATIONAL + "Verzeichnis"),
        a_heading("H3", 4, "Abkürzungen", "H2", None),
        a_heading("H4", 6, "§ 3 Dauer", None, VOCATIONAL + "Verordnungsteil"),
    )
    skeleton = Skeleton(headings, Contents((), frozenset()), 10.0, frozenset())

    assert await _guessed_units(connection, blocks, skeleton) == 1  # Lernfeld 1 alone
