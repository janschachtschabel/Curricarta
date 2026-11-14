"""An HTML page's tree as a browser builds it (plan M1 3b-3), for app/conversion/html_hidden.py.

A browser and Docling's parser - bs4's tree builder over html.parser - build a page otherwise: a browser
ends a paragraph where a block begins, a list item, a cell or a row where the next begins, keeps an element
of content open past ``<div/>``, ignores an end tag whose element is not open in its scope, moves a table's
stray text before it, opens a formatting element again after a misnested end, and reads a drawing's elements
by their own rules; Docling's parser does none of that, which made text a browser hides read and text it
shows lost. So the page is built by the HTML standard's tree construction itself - html5rdf, html5lib's,
which rdflib brings along - into a tree of our own: its text grows by appending (html5lib's own trees copy a
node's text at every append, quadratic where comments or stray end tags part a long text), and a page nested
deeper than DEEPEST_NESTING is unreadable - Docling's reading, recursive, fails a little deeper, and
html5lib looks into the open elements at each tag. Comments and the like are left out; the doctype is kept.
Two places where html5lib is not the standard are made so: it has no template's insertion mode - an
enclosing element's end would close a template, its rows join the table around it - so a template's content
is left out before the parser sees it, its text counted; and it is run with scripts on, as a browser runs,
so a noscript's content is its text.
"""

from typing import Any

import html5rdf
from html5rdf.constants import namespaces, tokenTypes
from html5rdf.treebuilders import base

from app.conversion.text_layer import UnreadablePdf

HTML, SVG, MATHML = namespaces["html"], namespaces["svg"], namespaces["mathml"]
VOID = frozenset(
    {
        "area", "base", "basefont", "bgsound", "br", "col", "embed", "frame", "hr", "img", "input", "keygen",
        "link", "meta", "param", "source", "track", "wbr",
    }
)  # fmt: skip
DEEPEST_NESTING = 512  # a browser's parser flattens what lies deeper; Docling's reading fails at some 1,600


class Element(base.Node):  # type: ignore[misc]  # html5rdf ships no types
    """An element of the page: its tag, namespace, attributes (of one given twice the first, as a browser
    keeps it; a foreign one's prefixed names as "prefix:name") and children - elements and texts."""

    def __init__(self, name: str | None, namespace: str | None = None) -> None:
        super().__init__(name)
        self.namespace = namespace or HTML
        # set once, as neither changes: html5lib reads it for each open element at each tag it scopes,
        # a property's call each time (some 16 million for a page 400 deep) and the more under coverage
        self.nameTuple: tuple[str, str | None] = (self.namespace, self.name)
        self.childNodes: list[Any] = []

    @property
    def tag(self) -> str:
        return self.name or ""

    @property
    def attrs(self) -> dict[str, str]:
        found: dict[str, str] = self.attributes
        return found

    @property
    def children(self) -> list["Element | str"]:
        return self.childNodes

    def appendChild(self, node: Any) -> None:
        if isinstance(node, _Text) and self.childNodes and isinstance(self.childNodes[-1], _Text):
            self.childNodes[-1].parts += node.parts
            return
        self.childNodes.append(node)
        node.parent = self

    def insertText(self, data: str, insertBefore: Any = None) -> None:
        if insertBefore is None:
            self.appendChild(_Text([data]))
            return
        at = self._index(insertBefore)
        if at and isinstance(self.childNodes[at - 1], _Text):
            self.childNodes[at - 1].parts.append(data)
            self._hint = at  # the table stayed where it was
        else:
            self.childNodes.insert(at, _Text([data]))

    def insertBefore(self, node: Any, refNode: Any) -> None:
        self.childNodes.insert(self._index(refNode), node)
        node.parent = self

    def removeChild(self, node: Any) -> None:
        self.childNodes.remove(node)
        node.parent = None

    def reparentChildren(self, newParent: Any) -> None:
        for child in self.childNodes:
            newParent.appendChild(child)
        self.childNodes = []

    def cloneNode(self) -> "Element":
        twin = Element(self.name, self.namespace)
        twin.attributes = dict(self.attributes)
        return twin

    def hasContent(self) -> bool:
        return bool(self.childNodes)

    def _index(self, child: Any) -> int:
        # a table's stray content goes before the same table again and again: look there first
        hint = getattr(self, "_hint", -1)
        if 0 <= hint < len(self.childNodes) and self.childNodes[hint] is child:
            at = hint
        else:
            at = self.childNodes.index(child)
        self._hint = at + 1
        return at


class _Text:
    """A text as it grows: its parts, joined once the page is built."""

    def __init__(self, parts: list[str]) -> None:
        self.parts = parts
        self.parent: Any = None


class _Document(Element):
    def __init__(self) -> None:
        super().__init__(None)


class _Comment(Element):
    def __init__(self, data: str) -> None:
        super().__init__("#comment")


class _Doctype(Element):
    def __init__(self, name: str, publicId: str | None, systemId: str | None) -> None:
        super().__init__("#doctype")
        self.doctype = name


class _Builder(base.TreeBuilder):  # type: ignore[misc]
    documentClass = _Document
    elementClass = Element
    commentClass = _Comment
    doctypeClass = _Doctype
    fragmentClass = _Document

    def insertElementNormal(self, token: Any) -> Any:
        element = super().insertElementNormal(token)
        self._held()
        return element

    def insertElementTable(self, token: Any) -> Any:
        element = super().insertElementTable(token)
        self._held()
        return element

    def _held(self) -> None:
        if len(self.openElements) > DEEPEST_NESTING:
            raise UnreadablePdf(f"the HTML page nests elements deeper than {DEEPEST_NESTING}")

    def testSerializer(self, node: Any) -> str:
        raise NotImplementedError


class Page:
    def __init__(self, root: Element, doctype: str | None, template_signs: int) -> None:
        self.root, self.doctype = root, doctype  # doctype: "html", where the page names one
        self.template_signs = template_signs  # the signs its templates held, left out


# Within a template, where the tokenizer reads an element's content as text, as the parser would have it read
_RAW_TEXT = {
    "script": "scriptDataState", "style": "rawtextState", "xmp": "rawtextState", "iframe": "rawtextState",
    "noembed": "rawtextState", "noframes": "rawtextState", "noscript": "rawtextState",
    "textarea": "rcdataState", "title": "rcdataState", "plaintext": "plaintextState",
}  # fmt: skip
_START, _EMPTY, _END = tokenTypes["StartTag"], tokenTypes["EmptyTag"], tokenTypes["EndTag"]
_TEXT = frozenset({tokenTypes["Characters"], tokenTypes["SpaceCharacters"]})


class _Parser(html5rdf.HTMLParser):  # type: ignore[misc]
    """html5lib's parser, a page's templates left out before it builds anything: it has no template's
    insertion mode, so an enclosing element's end would close one and its rows join the table around it,
    where a browser keeps their content inert."""

    template_signs = 0

    def mainLoop(self) -> None:
        tokenizer: Any = self.tokenizer  # type: ignore[has-type]  # html5rdf ships no types
        self.tokenizer = _InertTemplates(tokenizer, self)
        super().mainLoop()


class _InertTemplates:
    """The tokenizer's tokens without those from a template's start to its own end - nested ones counted -,
    the text among them counted; all else it is asked of, the tokenizer's."""

    def __init__(self, tokenizer: Any, parser: _Parser) -> None:
        object.__setattr__(self, "_tokenizer", tokenizer)
        object.__setattr__(self, "_parser", parser)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._tokenizer, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._tokenizer, name, value)

    def __iter__(self) -> Any:
        depth = 0
        text: list[str] = []
        source: str | None = None  # a script or a style within: its source is no text
        for token in self._tokenizer:
            kind, name = token["type"], token.get("name")
            if kind in (_START, _EMPTY) and name == "template":
                depth += 1
            elif not depth:
                yield token
            elif kind == _END and name == "template":
                depth -= 1
                if not depth:
                    self._parser.template_signs += len(" ".join("".join(text).split()))
                    text = []
            elif kind in _TEXT:
                if source is None:
                    text.append(token["data"])
            elif kind == _START and name in _RAW_TEXT:
                self._tokenizer.state = getattr(self._tokenizer, _RAW_TEXT[name])
                source = name if name in ("script", "style") else source
            elif kind == _END and name == source:
                source = None
        self._parser.template_signs += len(" ".join("".join(text).split()))  # a template the page left open


def parse_page(page: str) -> Page:
    """The page's tree, as a browser builds it with scripts on (a noscript's content is its text);
    UnreadablePdf for one nested deeper than DEEPEST_NESTING."""
    parser = _Parser(tree=_Builder)
    document = parser.parse(page, scripting=True)
    return Page(document, _settled(document), parser.template_signs)


def _settled(document: Element) -> str | None:
    """Join each text's parts, leave out comments and the doctype, and say the doctype's name."""
    doctype: str | None = None
    pending: list[Element] = [document]
    while pending:
        element = pending.pop()
        kept: list[Element | str] = []
        for child in element.childNodes:
            if isinstance(child, _Text):
                kept.append("".join(child.parts))
            elif isinstance(child, _Doctype):
                doctype = child.doctype
            elif not isinstance(child, _Comment):
                kept.append(child)
                pending.append(child)
        element.childNodes = kept
    return doctype


def attribute_name(name: Any) -> str:
    """An attribute's name as written: a foreign one's (prefix, name, namespace) as "prefix:name"."""
    if isinstance(name, tuple):
        prefix, local = name[0], name[1]
        return f"{prefix}:{local}" if prefix else str(local)
    return str(name)
