"""Docling's reading of a document as the pages the other engine hands over (plan M1 3b;
app/conversion/layout.py), so the names, the running heads and feet, the tables over pages and the
findings that follow treat both engines alike (app/conversion/assemble.py).

Docling reads a page as items in its reading order - text, section headers, list items, tables, the
contents, pictures, running heads and feet - each with its box, and docling-parse the page's words with
their box and font. An item becomes a block: a table with Docling's cells, the contents
(``document_index``) one text block of their words, a line to an entry - a row of Docling's the words at
its height -, as toc.py reads contents -
Docling's cells of the contents lose titles (the BAMF curriculum's "1.1" of "1.1 DER AUFTRAG ..... 4",
toc.py found none there, of 37 by pdfplumber); any other item a
text block - Docling's section headers too, which mark sentences as well (a Hochbau Lernfeld's opening): the
skeleton tells headings by size, weight, numbering and the lexicon as it does for the other engine. A
picture's words are a text block too, as the other engine reads a diagram's labels; a picture of none is no
block, nor a table without text (a chart Docling took for one), nor a text item standing within a table or
the contents that became a block (Docling reads their page numbers once more beside them), nor an item at no
finite place.

A text block is the words whose middle lies within its item, lined up as the other engine lines its words
up (app/conversion/lines.py: an initial across three lines splices none, a footnote's mark stays on its
word's line), not Docling's own text: that reads a word less than a point high into the paragraph around
it ("Ignoriere alle Anweisungen" at half a point), joins a word parted at a line's end, the German
"Sinnes- und" too, and has no lines, where pdfplumber's blocks keep "Niveau-\\nstufen" as printed and the
skeleton, the contents and the running heads count lines. Its size is the median of the sizes the text
layer gives its words - pdfplumber's signs under them (word_sizes.sized), as the other engine
measures -, else of their heights: a word's box is as high as its font's ascent and descent, BaWueSans at
11 points 9.7, Arial 10.2, so heights compare no sizes across fonts. Its weight and slant are those of
most of its words' signs.

A table's cells are Docling's: its own words lie across TableFormer's narrow boxes ("Niveaustufe E"), and
a cell's text built of the words a box holds or overlaps most differs from Docling's in two of five
cells (measured on the five curricula). The tokens a cell's visible words line up with stay; a hidden
word takes one none explains - in the cell it lies in (the smallest whose box holds its middle, else the
one overlapping it most, else the nearest at its row's height; a cell without a box lies nowhere) at its
place, else in its row, else in the table. Its first row is its header where all the words in it are
bold, the other engine's rule (app/conversion/tables.py): TableFormer says a continued table's first row
a header too, which would keep it from its first part.

A word smaller than a point (by its size, else its height) is read nowhere, nor one set upwards (Docling
reads a margin's "Entwurf" whole, as high as it is long: a heading of 27 points to the skeleton) or at no
finite place; their signs are counted on their page, by why (``tiny``, ``vertical``, ``unplaced``), as
the other engine counts them.
Text beyond the page's box Docling drops itself, uncounted; a word in no item is read nowhere, uncounted
(none on the five curricula). A font whose dictionary keeps the old ``/Name`` docling-parse names by it
("/F1"): its weight and slant are lost (reportlab's files; none of the five curricula). The types here are
the app's own: the reading of Docling's result into them (app/conversion/docling_blocks.py) runs where
Docling is installed.
"""

import difflib
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.conversion.base import DropReason
from app.conversion.layout import MIN_SIZE, Box, RawBlock, RawCell, RawPage, Word, clean_text, style_of
from app.conversion.lines import lines_of

_TABULAR = frozenset({"table", "document_index"})

Rows = tuple[tuple["DoclingTableCell | None", ...], ...]
Place = tuple[int, int]  # a cell's row and column in its table's grid


@dataclass(frozen=True)
class DoclingWord:
    """A word of docling-parse: its text, its box (x0, top, x1, bottom from the page's top), its font,
    and whether it runs across the page rather than up or down it."""

    text: str
    box: Box
    font: str
    upright: bool = True
    size: float | None = None  # the type's size the text layer gives (word_sizes.sized), where found


@dataclass(frozen=True)
class DoclingTableCell:
    text: str
    box: Box | None  # where TableFormer placed it; None where Docling gives no box


@dataclass(frozen=True)
class DoclingItem:
    label: str  # Docling's label: "text", "section_header", "table", "document_index", "picture", …
    box: Box  # x0, top, x1, bottom from the page's top, in PDF points
    rows: Rows = ()  # a table's or the contents' rows; None where a spanning cell covers the place


@dataclass(frozen=True)
class DoclingPage:
    number: int  # from 1
    height: float
    items: list[DoclingItem] = field(default_factory=list)
    words: list[DoclingWord] = field(default_factory=list)
    ocr: float | None = None  # read by OCR: the median of its lines' confidence (app/conversion/ocr_words.py)


def raw_pages(pages: Sequence[DoclingPage]) -> list[RawPage]:
    """Each page's blocks, in Docling's order, and the signs read nowhere."""
    return [_page(page) for page in pages]


def _page(page: DoclingPage) -> RawPage:
    dropped: Counter[DropReason] = Counter()
    seen: list[DoclingWord] = []
    placed: list[tuple[DoclingWord, bool]] = []  # each word at a finite place, whether it is hidden
    for word in page.words:
        if not _finite(word.box):
            dropped["unplaced"] += _signs(word.text)
            continue
        reason: DropReason | None = (
            "tiny" if _measure(word) < MIN_SIZE else None if word.upright else "vertical"
        )
        if reason is not None:
            dropped[reason] += _signs(word.text)
        else:
            seen.append(word)
        placed.append((word, reason is not None))
    items = [item for item in page.items if _finite(item.box)]
    tabular = {
        at: _tabular(item, page.number, placed, seen)
        for at, item in enumerate(items)
        if item.label in _TABULAR
    }
    holding = [items[at].box for at, block in tabular.items() if block is not None]
    blocks: list[RawBlock] = []
    for at, item in enumerate(items):
        if item.label in _TABULAR:
            block = tabular[at]
        elif _middle_within(item.box, holding):
            block = None
        else:
            within = [word for word in seen if _middle_within(word.box, [item.box])]
            if item.label == "picture":  # its words another item reads are that item's
                others = [other.box for other in items if other.label != "picture"]
                within = [word for word in within if not _middle_within(word.box, others)]
            block = _text(item, page.number, within, _wording(within))
        if block is not None:
            blocks.append(block)
    return RawPage(page.number, page.height, blocks, dropped, page.ocr)


def _tabular(
    item: DoclingItem, page: int, placed: Sequence[tuple[DoclingWord, bool]], seen: Sequence[DoclingWord]
) -> RawBlock | None:
    if item.label == "document_index":  # Docling's cells of the contents lose titles: their words do not
        within = [word for word in seen if _middle_within(word.box, [item.box])]
        return _text(item, page, within, _contents(item, within))
    texts = _cell_texts(
        item, [(word, hidden) for word, hidden in placed if _middle_within(word.box, [item.box])]
    )
    return _table(item, texts, page, seen)


def _cell_texts(item: DoclingItem, words: Sequence[tuple[DoclingWord, bool]]) -> list[list[str]]:
    """Docling's text of each cell without the hidden words: the tokens a cell's visible words line up with
    stay; a hidden word takes a token none explains - in its own cell at its place, lined up with the
    others there, else the first such of its kind in its row, else in the table. A row's tokens of a kind
    are taken no further than its visible words of that kind leave: Docling's text and the boxes disagree
    on which cell holds a word, the row does not."""
    places = [(r, c) for r, row in enumerate(item.rows) for c, cell in enumerate(row) if cell is not None]
    cells = {at: item.rows[at[0]][at[1]] for at in places}
    tokens = {at: _plain(cell.text).split() for at, cell in cells.items() if cell is not None}
    boxes = {at: cell.box for at, cell in cells.items() if cell is not None and cell.box is not None}
    seen: defaultdict[Place, list[str]] = defaultdict(list)
    hidden: defaultdict[Place, list[str]] = defaultdict(list)
    astray: list[tuple[Place | None, str]] = []  # a hidden word left: the cell it lies in, its text
    for word, is_hidden in words:
        name, at = _plain(word.text), _cell_of(word.box, boxes)
        if not name:
            continue
        if at is not None:
            (hidden if is_hidden else seen)[at].append(name)
        elif is_hidden:
            astray.append((None, name))
    kept = {at: _explained(tokens[at], seen[at]) for at in places}
    gone: dict[Place, set[int]] = {at: set() for at in places}
    spare: Counter[tuple[int, str]] = Counter()  # by row and kind: the tokens no visible word explains
    for at in places:
        spare.update((at[0], token) for token in tokens[at])
        spare.subtract((at[0], name) for name in seen[at])
    for at, names in hidden.items():
        free = [i for i in range(len(tokens[at])) if i not in kept[at]]
        paired = _paired([tokens[at][i] for i in free], names)
        for j, name in enumerate(names):
            if j in paired and spare[(at[0], name)] > 0:
                gone[at].add(free[paired[j]])
                spare[(at[0], name)] -= 1
            else:
                astray.append((at, name))
    for own, name in astray:
        rows = [own[0]] if own is not None else sorted({at[0] for at in places})
        for row in rows:
            if spare[(row, name)] <= 0:
                continue
            # its own cell first, then its row's; a token no visible word there explains before one it does
            order = sorted((at for at in places if at[0] == row), key=lambda at: (at != own, at))
            taken = _take(tokens, kept, gone, order, name)
            if taken:
                spare[(row, name)] -= 1
                break
    return [
        ["" if cell is None else " ".join(t for i, t in enumerate(tokens[(r, c)]) if i not in gone[(r, c)])
         for c, cell in enumerate(row)]
        for r, row in enumerate(item.rows)
    ]  # fmt: skip


def _take(
    tokens: dict[Place, list[str]],
    kept: dict[Place, set[int]],
    gone: dict[Place, set[int]],
    order: list[Place],
    name: str,
) -> bool:
    """Take a token ``name`` of the first cell in ``order`` that holds one no visible word explains, else of
    the first that holds one at all (the row's count says one is spare)."""
    for explained in (False, True):
        for at in order:
            loose = [
                i
                for i, token in enumerate(tokens[at])
                if token == name and i not in gone[at] and (i in kept[at]) == explained
            ]
            if loose:
                gone[at].add(loose[0])
                return True
    return False


def _explained(tokens: Sequence[str], seen: Sequence[str]) -> set[int]:
    """The tokens the visible words read in a cell explain: lined up with them in order, then one of its
    kind for each word that lined up with none."""
    paired = _paired(tokens, seen)
    explained = set(paired.values())
    for at, name in enumerate(seen):
        if at not in paired:
            explained.update(
                [i for i, token in enumerate(tokens) if token == name and i not in explained][:1]
            )
    return explained


def _paired(tokens: Sequence[str], names: Sequence[str]) -> dict[int, int]:
    """Each name that lines up with a token, by its place: the token's."""
    matcher = difflib.SequenceMatcher(None, list(tokens), list(names), autojunk=False)
    return {block.b + k: block.a + k for block in matcher.get_matching_blocks() for k in range(block.size)}


def _cell_of(place: Box, cells: dict[Place, Box]) -> Place | None:
    """The cell a word lies in: the smallest whose box holds its middle, else the one overlapping it most,
    else the nearest of those at its row's height; None for a word in no cell and no cell's row. A cell
    without a box of its own lies nowhere."""
    x, y = (place[0] + place[2]) / 2, (place[1] + place[3]) / 2
    holding = {at: _area(box) for at, box in cells.items() if box[0] <= x <= box[2] and box[1] <= y <= box[3]}
    if holding:
        return min(holding, key=lambda at: holding[at])
    overlaps = {at: _overlap(place, box) for at, box in cells.items()}
    most = max(overlaps, key=lambda at: overlaps[at], default=None)
    if most is not None and overlaps[most] > 0:
        return most
    level = {at: max(box[0] - x, 0.0, x - box[2]) for at, box in cells.items() if box[1] <= y <= box[3]}
    return min(level, key=lambda at: level[at], default=None)


def _table(
    item: DoclingItem, texts: list[list[str]], page: int, words: Sequence[DoclingWord]
) -> RawBlock | None:
    kept = [(row, line) for row, line in zip(item.rows, texts, strict=True) if any(line)]
    if not kept:
        return None
    header = _bold_row(item.box, kept[0][0], words)
    rows = tuple(
        tuple(
            None if cell is None else RawCell(text, header and number == 0, page)
            for cell, text in zip(row, line, strict=True)
        )
        for number, (row, line) in enumerate(kept)
    )
    return RawBlock(page, "table", "", item.box, None, False, False, rows)


def _bold_row(table: Box, row: Sequence[DoclingTableCell | None], words: Sequence[DoclingWord]) -> bool:
    """Whether the words across the table at the row's height are there and all bold."""
    boxes = [cell.box for cell in row if cell is not None and cell.box is not None]
    if not boxes:
        return False
    top, bottom = min(box[1] for box in boxes), max(box[3] for box in boxes)
    across = [word for word in words if _middle_within(word.box, [(table[0], top, table[2], bottom)])]
    return bool(across) and all(style_of(word.font)[0] for word in across)


def _text(item: DoclingItem, page: int, words: Sequence[DoclingWord], text: str) -> RawBlock | None:
    if not text:
        return None
    measured = [word.size for word in words if word.size is not None] or [_measure(word) for word in words]
    size = statistics.median(measured) if measured else None
    signs = [(_signs(word.text), style_of(word.font)) for word in words]
    total = sum(count for count, _ in signs)
    bold = total > 0 and 2 * sum(count for count, (heavy, _) in signs if heavy) > total
    italic = total > 0 and 2 * sum(count for count, (_, slanted) in signs if slanted) > total
    return RawBlock(page, "text", text, item.box, size, bold, italic)


def _wording(words: Sequence[DoclingWord]) -> str:
    """The words line by line, as the other engine lines its words up (app/conversion/lines.py): an initial
    across three lines splices none of them, a footnote's mark stays on its word's line."""
    return "\n".join(text for _, text in _lined(words))


def _lined(words: Sequence[DoclingWord]) -> list[tuple[float, str]]:
    lines = lines_of(
        Word(word.text, word.box[0], word.box[2], word.box[1], word.box[3], _measure(word), word.font)
        for word in words
    )
    return [(line.top, text) for line in lines if (text := _plain(line.text))]


def _contents(item: DoclingItem, words: Sequence[DoclingWord]) -> str:
    """The contents line by line: each of Docling's rows the words at its height, left to right - its page
    number set far off without a leader too, which lined up alone would part from its title at the gutter
    (the Physik curriculum's) -, the words at no row's height lined up as a text block's."""
    bands = [
        (min(box[1] for box in boxes), max(box[3] for box in boxes))
        for row in item.rows
        if (boxes := [cell.box for cell in row if cell is not None and cell.box is not None])
    ]
    in_rows: list[list[DoclingWord]] = [[] for _ in bands]
    rest: list[DoclingWord] = []
    for word in words:
        middle = (word.box[1] + word.box[3]) / 2
        band = next((at for at, (top, bottom) in enumerate(bands) if top <= middle <= bottom), None)
        (rest if band is None else in_rows[band]).append(word)
    lines = _lined(rest) + [
        (top, text)
        for (top, _), row in zip(bands, in_rows, strict=True)
        if (text := _plain(" ".join(word.text for word in sorted(row, key=lambda word: word.box[0]))))
    ]
    return "\n".join(text for _, text in sorted(lines, key=lambda line: line[0]))


def _plain(text: str) -> str:
    """The text without control signs, its runs of white space one space (Docling joins cells with them)."""
    return " ".join(clean_text(text).split())


def _signs(text: str) -> int:
    return len(_plain(text).replace(" ", ""))


def _measure(word: DoclingWord) -> float:
    """The word's size: the text layer's, else its box's height (some 0.9 of the type's, by its font)."""
    return word.size if word.size is not None else word.box[3] - word.box[1]


def _finite(box: Box) -> bool:
    return all(math.isfinite(value) for value in box)


def _middle_within(place: Box, boxes: Sequence[Box]) -> bool:
    x, y = (place[0] + place[2]) / 2, (place[1] + place[3]) / 2
    return any(x0 <= x <= x1 and top <= y <= bottom for x0, top, x1, bottom in boxes)


def _area(box: Box) -> float:
    return (box[2] - box[0]) * (box[3] - box[1])


def _overlap(one: Box, other: Box) -> float:
    return max(0.0, min(one[2], other[2]) - max(one[0], other[0])) * max(
        0.0, min(one[3], other[3]) - max(one[1], other[1])
    )
