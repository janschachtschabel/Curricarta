"""A want of memory in the conversion is no verdict on the file and no engine to mend (audit 2026-11-14):
wherever Python's allocation fails - as Docling loads its models, as it sets up its reading of a DOCX or
HTML page, as pdfplumber reads - the MemoryError reaches the child's end, which says ``died``: no other
attempt is made into the same memory limit. Docling itself is stood in for; it is not installed here."""

from pathlib import Path
from typing import Any

import pdfplumber
import pytest

from app.conversion import docling_blocks
from app.conversion.base import engine
from app.conversion.convert import convert_file
from app.conversion.docling_blocks import DoclingEngine
from app.conversion.runners import ConversionDied, convert_in_child
from tests.conversion import standins

pytestmark = pytest.mark.anyio
FIXTURES = Path(__file__).parent / "fixtures"


def wanting(*_: Any, **__: Any) -> Any:
    raise MemoryError


def test_a_want_of_memory_as_docling_loads_its_models_is_no_engine_to_mend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docling_blocks, "version", lambda name: "2.117.0")
    monkeypatch.setattr(docling_blocks, "_converter", wanting)

    with pytest.raises(MemoryError):
        convert_file(FIXTURES / "prose.pdf", DoclingEngine(Path("/models")), max_pages=800)


def test_a_want_of_memory_as_docling_sets_up_its_reading_of_a_page_is_no_engine_to_mend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docling_blocks, "version", lambda name: "2.117.0")
    monkeypatch.setattr(docling_blocks, "flow_converter", wanting)
    page = tmp_path / "lehrplan.html"
    page.write_text("<p>Ziele</p>", encoding="utf-8")

    with pytest.raises(MemoryError):
        DoclingEngine(Path("/models")).convert_flow(page, max_pages=10)


def test_a_want_of_memory_as_pdfplumber_reads_is_no_verdict_on_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdfplumber.page.Page, "extract_words", wanting)

    with pytest.raises(MemoryError):
        engine("pdfplumber").convert(FIXTURES / "tables.pdf", pages=4)


async def test_a_conversion_whose_models_want_memory_as_they_load_died() -> None:
    # in the child, as the job runs it: died, not an engine unavailable and asked again
    with pytest.raises(ConversionDied, match="memory"):
        await convert_in_child(
            FIXTURES / "prose.pdf", engine="docling", max_pages=800, convert=standins.loading_wants_memory
        )
