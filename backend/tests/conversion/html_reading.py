"""What Docling 2.117 reads of an HTML page, modelled for the tests of app/conversion/html_hidden.py: its
parser, bs4's tree builder over html.parser, pushes an element at its start tag, closes one closed on itself
("/>") and a void one at once, pops to the latest element of an end tag's name and ignores one of none open
- no implied end, no scope, of an attribute given twice the last (bs4's source, and probed in the
converter's image). Docling skips an element marked ``hidden`` or ``aria-hidden`` and one its own style sets
``display:none`` or ``visibility:hidden``, and the text of <script> and <style>."""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from app.conversion.html_tree import Element

# bs4's empty elements (HTMLTreeBuilder.empty_element_tags)
_VOID = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "keygen", "link", "menuitem", "meta",
        "param", "source", "track", "wbr", "basefont", "bgsound", "command", "frame", "image", "isindex",
        "nextid", "spacer",
    }
)  # fmt: skip


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str]
    children: list["Node | str"] = field(default_factory=list)


class _Naive(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(Node(tag, {name: value or "" for name, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for at in range(len(self.stack) - 1, 0, -1):
            if self.stack[at].tag == tag:
                del self.stack[at:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def naive_tree(page: str) -> Node:
    parser = _Naive()
    parser.feed(page)
    parser.close()
    return parser.root


def _skipped(node: Node) -> bool:
    style = node.attrs.get("style", "").replace(" ", "").lower()
    return (
        "hidden" in node.attrs
        or node.attrs.get("aria-hidden", "").lower() == "true"
        or "display:none" in style
        or "visibility:hidden" in style
        or node.tag in ("script", "style")
    )


def docling_reads(page: str) -> str:
    """The text Docling reads of ``page``, its words parted by single spaces."""
    words: list[str] = []
    pending: list[Node | str] = [naive_tree(page)]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            words += item.split()
        elif not _skipped(item):
            pending += reversed(item.children)
    return " ".join(words)


def shape(node: Node | Element) -> list[object]:
    """A tree as nested lists of its tags and texts, whitespace-only text left out."""
    return [
        child.strip() if isinstance(child, str) else [child.tag, *shape(child)]
        for child in node.children
        if not isinstance(child, str) or child.strip()
    ]
