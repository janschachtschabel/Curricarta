"""The conversion of an entry's DOCX or HTML page (plan M1 3b-3): asked of an engine that reads its type -
Docling -, where none is named the first offered that reads it; the type goes with the job, which writes the
file with its ending (app/conversion/job.py). A type no engine offered reads is refused, not_pdf."""

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.conversion.job import DOCLING_KIND, KIND
from app.sources.filetype import DOCX_MIME
from tests.api.test_conversions import (
    PROSE,
    client,
    client_for,
    docling_client,
    jobs,
    migrated,
    owner,
    upload,
    with_pages,
)
from tests.conversion.test_docx_hidden import docx, paragraph, run

pytestmark = pytest.mark.pg
__all__ = ["client", "docling_client", "migrated", "owner"]  # the fixtures, taken over

DOCX = docx(paragraph(run("Die Schülerinnen und Schüler planen.")))
HTML = "<h1>Lehrplan</h1><p>Die Schülerinnen und Schüler planen.</p>".encode()
FILES = [("lehrplan.docx", DOCX, DOCX_MIME), ("lehrplan.html", HTML, "text/html")]


@pytest.fixture
def docling_second(migrated: str, tmp_path: Path) -> Iterator[TestClient]:
    """The service offering pdfplumber first, Docling after it."""
    yield from client_for(migrated, tmp_path, conversion_engines="pdfplumber,docling")


@pytest.mark.parametrize(("name", "data", "mime"), FILES, ids=["docx", "html"])
@pytest.mark.parametrize("first", ["docling", "pdfplumber"])
def test_a_docx_and_an_html_page_are_converted_by_docling_their_type_named_in_the_job(
    migrated: str,
    tmp_path: Path,
    owner: tuple[UUID, dict[str, str]],
    name: str,
    data: bytes,
    mime: str,
    first: str,
) -> None:
    account, header = owner
    with_pages(migrated, account, None)
    engines = "docling,pdfplumber" if first == "docling" else "pdfplumber,docling"
    for offering in client_for(migrated, tmp_path, conversion_engines=engines):
        source_id = upload(offering, header, data, name=name)

        answer = offering.post(f"/api/v1/sources/{source_id}/conversions", headers=header)

        assert (answer.status_code, answer.json()["engine"]) == (202, "docling")
        body = answer.json()
        assert jobs(migrated, DOCLING_KIND) == [
            (UUID(body["job_id"]), DOCLING_KIND, str(account), {"conversion_id": body["id"], "mime": mime})
        ]
        assert jobs(migrated) == []


@pytest.mark.parametrize(("name", "data", "mime"), FILES, ids=["docx", "html"])
def test_a_docx_and_an_html_page_are_not_converted_where_docling_is_not_offered(
    client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]], name: str, data: bytes, mime: str
) -> None:
    _, header = owner
    source_id = upload(client, header, data, name=name)

    answer = client.post(f"/api/v1/sources/{source_id}/conversions", headers=header)

    assert (answer.status_code, answer.json()["code"]) == (422, "not_pdf")
    assert "PDF" in answer.json()["message"]  # what the service converts
    assert jobs(migrated) == []


def test_a_docx_asked_of_an_engine_that_reads_pdfs_alone_is_refused(
    docling_client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]]
) -> None:
    account, header = owner
    with_pages(migrated, account, None)
    source_id = upload(docling_client, header, DOCX, name="lehrplan.docx")

    answer = docling_client.post(
        f"/api/v1/sources/{source_id}/conversions", headers=header, json={"engine": "pdfplumber"}
    )

    assert (answer.status_code, answer.json()["code"]) == (422, "not_pdf")
    assert jobs(migrated) == [] and jobs(migrated, DOCLING_KIND) == []


def test_a_docx_of_an_account_without_pages_is_refused_for_them_not_given_to_pdfplumber(
    docling_second: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]]
) -> None:
    # pdfplumber's pages cost nothing, but it reads no DOCX: Docling is the one that could, and its pages
    # are wanting
    _, header = owner
    source_id = upload(docling_second, header, DOCX, name="lehrplan.docx")

    answer = docling_second.post(f"/api/v1/sources/{source_id}/conversions", headers=header)

    assert (answer.status_code, answer.json()["code"]) == (403, "no_pages")
    assert jobs(migrated) == [] and jobs(migrated, KIND) == []


def test_markdown_is_converted_by_no_engine_offered(
    docling_client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]]
) -> None:
    account, header = owner
    with_pages(migrated, account, None)
    source_id = upload(docling_client, header, b"# Lehrplan\n\nLernfeld 1", name="lehrplan.md")

    answer = docling_client.post(f"/api/v1/sources/{source_id}/conversions", headers=header)

    assert (answer.status_code, answer.json()["code"]) == (422, "not_pdf")
    assert jobs(migrated, DOCLING_KIND) == []


def test_a_package_of_another_type_taken_for_a_docx_is_converted_by_none(
    docling_client: TestClient, migrated: str, owner: tuple[UUID, dict[str, str]]
) -> None:
    # its bytes are a ZIP's, its type a DOCX's; the register keeps its ending, which no engine reads
    account, header = owner
    with_pages(migrated, account, None)
    source_id = upload(docling_client, header, DOCX, name="tabelle.xlsx")

    answer = docling_client.post(f"/api/v1/sources/{source_id}/conversions", headers=header)

    assert (answer.status_code, answer.json()["code"]) == (422, "not_pdf")
    assert jobs(migrated, DOCLING_KIND) == []


@pytest.mark.parametrize(
    ("name", "data", "engines", "read_by", "readable"),
    [
        ("lehrplan.pdf", PROSE, "pdfplumber", ["pdfplumber"], True),
        ("lehrplan.pdf", PROSE, "docling,pdfplumber", ["docling", "pdfplumber"], True),
        ("lehrplan.docx", DOCX, "docling,pdfplumber", ["docling"], True),
        # its conversion by Docling, made while it was offered, stays readable
        ("lehrplan.docx", DOCX, "pdfplumber", [], True),
        ("lehrplan.html", HTML, "pdfplumber", [], True),
        ("tabelle.xlsx", DOCX, "docling,pdfplumber", [], False),
        ("lehrplan.md", b"# Lehrplan", "docling,pdfplumber", [], False),
    ],
    ids=["pdf", "pdf-both", "docx", "docx-alone", "html-alone", "xlsx", "markdown"],
)
def test_an_entry_names_the_engines_offered_that_read_its_file(
    migrated: str,
    tmp_path: Path,
    owner: tuple[UUID, dict[str, str]],
    name: str,
    data: bytes,
    engines: str,
    read_by: list[str],
    readable: bool,
) -> None:
    # the entry's page asks of none where none reads it, and says so
    _, header = owner
    for offering in client_for(migrated, tmp_path, conversion_engines=engines):
        source_id = upload(offering, header, data, name=name)

        entry = offering.get(f"/api/v1/sources/{source_id}", headers=header).json()

        assert (entry["conversion_engines"], entry["conversion_readable"]) == (read_by, readable)
