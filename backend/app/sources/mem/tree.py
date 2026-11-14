"""The tree of one MEM plan, built from the rows of its closure and its references (plan M2, E8), after the
old app's tree.py.

The Länder state has-part as they please: the four frozen plans state the closure - every part names the
plan and each ancestor as its whole -, a plan may also state only the direct parts, or some of the path.
A part's real parents are its stated ancestors no other stated ancestor lies below, through what the
parts state of their own ancestors: that undoes the closure, keeps a direct statement, and finds a second
parent at any depth. The part hangs under the deepest real parent, the first by label among equally deep
ones; the others are kept (``other_parents``).

A reference (``hat Verweis``) is no part: it hangs under the part holding it, the first by label where
parts share it, and names every holder (``holders``). A reference the closure holds as a part stays that
part and names its holders all the same. A part or a reference the rows give twice is refused: the
pages matched their count, so a row given twice stands for one that is missing.

Children follow the store's position, then their number, then the number in their IRI, then their
label, so two imports of one plan agree; a part's references come after its parts. Parts joined in a
cycle are refused, not dropped: the import would hold less than the store, and nobody would know.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.sources.mem.queries import LP, SEPARATOR
from app.sources.mem.sparql import MAX_IRI, MemRefused

VERWEIS = LP + "LP_0030065"  # what hat Verweis points at is a Verweis, by the ontology's range
_NO_NUMBER = 10**18
_WHOLE = re.compile(r"-?[0-9]{1,15}")  # a position or number int() takes, short of _NO_NUMBER
# what the database cannot hold in text: a NUL, a lone surrogate (JSON may spell one); the catalogue too
UNSTORABLE = re.compile(r"[\x00\ud800-\udfff]")
# the CHECK of the tables' MEM IRIs (migration 0030) and the query client's IRI rule, whichever is stricter:
# [:cntrl:] holds the C1 controls too, Python's \s every Unicode space; no lone surrogate, which is no UTF-8
_STORABLE_IRI = re.compile(r'https?://[^\s\x00-\x1f\x7f-\x9f\ud800-\udfff<>"{}|\\^`]+')


def storable_iri(value: str) -> bool:
    """Whether the tables take ``value`` as a MEM IRI."""
    return len(value) <= MAX_IRI and _STORABLE_IRI.fullmatch(value) is not None


@dataclass
class MemPart:
    """A part as the store describes it, placed in the tree."""

    iri: str
    label: str
    classes: tuple[str, ...]
    description: str | None = None
    grades: tuple[str, ...] = ()
    number: str | None = None
    position: int | None = None
    hours: str | None = None
    page: str | None = None  # the part's page in the Land's own curriculum database
    targets: tuple[str, ...] = ()  # a reference's: what it points at
    reference: bool = False  # held through hat Verweis, and no part of the closure
    parent: str | None = None
    other_parents: tuple[str, ...] = ()
    holders: tuple[str, ...] = ()  # the parts holding it through hat Verweis
    children: list["MemPart"] = field(default_factory=list)


@dataclass(frozen=True)
class MemTree:
    parts: dict[str, MemPart]
    roots: list[MemPart]


def build_tree(rows: Sequence[Mapping[str, str]], references: Sequence[Mapping[str, str]]) -> MemTree:
    """The tree behind the closure's rows (queries.closure_page) with the references
    (queries.reference_page) hung in; MemRefused for a row given twice or parts joined in a cycle."""
    _refuse_twice(row["n"] for row in rows)
    _refuse_twice((row["x"], row["v"]) for row in references)
    parts = {row["n"]: _part(row) for row in rows}
    stated = {
        row["n"]: {a for a in _split(row.get("ancestors", "")) if a in parts and a != row["n"]}
        for row in rows
    }
    above: dict[str, set[str]] = {}
    for iri, ancestors in stated.items():
        above[iri] = _above(stated, ancestors)
    # a part above itself is in a cycle; were it left in, the parent rule below would drop each member
    # as lying below another, and a cycle stating its closure would come out as roots. A parent is a
    # stated ancestor, so with no cycle among these the parents form none either: every part is placed
    cyclic = [iri for iri, up in above.items() if iri in up]
    if cyclic:
        raise MemRefused(f"{len(cyclic)} parts of the plan are joined in a cycle")
    roots = []
    for part in parts.values():
        candidates = stated[part.iri]
        # a candidate below another one is that one's ancestor, no parent
        parents = [c for c in candidates if not any(c in above[other] for other in candidates if other != c)]
        if not parents:
            roots.append(part)
            continue
        parents.sort(key=lambda each: (-len(above[each]), parts[each].label, each))
        part.parent, part.other_parents = parents[0], tuple(parents[1:])
        parts[parents[0]].children.append(part)
    _hang_references(parts, references)
    for part in parts.values():
        part.children.sort(key=_order)
    roots.sort(key=_order)
    return MemTree(parts, roots)


def _above(stated: Mapping[str, set[str]], starts: Iterable[str]) -> set[str]:
    """``starts`` and every part above them, through the ancestors the parts state."""
    seen: set[str] = set()
    waiting = list(starts)
    while waiting:
        iri = waiting.pop()
        if iri not in seen:
            seen.add(iri)
            waiting.extend(stated.get(iri, ()))
    return seen


def _hang_references(parts: dict[str, MemPart], references: Sequence[Mapping[str, str]]) -> None:
    held: dict[str, list[str]] = {}
    for row in references:
        if row["x"] in parts:
            held.setdefault(row["v"], []).append(row["x"])
    described: dict[str, Mapping[str, str]] = {}  # label, classes and targets depend on the reference alone
    for row in references:
        described.setdefault(row["v"], row)
    for iri, holders in held.items():
        holders.sort(key=lambda each: (parts[each].label, each))
        if iri in parts:  # a part of the closure: it stays where the closure puts it
            parts[iri].holders = tuple(holders)
            parts[iri].targets = tuple(sorted(_split(described[iri].get("target", ""))))
            continue
        row = described[iri]
        reference = MemPart(
            iri=iri,
            label=_label(row.get("label"), iri),
            classes=tuple(dict.fromkeys((VERWEIS, *_split(row.get("types", ""))))),
            targets=tuple(sorted(_split(row.get("target", "")))),
            reference=True,
            parent=holders[0],
            holders=tuple(holders),
        )
        parts[iri] = reference
        parts[holders[0]].children.append(reference)


def _part(row: Mapping[str, str]) -> MemPart:
    position = row.get("position") or ""
    return MemPart(
        iri=row["n"],
        label=_label(row.get("label"), row["n"]),
        classes=_split(row.get("types", "")),
        description=row.get("description") or None,
        grades=tuple(sorted(_split(row.get("grades", "")))),
        number=row.get("number") or None,
        position=int(position) if _WHOLE.fullmatch(position) else None,
        hours=row.get("hours") or None,
        page=row.get("page") or None,
    )


def _refuse_twice(keys: Iterable[object]) -> None:
    if any(count > 1 for count in Counter(keys).values()):
        raise MemRefused("a row given twice: the plan's pages are not to be trusted")


def _order(part: MemPart) -> tuple[int, int, str, str, str]:
    if part.reference:
        return (4, 0, "", part.label, part.iri)
    if part.position is not None:
        return (0, part.position, "", part.label, part.iri)
    if part.number is None:
        return (3, _iri_number(part.iri), "", part.label, part.iri)
    if _WHOLE.fullmatch(part.number) and not part.number.startswith("-"):
        return (1, int(part.number), "", part.label, part.iri)
    return (2, 0, part.number, part.label, part.iri)


def _iri_number(iri: str) -> int:
    """The first number of the IRI's last segment ("kompetenzbereich-7079-1"): Rhineland-Palatinate gives
    its parts neither position nor number, its resource numbers follow the document."""
    found = re.search(r"[0-9]{1,15}", iri.rstrip("/").rsplit("/", 1)[-1])
    return int(found.group()) if found else _NO_NUMBER


def _split(joined: str) -> tuple[str, ...]:
    return tuple(part for part in joined.split(SEPARATOR) if part)


def _label(raw: str | None, iri: str) -> str:
    """On one line: the store writes a heading and its lead-in as two lines of one label; without a NUL or a
    lone surrogate, which the database cannot hold in text."""
    return " ".join(UNSTORABLE.sub("", raw or "").split()) or UNSTORABLE.sub(
        "", iri.rstrip("/").rsplit("/", 1)[-1]
    )
