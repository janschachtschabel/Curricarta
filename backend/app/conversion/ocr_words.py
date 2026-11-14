"""The words of a page read by OCR (plan M1 3b-2): EasyOCR, in Docling, gives lines - a text, a box, its
confidence - with no font and no size. The skeleton needs a size: a heading is one set larger than the body
(app/pipeline/skeleton.py). The box's height follows the letters' ascenders and descenders, not the type's
size, and the width a sign takes follows its weight and its case; the x-height of the ink - the band lower
case fills - follows the size. It is measured word by word, the line's size the median: a scan set a little
askew lowers its words along a line, and the band of a whole line of 400 points, 0.3 degrees askew, was 6
pixels too high - the body measured larger than a heading set 14 points. Measured so on scans of pages of
the five acceptance curricula, the items set larger than the body were all found; called larger besides
were headings set in capitals - their capitals' height in place of an x-height, a heading's emphasis OCR
says no weight of otherwise -, a logo's word in capitals, a figure's labels and a running head. A line's
words share its box by their signs; they carry no font, so none is bold (simplify: OCR says no weight).
"""

import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.conversion.docling_pages import DoclingWord
from app.conversion.layout import Box

# The x-height of a type in its size: 0.557 measured (Arial, BaWueSans, the curricula's own), 0.5-0.55 the
# common sans; the ratio of a heading's to the body's is what the skeleton weighs
X_HEIGHT = 0.55
# The height of an OCR line's box in its type's size, 1.275-1.33 measured: a line's measure where its ink is
# none to measure, on the scale of those measured beside it
BOX_HEIGHT = 1.3
SCALE = 200 / 72  # pixels to a point of the page's image the lines are measured on: 200 dpi, a scan's
# pixels: a page's image, its longer side, at most - A2 at SCALE, 4677; a poster's would hold tens of
# thousands, gigabytes - a larger page is rendered smaller, its lines measured at that scale
LARGEST_IMAGE = 5000
INK = 128  # darker than this is ink: a scan's paper is seldom white
DENSE = 0.4  # rows of at least this share of the fullest row's ink lie in the band lower case fills
# An x-height under this share of its line's box is no type's - a rule, a dotted line, a speck: lines measure
# some 0.44 (an x-height 0.557 of the size, a box 1.275)
THINNEST = 0.2
_WORD = re.compile(r"\S+")


@dataclass(frozen=True)
class OcrLine:
    text: str
    box: Box  # x0, top, x1, bottom from the page's top, in points
    confidence: float  # EasyOCR's, from 0 to 1


class PageImages:
    """A file's pages as pdfium renders them, grey, at SCALE - a page larger than LARGEST_IMAGE then,
    smaller -: what OCR's lines are measured on."""

    def __init__(self, path: Path) -> None:
        import pypdfium2 as pdfium  # in the converting child alone

        self._document = pdfium.PdfDocument(str(path))

    def render(self, number: int) -> tuple[Image.Image, float]:
        """The page ``number`` (from 1), and its pixels to a point."""
        page = self._document[number - 1]
        scale = min(SCALE, LARGEST_IMAGE / max(*page.get_size(), 1.0))
        image: Image.Image = page.render(scale=scale, grayscale=True).to_pil()
        return image, scale

    def close(self) -> None:
        self._document.close()


def words_of(lines: Sequence[OcrLine], page: Image.Image, scale: float) -> list[DoclingWord]:
    """Each line's words, each at the share of the line's box its signs take, at the line's size (``_size``)
    on ``page`` - the page's image, grey, ``scale`` pixels to a point."""
    words: list[DoclingWord] = []
    for line in lines:
        if not line.text.strip():
            continue
        x0, top, x1, bottom = line.box
        step = (x1 - x0) / len(line.text)
        placed = [
            (word.group(), (x0 + step * word.start(), top, x0 + step * word.end(), bottom))
            for word in _WORD.finditer(line.text)
        ]
        size = _size(placed, page, scale) if all(math.isfinite(value) for value in line.box) else None
        words += [DoclingWord(text, box, "", upright=True, size=size) for text, box in placed]
    return words


def _size(placed: Sequence[tuple[str, Box]], page: Image.Image, scale: float) -> float | None:
    """A line's size: the median x-height of its words in lower case, else of its words of letters - their
    capitals' height: a line in capitals reads larger -; the box's measure where none has letters, or ink as
    high as a type's (THINNEST)."""
    height = placed[0][1][3] - placed[0][1][1]
    lower = [box for text, box in placed if any(sign.islower() for sign in text)]
    lettered = lower or [box for text, box in placed if any(sign.isalpha() for sign in text)]
    bands = [
        band / scale
        for box in lettered
        if (band := x_height(_crop(page, box, scale))) is not None and band / scale >= THINNEST * height
    ]
    if bands:
        return statistics.median(bands) / X_HEIGHT
    return height / BOX_HEIGHT if height > 0 else None


def x_height(image: Image.Image) -> float | None:
    """The x-height, in pixels, of the line of type in ``image`` (grey): the longest run of rows whose ink
    is at least DENSE of the fullest row's; None where it holds none."""
    ink = image.convert("L").point(lambda value: 255 if value < INK else 0)
    rows = list(ink.resize((1, ink.height), Image.Resampling.BOX).tobytes()) if ink.height else []
    fullest = max(rows, default=0)
    if fullest == 0:
        return None
    longest = run = 0
    for row in rows:
        run = run + 1 if row >= DENSE * fullest else 0
        longest = max(longest, run)
    return float(longest)


def _crop(page: Image.Image, box: Box, scale: float) -> Image.Image:
    """The box's part of the page's image, within it: beyond its edge PIL would hand black, read as ink."""
    x0, top, x1, bottom = box
    left, upper = max(0, int(x0 * scale)), max(0, int(top * scale))
    right, lower = min(page.width, int(x1 * scale) + 1), min(page.height, int(bottom * scale) + 1)
    return page.crop((left, upper, max(left, right), max(upper, lower)))
