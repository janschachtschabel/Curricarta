"""The job source.convert: a register file's conversion into blocks (plan M1, 3.5).

The store is a folder, the database real, the conversion runs in its child process as in the
service - on the fixtures of tests/conversion.
"""

import contextlib
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from prometheus_client import REGISTRY
from psycopg_pool import AsyncConnectionPool

from app.conversion.base import offered_engines
from app.conversion.job import DOCLING_KIND, KIND, convert_source, kind_of
from app.conversion.runners import ConversionFailed, Convert
from app.core.ids import new_id
from app.core.logging import current_request_id, set_request_id
from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.db.accounts import create_account
from app.db.conversions import blocks_on_page, conversion_for, lock_conversion, start_conversion
from app.db.migrate import migrate
from app.jobs.context import JobContext
from app.jobs.handlers import make_handlers
from app.jobs.outcome import PermanentError
from app.jobs.queue import Job, claim, enqueue
from tests.conversion import standins
from tests.conversion.raw_pdf import SENTENCE, pages_pdf
from tests.support import make_settings

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

FIXTURES = Path(__file__).resolve().parents[1] / "conversion" / "fixtures"


@pytest.fixture
async def context(database_url: str, tmp_path: Path) -> AsyncIterator[JobContext]:
    migrate(database_url)
    async with AsyncConnectionPool(database_url, min_size=1, max_size=4, open=False) as pool:
        storage = AsyncStorage(FileSystemStorage(tmp_path / "store"))
        settings = make_settings(database_url=database_url, max_pdf_pages=10, convert_timeout_s=60)
        yield JobContext(pool=pool, storage=storage, settings=settings)


def settled(context: JobContext, database_url: str, **settings: Any) -> JobContext:
    """The context with other settings."""
    return JobContext(context.pool, context.storage, make_settings(database_url=database_url, **settings))


async def a_conversion(
    context: JobContext,
    data: bytes | None,
    engine: str = "pdfplumber",
    account: UUID | None = None,
    mime: str | None = None,
) -> tuple[UUID, UUID, Job]:
    """A register file holding ``data`` (none in the store where None), its conversion by ``engine``
    asked for - of a file of type ``mime``, a job of none as before 3b-3 -, and the job claimed: (file,
    conversion, job)."""
    file_id, conversion_id = new_id(), new_id()
    key = f"sources/{file_id.hex}"
    if data is not None:
        await context.storage.put(key, data)
    async with context.pool.connection() as connection, connection.transaction():
        await connection.execute(
            "INSERT INTO source_file (id, sha256, size_bytes, storage_key) VALUES (%s, %s, %s, %s)",
            (file_id, new_id().bytes * 2, len(data or b""), key),
        )
        await lock_conversion(connection, file_id, engine)
        payload = {"conversion_id": str(conversion_id), **({"mime": mime} if mime else {})}
        job_id = await enqueue(connection, kind_of(engine), "test", payload)
        await start_conversion(
            connection,
            conversion_id,
            source_file_id=file_id,
            engine=engine,
            account_id=account,
            job_id=job_id,
        )
    async with context.pool.connection() as connection:
        job = await claim(connection, "w1", [kind_of(engine)], 60)
    assert job is not None and job.id == job_id
    return file_id, conversion_id, job


async def state(context: JobContext, file_id: UUID) -> Any:
    async with context.pool.connection() as connection:
        return await conversion_for(connection, file_id, "pdfplumber")


def counted(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_a_pdf_in_the_store_becomes_blocks_markdown_and_booked_pages(context: JobContext) -> None:
    file_id, conversion_id, job = await a_conversion(context, (FIXTURES / "prose.pdf").read_bytes())
    done_before = counted("curricarta_conversions_total", engine="pdfplumber", outcome="done")
    pages_before = counted("curricarta_conversion_pages_total", engine="pdfplumber")

    result = await convert_source(context, job)

    found = await state(context, file_id)
    assert (found.status, found.pages, found.engine_version) == ("done", 2, "0.11.10")
    assert result == {"conversion_id": str(conversion_id), "pages": 2, "blocks": 7}
    async with context.pool.connection() as connection:
        blocks = await blocks_on_page(connection, conversion_id, 1)
        cursor = await connection.execute("SELECT markdown FROM conversion WHERE id = %s", (conversion_id,))
        (markdown,) = await cursor.fetchone() or ("",)
        cursor = await connection.execute("SELECT progress FROM job WHERE id = %s", (job.id,))
        (progress,) = await cursor.fetchone() or (None,)
    assert blocks[0].bold and blocks[0].text == "1 Lernfeld Steuerungstechnik"
    assert markdown.startswith("<!-- p1-b1 -->\n1 Lernfeld Steuerungstechnik\n")
    assert progress == {"code": "converting", "params": {}}
    assert counted("curricarta_conversions_total", engine="pdfplumber", outcome="done") == done_before + 1
    assert counted("curricarta_conversion_pages_total", engine="pdfplumber") == pages_before + 2


async def test_a_conversion_run_again_books_its_pages_once(context: JobContext) -> None:
    _, conversion_id, job = await a_conversion(context, (FIXTURES / "prose.pdf").read_bytes())

    await convert_source(context, job)
    await convert_source(context, job)

    async with context.pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT count(*) FROM conversion_usage WHERE conversion_id = %s", (conversion_id,)
        )
        assert await cursor.fetchone() == (1,)


@pytest.mark.parametrize(
    ("data", "max_pages", "code"),
    [
        ((FIXTURES / "scan.pdf").read_bytes(), 10, "needs_ocr"),
        ((FIXTURES / "edges.pdf").read_bytes(), 4, "too_many_pages"),  # 5 pages
        (b"PK\x03\x04 a docx", 10, "not_pdf"),
        (b"%PDF-1.7\nno document\n", 10, "unreadable"),
        # what the upload takes for a PDF the job takes for one too (app/sources/filetype.py)
        (b"%PDF no document\n", 10, "unreadable"),
        (pages_pdf([SENTENCE], count=3), 10, "unreadable"),
        (None, 10, "file_gone"),
    ],
    ids=["scan", "too-many-pages", "docx", "broken", "no-dash", "a-page-lost", "gone"],
)
async def test_a_file_that_cannot_be_converted_fails_with_its_reason_for_good(
    context: JobContext, database_url: str, data: bytes | None, max_pages: int, code: str
) -> None:
    context = settled(context, database_url, max_pdf_pages=max_pages)
    file_id, _, job = await a_conversion(context, data)
    before = counted("curricarta_conversions_total", engine="pdfplumber", outcome=code)

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job)

    assert failed.value.code == code
    found = await state(context, file_id)
    assert (found.status, found.error_code) == ("failed", code)
    assert counted("curricarta_conversions_total", engine="pdfplumber", outcome=code) == before + 1


async def test_a_conversion_past_its_deadline_ends_its_process_and_fails_for_good(
    context: JobContext, database_url: str
) -> None:
    quick = settled(context, database_url, convert_timeout_s=1)
    file_id, _, job = await a_conversion(quick, (FIXTURES / "prose.pdf").read_bytes())

    with pytest.raises(PermanentError) as failed:
        await convert_source(quick, job, convert=standins.working)

    assert failed.value.code == "timed_out"
    assert (await state(quick, file_id)).error_code == "timed_out"


async def test_a_conversion_that_crashes_fails_for_good(context: JobContext) -> None:
    # the same file crashes the same engine each time: another attempt would only cost
    file_id, _, job = await a_conversion(context, (FIXTURES / "prose.pdf").read_bytes())
    before = counted("curricarta_conversions_total", engine="pdfplumber", outcome="crashed")

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job, convert=standins.crashing)

    assert failed.value.code == "crashed"
    assert (await state(context, file_id)).error_code == "crashed"
    assert counted("curricarta_conversions_total", engine="pdfplumber", outcome="crashed") == before + 1


@pytest.mark.skipif(sys.platform == "win32", reason="a signal ends a process on POSIX")
async def test_a_conversion_the_kernel_kills_fails_for_good(context: JobContext) -> None:
    file_id, _, job = await a_conversion(context, (FIXTURES / "prose.pdf").read_bytes())

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job, convert=standins.vanishing)

    assert failed.value.code == "died"
    assert (await state(context, file_id)).error_code == "died"


async def test_a_child_that_exits_without_an_answer_leaves_the_conversion_to_another_attempt(
    context: JobContext,
) -> None:
    file_id, _, job = await a_conversion(context, (FIXTURES / "prose.pdf").read_bytes())

    with pytest.raises(ConversionFailed):  # no PermanentError: the worker tries it again
        await convert_source(context, job, convert=standins.exiting)

    found = await state(context, file_id)
    assert (found.status, found.error_code) == ("pending", None)


async def test_the_child_logs_as_the_service_does_under_the_job_s_request(
    context: JobContext, database_url: str
) -> None:
    told = settled(context, database_url, log_level="ERROR", log_format="json")
    _, conversion_id, job = await a_conversion(told, (FIXTURES / "prose.pdf").read_bytes())
    before = current_request_id()
    set_request_id("job-trace-7")  # as the worker does for the job (app/jobs/worker.py)
    try:
        await convert_source(told, job, convert=standins.telling_its_logging)
    finally:
        set_request_id(before)

    async with told.pool.connection() as connection:
        blocks = await blocks_on_page(connection, conversion_id, 1)
    assert blocks[0].text == "ERROR JsonFormatter job-trace-7"


@pytest.mark.parametrize(
    ("data", "convert", "timeout_s"),
    [
        ((FIXTURES / "prose.pdf").read_bytes(), standins.reading, 60),
        ((FIXTURES / "prose.pdf").read_bytes(), standins.refusing, 60),
        ((FIXTURES / "prose.pdf").read_bytes(), standins.working, 1),
    ],
    ids=["done", "refused", "past-its-deadline"],
)
async def test_a_conversion_leaves_no_file_behind(
    context: JobContext,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
    convert: Convert,
    timeout_s: float,
) -> None:
    timed = settled(context, database_url, convert_timeout_s=timeout_s)
    _, _, job = await a_conversion(timed, data)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    with contextlib.suppress(PermanentError):
        await convert_source(timed, job, convert=convert)

    assert list(scratch.iterdir()) == []


async def test_the_pages_of_pdfplumber_are_booked_as_costing_nothing(context: JobContext) -> None:
    _, conversion_id, job = await a_conversion(context, (FIXTURES / "prose.pdf").read_bytes())

    await convert_source(context, job)

    async with context.pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT engine, pages, billable FROM conversion_usage WHERE conversion_id = %s", (conversion_id,)
        )
        assert await cursor.fetchone() == ("pdfplumber", 2, False)


async def test_a_job_whose_conversion_is_gone_fails_for_good(context: JobContext) -> None:
    async with context.pool.connection() as connection:
        await enqueue(connection, KIND, "test", {"conversion_id": str(new_id())})
        job = await claim(connection, "w1", [KIND], 60)
    assert job is not None

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job)

    assert failed.value.code == "conversion_gone"


async def asked_again(context: JobContext, file_id: UUID, conversion_id: UUID) -> UUID:
    """The conversion asked for again under a new job, as after its old job counted as failed."""
    async with context.pool.connection() as connection, connection.transaction():
        await lock_conversion(connection, file_id, "pdfplumber")
        job_id = await enqueue(connection, KIND, "test", {"conversion_id": str(conversion_id)})
        await start_conversion(
            connection,
            conversion_id,
            source_file_id=file_id,
            engine="pdfplumber",
            account_id=None,
            job_id=job_id,
        )
    return job_id


@pytest.mark.parametrize(
    ("data", "convert"),
    [((FIXTURES / "prose.pdf").read_bytes(), standins.reading), ((FIXTURES / "scan.pdf").read_bytes(), None)],
    ids=["converted", "refused"],
)
async def test_a_job_its_conversion_was_asked_again_without_leaves_it_to_the_new_one(
    context: JobContext, data: bytes, convert: Convert | None
) -> None:
    file_id, conversion_id, old_job = await a_conversion(context, data)
    new_job = await asked_again(context, file_id, conversion_id)
    done_before = counted("curricarta_conversions_total", engine="pdfplumber", outcome="done")
    refused_before = counted("curricarta_conversions_total", engine="pdfplumber", outcome="needs_ocr")

    with contextlib.suppress(PermanentError):  # the old job ends as it ends; the conversion is not its
        await convert_source(context, old_job, **({"convert": convert} if convert else {}))

    found = await state(context, file_id)
    assert (found.status, found.error_code, found.job_id) == ("pending", None, new_job)
    async with context.pool.connection() as connection:
        assert await blocks_on_page(connection, conversion_id, 1) == []
    assert counted("curricarta_conversions_total", engine="pdfplumber", outcome="done") == done_before
    # a job whose conversion is no longer its counts nothing, as it records nothing
    assert counted("curricarta_conversions_total", engine="pdfplumber", outcome="needs_ocr") == refused_before


async def test_the_worker_knows_the_conversion(context: JobContext) -> None:
    assert KIND == "source.convert"
    assert KIND in make_handlers(context)


def test_each_engine_s_conversions_are_a_job_kind_of_their_own() -> None:
    # Docling's take a worker with Docling and its models, pdfplumber's any (app/jobs/handlers.py)
    assert {engine: kind_of(engine) for engine in offered_engines()} == {
        "pdfplumber": KIND,
        "docling": DOCLING_KIND,
    }
    assert DOCLING_KIND == "source.convert_docling"


async def an_account(context: JobContext, page_limit: int | None, spent: int = 0) -> UUID:
    """An account with a quota of ``page_limit`` pages, ``spent`` of them booked for a conversion by
    Docling."""
    async with context.pool.connection() as connection:
        account = await create_account(connection, f"Konto {new_id().hex[:8]}", ["nutzer"])
        await connection.execute(
            "INSERT INTO quota (account_id, page_limit) VALUES (%s, %s)", (account, page_limit)
        )
    if spent:
        _, conversion_id, _ = await a_conversion(context, None, "docling", account)
        async with context.pool.connection() as connection:
            await connection.execute(
                "INSERT INTO conversion_usage (conversion_id, account_id, engine, pages, billable)"
                " VALUES (%s, %s, 'docling', %s, true)",
                (conversion_id, account, spent),
            )
    return account


async def usage_of_conversion(context: JobContext, conversion_id: UUID) -> Any:
    async with context.pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT engine, pages, billable FROM conversion_usage WHERE conversion_id = %s", (conversion_id,)
        )
        return await cursor.fetchone()


async def test_a_conversion_by_docling_of_an_account_without_pages_left_converts_nothing(
    context: JobContext,
) -> None:
    # started while a page was left, the pages of another conversion booked meanwhile
    account = await an_account(context, page_limit=5, spent=5)
    file_id, conversion_id, job = await a_conversion(
        context, (FIXTURES / "prose.pdf").read_bytes(), "docling", account
    )

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job, convert=standins.crashing)  # converting would crash

    assert failed.value.code == "no_pages"
    async with context.pool.connection() as connection:
        found = await conversion_for(connection, file_id, "docling")
    assert found is not None and (found.status, found.error_code) == ("failed", "no_pages")
    assert await usage_of_conversion(context, conversion_id) is None


async def test_a_file_of_more_pages_than_the_account_has_left_is_not_converted_by_docling(
    context: JobContext,
) -> None:
    account = await an_account(context, page_limit=10, spent=9)  # one left, the file has two
    _, conversion_id, job = await a_conversion(
        context, (FIXTURES / "prose.pdf").read_bytes(), "docling", account
    )

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job, convert=standins.read_by_pdfplumber)

    assert failed.value.code == "no_pages"
    assert await usage_of_conversion(context, conversion_id) is None


@pytest.mark.parametrize("page_limit", [None, 12], ids=["no-limit", "pages-left"])
async def test_a_file_within_the_pages_the_account_has_left_is_converted_and_booked(
    context: JobContext, page_limit: int | None
) -> None:
    account = await an_account(context, page_limit=page_limit, spent=10 if page_limit else 0)
    _, conversion_id, job = await a_conversion(
        context, (FIXTURES / "prose.pdf").read_bytes(), "docling", account
    )

    await convert_source(context, job, convert=standins.read_by_pdfplumber)

    assert await usage_of_conversion(context, conversion_id) == ("docling", 2, True)


async def test_pdfplumber_s_pages_are_not_held_to_the_quota(context: JobContext) -> None:
    account = await an_account(context, page_limit=0)
    _, conversion_id, job = await a_conversion(
        context, (FIXTURES / "prose.pdf").read_bytes(), "pdfplumber", account
    )

    await convert_source(context, job)

    assert await usage_of_conversion(context, conversion_id) == ("pdfplumber", 2, False)


async def test_a_conversion_by_docling_no_account_asked_for_has_no_pages(context: JobContext) -> None:
    _, _, job = await a_conversion(context, (FIXTURES / "prose.pdf").read_bytes(), "docling")

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job, convert=standins.read_by_pdfplumber)

    assert failed.value.code == "no_pages"


@pytest.mark.parametrize(
    ("max_pages", "spent", "pages", "code"),
    [
        (2, 9, 3, "too_many_pages"),  # one left of ten, two the service takes, the file three: split it
        (1, 9, 2, "too_many_pages"),  # as many left as the service takes: the service's limit
        (3, 9, 2, "no_pages"),  # one left, the file two, the service takes three: ask for pages
    ],
    ids=["over-both", "left-as-the-service-s", "over-the-pages-left"],
)
async def test_a_file_too_long_says_whose_limit_it_is_over(
    context: JobContext, database_url: str, max_pages: int, spent: int, pages: int, code: str
) -> None:
    account = await an_account(context, page_limit=10, spent=spent)
    context = settled(context, database_url, max_pdf_pages=max_pages)
    _, _, job = await a_conversion(context, pages_pdf([SENTENCE] * pages), "docling", account)

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job, convert=standins.read_by_pdfplumber)

    assert failed.value.code == code
