"""A DOCX's text no reader sees, taken out before Docling reads it (plan M1 3b-3).

Docling 2.117 reads a run set hidden (``w:vanish``) and one set at half a point as any other - measured in
the converter's image -, which would hand the model text the reader never saw: an instruction hidden in a
file is the classic way to steer one. A PDF's engines drop such text (app/conversion/docling_pages.py,
``tiny``); so is it here: every run whose properties hide it or set it under a point (``w:sz`` in
half-points, under 2; ``w:szCs`` for a run of complex script) leaves the body, the footnotes and the
endnotes, its signs counted by why (``hidden``, ``tiny``) - wherever it stands: in a link, a tracked
insertion, a content control, a table, a text box (Word writes one twice, for older readers: counted once).

The parts are those the package's relationships name by their exact types, as python-docx - Docling's reader
- finds them, whatever their names, a target resolved from its part's folder with ".." ending at the root;
two parts of one kind it refuses, and so is such a package refused, and one naming a part from the root of
the disk. A run's property is its own where it says one, else its character style's, else its paragraph's
style's - each with the styles it is based on, however long the chain -, else the document's default; a
style of no type is a paragraph style, and one naming a style there is not takes the default style of its
type, as Word takes them. Headers and footers Docling reads as furniture, which the conversion leaves out
(app/conversion/docling_flow.py). Changes tracked stay as Docling reads them: deleted text out, inserted in.
Text set white, or behind a shape, is not seen to (simplify: as a PDF's colour is not); nor is a table
style's hiding, and a style's ``w:vanish`` is taken as set, not as the toggle of the style it is based on
(simplify: Word never writes either for text), nor a run of Arabic or Hebrew letters not marked complex
script (``w:cs``, ``w:rtl``), which Word sizes by ``w:szCs`` as well. A package of Strict Office Open XML is
refused: Docling turns its namespaces into the transitional ones before reading, which the cleaning reads
alone.

The standard library reads the package - zipfile and ElementTree, which resolves no external entity, its
expat (2.4.1 and later) bounding an entity's expansion; a part that declares a document type or an entity, in
whatever encoding expat reads, is refused besides, as Word never writes one, and so is one declaring
namespaces by the hundred. The package was held to its bounds when it came in (app/sources/archives.py). A
part that changes is written anew, the others as they were.
"""

import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from xml.parsers import expat

from app.conversion.base import DropReason
from app.conversion.text_layer import UnreadablePdf

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_RELATIONSHIP = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_TYPES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_MAIN, _STYLES = _TYPES + "officeDocument", _TYPES + "styles"
_NOTES = (_TYPES + "footnotes", _TYPES + "endnotes")  # the parts read with the main one
_ONE_EACH = frozenset({_MAIN, _STYLES, *_NOTES})  # of these python-docx takes one, refusing two
SMALLEST_HALF_POINTS = 2  # w:sz counts half-points: under a point no reader reads it
MOST_NAMESPACES = 256  # a part Word writes declares some 40; each written anew looks through all before
_OFF = frozenset({"0", "false", "off"})
_STRICT = b"purl.oclc.org/ooxml"  # what Docling looks for to read a package as Strict
_STRICT_LOOKED_AT = 65536  # in so many bytes of the package's relationships
_OWN_PREFIX = re.compile(r"ns\d+")  # the prefixes ElementTree gives, which it takes no other to name

# A property as found: the element, or None where no style says it
_Found = ET.Element | None


@dataclass
class _Styles:
    """The styles' run properties by type and id, their bases, the defaults; each property of a style found
    once, the chain of its bases walked once."""

    properties: dict[tuple[str, str], ET.Element] = field(default_factory=dict)
    bases: dict[tuple[str, str], str] = field(default_factory=dict)
    known: set[tuple[str, str]] = field(default_factory=set)
    defaults: dict[str, str] = field(default_factory=dict)  # by type: the default style's id
    document: ET.Element | None = None  # docDefaults' run properties
    _found: dict[tuple[str, str, str], _Found] = field(default_factory=dict)

    def find(self, kind: str, style: str | None, name: str) -> _Found:
        """The property ``name`` of the style ``style`` of ``kind`` - of the type's default where there is no
        such style - or of the nearest style it is based on that says it."""
        current = style if style is not None and (kind, style) in self.known else self.defaults.get(kind)
        walked: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        found: _Found = None
        while current is not None:
            key = (kind, current, name)
            if key in self._found:
                found = self._found[key]
                break
            if key in seen:  # a loop of bases: none says it
                break
            walked.append(key)
            seen.add(key)
            properties = self.properties.get((kind, current))
            if properties is not None and (found := properties.find(f"{W}{name}")) is not None:
                break
            base = self.bases.get((kind, current))
            current = base if base is not None and (kind, base) in self.known else None
        for key in walked:
            self._found[key] = found
        return found


def clean_docx(data: bytes) -> tuple[bytes, Counter[DropReason]]:
    """The DOCX with every run a reader does not see taken out, and the signs taken by why; the bytes as they
    came where none is. UnreadablePdf for a package or a part that cannot be read."""
    dropped: Counter[DropReason] = Counter()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            names = set(package.namelist())
            if any(name.startswith("/") for name in names):
                raise UnreadablePdf("the DOCX names a part from the root, which Word never writes")
            if "_rels/.rels" in names and _STRICT in package.read("_rels/.rels")[:_STRICT_LOOKED_AT]:
                # Docling turns such a package's namespaces into the transitional ones before reading: a run
                # hidden in a strict namespace would pass the cleaning, which reads the transitional ones
                raise UnreadablePdf("the DOCX is of Strict Office Open XML, which is not converted")
            main = _related(package, names, "").get(_MAIN)
            if main is None or main not in names:
                raise UnreadablePdf("the DOCX names no main part")
            related = _related(package, names, main)
            sheet = related.get(_STYLES)
            styles = _styles(package.read(sheet)) if sheet in names else _Styles()
            changed: dict[str, bytes] = {}
            for part in dict.fromkeys((main, *(related[kind] for kind in _NOTES if kind in related))):
                if part in names:
                    cleaned = _cleaned(package.read(part), styles, dropped)
                    if cleaned is not None:
                        changed[part] = cleaned
            if not changed:
                return data, dropped
            return _repacked(package, changed), dropped
    except UnreadablePdf:
        raise
    except (zipfile.BadZipFile, ET.ParseError, EOFError, ValueError) as error:
        raise UnreadablePdf(f"the DOCX cannot be read: {type(error).__name__}") from None


def _related(package: zipfile.ZipFile, names: set[str], part: str) -> dict[str, str]:
    """The parts ``part`` relates to - the package's own relationships for "" -, by the relationship's type;
    UnreadablePdf where it names two of a kind python-docx takes one of."""
    folder, _, name = part.rpartition("/")
    listed = posixpath.join(folder, "_rels", f"{name}.rels")
    if listed not in names:
        return {}
    found: dict[str, str] = {}
    for relationship in _parsed(package.read(listed)).iter(_RELATIONSHIP):
        kind, target = relationship.get("Type", ""), relationship.get("Target", "")
        if relationship.get("TargetMode") == "External" or not target:
            continue
        if kind in found and kind in _ONE_EACH:
            raise UnreadablePdf("the DOCX names two parts of one kind, which python-docx refuses")
        # as python-docx names it (PackURI.from_rel_ref, membername): from the part's folder, ".." ending at
        # the root, the first slash dropped
        found.setdefault(kind, posixpath.normpath(posixpath.join("/" + folder, target))[1:])
    return found


class _Declared(Exception):
    """A part declares a document type or an entity."""


def _declares(xml: bytes) -> bool:
    """Whether the part declares a document type or an entity: asked of expat itself, which reads the part in
    whatever encoding it tells, and stops at the declaration before expanding anything."""

    def declared(*_: object) -> None:
        raise _Declared

    checker = expat.ParserCreate()
    checker.StartDoctypeDeclHandler = declared
    checker.EntityDeclHandler = declared
    try:
        checker.Parse(xml, True)
    except _Declared:
        return True
    except expat.ExpatError:
        return False  # not XML: ElementTree says so after
    return False


def _parsed(xml: bytes) -> ET.Element:
    if _declares(xml):
        raise UnreadablePdf("the DOCX declares a document type or entities, which Word never writes")
    # expat 2.4.1 and later bound an entity's expansion, ElementTree resolves no external one; and declared
    # entities were refused above (Python's docs: XML vulnerabilities)
    return ET.fromstring(xml)  # noqa: S314


def _styles(xml: bytes) -> _Styles:
    root = _parsed(xml)
    styles = _Styles()
    defaults = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
    styles.document = defaults
    for style in root.iter(f"{W}style"):
        kind, name = style.get(f"{W}type") or "paragraph", style.get(f"{W}styleId", "")
        styles.known.add((kind, name))
        properties = style.find(f"{W}rPr")
        if properties is not None:
            styles.properties[(kind, name)] = properties
        based = style.find(f"{W}basedOn")
        if based is not None:
            styles.bases[(kind, name)] = based.get(f"{W}val", "")
        if style.get(f"{W}default") in ("1", "true", "on"):
            styles.defaults[kind] = name
    return styles


def _cleaned(xml: bytes, styles: _Styles, dropped: Counter[DropReason]) -> bytes | None:
    """The part without its hidden runs, or None where it holds none."""
    root = _parsed(xml)
    taken = _walk(root, None, styles, dropped, counted=True)
    if not taken:
        return None
    _register_prefixes(xml)
    written: bytes = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    return written


def _walk(
    element: ET.Element,
    paragraph: str | None,
    styles: _Styles,
    dropped: Counter[DropReason],
    *,
    counted: bool,
) -> bool:
    """Take the hidden runs out of ``element``'s tree, their signs counted where ``counted`` - not in the copy
    Word writes of a text box for older readers -; ``paragraph``: the style of their paragraph. Whether any
    was taken out."""
    kept: list[ET.Element] = []
    taken = False
    for child in element:
        if child.tag == f"{W}r" and (reason := _hidden(child, paragraph, styles)) is not None:
            if counted:
                dropped[reason] += sum(len(text.text or "") for text in child.iter(f"{W}t"))
            taken = True
            continue
        within = _paragraph_style(child) if child.tag == f"{W}p" else paragraph
        # a run's drawing may hold a text box of paragraphs
        taken = _walk(child, within, styles, dropped, counted=counted and child.tag != _FALLBACK) or taken
        kept.append(child)
    if len(kept) < len(element):
        element[:] = kept  # at once: one by one, each removal looked for its run anew
    return taken


def _hidden(run: ET.Element, paragraph: str | None, styles: _Styles) -> DropReason | None:
    own = run.find(f"{W}rPr")
    character = None if own is None else own.find(f"{W}rStyle")
    character_style = None if character is None else character.get(f"{W}val")

    def found(name: str) -> _Found:
        mine = None if own is None else own.find(f"{W}{name}")
        if mine is not None:
            return mine
        for kind, style in (("character", character_style), ("paragraph", paragraph)):
            if (by_style := styles.find(kind, style, name)) is not None:
                return by_style
        return None if styles.document is None else styles.document.find(f"{W}{name}")

    if _on(found("vanish")):
        return "hidden"
    size = found("szCs" if _on(found("cs")) or _on(found("rtl")) else "sz")
    value = None if size is None else size.get(f"{W}val", "")
    if value is not None and value.isdigit() and int(value) < SMALLEST_HALF_POINTS:
        return "tiny"
    return None


def _on(toggle: _Found) -> bool:
    return toggle is not None and toggle.get(f"{W}val", "1").lower() not in _OFF


def _paragraph_style(paragraph: ET.Element) -> str | None:
    style = paragraph.find(f"{W}pPr/{W}pStyle")
    return None if style is None else style.get(f"{W}val")


def _register_prefixes(xml: bytes) -> None:
    """Keep the part's prefixes as they are when it is written anew: ElementTree would name them ns0, ns1."""
    declared = {(prefix, uri) for _event, (prefix, uri) in _namespaces(xml) if prefix}
    if len(declared) > MOST_NAMESPACES:
        raise UnreadablePdf(f"a part of the DOCX declares {len(declared)} namespaces, Word some 40")
    for prefix, uri in sorted(declared):
        if not _OWN_PREFIX.fullmatch(prefix):
            ET.register_namespace(prefix, uri)


def _namespaces(xml: bytes) -> Iterator[tuple[str, tuple[str, str]]]:
    # the part was parsed whole before (_parsed): the same bytes, read for their prefixes alone
    return ET.iterparse(io.BytesIO(xml), events=("start-ns",))  # noqa: S314


def _repacked(package: zipfile.ZipFile, changed: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as repacked:
        for info in package.infolist():
            if info.filename in changed:
                repacked.writestr(info.filename, changed[info.filename], compress_type=zipfile.ZIP_DEFLATED)
            else:
                repacked.writestr(info, package.read(info.filename))
    return out.getvalue()
