"""The job's file of each type a conversion reads (app/conversion/job.py, plan M1 3b-3): written with the
ending of the type its entry has, held to it by its bytes - a file of another type fails, not_pdf, before
it is converted. The store is a folder, the database real, the conversion a stand-in in its child process."""

from uuid import UUID

import pytest

from app.conversion.job import convert_source
from app.db.conversions import conversion_for
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from app.sources.filetype import DOCX_MIME
from tests.conversion import standins
from tests.jobs.test_source_convert import FIXTURES, a_conversion, an_account, context

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["context"]  # the fixture, taken over

PDF = (FIXTURES / "prose.pdf").read_bytes()
DOCX = b"PK\x03\x04 a docx"  # held to its signature alone: the upload checked the package
HTML = "<p>Die Schülerinnen und Schüler planen.</p>".encode()


@pytest.mark.parametrize(
    ("mime", "data", "name"),
    [
        (None, PDF, "source.pdf"),  # a job queued before 3b-3: its file is a PDF
        ("application/pdf", PDF, "source.pdf"),
        (DOCX_MIME, DOCX, "source.docx"),
        ("text/html", HTML, "source.html"),
    ],
    ids=["before-3b-3", "pdf", "docx", "html"],
)
async def test_a_file_is_handed_to_the_engine_with_the_ending_of_its_type(
    context: JobContext, mime: str | None, data: bytes, name: str
) -> None:
    account = await an_account(context, page_limit=None)
    _, conversion_id, job = await a_conversion(context, data, "docling", account, mime=mime)

    await convert_source(context, job, convert=standins.naming)

    async with context.pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT text FROM document_block WHERE conversion_id = %s", (conversion_id,)
        )
        assert await cursor.fetchall() == [(name,)]


@pytest.mark.parametrize(
    ("mime", "data", "engine"),
    [
        ("application/pdf", DOCX, "pdfplumber"),
        (DOCX_MIME, PDF, "docling"),
        ("text/html", PDF, "docling"),  # a PDF, whatever its name says
        ("text/html", "<p>Prüfen</p>".encode("latin-1"), "docling"),  # no UTF-8: no HTML page
        ("text/markdown", b"# Ziele", "docling"),  # a type no conversion reads yet
        ("text/html", HTML, "pdfplumber"),  # an engine that reads PDFs alone
        (DOCX_MIME, DOCX, "pdfplumber"),
    ],
    ids=[
        "pdf-a-zip",
        "docx-a-pdf",
        "html-a-pdf",
        "html-not-utf-8",
        "markdown",
        "html-pdfplumber",
        "docx-pdfplumber",
    ],
)
async def test_a_file_not_of_a_type_its_engine_reads_fails_for_good_unconverted(
    context: JobContext, mime: str, data: bytes, engine: str
) -> None:
    account: UUID | None = await an_account(context, page_limit=None) if engine == "docling" else None
    file_id, _, job = await a_conversion(context, data, engine, account, mime=mime)

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job, convert=standins.crashing)  # converting would crash

    assert failed.value.code == "not_pdf"
    async with context.pool.connection() as connection:
        found = await conversion_for(connection, file_id, engine)
    assert found is not None and (found.status, found.error_code) == ("failed", "not_pdf")
