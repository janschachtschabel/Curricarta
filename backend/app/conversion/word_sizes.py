"""Each of Docling's words with the size of the text layer's signs under it (plan M1 3b): docling-parse
gives none, and the heights of its boxes differ from one font to another (BaWueSans 11 points 9.7 high,
Arial 10.2) - pdfplumber's signs are the other engine's measure, so both engines' sizes compare."""

import math
import statistics
import unicodedata
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from app.conversion.docling_pages import DoclingWord

# a sign of the text layer: its middle, x and y from the page's top, its size, its text
Sign = tuple[float, float, float, str]
_BAND = 4.0  # points: the height of the bands the signs are filed in, to find a word's


def sized(words: Sequence[DoclingWord], signs: Sequence[Sign]) -> list[DoclingWord]:
    """The words, each with the size of its own signs among the text layer's whose middle lies within its
    box - those of one size that spell it, else those of one size as many as its own -: a sentence set at
    half a point across a word lends it none; one under which none lies keeps none. The signs are filed
    by band and, in each, by x: a page of many words on one line costs no more than one of few."""
    filed: defaultdict[int, list[Sign]] = defaultdict(list)
    for sign in signs:
        if all(math.isfinite(value) for value in sign[:3]):
            filed[int(sign[1] // _BAND)].append(sign)
    bands = {band: sorted(found) for band, found in filed.items()}
    xs = {band: [sign[0] for sign in found] for band, found in bands.items()}
    lowest, highest = (min(bands), max(bands)) if bands else (0, -1)
    measured: list[DoclingWord] = []
    for word in words:
        x0, top, x1, bottom = word.box
        if not all(math.isfinite(value) for value in word.box):
            measured.append(word)
            continue
        under: list[Sign] = []
        for band in range(max(lowest, int(top // _BAND)), min(highest, int(bottom // _BAND)) + 1):
            if band in bands:
                found = bands[band][bisect_left(xs[band], x0) : bisect_right(xs[band], x1)]
                under += [sign for sign in found if top <= sign[1] <= bottom]
        size = _own_size(word.text, under)
        measured.append(word if size is None else replace(word, size=size))
    return measured


def _own_size(text: str, under: Sequence[Sign]) -> float | None:
    by_size: defaultdict[float, list[Sign]] = defaultdict(list)
    for sign in under:
        by_size[round(sign[2], 2)].append(sign)
    if not by_size:
        return None
    wanted = _spelled(text)

    def spells(signs: list[Sign]) -> bool:
        return bool(wanted) and wanted in "".join(_spelled(sign[3]) for sign in sorted(signs))

    # pdfminer reads a ligature as one sign or as its letters, and a sign printed over itself twice
    own = max(by_size.values(), key=lambda signs: (spells(signs), -abs(len(signs) - len(wanted))))
    return statistics.median(sign[2] for sign in own)


def _spelled(text: str) -> str:
    """A text as both readers spell it alike: ligatures as their letters, no white space."""
    return "".join(unicodedata.normalize("NFKC", text).split())
