"""Which engines read a register entry's file (app/conversion/readers.py, plan M1 3b-3): by its type, and
for a ZIP by its ending, which the register keeps for a package of another type (app/sources/filetype.py)."""

import pytest

from app.conversion.readers import readers
from app.sources.filetype import DOCX_MIME, DetectedType, stored_name

BOTH = ["docling", "pdfplumber"]


@pytest.mark.parametrize(
    ("mime", "name", "offered", "read_by"),
    [
        ("application/pdf", "plan.pdf", BOTH, BOTH),  # in the order offered
        ("application/pdf", "plan.pdf", ["pdfplumber"], ["pdfplumber"]),
        (DOCX_MIME, "plan.docx", ["pdfplumber", "docling"], ["docling"]),
        (DOCX_MIME, "plan.DOCX", BOTH, ["docling"]),
        ("text/html", "plan.html", BOTH, ["docling"]),
        ("text/html", "plan.html", ["pdfplumber"], []),
        ("text/markdown", "plan.md", BOTH, []),
        (None, None, BOTH, []),  # an entry without its file
    ],
)
def test_an_entry_s_file_is_read_by_the_engines_offered_that_read_its_type(
    mime: str | None, name: str | None, offered: list[str], read_by: list[str]
) -> None:
    assert readers(offered, mime, name) == read_by


@pytest.mark.parametrize("ending", [".xlsx", ".pptx", ".odt", ".docm"])
def test_a_package_of_another_type_is_read_by_none_though_its_bytes_say_docx(ending: str) -> None:
    # every ZIP is taken for a DOCX by its signature; the register keeps a package's ending of another type
    name = stored_name(f"tabelle{ending}", DetectedType(DOCX_MIME, ".docx"))

    assert (name, readers(BOTH, DOCX_MIME, name)) == (f"tabelle{ending}", [])
