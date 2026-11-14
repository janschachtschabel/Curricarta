"""An HTML page's text no reader sees, taken out before Docling reads it (plan M1 3b-3).

Docling 2.117 skips an element marked ``hidden`` or ``aria-hidden`` and one its own style sets
``display:none`` or ``visibility:hidden``, but reads a <template>, a closed <dialog>, a frame's or a video's
fallback, a drawing's definitions - which no browser shows -, an element set at no size or no opacity, and
one a stylesheet hides by its class: measured in the converter's image. Text no reader sees is the classic way
to steer a model; a PDF's engines drop it (app/conversion/docling_pages.py), and so is it here, its signs
counted (``hidden``) - those Docling skips by itself too.

The page is built as a browser builds it (app/conversion/html_tree.py) and the elements that hide all they
hold are left out with it: one marked so, one no browser renders (a template, a dialog not opened, a
frame's, a media element's or a gauge's fallback, a stray title, a drawing's definitions and descriptions, a
formula's annotation or phantom), one its style gives no display, no opacity or hidden content, a drawing's
element set so by its own attributes; a drawing's characters outside its text elements are drawn nowhere. An
element set at no size or unseen hides its own text, that of the elements within and what they carry as text
(an image's alternative, a field's value), but not of one that sets itself otherwise again - as an old way
to lay out tiles does. What the page's styles say is app/conversion/html_styles.py's. The rest is written
anew, every element with its end tag, each attribute once and none Docling would hide by (styles, aria-
hidden) or read as text that no reader sees (a field's name, a password): Docling's parser, which builds a
page otherwise than a browser (tests/conversion/html_reading.py), reads that tree and no other - a page
hiding nothing is written anew too; scripts, styles, noscripts, comments, the head but its title and a
<meta> naming the encoding are left out, an <xmp> - which Docling's parser reads as raw text - written as
<pre>. Text set in the paper's colour, moved off the screen, or hidden by a stylesheet the page links to, is
not seen to (simplify: as a PDF's colour is not).
"""

import html
import re
from collections import Counter
from dataclasses import dataclass

from app.conversion.base import DropReason
from app.conversion.html_styles import Rules, declarations, look_of, screen_sheet
from app.conversion.html_tree import HTML, MATHML, SVG, VOID, Element, attribute_name, parse_page

_LEFT_OUT = frozenset({"script", "style", "noscript"})  # no text of the page: Docling skips them too
# What no browser renders, by namespace: the fallback of a frame, a media element, a gauge, a stray title...
_NEVER_SHOWN = {
    HTML: frozenset(
        {
            "template",
            "iframe",
            "noembed",
            "noframes",
            "datalist",
            "rp",
            "title",
            "video",
            "audio",
            "canvas",
            "progress",
            "meter",
        }
    ),
    SVG: frozenset(
        {
            "defs",
            "title",
            "desc",
            "metadata",
            "symbol",
            "clipPath",
            "mask",
            "pattern",
            "marker",
            "script",
            "style",
        }
    ),
    MATHML: frozenset({"annotation", "annotation-xml", "mphantom"}),
}
# What an element carries as text a reader sees only with it: an image's alternative, a field's value
_TEXT_ATTRIBUTES = ("alt", "value", "placeholder")
_NOT_WRITTEN = frozenset({"style", "hidden", "aria-hidden"})  # judged here; Docling would hide by them
_NAME = re.compile(r"[^\s\"'<>/=]+")  # an attribute's name as it can be written again


@dataclass(frozen=True)
class _Seen:
    """Of an element's text: whether it is set at no size, whether unseen - inherited, or its own."""

    no_size: bool = False
    unseen: bool = False
    drawing: bool = False  # within a drawing outside its text elements, where no character is drawn

    @property
    def hidden(self) -> bool:
        return self.no_size or self.unseen or self.drawing


def clean_html(page: str) -> tuple[str, Counter[DropReason]]:
    """The page without what no reader sees, written anew - a page hiding nothing too, as Docling's parser
    would build it otherwise all the same -, and the signs left out. UnreadablePdf for a page nested deeper
    than any reader reads (app/conversion/html_tree.py)."""
    tree = parse_page(page)
    rules = Rules("\n".join(_sheets(tree.root)))
    written, signs = _written(tree.root, rules)
    signs += tree.template_signs
    dropped: Counter[DropReason] = Counter()
    if signs:
        dropped["hidden"] = signs
    doctype = f"<!DOCTYPE {tree.doctype}>" if tree.doctype else ""
    return doctype + written, dropped


def _sheets(root: Element) -> list[str]:
    """The text of the page's <style> blocks for the screen, in the page's order - not of those in a template
    or a noscript, which apply nowhere while scripts run."""
    texts: list[str] = []
    pending: list[Element] = [root]
    while pending:
        element = pending.pop()
        if element.tag in ("template", "noscript"):
            continue
        if element.tag == "style" and screen_sheet(element.attrs.get("media")):
            texts += [child for child in element.children if isinstance(child, str)]
        pending += [child for child in reversed(element.children) if isinstance(child, Element)]
    return texts


def _written(root: Element, rules: Rules) -> tuple[str, int]:
    """The tree written as HTML without what it hides, and the signs of the text left out. One step at a time,
    not by recursion: a page may be built deep."""
    out: list[str] = []
    signs = 0
    pending: list[tuple[Element | str, _Seen] | str] = [(child, _Seen()) for child in reversed(root.children)]
    while pending:
        item = pending.pop()
        if isinstance(item, str):  # an end tag due
            out.append(item)
            continue
        node, seen = item
        if isinstance(node, str):
            if seen.hidden and node.strip():
                signs += _signs(node)
            else:
                out.append(html.escape(node, quote=False))
            continue
        if node.tag in _LEFT_OUT or _names_a_charset(node):
            continue
        if node.tag == "head":
            out.append(_head(node))
            continue
        style = _style_of(node)
        look = rules.look(node.tag, (node.attrs.get("class") or "").split(), style)
        if look.hides or _hides_all(node, style):
            signs += _signs_within(node)
            continue
        within = _Seen(
            no_size=seen.no_size if look.no_size is None else look.no_size,
            unseen=seen.unseen if look.unseen is None else look.unseen,
            drawing=_drawing(node, seen.drawing),
        )
        if within.hidden and node.tag in VOID:  # an image, a field: what it carries as text is not seen
            signs += sum(_signs(node.attrs.get(name) or "") for name in _TEXT_ATTRIBUTES)
            continue
        out.append(_start_tag(node))
        if node.tag not in VOID:
            pending.append(f"</{_written_as(node)}>")
            pending += [(child, within) for child in reversed(node.children)]
    return "".join(out), signs


def _head(head: Element) -> str:
    """The page's head, which Docling does not read, with its title alone."""
    titles = [child for child in head.children if isinstance(child, Element) and child.tag == "title"]
    text = "".join(part for title in titles[:1] for part in title.children if isinstance(part, str))
    return f"<head><title>{html.escape(text, quote=False)}</title></head>" if titles else "<head></head>"


# A drawing's elements that draw their characters: text, and within text, its spans and its links
_DRAWN = frozenset({"text"})
_DRAWN_WITHIN = frozenset({"tspan", "textPath", "a"})
_PRESENTATION = ("display", "visibility", "opacity", "font-size")  # a drawing's attributes as styles
_WRITTEN_AS = {"xmp": "pre", "plaintext": "pre"}  # what Docling's parser would read as raw text


def _drawing(element: Element, outer: bool) -> bool:
    """Whether the characters within ``element`` stand where a drawing draws none - in it, outside its text;
    the page's own content within it (foreignObject) is the page's again."""
    if element.namespace != SVG:
        return outer
    if element.tag in _DRAWN or element.tag == "foreignObject":
        return False
    return outer if element.tag in _DRAWN_WITHIN else True


def _style_of(element: Element) -> str:
    """The element's style attribute, after a drawing's presentation attributes, which say the same."""
    style = element.attrs.get("style") or ""
    if element.namespace != SVG:
        return style
    presented = [f"{name}:{element.attrs[name]}" for name in _PRESENTATION if name in element.attrs]
    return ";".join([*presented, style])


def _written_as(element: Element) -> str:
    return _WRITTEN_AS.get(element.tag, element.tag) if element.namespace == HTML else element.tag


def _hides_all(element: Element, style: str) -> bool:
    """Whether the element hides all it holds beside its styles' display and opacity: marked so, one no
    browser renders - a dialog not opened is a note to read on a click, not the page's text -, a drawing's
    element its own attributes hide, one unseen by its own style (Docling skips that one whole, whatever
    within shows itself again)."""
    attrs = element.attrs
    if "hidden" in attrs or (attrs.get("aria-hidden") or "").strip().lower() in ("true", "1", "yes"):
        return True
    if element.tag in _NEVER_SHOWN.get(element.namespace, frozenset()):
        return True
    if element.tag == "dialog" and "open" not in attrs:
        return True
    if element.namespace == SVG and (
        (attrs.get("display") or "").strip().lower() == "none"
        or (attrs.get("visibility") or "").strip().lower() in ("hidden", "collapse")
    ):
        return True
    return look_of(declarations(style)).unseen is True


def _names_a_charset(element: Element) -> bool:
    """A <meta> naming the page's encoding: it goes on in UTF-8, which one naming another would belie."""
    if element.tag != "meta":
        return False
    equiv = (element.attrs.get("http-equiv") or "").strip().lower()
    return "charset" in element.attrs or equiv == "content-type"


def _signs_within(element: Element) -> int:
    signs = 0
    pending: list[Element | str] = [element]
    while pending:
        node = pending.pop()
        if isinstance(node, str):
            signs += _signs(node)
        elif node.tag not in _LEFT_OUT:
            pending += node.children
            signs += sum(_signs(node.attrs.get(name) or "") for name in _TEXT_ATTRIBUTES)
    return signs


def _signs(text: str) -> int:
    return len(" ".join(text.split()))


def _start_tag(element: Element) -> str:
    written = [_written_as(element)]
    password = element.tag == "input" and (element.attrs.get("type") or "").strip().lower() == "password"
    for key, value in element.attrs.items():
        name = attribute_name(key)
        if not _NAME.fullmatch(name) or name.lower() in _NOT_WRITTEN:
            continue
        if element.tag == "input" and (name == "name" or (password and name == "value")):
            continue  # never shown: Docling would read it as text
        written.append(name if value is None else f'{name}="{html.escape(value, quote=True)}"')
    return f"<{' '.join(written)}>"
