"""Whether a PDF carries a text layer pdfplumber can read, or needs OCR first (plan M1, 3.5)."""

from pathlib import Path

import pytest

from app.conversion import text_layer
from app.conversion.text_layer import (
    PageText,
    TooManyPages,
    UnreadablePdf,
    needs_ocr,
    page_text_lengths,
    scanned,
)
from tests.conversion.raw_pdf import SENTENCE, form_pdf, image, nested_forms_pdf, pages_pdf

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = 100


def test_each_page_yields_the_signs_of_its_text_layer() -> None:
    pages = page_text_lengths(FIXTURES / "edges.pdf", max_pages=PAGES)

    assert [page.page for page in pages] == [1, 2, 3, 4, 5]
    assert all(page.signs > 100 for page in pages)


def test_a_page_of_an_image_yields_no_text() -> None:
    pages = page_text_lengths(FIXTURES / "scan.pdf", max_pages=PAGES)

    assert [page.signs > 0 for page in pages] == [True, False, False, False]


def test_a_page_of_little_text_and_an_image_over_much_of_it_is_scanned(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.pdf"
    path.write_bytes(
        pages_pdf(
            [
                SENTENCE + image(0, 0, 595, 842),  # a text layer over a picture: read as it is
                image(50, 100, 480, 600),  # a scanned page, 57 % of it
                b"",  # an empty page: nothing to read
                image(450, 760, 100, 60),  # a logo alone, 1 % of the page: none of Docling's OCR reads it
                image(-1000, 0, 1059.5, 842),  # an image mostly beside the page: 10 % on it
            ]
        )
    )

    pages = page_text_lengths(path, max_pages=PAGES, images=True)

    assert [round(page.imaged, 2) for page in pages] == [0.0, 0.57, 0.0, 0.01, 0.1]
    assert scanned(pages) == [2, 5]


def test_the_pages_of_a_scan_are_scanned_but_its_title_page_of_text() -> None:
    assert scanned(page_text_lengths(FIXTURES / "scan.pdf", max_pages=PAGES, images=True)) == [2, 3, 4]


def test_the_images_are_measured_only_where_asked_for_an_engine_that_reads_scans() -> None:
    pages = page_text_lengths(FIXTURES / "scan.pdf", max_pages=PAGES)

    assert [page.imaged for page in pages] == [0.0] * 4 and scanned(pages) == []


@pytest.mark.parametrize(
    ("content", "form", "matrix", "share"),
    [
        # a scan placed in a form, the form scaled as it is drawn: the whole page
        (b"q 10 0 0 10 0 0 cm /Fm1 Do Q", b"q 59.5 0 0 84.2 0 0 cm /Im1 Do Q", b"", 1.0),
        (b"q 0.24 0 0 0.24 0 0 cm /Fm1 Do Q", b"q 2479 0 0 3508 0 0 cm /Im1 Do Q", b"", 1.0),
        # the form's own matrix scales it as well
        (b"/Fm1 Do", b"q 59.5 0 0 84.2 0 0 cm /Im1 Do Q", b"/Matrix [10 0 0 10 0 0]", 1.0),
        # drawn beside the page: none of it on it
        (b"q 1 0 0 1 2000 2000 cm /Fm1 Do Q", b"q 595 0 0 842 0 0 cm /Im1 Do Q", b"", 0.0),
    ],
    ids=["form scaled up", "form scaled down", "form's matrix", "form beside the page"],
)
def test_an_image_in_a_form_covers_the_page_as_the_form_is_drawn(
    tmp_path: Path, content: bytes, form: bytes, matrix: bytes, share: float
) -> None:
    path = tmp_path / "lehrplan.pdf"
    path.write_bytes(form_pdf(content, form, matrix=matrix))

    [page] = page_text_lengths(path, max_pages=PAGES, images=True)

    assert round(page.imaged, 2) == share


def test_an_image_in_a_form_in_a_form_is_placed_by_the_inner_form_then_the_outer(tmp_path: Path) -> None:
    # the outer form halves, the inner moves by 1000: the image lands at 500-550, on the page - moved first
    # and halved after, it would lie beside it
    path = tmp_path / "lehrplan.pdf"
    path.write_bytes(
        nested_forms_pdf(
            b"q 0.5 0 0 0.5 0 0 cm /Fn Do Q",
            [b"q 1 0 0 1 1000 0 cm /Fn Do Q", b"q 100 0 0 100 0 0 cm /Im1 Do Q"],
        )
    )

    [page] = page_text_lengths(path, max_pages=PAGES, images=True)

    assert round(page.imaged, 3) == 0.005


@pytest.mark.parametrize(
    ("deep", "share"), [(text_layer.DEEPEST_FORM, 1.0), (text_layer.DEEPEST_FORM + 1, 0.0)]
)
def test_forms_are_looked_into_as_deep_as_taken_and_no_deeper(
    tmp_path: Path, deep: int, share: float
) -> None:
    path = tmp_path / "lehrplan.pdf"
    path.write_bytes(
        nested_forms_pdf(b"/Fn Do", [b"/Fn Do"] * (deep - 1) + [b"q 595 0 0 842 0 0 cm /Im1 Do Q"])
    )

    [page] = page_text_lengths(path, max_pages=PAGES, images=True)

    assert page.imaged == share


def test_a_page_of_more_objects_than_looked_at_is_measured_on_the_first_of_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a file made to cost: a million images in forms nested deep took 10 s a page
    monkeypatch.setattr(text_layer, "MOST_OBJECTS", 5)
    path = tmp_path / "lehrplan.pdf"
    path.write_bytes(pages_pdf([b"".join(image(0, 84.2 * at, 59.5, 84.2) for at in range(10))]))  # 1 % each

    [page] = page_text_lengths(path, max_pages=PAGES, images=True)

    assert round(page.imaged, 2) == 0.05


def test_a_scan_needs_ocr_and_a_born_digital_plan_does_not() -> None:
    assert needs_ocr(page_text_lengths(FIXTURES / "scan.pdf", max_pages=PAGES))
    assert not needs_ocr(page_text_lengths(FIXTURES / "edges.pdf", max_pages=PAGES))


@pytest.mark.parametrize(
    ("with_text", "without", "wanted"),
    [
        (21, 2, False),  # a measured curriculum: two near-empty pages of 23
        (6, 3, True),  # a third without text: a scanned annex
        (0, 0, True),  # no page at all: nothing to read
    ],
)
def test_a_document_needs_ocr_where_under_four_fifths_of_its_pages_carry_text(
    with_text: int, without: int, wanted: bool
) -> None:
    pages = [PageText(page=n, signs=1500, drawn=1500) for n in range(1, with_text + 1)]
    pages += [PageText(page=with_text + n, signs=12, drawn=12) for n in range(1, without + 1)]

    assert needs_ocr(pages) is wanted


def test_a_file_that_is_no_pdf_is_unreadable_and_says_so_without_its_path(tmp_path: Path) -> None:
    broken = tmp_path / "geheim" / "lehrplan.pdf"
    broken.parent.mkdir()
    broken.write_bytes(b"%PDF-1.7\nthis is no document\n")

    with pytest.raises(UnreadablePdf) as refused:
        page_text_lengths(broken, max_pages=PAGES)

    assert "geheim" not in str(refused.value)


def test_a_page_the_file_claims_but_lacks_makes_it_unreadable(tmp_path: Path) -> None:
    lying = tmp_path / "lehrplan.pdf"
    lying.write_bytes(pages_pdf([SENTENCE], count=3))  # a common breakage: the tree counts pages it lost

    with pytest.raises(UnreadablePdf):
        page_text_lengths(lying, max_pages=PAGES)


def test_too_many_pages_are_counted_before_any_page_is_read(tmp_path: Path) -> None:
    lying = tmp_path / "lehrplan.pdf"
    lying.write_bytes(pages_pdf([SENTENCE], count=3))  # reading a page past the first would fail

    with pytest.raises(TooManyPages) as refused:
        page_text_lengths(lying, max_pages=2)

    assert refused.value.pages == 3
