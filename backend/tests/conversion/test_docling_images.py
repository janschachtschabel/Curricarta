"""The pdfium part of the page images Docling's models read (app/conversion/docling_images.py), without
Docling: pypdfium2 and Pillow are in the default environment, Docling only in the converter's image."""

import gc
import logging
import threading
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pypdfium2
import pytest
from PIL import Image, ImageChops

from app.conversion.docling_images import draw_with_pdfium, render
from tests.conversion.raw_pdf import SENTENCE, pages_pdf
from tests.conversion.test_pdfplumber_blocks import turned_pdf

A4 = (595.0, 842.0)
# page k is dark across one band of its own, a twentieth of the page high: (top, bottom) from the top
BANDS = [(100 + 100 * k, 142 + 100 * k) for k in range(3)]


def _band(k: int) -> bytes:
    top, bottom = BANDS[k]
    return b"0 g 0 %d 595 %d re f\n" % (842 - bottom, bottom - top)


@pytest.fixture
def document(tmp_path: Path) -> Iterator[Any]:
    path = tmp_path / "pages.pdf"
    path.write_bytes(pages_pdf([SENTENCE + _band(k) for k in range(3)]))
    pdf = pypdfium2.PdfDocument(path)
    yield pdf
    pdf.close()


def _lightest(image: Image.Image) -> int:
    _, lightest = cast("tuple[int, int]", image.convert("L").getextrema())
    return lightest


def _dark(image: Image.Image, top: float, bottom: float, scale: float) -> bool:
    return _lightest(image.crop((0, round(top * scale), image.width, round(bottom * scale)))) < 64


@pytest.mark.parametrize("scale", [1.0, 2.0, 4.5 / 1.5, 1 / 3])
def test_a_page_comes_at_its_size_times_the_scale_in_rgb(document: Any, scale: float) -> None:
    image = render(document, 0, A4, scale)

    assert image is not None
    assert image.size == (round(595 * scale), round(842 * scale))
    assert image.mode == "RGB"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_the_page_drawn_is_the_page_at_the_index(document: Any, index: int) -> None:
    image = render(document, index, A4, 1.0)

    assert image is not None
    assert [_dark(image, top + 4, bottom - 4, 1.0) for top, bottom in BANDS] == [k == index for k in range(3)]


@pytest.mark.parametrize(("scale", "tolerance"), [(2.0, 0), (1.0, 51)])
def test_a_crop_is_the_same_region_of_the_whole_page(document: Any, scale: float, tolerance: int) -> None:
    # left, top, right, bottom from the top left, in points; each edge falls on a pixel both at the scale
    # and at pdfium's 1.5 times it. At 2 the page is 1785 x 2526 pixels in pdfium, both whole, and the
    # crop is the same pixels. At 1 its width, 892.5, comes as 893: the whole page is scaled down by
    # 893/595 where the crop is by 1.5, and its pixels slide against the crop's by up to
    # 360 * (893/892.5 - 1) = 0.2 pdfium pixels at the right edge - 0.2 * 255 = 51 in grey on an edge
    crop = (60.0, 120.0, 360.0, 260.0)
    whole = render(document, 1, A4, scale)
    part = render(document, 1, A4, scale, crop)

    assert whole is not None and part is not None
    left, top, right, bottom = (round(value * scale) for value in crop)
    assert part.size == (right - left, bottom - top)
    assert _lightest(ImageChops.difference(part, whole.crop((left, top, right, bottom)))) <= tolerance
    assert _dark(part, BANDS[1][0] - crop[1] + 4, BANDS[1][1] - crop[1] - 4, scale)


@pytest.mark.parametrize("rotate", [90, 270])
def test_a_turned_page_comes_turned(tmp_path: Path, rotate: int) -> None:
    path = tmp_path / "turned.pdf"
    path.write_bytes(turned_pdf(rotate, cropped=False))
    pdf = pypdfium2.PdfDocument(path)
    try:
        image = render(pdf, 0, (842.0, 595.0), 1.0)
    finally:
        pdf.close()

    assert image is not None and image.size == (842, 595)


@pytest.mark.parametrize("size", [(842.0, 595.0), (595.0, 841.0), (594.0, 842.0)])
def test_a_page_pdfium_measures_otherwise_than_the_size_given_is_not_drawn(
    document: Any, size: tuple[float, float]
) -> None:
    assert render(document, 0, size, 1.0) is None


def test_a_size_within_half_a_point_is_the_same_size(document: Any) -> None:
    image = render(document, 0, (595.4, 841.6), 1.0)

    assert image is not None and image.size == (595, 842)


class _Bitmap:
    def __init__(self, fails: bool) -> None:
        self.fails = fails
        self.closed = False

    def to_pil(self) -> Image.Image:
        if self.fails:
            raise RuntimeError("to_pil")
        return Image.new("RGB", (10, 10))

    def close(self) -> None:
        self.closed = True


class _Page:
    def __init__(self, bitmap: _Bitmap | None) -> None:
        self.bitmap = bitmap
        self.closed = False

    def get_size(self) -> tuple[float, float]:
        return A4

    def render(self, **_: Any) -> _Bitmap:
        if self.bitmap is None:
            raise RuntimeError("render")
        return self.bitmap

    def close(self) -> None:
        self.closed = True


class _Document:
    def __init__(self, page: _Page) -> None:
        self.page = page

    def __getitem__(self, index: int) -> _Page:
        return self.page


def test_a_page_whose_drawing_raises_is_closed() -> None:
    page = _Page(None)

    with pytest.raises(RuntimeError, match="render"):
        render(_Document(page), 0, A4, 1.0)

    assert page.closed


def test_a_bitmap_whose_image_raises_is_closed_with_its_page() -> None:
    bitmap = _Bitmap(fails=True)
    page = _Page(bitmap)

    with pytest.raises(RuntimeError, match="to_pil"):
        render(_Document(page), 0, A4, 1.0)

    assert bitmap.closed and page.closed


def test_the_page_and_its_bitmap_are_closed_once_drawn() -> None:
    bitmap = _Bitmap(fails=False)
    page = _Page(bitmap)

    assert render(_Document(page), 0, A4, 1.0) is not None
    assert bitmap.closed and page.closed


class _Size:
    def __init__(self, width: float, height: float) -> None:
        self.width, self.height = width, height


class _Box:
    """A crop box as Docling hands it: its edges from the top left, after to_top_left_origin."""

    def __init__(self, ltrb: tuple[float, float, float, float]) -> None:
        self.ltrb = ltrb

    def to_top_left_origin(self, page_height: float) -> "_Box":
        return self

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.ltrb


class _PageBackend:
    """Docling's docling-parse page backend, as far as the renderer reads it."""

    def __init__(self, page_no: int, size: tuple[float, float]) -> None:
        self.page_no = page_no
        self.size = size
        self.native: list[tuple[float, Any]] = []

    def get_size(self) -> _Size:
        return _Size(*self.size)

    def get_page_image(self, scale: float = 1, cropbox: Any = None) -> Image.Image:
        self.native.append((scale, cropbox))
        return Image.new("RGB", (1, 1))


def test_the_renderer_draws_the_page_by_its_number_from_one(document: Any) -> None:
    backend = _PageBackend(2, A4)
    draw_with_pdfium(backend, document, threading.Lock())

    image = backend.get_page_image(1.0)
    part = backend.get_page_image(2.0, _Box((0.0, 100.0, 595.0, 400.0)))

    assert image.size == (595, 842) and part.size == (1190, 600)
    assert [_dark(image, top + 4, bottom - 4, 1.0) for top, bottom in BANDS] == [False, True, False]
    assert backend.native == []


def test_the_renderer_does_not_keep_its_page_backend_alive(document: Any) -> None:
    backend = _PageBackend(1, A4)
    draw_with_pdfium(backend, document, threading.Lock())
    gone = weakref.ref(backend)

    gc.disable()
    try:
        del backend
        assert gone() is None  # let go by its count of references, without waiting for the cyclic collector
    finally:
        gc.enable()


def test_a_page_pdfium_measures_otherwise_comes_from_the_page_backend_with_one_warning(
    document: Any, caplog: pytest.LogCaptureFixture
) -> None:
    backend = _PageBackend(1, (842.0, 595.0))
    draw_with_pdfium(backend, document, threading.Lock())
    box = _Box((0.0, 0.0, 10.0, 10.0))

    with caplog.at_level(logging.WARNING, logger="app.conversion.docling_images"):
        backend.get_page_image(2.0)
        backend.get_page_image(1.0, box)

    assert backend.native == [(2.0, None), (1.0, box)]
    warnings = [record for record in caplog.records if record.name == "app.conversion.docling_images"]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert "page 1" in warnings[0].getMessage()
