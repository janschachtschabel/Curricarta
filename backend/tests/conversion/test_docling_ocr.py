"""The engine docling's reading of scanned pages (plan M1 3b-2), on stand-ins shaped as Docling 2.117 with
EasyOCR hands them over (probed in the converter's image on 2026-11-06): the lines OCR read in the parsed
page's textline_cells, from_ocr, with a confidence and no font. Scanned pages are read by a pipeline of
their own, in runs; Docling itself runs in tests/conversion/test_docling_e2e.py."""

from pathlib import Path
from types import SimpleNamespace as Shape
from typing import Any

import pytest
from PIL import Image, ImageDraw

from app.conversion import docling_blocks
from app.conversion.base import EngineUnavailable
from app.conversion.docling_blocks import DoclingEngine, read_blocks
from app.conversion.ocr_words import LARGEST_IMAGE, SCALE, X_HEIGHT, PageImages
from app.conversion.text_layer import TooDense
from tests.conversion.raw_pdf import image, pages_pdf
from tests.conversion.test_docling_blocks import HEIGHT, LAYERS, bbox, item, rect, result

FIXTURES = Path(__file__).parent / "fixtures"


def ocr_line(text: str, box: tuple[float, float, float, float], confidence: float = 0.9) -> Shape:
    return Shape(text=text, rect=rect(*box), from_ocr=True, confidence=confidence)


def inked(*boxes: tuple[float, float, float, float]) -> Image.Image:
    """An A4 page's image at the scale OCR's words are measured on, each box filled with ink."""
    image = Image.new("L", (round(595 * SCALE), round(842 * SCALE)), 255)
    draw = ImageDraw.Draw(image)
    for x0, top, x1, bottom in boxes:
        draw.rectangle((x0 * SCALE, top * SCALE, x1 * SCALE, bottom * SCALE), fill=0)
    return image


def blank(number: int) -> tuple[Image.Image, float]:
    return inked(), SCALE


def test_scanned_pages_are_read_with_ocr_in_runs_of_their_own_eight_at_most() -> None:
    runs = [((1, 2), False), ((3, 5), True), ((6, 13), False), ((14, 14), True), ((15, 16), False)]
    asked: list[tuple[tuple[int, int], bool]] = []

    def convert(pages: tuple[int, int], ocr: bool) -> Shape:
        asked.append((pages, ocr))
        return result(range(pages[0], pages[1] + 1), counted=16)

    read = [
        page.number
        for block in read_blocks(
            convert, pages=16, max_signs=100, layers=LAYERS, scanned={3, 4, 5, 14}, render=blank
        )
        for page in block
    ]

    assert asked == runs
    assert read == list(range(1, 17))


def test_an_ocr_line_is_words_at_its_ink_s_size_and_the_page_says_how_sure_ocr_was() -> None:
    lines = {
        1: [
            ocr_line("Die Schüler", (100, 200, 210, 220), 0.9),
            ocr_line("planen", (100, 230, 160, 250), 0.7),
            Shape(
                text="Seite 3", rect=rect(100, 800, 150, 810), from_ocr=False, confidence=1.0
            ),  # the layer's
        ]
    }

    def convert(pages: tuple[int, int], ocr: bool) -> Shape:
        return result(range(1, 2), lines=lines)

    def render(number: int) -> tuple[Image.Image, float]:
        return inked((100, 200, 210, 220), (100, 230, 160, 250)), SCALE  # each line all ink: its band its box

    [[page]] = read_blocks(convert, pages=1, max_signs=100, layers=LAYERS, scanned={1}, render=render)

    assert [word.text for word in page.words] == ["Die", "Schüler", "planen"]
    assert all(word.font == "" and word.size == pytest.approx(20 / X_HEIGHT, rel=0.05) for word in page.words)
    assert page.ocr == 0.8  # the median of the lines' confidence


def test_a_page_read_without_ocr_says_no_confidence() -> None:
    def convert(pages: tuple[int, int], ocr: bool) -> Shape:
        return result(range(1, 2))

    [[page]] = read_blocks(convert, pages=1, max_signs=100, layers=LAYERS)

    assert page.ocr is None


def test_the_text_ocr_read_counts_towards_the_page_s_density() -> None:
    def convert(pages: tuple[int, int], ocr: bool) -> Shape:
        return result(range(1, 2), lines={1: [ocr_line("x" * 101, (10, 10, 500, 20))]})

    with pytest.raises(TooDense):
        list(read_blocks(convert, pages=1, max_signs=100, layers=LAYERS, scanned={1}, render=blank))


class Pipeline:
    """Docling's converter stood in for: a result for each page range, the lines OCR read where it reads."""

    def __init__(self, ocr: bool, pages: int) -> None:
        self.ocr, self.pages, self.asked = ocr, pages, 0

    def convert(self, path: Path, *, page_range: tuple[int, int], raises_on_error: bool) -> Shape:
        self.asked += 1
        numbers = range(page_range[0], page_range[1] + 1)
        lines = {n: [ocr_line(f"Gescannte Seite {n}", (100, 200, 300, 220), 0.6 + n / 10)] for n in numbers}
        if not self.ocr:
            return result(numbers, counted=self.pages)
        texts = [item("text", (n, bbox(95, HEIGHT - 195, 305, HEIGHT - 225))) for n in numbers]
        return result(numbers, texts, counted=self.pages, lines=lines)


@pytest.fixture
def pipelines(monkeypatch: pytest.MonkeyPatch) -> dict[bool, Pipeline]:
    made: dict[bool, Pipeline] = {}

    def converter(models: Path, ocr: bool) -> tuple[Pipeline, Any]:
        made[ocr] = Pipeline(ocr, 4)
        return made[ocr], LAYERS

    monkeypatch.setattr(docling_blocks, "version", lambda name: "2.117.0")
    monkeypatch.setattr(docling_blocks, "_converter", converter)
    return made


def test_a_file_without_a_scanned_page_loads_no_ocr(pipelines: dict[bool, Pipeline]) -> None:
    DoclingEngine(Path("/models")).convert(FIXTURES / "scan.pdf", pages=4)

    assert list(pipelines) == [False]


def test_a_scan_s_pages_are_read_by_ocr_on_their_images_and_said_so(pipelines: dict[bool, Pipeline]) -> None:
    conversion = DoclingEngine(Path("/models")).convert(FIXTURES / "scan.pdf", pages=4, scanned=[2, 3, 4])

    assert (pipelines[False].asked, pipelines[True].asked) == (1, 1)
    assert [block.text for block in conversion.blocks] == [f"Gescannte Seite {n}" for n in (2, 3, 4)]
    assert [(finding.code, finding.params) for finding in conversion.findings] == [
        ("ocr_read", {"pages": [2, 3, 4], "confidence": 0.8}),
    ]


def test_a_page_far_larger_than_a_sheet_is_rendered_no_larger_than_its_measure_needs(tmp_path: Path) -> None:
    # a poster, 3.5 m wide: at 200 dpi its image would hold some 27,000 pixels across
    huge = tmp_path / "plakat.pdf"
    huge.write_bytes(pages_pdf([image(0, 0, 9999, 84)]).replace(b"[0 0 595 842]", b"[0 0 9999 84]"))
    images = PageImages(huge)
    try:
        picture, scale = images.render(1)
    finally:
        images.close()

    assert max(picture.size) <= LARGEST_IMAGE
    assert scale == pytest.approx(LARGEST_IMAGE / 9999)
    assert abs(picture.size[1] - 84 * scale) <= 1  # pdfium rounds a side up


def test_an_ocr_pipeline_that_does_not_load_is_no_verdict_on_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the title page has a text layer, the rest is scanned: the second pipeline loads after the first
    def converter(models: Path, ocr: bool) -> tuple[Pipeline, Any]:
        if ocr:
            raise OSError("EasyOCR's folder cannot be made")
        return Pipeline(False, 4), LAYERS

    monkeypatch.setattr(docling_blocks, "version", lambda name: "2.117.0")
    monkeypatch.setattr(docling_blocks, "_converter", converter)

    with pytest.raises(EngineUnavailable):
        DoclingEngine(Path("/models")).convert(FIXTURES / "scan.pdf", pages=4, scanned=[2, 3, 4])
