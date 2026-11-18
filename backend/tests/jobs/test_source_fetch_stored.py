"""The job source.fetch stores its file again where the object left the store between its look and its row,
as a sweep emptying the note of the same bytes' file taken away before would make it (app/db/deleting.py).
Fixtures: test_source_fetch.py."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.jobs.context import JobContext
from app.sources.fetch_job import fetch_source
from tests.jobs.test_source_fetch import PDF, add_source, context, pdf_answer, serving

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["context"]  # the fixture, from test_source_fetch


class TakenAfterTheLook(FileSystemStorage):
    """A store whose first answer that an object is there is out of date by the time the row is written."""

    looked = False

    def exists(self, key: str) -> bool:
        if not self.looked:
            self.looked = True
            return True
        return super().exists(key)


async def test_a_fetch_whose_object_left_the_store_meanwhile_stores_it_again(
    context: JobContext, tmp_path: Path
) -> None:
    store = FileSystemStorage(tmp_path / "taken")
    taken = replace(context, storage=AsyncStorage(TakenAfterTheLook(store.root)))
    _, job = await add_source(taken)

    await fetch_source(taken, job, transport=serving(pdf_answer))

    assert store.get(f"sources/{hashlib.sha256(PDF).hexdigest()}") == PDF
