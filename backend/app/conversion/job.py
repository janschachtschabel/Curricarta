"""The jobs source.convert and source.convert_docling: a register file's conversion into blocks by
pdfplumber or by Docling (plan M1, 3.5, 3b); a kind of their own each, as Docling's take a worker
of the converter's image (app/jobs/handlers.py). Docling's pages are billed, pdfplumber's not: a
Docling conversion is held to the pages its asker has left as it starts - none left, or a file of more,
ends it with ``no_pages`` before Docling reads it (a file over the service's limit too: ``too_many_pages``,
split it); the API refused one with none left already, but the pages are booked when a conversion is
done, and another of the same account may have spent them since. The hold reserves nothing: exact where
one converter runs (Compose), two side by side may each take what is left - an account's overshoot is
then up to one file each.

The job takes the file from the store, checks by its bytes that it is of the type its entry has - one the
engine reads (app/conversion/readers.py), a job queued without one a PDF -, and converts it, written with
the type's ending, in a child process (app/conversion/runners.py) within CONVERT_TIMEOUT_S; the child
refuses a file it cannot serve (app/conversion/convert.py). Done, the blocks, the Markdown and the pages go
in one transaction, the pages booked once (app/db/conversions.py). A failure another attempt cannot cure -
the file's own, a crash of the conversion on it, the deadline, a child the kernel killed - ends the
conversion with its reason, for good; one that may pass (a child gone without a word, the database) is tried
again by the worker. The child logs as the service does, under the job's request
(app/conversion/runners.py).

A cancel or a lost lease cancels the job's task, which ends the child (runners.py). A job whose
conversion no longer waits for it - asked again after it counted as failed, or done by its own
attempt before - records nothing and counts nothing (app/db/conversions.py).
"""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

from app.conversion.convert import ConversionRefused
from app.conversion.markdown import markdown_of
from app.conversion.readers import ENDINGS, READS
from app.conversion.runners import (
    ChildLog,
    ConversionCrashed,
    ConversionDied,
    Convert,
    convert_in_child,
    convert_with_engine,
)
from app.core.logging import current_request_id
from app.core.metrics import observe_conversion
from app.core.storage import ObjectNotFound
from app.db.conversions import FailureCode, conversion_target, record_conversion, record_failure
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from app.jobs.queue import Job, report_progress
from app.sources.filetype import PDF_MIME, detect_type
from app.usage.ledger import usage_of

log = logging.getLogger(__name__)
KIND = "source.convert"
DOCLING_KIND = "source.convert_docling"
_KINDS = {"pdfplumber": KIND, "docling": DOCLING_KIND}
BILLABLE = frozenset({"docling"})  # the engines whose pages count against an account's quota
READS_SCANS = frozenset({"docling"})  # the engines that read a scan by OCR (the engine's reads_scans)
MESSAGES: dict[FailureCode, str] = {
    "unreadable": "The file cannot be read.",
    "too_many_pages": "The file has more pages than the service converts.",
    "too_dense": "A page of the file holds more text than any page does.",
    "needs_ocr": "Too few pages carry a text layer: the file is a scan, which this engine does not read.",
    "empty": "The conversion found no text beyond running heads and feet.",
    "timed_out": "The conversion took longer than it may.",
    "died": "The conversion's process was ended, most likely for its memory.",
    "crashed": "The conversion failed on this file.",
    "not_pdf": "The file is of no type the engine converts: a PDF, for Docling a DOCX or an HTML page too.",
    "file_gone": "The file is missing from the store.",
    "no_pages": "The account has fewer pages left for the converter than the file holds.",
    "too_many_ocr_pages": "More pages of the PDF are scans to read by OCR than one conversion reads.",
}


def kind_of(engine: str) -> str:
    """The job kind that converts with ``engine``."""
    return _KINDS[engine]


async def convert_source(
    context: JobContext, job: Job, *, convert: Convert = convert_with_engine
) -> dict[str, Any]:
    """``convert`` stands in for the conversion in tests (runners.convert_in_child)."""
    conversion_id = UUID(job.payload["conversion_id"])
    async with context.pool.connection() as connection:
        target = await conversion_target(connection, conversion_id)
    if target is None:
        raise PermanentError("conversion_gone", "The conversion is no longer in the register.")
    key, engine, account_id = target
    mime = job.payload.get("mime", PDF_MIME)  # queued before 3b-3, a job converts a PDF
    max_pages = context.settings.max_pdf_pages
    if engine in BILLABLE:
        async with context.pool.connection() as connection:
            left = 0 if account_id is None else (await usage_of(connection, account_id)).pages_left
        if left == 0:
            await _fail(context, job, conversion_id, engine, "no_pages")
        held = left is not None and left < max_pages  # the file may hold no more than the pages left
        max_pages = min(max_pages, left) if left is not None else max_pages
    else:
        held = False
    try:
        data = await context.storage.get(key)
    except ObjectNotFound:
        log.warning("the file of conversion %s is not in the store: %s", conversion_id, key)
        await _fail(context, job, conversion_id, engine, "file_gone")
    ending = ENDINGS.get(mime, "")
    found = detect_type(f"source{ending}", data) if mime in READS[engine] else None
    if found is None or found.mime != mime:
        await _fail(context, job, conversion_id, engine, "not_pdf")
    async with context.pool.connection() as connection:
        await report_progress(connection, job, "converting", {})
    settings = context.settings
    told = ChildLog(level=settings.log_level, format=settings.log_format, request_id=current_request_id())
    # one mkdir, made here: in a thread, a cancel meanwhile would leave the folder behind
    folder = Path(tempfile.mkdtemp(prefix="source-"))
    try:
        path = folder / f"source{ending}"
        await asyncio.to_thread(path.write_bytes, data)
        del data  # the child reads the file; the worker need not hold it for the conversion's length
        try:
            async with asyncio.timeout(settings.convert_timeout_s):
                conversion = await convert_in_child(
                    path, engine=engine, max_pages=max_pages, convert=convert, child_log=told
                )
        except TimeoutError:
            await _fail(context, job, conversion_id, engine, "timed_out")
        except ConversionRefused as refused:
            # over the pages left, within what the service takes: more pages would have it converted
            beyond = (
                held
                and refused.code == "too_many_pages"
                and refused.pages is not None
                and refused.pages <= settings.max_pdf_pages
            )
            await _fail(context, job, conversion_id, engine, "no_pages" if beyond else refused.code)
        except ConversionCrashed:
            await _fail(context, job, conversion_id, engine, "crashed")
        except ConversionDied:
            await _fail(context, job, conversion_id, engine, "died")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    markdown = await asyncio.to_thread(markdown_of, conversion)  # a long document's text: off the loop
    async with context.pool.connection() as connection:
        recorded = await record_conversion(
            connection, conversion_id, job.id, conversion, markdown, billable=engine in BILLABLE
        )
    if recorded:
        observe_conversion(engine, "done", conversion.pages)
    else:
        log.info("conversion %s no longer waits for job %s: its result goes", conversion_id, job.id)
    return {"conversion_id": str(conversion_id), "pages": conversion.pages, "blocks": len(conversion.blocks)}


async def _fail(
    context: JobContext, job: Job, conversion_id: UUID, engine: str, code: FailureCode
) -> NoReturn:
    async with context.pool.connection() as connection:
        recorded = await record_failure(connection, conversion_id, job.id, code)
    if recorded:
        observe_conversion(engine, code)
    else:
        log.info("conversion %s no longer waits for job %s: its %s goes", conversion_id, job.id, code)
    raise PermanentError(code, MESSAGES[code])
