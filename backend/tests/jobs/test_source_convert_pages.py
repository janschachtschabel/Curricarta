"""A conversion by an engine that costs, held to the pages its asker has left as it starts, is held to them
again as it is booked (audit 2026-11-14): pages another conversion of the account booked meanwhile end it as
no_pages, with nothing written."""

import psycopg
import pytest

from app.conversion import job as job_module
from app.conversion.base import Conversion
from app.conversion.job import convert_source
from app.conversion.markdown import markdown_of
from app.db.conversions import conversion_for
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from tests.conversion import standins
from tests.jobs.test_source_convert import (
    FIXTURES,
    a_conversion,
    an_account,
    context,
    counted,
    usage_of_conversion,
)

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["context"]  # the fixture, shared with test_source_convert


async def test_a_conversion_past_the_pages_left_at_its_end_fails_as_no_pages(
    context: JobContext, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await an_account(context, page_limit=10)
    _, other, _ = await a_conversion(context, None, "docling", account)
    file_id, conversion_id, job = await a_conversion(
        context, (FIXTURES / "prose.pdf").read_bytes(), "docling", account
    )

    def booked_meanwhile(conversion: Conversion) -> str:
        # while this one was converted, ten pages left as it began, another booked nine
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                "INSERT INTO conversion_usage (conversion_id, account_id, engine, pages, billable)"
                " VALUES (%s, %s, 'docling', 9, true)",
                (other, account),
            )
        return markdown_of(conversion)

    monkeypatch.setattr(job_module, "markdown_of", booked_meanwhile)
    failed_before = counted("curricarta_conversions_total", engine="docling", outcome="no_pages")

    with pytest.raises(PermanentError) as failed:
        await convert_source(context, job, convert=standins.read_by_pdfplumber)

    assert failed.value.code == "no_pages"
    assert counted("curricarta_conversions_total", engine="docling", outcome="no_pages") == failed_before + 1
    async with context.pool.connection() as connection:
        found = await conversion_for(connection, file_id, "docling")
        cursor = await connection.execute(
            "SELECT count(*) FROM document_block WHERE conversion_id = %s", (conversion_id,)
        )
        blocks = await cursor.fetchone()
    assert found is not None and (found.status, found.error_code) == ("failed", "no_pages")
    assert blocks == (0,)
    assert await usage_of_conversion(context, conversion_id) is None
