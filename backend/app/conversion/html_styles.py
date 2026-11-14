"""What an HTML page's own styles say of an element's visibility (app/conversion/html_hidden.py, M1 3b-3).

An element's look is the declarations of the rules that name its class alone (``.weg``, ``p.weg``) - those
at the top of the page's <style> blocks for the screen, and within ``@media screen``, ``all`` or ``only
screen``, ``@layer`` and ``@supports`` (its condition taken as met) -, in their order, the later winning,
then those of its own style attribute; one marked ``!important`` wins over one that is not, as in a browser.
The winner of each class, tag and property is found once, so an element's look takes a step for each of its
classes. A rule of another selector, of a narrow screen or of print alone says nothing here (simplify: no
other selectors, no specificity, no stylesheet the page links to).

Of the properties a child inherits and may set again: a size of no length - under a pixel or a point, under a
tenth of an em, a tenth - is no size; one relative to the parent's (em, %, smaller, ``inherit``) keeps the
parent's, as a size relative to none is none; any other sets one. A visibility of ``inherit`` keeps the
parent's. An opacity under a tenth hides as none: no reader sees it.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

# a comment never closed runs to the end, as in a browser: one scan, however many begin
_COMMENT = re.compile(r"/\*.*?(?:\*/|\Z)", re.DOTALL)
_IMPORTANT = re.compile(r"!\s*important\s*$")
# one way to read a number: "\d+\.?\d*" splits a run of digits many ways, and a value that fails took 10 s
_LENGTH = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([a-z%]*)")
_KEYWORD = re.compile(r"[a-z-]+")
_CLASS_ALONE = re.compile(r"([a-zA-Z][a-zA-Z0-9]*)?\.([-\w]+)")
_SCREEN = frozenset({"", "all", "screen", "only screen", "only all"})
_READ_WITHIN = frozenset({"@layer", "@supports"})  # rules within them apply as any (a condition taken as met)
_DEEPEST_MEDIA = 3  # @media within @media: deeper ones say nothing (each depth reads its rules once more)
_PROPERTIES = frozenset({"display", "visibility", "font-size", "opacity", "content-visibility", "font"})
# The sizes "font" may name as a word, and the words that keep the parent's
_SIZE_WORDS = frozenset(
    {
        "xx-small",
        "x-small",
        "small",
        "medium",
        "large",
        "x-large",
        "xx-large",
        "xxx-large",
        "smaller",
        "larger",
    }
)
_KEEPS_PARENT = frozenset({"inherit", "unset", "revert", "revert-layer", "smaller", "larger"})
# What a length is in pixels; a relative one, against the parent's, under which it is none
_PIXELS = {"px": 1.0, "pt": 4 / 3, "pc": 16.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4, "q": 96 / 101.6}
_RELATIVE_LEAST = {"em": 0.1, "ex": 0.2, "ch": 0.2, "%": 10.0, "rem": 0.1, "vw": 0.1, "vh": 0.1}

# A property's value, lower case, and whether it is marked !important
Declarations = dict[str, tuple[str, bool]]


@dataclass(frozen=True)
class Look:
    """What an element's declarations say: whether it hides all within it (no display, no opacity), and of
    two properties its children inherit - and may set otherwise - True where it sets them so that nothing
    is seen, False where it sets them so that it is, None where it keeps its parent's."""

    hides: bool = False
    no_size: bool | None = None
    unseen: bool | None = None


def declarations(text: str, into: Declarations | None = None) -> Declarations:
    """The declarations of a rule's body or a style attribute over those ``into`` holds: the later win, but
    not over one marked ``!important`` unless it is too."""
    found = dict(into or {})
    for part in _COMMENT.sub("", text).split(";"):
        name, colon, value = part.partition(":")
        name, value = name.strip().lower(), value.strip().lower()
        if not colon or name not in _PROPERTIES:
            continue
        important = bool(_IMPORTANT.search(value))
        value = _IMPORTANT.sub("", value).strip()
        if name == "font":  # the shorthand sets the size too: "font: 0/0 a" hides as "font-size: 0"
            name, value = "font-size", _size_in_font(value)
            if not value:
                continue
        if important or not found.get(name, ("", False))[1]:
            found[name] = (value, important)
    return found


def _size_in_font(font: str) -> str:
    """The size the ``font`` shorthand names: its first length or size word, a line height after "/" left."""
    for word in font.split():
        size = word.partition("/")[0]
        found = _LENGTH.fullmatch(size)
        if size in _SIZE_WORDS or (found is not None and (found.group(2) or float(found.group(1)) == 0)):
            return size
    return ""


def look_of(found: Declarations) -> Look:
    display, opacity = found.get("display", ("", False))[0], found.get("opacity", ("", False))[0]
    size, visibility = found.get("font-size"), found.get("visibility")
    return Look(
        hides=display == "none"
        or _faint(opacity)
        or found.get("content-visibility", ("", False))[0] == "hidden",
        no_size=None if size is None else _no_size(size[0]),
        unseen=None if visibility is None else _unseen(visibility[0]),
    )


def _faint(opacity: str) -> bool:
    found = _LENGTH.fullmatch(opacity)
    if found is None or found.group(2) not in ("", "%"):
        return False
    return float(found.group(1)) < (10.0 if found.group(2) else 0.1)


def _no_size(size: str) -> bool | None:
    if size in _KEEPS_PARENT:
        return None
    found = _LENGTH.fullmatch(size)
    if found is None:
        return (
            False if _KEYWORD.fullmatch(size) else None
        )  # "x-small": a size; a calc(), a var(): the parent's
    number, unit = float(found.group(1)), found.group(2)
    if number == 0:  # a size of no length, in whatever unit
        return True
    if unit in _PIXELS or not unit:
        return number * _PIXELS.get(unit, 1.0) < 1
    if unit in _RELATIVE_LEAST:
        if number < _RELATIVE_LEAST[unit]:
            return True
        return False if unit in ("rem", "vw", "vh") else None  # relative to the parent's: as the parent's
    return None


def _unseen(visibility: str) -> bool | None:
    if visibility in ("hidden", "collapse"):
        return True
    return False if visibility in ("visible", "initial") else None


class Rules:
    """The rules of a page's stylesheets (the text of its <style> blocks for the screen) that name a class
    alone and set one of the properties that hide: of each class, tag (None for any) and property the
    winner."""

    def __init__(self, css: str) -> None:
        # (class, tag) -> property -> (important, order, value)
        self._winners: defaultdict[tuple[str, str | None], dict[str, tuple[bool, int, str]]] = defaultdict(
            dict
        )
        self._count = 0
        self._read(_COMMENT.sub("", css), depth=0)

    def look(self, tag: str, classes: list[str], style: str) -> Look:
        """The look of an element ``tag`` of ``classes`` and the style attribute ``style``."""
        found: dict[str, tuple[bool, int, str]] = {}
        for name in set(classes):
            for key in ((name, None), (name, tag)):
                for prop, winner in self._winners.get(key, {}).items():
                    if prop not in found or winner[:2] > found[prop][:2]:
                        found[prop] = winner
        for prop, (value, important) in declarations(style).items():
            if prop not in found or important or not found[prop][0]:
                found[prop] = (important, self._count, value)
        return look_of({prop: (value, important) for prop, (important, _, value) in found.items()})

    def _read(self, css: str, depth: int) -> None:
        at = 0
        while (opening := css.find("{", at)) >= 0:
            selectors = css[at:opening].split(";")[-1].strip()  # after an @import, an @charset
            close, nested = _block_end(css, opening)
            body = css[opening + 1 : close]
            at = close + 1
            if selectors.startswith("@"):
                rule, _, query = selectors.partition(" ")
                screen = all(" ".join(part.lower().split()) in _SCREEN for part in query.split(","))
                within = rule.lower() in _READ_WITHIN or (rule.lower() == "@media" and screen)
                if within and depth < _DEEPEST_MEDIA:
                    self._read(body, depth + 1)
                continue
            if nested:
                continue
            said = declarations(body)
            if not said:
                continue
            for selector in selectors.split(","):
                if found := _CLASS_ALONE.fullmatch(selector.strip()):
                    tag = found.group(1).lower() if found.group(1) else None
                    winners = self._winners[(found.group(2), tag)]
                    for prop, (value, important) in said.items():
                        if prop not in winners or important or not winners[prop][0]:
                            winners[prop] = (important, self._count, value)
            self._count += 1


def screen_sheet(media: str | None) -> bool:
    """Whether a <style> block of the attribute ``media`` applies to every screen."""
    return media is None or all(" ".join(part.lower().split()) in _SCREEN for part in media.split(","))


def _block_end(css: str, opening: int) -> tuple[int, bool]:
    """Where the block opened at ``opening`` closes (the end of the text where it does not), and whether it
    holds a block of its own."""
    depth, at, nested = 1, opening + 1, False
    while at < len(css):
        sign = css[at]
        if sign == "{":
            depth, nested = depth + 1, True
        elif sign == "}":
            depth -= 1
            if not depth:
                return at, nested
        at += 1
    return len(css), nested
