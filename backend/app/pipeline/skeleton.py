"""A document's skeleton without the model (plan M1 6.3): its headings, their levels and parents,
their codes, and the node type a strong pattern of the lexicon gives a heading.

A heading is a text block of 200 signs and three lines at most that ends in no full stop, comma or
semicolon, is no list (two lines numbered) and is one of these: a pattern of the document's active
cues for headings or codes finds it that names a node type of the profile; it is numbered and set
bold or larger; the contents name it (app/pipeline/toc.py); it is set larger than the body by
LARGER; it is bold, 80 signs at most, and the text after it is not. What layout alone makes a
heading is none on the first page of a document of more pages - the title page, its title set
larger than any heading - and nothing before the end of the title pages is a heading
(app/pipeline/toc.py says where they end; where the contents end them, they run on to the page of
the heading the contents' first entry names, an imprint after the contents with them). A table
is a heading where a pattern finds its title - its first row's first cell with text (a learning
field set as a table, "Lernfeld 5: …") - or the contents name it with its number, or a label of
its first rows names it ("Modultitel:", app/pipeline/table_titles.py: titled, typed and coded by
its labels) - where the module's own heading stands right before it, alike or with its code or
"Modul" before ("INF-B-110 Grundlagen …"), that heading is the module, typed and coded by them; its
content is never one. A numbered entry names a title without its number only where no block bears
the number with it (an overview's line before the chapter's own heading). Headers and footers are
no text.
The level is the depth of a heading's numbering, else its entry's in the contents, else the rank
of its size among those of the larger headings (the largest first), else - bold, a table - one
below the smallest of them, and below the last numbered heading before it where the numbering
goes on within it (a section's bold parts are its own, not the chapters' siblings), no part's
("Teil", "Anhang") nor one the contents name. A module's table, and an unnumbered module heading
merged with it, lies at its entry's level, else one below its group: the last heading before it
shallower than the modules, or numbered, or set larger - a bold line as deep as they is a note
beside them. A heading lies under the last
one before it of a smaller level; its level as the skeleton gives it is its depth in that tree,
from 1.
A strong cue - of STRONG at least, a threshold not yet measured (konzept §20.6) - types a heading
where all such cues that find it name one node type, and no homonym finds it: the node then
comes from a rule, the cue's IRI its rule. Cues tied for their word name other targets, so they
type nothing unless those agree on the node type. Where the pattern of a homonym or a strong cue
took too long, it may have found any heading and said otherwise: no heading is typed by a rule.
Any other heading's type is left to the model (X1, plan M1 6.4).
A heading's code is its label's for a module, else its numbering, else - where a heading's
pattern found it - the number behind the word that leads it ("Lernfeld 5:" 5, "Kompetenzbereich
III" III), else its place among its siblings, assigned (app/domain/iris.py). Its title is its
wording, its lines joined by a space.
"""

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, replace

from app.conversion.base import Block
from app.domain.iris import assign_code
from app.domain.lexicon import HOMONYM, NEGATIVE, ActiveCue
from app.pipeline.patterns import PatternSearch
from app.pipeline.table_titles import Labelled, Labels, read_labels, table_labels
from app.pipeline.toc import (
    OUTSIDE,
    Contents,
    TocEntry,
    find_contents,
    leading_number,
    number_depth,
    starts_part,
    title_key,
)

STRONG = 0.9
LARGER = 1.15  # times the body's size
LONGEST = 200
MOST_LINES = 3
LONGEST_BOLD = 80
_CV = "https://w3id.org/wlo/curriculum/vocab#"
_PATTERN_KINDS = frozenset({_CV + "ck_headingPattern", _CV + "ck_codePattern"})
IN_CONTENTS = _CV + "occ_toc"  # a cue of the contents' lines (the MEM import too)
_SENTENCE_ENDS = (".", ",", ";")
# A module's heading as hs:cue-modulkopf reads it: "Modul 3: Datenbanken", "Modul INF-110 - …"
_MODULE_HEAD = re.compile(r"Modul\s+[A-Z0-9][\w.-]*\s*[:\-\N{EN DASH}]\s*(?P<rest>\S.*)")
# The code behind the word that leads a heading: "Lernfeld 13GH:", "Teil A", "§ 8", "CE01" - a
# letter only behind a space, never one of a code's ("INF-B-110" gives no "F")
_DESIGNATOR = re.compile(r"(?:[^\W\d_]+\.?|§)(?:\s*(\d+(?:\.\d+)*[A-Z]*)|\s+([IVX]+\b|[A-Z]\b))")


@dataclass(frozen=True)
class Heading:
    key: str  # H1, H2, … in reading order
    position: int  # of its block among the conversion's blocks
    block_id: str
    page: int
    level: int  # its depth in the tree, 1 at the top
    parent: str | None  # the key of the heading it lies under
    title: str
    code: str
    code_assigned: bool
    node_type: str | None
    rule_id: str | None  # the cue that typed it


@dataclass(frozen=True)
class Skeleton:
    headings: tuple[Heading, ...]
    contents: Contents
    body_size: float | None
    timeouts: frozenset[str]  # the cues whose pattern took too long


@dataclass(frozen=True)
class _Found:
    position: int
    block: Block
    title: str
    number: str | None
    entry: TocEntry | None
    large: bool
    matched: tuple[ActiveCue, ...]  # the cues for headings that found it
    labelled: bool = False  # a module: a table its label names, or its heading merged with it
    code: str | None = None  # the code its label gives


def build_skeleton(
    blocks: Sequence[Block], cues: Iterable[ActiveCue], node_types: Collection[str]
) -> Skeleton:
    """The skeleton of the blocks (all of a conversion's, in order) by the document's active cues
    and the node types of its profile."""
    held = list(cues)
    search = PatternSearch()
    contents = find_contents(
        blocks, [found.cue for found in held if IN_CONTENTS in found.cue.maps_to], search
    )
    body = body_size(blocks)
    heading_cues = [
        found
        for found in held
        if found.cue.kind in _PATTERN_KINDS
        and found.cue.role != NEGATIVE
        and any(target in node_types for target in found.cue.maps_to)
    ]
    labels = table_labels(held, node_types)
    found = _candidates(blocks, contents, body, heading_cues, labels, search)
    headings = _tree(found, _raw_levels(found))
    # a homonym or a strong cue whose pattern took too long may have found any heading and said
    # otherwise: none is typed by a rule
    typing = [*heading_cues, *labels.titles]
    unsure = any(item.cue.iri in search.timeouts and _may_type(item) for item in typing)
    typed = [
        heading if unsure else _with_type(heading, item, node_types)
        for heading, item in zip(headings, found, strict=True)
    ]
    return Skeleton(tuple(typed), contents, body, frozenset(search.timeouts))


def body_size(blocks: Sequence[Block]) -> float | None:
    """The size most of the text is set in: the median of the text blocks' sizes, by their signs."""
    sized = sorted(
        (block.font_size, len(block.text)) for block in blocks if block.kind == "text" and block.font_size
    )
    half, counted = sum(signs for _, signs in sized) / 2, 0
    for size, signs in sized:
        counted += signs
        if counted >= half:
            return size
    return None


def _candidates(
    blocks: Sequence[Block],
    contents: Contents,
    body: float | None,
    cues: Sequence[ActiveCue],
    labels: Labels,
    search: PatternSearch,
) -> list[_Found]:
    order = [position for position, block in enumerate(blocks) if block.kind not in OUTSIDE]
    start = _body_start(blocks, order, contents, labels, search)
    shaped: dict[int, str] = {}  # the heading-shaped blocks of the body, by position: their titles
    named_by: dict[int, Labelled] = {}  # the tables their labels name
    for position in order:
        if position < start or position in contents.positions:
            continue
        title, label = _heading_title(blocks[position], labels, search)
        if title is not None:
            shaped[position] = title
            if label is not None:
                named_by[position] = label
    entries = {title_key(entry.title): entry for entry in contents.entries}
    numbered = {(title_key(title), leading_number(title)) for title in shaped.values()}
    pages = max((block.page for block in blocks), default=1)
    found: list[_Found] = []
    for at, position in enumerate(order):
        block = blocks[position]
        if position not in shaped:
            continue
        title = shaped[position]
        matched = tuple(cue for cue in cues if search.found(cue.cue, title))
        entry = _named(title, entries, numbered)
        if (label := named_by.get(position)) is not None:
            _add_module(found, order[at - 1] if at else None, _Found(
                position, block, title, leading_number(title), entry, large=False, matched=label.cues,
                labelled=True, code=label.code,
            ))  # fmt: skip
            continue
        if block.kind == "table":
            # named by the contents with their number: a table's column head named alike heads nothing
            number = leading_number(title)
            named = entry is not None and number is not None and number == leading_number(entry.title)
            if matched or named:
                found.append(_Found(position, block, title, number, entry, large=False, matched=matched))
            continue
        number = leading_number(title)
        large = body is not None and block.font_size is not None and block.font_size >= LARGER * body
        after = blocks[order[at + 1]] if at + 1 < len(order) else None
        bold = block.bold and len(title) <= LONGEST_BOLD and not (after is not None and after.bold)
        by_layout = (large or bold) and not (pages > 1 and block.page == 1)
        if matched or entry is not None or (number is not None and (large or block.bold)) or by_layout:
            found.append(_Found(position, block, title, number, entry, large, matched))
    return found


def _add_module(found: list[_Found], before: int | None, module: _Found) -> None:
    """A module's table among the headings found - or, where the module's own heading stands right
    before it (the block ``before``), that heading typed and coded by the table's label: one node."""
    last = found[-1] if found and found[-1].position == before else None
    if last is not None and not last.labelled and _same_module(last.title, module.title, module.code):
        found[-1] = replace(last, matched=(*last.matched, *module.matched), code=module.code, labelled=True)
    else:
        found.append(module)


def _same_module(heading: str, title: str, code: str | None) -> bool:
    """Whether a heading names the module a table's label names: alike, or with the module's code or
    the word "Modul" before ("INF-B-110 Grundlagen der Programmierung", "Modul: Datenbanken", "Modul
    3: Datenbanken" as hs:cue-modulkopf has it) - no group's word ("Modulhandbuch Physik")."""
    named, own = title_key(heading), title_key(title)
    if named == own:
        return True
    if own and named in {"modul" + own, *([title_key(code) + own] if code else [])}:
        return True
    found = _MODULE_HEAD.fullmatch(heading.strip())
    return found is not None and title_key(found["rest"]) == own


def _body_start(
    blocks: Sequence[Block], order: Sequence[int], contents: Contents, labels: Labels, search: PatternSearch
) -> int:
    """Where the title pages end: where contents read end them, they run on to the page the body
    begins on, the page of the heading of those contents' first entry - an imprint on the contents'
    page is front matter, and as a heading set larger than the parts it held them all (Hochbauberufe
    BW 2026, acceptance M1). The first entry, not any: contents often list the imprint too; its
    page, not its heading: a chapter whose line in the contents names no page heads it there
    (Rahmencurriculum Integrationskurse). A heading is the first entry's by its key and, where both
    are numbered, its number. Contents whose first entry names no heading after them before the
    next entry's heading - its own missed, a namesake further in ("3.1 Einleitung") would take the
    chapters before it -, or whose pages were not read, end them where they stand. A part the
    contents name without a page, on a divider page of its own before the first entry's heading,
    begins the body on its page: the first heading between the contents and that one that one of
    their lines without a page names."""
    if contents.front_end is None:
        return 0
    run: list[int] = []  # the blocks of the contents that end the title pages, where they were read
    for position in order[order.index(contents.front_end) :]:
        if position not in contents.positions:
            break
        run.append(position)
    held = set(run)
    entries = [entry for entry in contents.entries if entry.position in held]
    if not entries or not contents.paged:  # pages past the document's: read, but they move no end
        return contents.front_end
    keys = [title_key(entry.title) for entry in entries]
    number = leading_number(entries[0].title)
    following = next((key for key in keys[1:] if key != keys[0]), None)
    parts = {title_key(line): leading_number(line) for line in contents.pageless}
    after = [position for position in order if position > run[-1] and position not in contents.positions]
    divider: int | None = None  # the first heading a line of the contents without a page names
    for position in after:
        title, _ = _heading_title(blocks[position], labels, search)
        if title is None:  # no heading: its key is never wanted, nor worth the counting
            continue
        key = title_key(title)
        if key == keys[0] and (number is None or leading_number(title) in (None, number)):
            begins = blocks[divider if divider is not None else position].page
            return next(at for at in after if blocks[at].page == begins)
        if key == following:
            break
        divides = blocks[position].page > blocks[run[-1]].page  # a page of its own after the contents
        if divider is None and divides and key in parts and leading_number(title) in (None, parts[key]):
            divider = position
    return contents.front_end


def _named(
    title: str, entries: dict[str, TocEntry], numbered: Collection[tuple[str, str | None]]
) -> TocEntry | None:
    """The contents' entry naming ``title``, by its key; a numbered entry names a title without its
    number only where no heading-shaped block bears the number with it - an overview's line naming
    the chapter before its own heading does (RLP Physik 7-10, acceptance M1)."""
    key = title_key(title)
    entry = entries.get(key)
    if entry is None:
        return None
    number = leading_number(entry.title)
    if number is not None and leading_number(title) is None and (key, number) in numbered:
        return None
    return entry


def _heading_title(block: Block, labels: Labels, search: PatternSearch) -> tuple[str | None, Labelled | None]:
    """A block's title where it is heading-shaped, its lines joined, and the labels that gave it -
    a table's title its labels name, the wrapped one first, else its first cell with text."""
    label = read_labels(block, labels, search)
    for wording in label.titles if label is not None else (_wording(block),):
        lines = [line.strip() for line in wording.splitlines() if line.strip()]
        if _shaped(title := " ".join(lines), lines):
            return title, label
    return None, None


def _wording(block: Block) -> str:
    """A text block's text; a table's first cell with text in its first row - the topic a table of
    its own heads in its second cell, its first left empty (RLP Physik 7-10, acceptance M1)."""
    if block.kind != "table":
        return block.text
    first = [cell for cell in block.cells if cell.row == 1 and cell.text.strip()]
    return min(first, key=lambda cell: cell.column).text if first else ""


def _shaped(title: str, lines: Sequence[str]) -> bool:
    numbered = sum(leading_number(line) is not None for line in lines)
    return (
        bool(title)
        and len(title) <= LONGEST
        and len(lines) <= MOST_LINES
        and not title.endswith(_SENTENCE_ENDS)
        and numbered < 2
    )


def _raw_levels(found: Sequence[_Found]) -> list[int]:
    """Each heading's level as the document sets it, before the tree makes it a depth. A module's
    table (or the module's heading merged with it, unnumbered) lies at the contents' level, else one
    below its group - the last heading no module before it lies at or below."""
    sizes = sorted({_size_class(item.block) for item in found if item.large}, reverse=True)
    below = len(sizes) + 1
    levels: list[int] = []
    numbered: str | None = None  # the numbering of the last numbered heading
    above: int | None = None  # the level of the modules' group
    module: int | None = None  # the level of the last module
    after = _next_numbers(found)
    for at, item in enumerate(found):
        if item.labelled and (item.number is None or item.block.kind == "table"):
            entry = item.entry.level if item.entry is not None else None
            level = entry if entry is not None else below if above is None else above + 1
        elif item.number is not None:
            numbered, level = item.number, number_depth(item.number)
        elif item.entry is not None and item.entry.level is not None:
            level = item.entry.level
        elif item.large:
            level = sizes.index(_size_class(item.block)) + 1
        elif (
            numbered is not None
            and item.entry is None
            and not starts_part(item.title)
            and _goes_on(numbered, after[at])
        ):
            level = max(below, number_depth(numbered) + 1)  # a part of the section before
        else:
            level = below
        levels.append(level)
        if item.labelled:
            module = level
            continue
        if module is not None and level < module:
            module = None  # a shallower heading opens a new region of modules
        # a group is any heading but a bold line as deep as the modules (a note between them)
        if module is None or item.number is not None or item.large:
            above = level
    return levels


def _next_numbers(found: Sequence[_Found]) -> list[str | None]:
    """For each heading the numbering of the next numbered heading after it: one pass from the end."""
    after: list[str | None] = [None] * len(found)
    upcoming: str | None = None
    for at in range(len(found) - 1, -1, -1):
        after[at] = upcoming
        upcoming = found[at].number if found[at].number is not None else upcoming
    return after


def _goes_on(numbered: str, after: str | None) -> bool:
    """Whether the numbering goes on within the section ``numbered`` was - the next numbered heading,
    ``after``, shallower ("1.2" … "2") or within the same parent ("6.1.1" … "6.1.2"), not a new one's
    ("A.2" … "B.1", "1.2" … "2.1")."""
    depth = number_depth(numbered)
    if after is None or number_depth(after) < depth:
        return True
    return after.split(".")[: depth - 1] == numbered.split(".")[: depth - 1]


def _size_class(block: Block) -> float:
    """A size to half a point: sizes creep a little from line to line and heading to heading."""
    return round((block.font_size or 0) * 2) / 2


def _tree(found: Sequence[_Found], levels: Sequence[int]) -> list[Heading]:
    """The headings with their parents, depths and codes."""
    stack: list[tuple[int, Heading]] = []  # the open headings with their raw levels
    siblings: dict[str | None, int] = {}
    headings: list[Heading] = []
    for number, (item, level) in enumerate(zip(found, levels, strict=True), start=1):
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        key = None if parent is None else parent.key
        siblings[key] = siblings.get(key, 0) + 1
        code = _printed_code(item)
        heading = Heading(
            key=f"H{number}",
            position=item.position,
            block_id=item.block.id,
            page=item.block.page,
            level=1 if parent is None else parent.level + 1,
            parent=key,
            title=item.title,
            code=code if code is not None else assign_code(siblings[key]),
            code_assigned=code is None,
            node_type=None,
            rule_id=None,
        )
        stack.append((level, heading))
        headings.append(heading)
    return headings


def _printed_code(item: _Found) -> str | None:
    if item.labelled and item.code is not None:  # its label's code
        return item.code
    if item.number is not None:
        return item.number
    # the number behind a pattern's word ("Lernfeld 5:"); a label is no pattern ("Physik I", no "I")
    patterned = any(found.cue.kind in _PATTERN_KINDS for found in item.matched)
    designated = _DESIGNATOR.match(item.title) if patterned else None
    return None if designated is None else designated[1] or designated[2]


def _may_type(found: ActiveCue) -> bool:
    return found.cue.role == HOMONYM or (found.cue.strength or 0.0) >= STRONG


def _with_type(heading: Heading, item: _Found, node_types: Collection[str]) -> Heading:
    if any(found.cue.role == HOMONYM for found in item.matched):
        return heading  # the word means more than one thing here: the model tells which
    strong = [found for found in item.matched if (found.cue.strength or 0.0) >= STRONG]
    targets = {target for found in strong for target in found.cue.maps_to if target in node_types}
    if len(targets) != 1:
        return heading
    rule = min(found.cue.iri for found in strong)
    return replace(heading, node_type=targets.pop(), rule_id=rule)
