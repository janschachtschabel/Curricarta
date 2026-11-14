"""A document's table of contents (plan M1 6.3), read from its blocks without the model.

An entry is a line that ends in a page - behind a leader ("2.1 Ziele ..... 5", "Vorwort . . . iii"),
or behind a numbered title without one ("2.1 Ziele 5"), or as a contents' pattern of the lexicon
has it (a cue that maps to the contents, ``cv:occ_toc``; one that only occurs in them is the word
of a heading the contents name too, no entry's form). An entry may run over up to four lines - in
its block where it begins numbered or as a part's ("Teil VII …"), within a block or into the next
where a line runs on ("… und", "…;") or the next goes on ("und Physik", a small letter) - and its
pages may stand as a column of their own, a block of pages after a block of titles (pdfplumber,
RLP Physik 7-10). Blocks whose lines are entries the more, one after another (pages may part them;
a block of no entry between two - an entry's first lines, a part's line without a page - holds
them together, text with a sentence's end parts them), are the contents where they hold three
entries at least, with a title right before them ("Inhalt", "Inhaltsverzeichnis"), and where their
pages run as a contents' do: never back, within the document's pages, not all one - lines of
numbers elsewhere (a learning fields' overview with its hours, notes with their years) are none.
Titled, their pages may run past the document's (a gazette's reprint counting its booklet's): their
entries are read, though they end no title pages. A heading after them whose number at its end
reads as a page - its line one of their titles, or on a later page set as none of them - closes
them; refused only by its last block - one entry alone without a leader on a later page, set as
they are -, the run drops it. An entry's level is the depth of its numbering ("A.1", "6 .2 .4" as
a gazette sets it); an entry without one has none, since a block's lines share their indentation.
The contents' lines naming no page before their first entry are kept for a part on a divider page
of its own (app/pipeline/skeleton.py). The contents are never a section of the document (the old
app's lesson: they became
a root with the headings again as children), and a heading they name is one whatever its type
(app/pipeline/skeleton.py). Where the title pages end, the document's first run of three
entries at least says, whatever it is, and no run after it (a list of figures, an annex's
contents): they end there where its pages are read and it has a title or stands within the
first FRONT_PAGES pages (contents behind a long foreword have their title), or where it has
a title and stands within them though its pages are refused; else nowhere. Doubt makes headings
of the title pages; title pages of headings only within the first FRONT_PAGES pages (a first run
there that is no contents: notes citing pages), or where the first run is titled contents read
deep in (an annex's or a part's, where those up front are not read).
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from app.conversion.base import Block
from app.domain.lexicon import Cue
from app.pipeline.patterns import PatternSearch

LEAST_ENTRIES = 3
FRONT_PAGES = 5  # contents within them end the title pages untitled, or titled though refused
OUTSIDE = frozenset({"page_header", "page_footer"})  # the kinds of block no part of the text is

# A numbering that leads a title: "1", "1.2", "1.2." - two digits a part, so a year leads none -, a
# part's letter before it ("A.1"), its stops set apart as an official gazette sets them ("6 .2 .4"),
# or a letter or Roman numeral with its full stop ("A.", "IV.")
_NUMBER = re.compile(r"((?:[A-Z]\.)?\d{1,2}(?: ?\.\d{1,2})*)(?: ?\.)?(?=\s)|([A-Z]|[IVX]+)\.(?=\s)")
_LEADER = re.compile(r"(?P<title>\S.*?)\s*(?:[.…·_]\s*){2,}(?P<page>\d{1,4}|[ivxlc]{1,7})")
_NUMBERED = re.compile(r"(?P<title>\d{1,2}(?:\.\d{1,2})*\.?\s+\S.*?)\s+(?P<page>\d{1,4})")
_PAGE = re.compile(r"\d{1,4}|[ivxlc]{1,7}")
_TITLE = re.compile(r"(?i:inhalt|inhaltsverzeichnis|inhaltsübersicht|gliederung)")
_CONTENTS_TITLE = re.compile(r"(?i:inhalt|inhaltsverzeichnis|inhaltsübersicht)")  # no outline's
MOST_PENDING = 3  # lines an entry may run over before the line that ends it
_SENTENCE_ENDS = (".", "!", "?")
HEADING_LARGER = 1.15  # times the largest size of the contents: a heading after them
LONGEST_ENTRY = 500  # signs of an entry so joined: four lines and their leaders
# The word that leads a part's line in the contents ("Teil VII", "Kapitel 3", "Anhang")
_PART = re.compile(r"(?i:teil|kapitel|abschnitt|anhang|anlage)\b")
# How a line ends that an entry runs on from: a comma, a semicolon, a dash, a word that links on
_RUNS_ON = re.compile(
    r"(?:[,;\-\N{EN DASH}]|\b(?:und|oder|sowie|der|die|des|dem|den|im|in|für|zur|zum|zu|von|mit))$"
)
# How a line begins that goes on with the line before it: a small letter, a word that links on
_GOES_ON = re.compile(r"[a-zäöüß]|(?i:und|oder|sowie)\b")


@dataclass(frozen=True)
class TocEntry:
    title: str  # as printed, its numbering with it
    page: str  # the printed page the contents give
    level: int | None  # the depth of its numbering
    position: int  # of the block it stands in, among the conversion's blocks
    leader: bool = field(default=False, compare=False)  # its page behind a leader ("..... 5")


@dataclass(frozen=True)
class Contents:
    entries: tuple[TocEntry, ...]
    positions: frozenset[int]  # the blocks the contents fill, their title with them
    front_end: int | None = None  # where the title pages end: the first block of the run that decides it
    pageless: tuple[str, ...] = ()  # that run's lines before its first entry naming no page: a part's
    paged: bool = True  # whether that run's pages lie within the document: else no entry moves the end


def title_page_blocks(blocks: Sequence[Block], front_end: int | None) -> frozenset[str] | None:
    """The ids of the blocks on the title pages: those before ``front_end``; None where the contents ended
    none, so that no title pages are known."""
    return None if front_end is None else frozenset(block.id for block in blocks[:front_end])


def leading_number(text: str) -> str | None:
    """The numbering a title begins with ("1.2" of "1.2 Ziele", "IV" of "IV. Anhang", "6.2.4" of
    "6 .2 .4 Regeln"), or None."""
    found = _NUMBER.match(text)
    return None if found is None else (found[1] or found[2]).replace(" ", "")


def number_depth(number: str) -> int:
    """How deep a numbering lies: "2" at 1, "2.1" at 2; a letter or a Roman numeral at 1."""
    return number.count(".") + 1


def title_key(title: str) -> str:
    """A title as a heading and its entry are compared: without its numbering, its letters and
    digits alone, in one case."""
    number = _NUMBER.match(title)
    rest = title[number.end() :] if number is not None else title
    return "".join(sign for sign in unicodedata.normalize("NFC", rest).casefold() if sign.isalnum())


@dataclass
class _Run:
    """Blocks of entries one after another: each with its entries, a block an entry runs on from or a
    part's line without a page with none."""

    blocks: list[tuple[int, list[TocEntry]]] = field(default_factory=list)
    pageless: list[str] = field(default_factory=list)  # its lines before its first entry naming no page
    listed: list[TocEntry] = field(default_factory=list)  # its entries
    # what a heading after it is told apart by, kept as blocks come: each looked at once
    keys: set[tuple[str, str | None]] = field(default_factory=set)  # its titles' keys and numbers
    leaders: bool = True  # all its entries behind a leader
    largest: float = 0.0  # the largest size of its blocks
    last_page: int = 0

    def add(self, position: int, found: list[TocEntry], block: Block) -> None:
        self.blocks.append((position, found))
        self.listed.extend(found)
        self.keys.update((title_key(entry.title), leading_number(entry.title)) for entry in found)
        self.leaders = self.leaders and all(entry.leader for entry in found)
        self.largest = max(self.largest, block.font_size or 0.0)
        self.last_page = block.page


def find_contents(blocks: Sequence[Block], cues: Sequence[Cue], search: PatternSearch) -> Contents:
    """The contents among the blocks (all of a conversion's, in order); ``cues`` are the lexicon's
    for contents lines."""
    order = [position for position, block in enumerate(blocks) if block.kind not in OUTSIDE]
    runs = _runs(blocks, order, cues, search)
    pages = max((block.page for block in blocks), default=0)
    entries: list[TocEntry] = []
    positions: set[int] = set()
    front_end: int | None = None
    pageless: tuple[str, ...] = ()
    front_paged = True
    first_run = True
    for each in runs:
        run, listed = each.blocks, each.listed
        paged = _paged(listed, pages)
        if not paged and _heading_last(run, blocks, len(listed)) and _paged(listed[:-1], pages):
            # a heading set as the entries, its number at its end read as a page past the document
            run, listed, paged = run[:-1], listed[:-1], True
        if len(listed) < LEAST_ENTRIES:
            continue
        first = run[0][0]
        before = order.index(first) - 1
        title = blocks[order[before]].text.strip() if before >= 0 else ""
        titled = _TITLE.fullmatch(title) is not None
        if first_run:  # a later one (an annex's contents) moves no end
            first_run = False
            front = blocks[first].page <= FRONT_PAGES
            if (paged and (titled or front)) or (titled and front):
                front_end, front_paged = first, paged  # its title is before it
                pageless = tuple(line for line in each.pageless if _TITLE.fullmatch(line) is None)
        # titled as contents, they may count the pages of the print they reprint (an official
        # gazette's, a web PDF without its blank pages): their entries are read, though they end no
        # title pages - an outline's ("Gliederung") with its hours is none
        if not (paged or (_CONTENTS_TITLE.fullmatch(title) is not None and _paged(listed, None))):
            continue
        if titled:
            positions.add(order[before])
        positions.update(position for position, _ in run)
        entries.extend(listed)
    return Contents(tuple(entries), frozenset(positions), front_end, pageless, front_paged)


def _heading_last(run: Sequence[tuple[int, list[TocEntry]]], blocks: Sequence[Block], listed: int) -> bool:
    """Whether a run's last block may be a heading after its ``listed`` entries: one entry alone,
    without a leader, on a page after the block before it, and enough entries without it."""
    return (
        len(run) > 1
        and listed - 1 >= LEAST_ENTRIES
        and len(run[-1][1]) == 1
        and not run[-1][1][0].leader
        and blocks[run[-1][0]].page > blocks[run[-2][0]].page
    )


def _runs(
    blocks: Sequence[Block], order: Sequence[int], cues: Sequence[Cue], search: PatternSearch
) -> list[_Run]:
    """The runs of entries among the blocks in reading order. A block of no entry between two of
    them on the page of the one before, or between the contents' title and their first - an entry's
    first lines, a part's line without a page - is held and parts no run; two such part one. A block
    of pages after a block of titles on its page, as many pages as titles without one, gives them
    their pages."""
    runs = [_Run()]
    held: tuple[int, list[str]] | None = None
    taken: set[int] = set()  # the blocks of pages read with the titles before them
    for at, position in enumerate(order):
        if position in taken:
            continue
        block, run = blocks[position], runs[-1]
        lines = _lines(block)
        column = _page_column(blocks, order, at, lines, cues, search)
        if column is not None:
            taken.add(column[0])
            lines = column[1]
        carried = held[1] if held is not None else []
        found, left, took, leading = _read(lines, position, cues, search, carried)
        if found and run.blocks and _heads_after(block, lines, found, run):
            found = []  # a heading after them closes them
        if found and len(found) >= len(left):
            if not run.listed:  # the lines before its first entry: a part's on a divider page
                run.pageless.extend([] if held is None or took else held[1])
                run.pageless.extend(left[:leading])
            if held is not None:
                run.add(held[0], [], blocks[held[0]])
            run.add(position, found, block)
            if column is not None:
                run.add(column[0], [], blocks[column[0]])
            held = None
            continue
        if held is None and _holds(block, lines, run, blocks, order, at):
            held = (position, lines)
            continue
        held = None
        if run.blocks:
            runs.append(_Run())
    return runs


def _lines(block: Block) -> list[str]:
    """A text block's lines, each run of white space as one: the entry's forms are then read in linear
    time; none of any other block."""
    if block.kind != "text":
        return []
    return [joined for line in block.text.splitlines() if (joined := " ".join(line.split()))]


def _holds(
    block: Block, lines: Sequence[str], run: _Run, blocks: Sequence[Block], order: Sequence[int], at: int
) -> bool:
    """Whether a block of no entry may stand in a run: lines an entry may run over, ending in no
    sentence's end (text between entries parts them), on the page of the entries before it - or, the
    run not begun, right after the contents' title."""
    if run.blocks:
        placed = block.page == blocks[run.blocks[-1][0]].page
    else:
        placed = at > 0 and _TITLE.fullmatch(blocks[order[at - 1]].text.strip()) is not None
    return (
        placed
        and 0 < len(lines) <= MOST_PENDING
        and sum(map(len, lines)) <= LONGEST_ENTRY
        and not lines[-1].endswith(_SENTENCE_ENDS)
    )


def _page_column(
    blocks: Sequence[Block],
    order: Sequence[int],
    at: int,
    lines: Sequence[str],
    cues: Sequence[Cue],
    search: PatternSearch,
) -> tuple[int, list[str]] | None:
    """The block of pages after the block at ``at`` - set apart as a column of their own - and its
    lines with their pages, where as many lines lack one as it holds pages; else None."""
    if not lines or at + 1 >= len(order):
        return None
    after = blocks[order[at + 1]]
    pages = _lines(after)
    if (
        after.page != blocks[order[at]].page
        or not pages
        or any(_PAGE.fullmatch(page) is None for page in pages)
    ):
        return None
    lacking = [index for index, line in enumerate(lines) if _entry(line, 0, cues, search) is None]
    if len(lacking) != len(pages):
        return None
    paged = list(lines)
    for index, page in zip(lacking, pages, strict=True):
        paged[index] = f"{lines[index]} {page}"
    return order[at + 1], paged


def _paged(entries: Sequence[TocEntry], pages: int | None) -> bool:
    """Whether the entries' pages run as a contents' do: never back, within the document's ``pages``
    (None: any), not all one page; Roman numerals alone are the front matter's own."""
    numbers = [int(entry.page) for entry in entries if entry.page.isdigit()]
    if not numbers:
        return True
    rising = all(earlier <= later for earlier, later in pairwise(numbers))
    return rising and (pages is None or max(numbers) <= pages) and len(set(numbers)) > 1


def _read(
    lines: Sequence[str],
    position: int,
    cues: Sequence[Cue],
    search: PatternSearch,
    carried: Sequence[str] = (),
) -> tuple[list[TocEntry], list[str], bool, int]:
    """The entries of the lines - an entry run over up to MOST_PENDING lines before the one that ends
    it as one -, the lines of them no entry took, whether one took the ``carried`` lines, those of a
    block held before them, and how many of the lines left stand before the first entry."""
    entries: list[TocEntry] = []
    left: list[str] = []
    pending, carrying, took = list(carried), len(carried), False
    leading: int | None = None
    for line in lines:
        if pending and _continues(pending, line, within=not carrying):
            joined = " ".join([*pending, line])
            if len(joined) <= LONGEST_ENTRY and (entry := _entry(joined, position, cues, search)) is not None:
                leading = len(left) if leading is None else leading
                entries.append(entry)
                took = took or carrying > 0
                pending, carrying = [], 0
                continue
            if len(pending) < MOST_PENDING:
                pending.append(line)
                continue
        left.extend(pending[carrying:])
        pending, carrying = [], 0
        if (entry := _entry(line, position, cues, search)) is not None:
            leading = len(left) if leading is None else leading
            entries.append(entry)
        else:
            pending.append(line)
    left.extend(pending[carrying:])
    return entries, left, took, len(left) if leading is None else leading


def _continues(pending: Sequence[str], line: str, *, within: bool) -> bool:
    """Whether ``line`` goes on with the entry the ``pending`` lines begin: it is numbered as none of
    its own, and they begin as an entry does - numbered, or a part's - in its block, or end as a line
    runs on, or it begins as one goes on from the line before."""
    if _leads(line):
        return False
    if within and _leads(pending[0]):
        return True
    return _RUNS_ON.search(pending[-1]) is not None or _GOES_ON.match(line) is not None


def _leads(line: str) -> bool:
    """Whether a line begins as an entry of its own: numbered, or a part's ("Teil VII …")."""
    return leading_number(line) is not None or starts_part(line)


def starts_part(title: str) -> bool:
    """Whether a title begins with the word of a part ("Teil", "Kapitel", "Anhang", …)."""
    return _PART.match(title) is not None


def _entry(line: str, position: int, cues: Sequence[Cue], search: PatternSearch) -> TocEntry | None:
    # no entry is longer; and the leader's pattern backtracks in quadratic time on a long line of fill
    # signs, holding the interpreter (re releases it for no thread): 40,000 dots took a minute
    if len(line) > LONGEST_ENTRY:
        return None
    led = _LEADER.fullmatch(line)
    found = led or _NUMBERED.fullmatch(line)
    if found is not None:
        title, page = found["title"], found["page"]
    elif any(search.found(cue, line) for cue in cues) and len(parts := line.rsplit(maxsplit=1)) == 2:
        title, page = parts
        if _PAGE.fullmatch(page) is None:
            return None
    else:
        return None
    number = leading_number(title)
    return TocEntry(title, page, None if number is None else number_depth(number), position, led is not None)


def _heads_after(block: Block, lines: Sequence[str], found: Sequence[TocEntry], run: _Run) -> bool:
    """Whether a block of one entry after a run is a heading the contents lead to, its number at its end
    taken for a page ("1 Einleitung 2026", "2.1 Kompetenzen der Jahrgangsstufe 10"): its line is one of
    the run's titles, or, on a later page, it is set as none of the run's entries are - without the
    leader they all have, or larger by HEADING_LARGER than the largest of their blocks."""
    if len(found) != 1 or len(lines) != 1:
        return False
    if (title_key(lines[0]), leading_number(lines[0])) in run.keys:
        return True
    if block.page <= run.last_page:
        return False
    if run.leaders and not found[0].leader:
        return True
    return block.font_size is not None and run.largest > 0 and block.font_size >= HEADING_LARGER * run.largest
