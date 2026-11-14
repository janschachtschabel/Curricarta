"""The jobs that extract a document (plan M1 6.6, 7a), repair it (8b) and check it again after its
editors changed it (9), as their starter names them: their kinds, and their unique key - one of them
waits or runs on a document at a time (job.unique_key, migration 0018), so a repair never meets an
extraction, nor an editor a stage (app/db/editing.py). Apart from the pipeline
(app/pipeline/run.py, x6_repair.py), so the API starts them without importing it."""

from collections.abc import Set
from typing import Any
from uuid import UUID

from app.db.documents import Document

KIND = "extract.run"
REPAIR_KIND = "extract.repair"
CHECK_KIND = "extract.check"


def unique_key(document_id: UUID) -> str:
    """The key of the document's extraction job, an extraction's, a repair's or a check's."""
    return f"{KIND}:{document_id}"


def checkable(document: Document, done: Set[str]) -> bool:
    """Whether a check (X5 again) may start on the document, given the stages ``done`` on it: once X5
    checked it; a draft copy, which takes no runs along, at once; an import from MEM-Schule once its
    run IM wrote the plan's tree, so that one whose X5 failed is checked on (plan M2 E1)."""
    return document.copy_of is not None or "X5" in done or (document.mem_iri is not None and "IM" in done)


def document_in(payload: dict[str, Any]) -> UUID | None:
    """The document a job's payload names (``{"document_id": …}``); none for none or no id."""
    try:
        return UUID(str(payload["document_id"]))
    except (KeyError, ValueError):
        return None
