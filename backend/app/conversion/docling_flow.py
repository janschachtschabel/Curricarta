"""The engine docling on a DOCX and an HTML page (plan M1 3b-3): what Docling reads of them, as items.

The file's text no reader sees is taken out (a DOCX's runs, app/conversion/docx_hidden.py) or marked hidden
(an HTML page's elements, app/conversion/html_hidden.py) before Docling reads it, which it does without a
page, without a place and without a model, in a fraction of a second. Its body alone is the document's: a
DOCX's headers and footers, an HTML page's navigation, its head and foot, Docling reads as furniture, which
is left out. Of each item: a title, a heading with its level, text with its weight and slant, a list item
with its mark - a numbered one counted in its list where Docling gives none, as for an HTML page -, a
table's grid with its header row; a picture is no item, its caption is. Docling parts a paragraph at each
word set bold or slanted into items of one inline group: they are one item again, their texts joined, bold or
slanted as most of its signs are - a list item's or a heading's so parted comes without text, the group under
it, and keeps its kind and mark. Docling hands the parts over without the spaces between them: they are joined
with one, a word parted within ("Schüler<i>innen</i>") too (simplify). The items become a conversion in
app/conversion/flow.py.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.conversion.base import DropReason
from app.conversion.docx_hidden import clean_docx
from app.conversion.flow import FlowCell, FlowItem
from app.conversion.html_hidden import clean_html
from app.conversion.text_layer import UnreadablePdf

# A file's bytes by its name, read by Docling: its result
ConvertBytes = Callable[[str, bytes], Any]

FLOW_SUFFIXES = frozenset({".docx", ".html", ".htm"})
_HEADING = "section_header"
_TEXT = frozenset(
    {
        "text",
        "paragraph",
        "caption",
        "footnote",
        "reference",
        "code",
        "formula",
        "document_index",
        "handwritten_text",
    }
)
_NO_SPACE_BEFORE = tuple(".,;:!?)]}»“")
_BREAK = "\ue000"  # Docling's sign for <br>, left in a list item's and a heading's text
_DEEPEST = 64  # how far up an item's parents are looked through for a table


def flow_converter() -> tuple[ConvertBytes, Collection[Any]]:
    """Docling's reading of a DOCX's and an HTML page's bytes, and the body's layer. An HTML page's
    resources - pictures, stylesheets, frames - are fetched from nowhere, nor is the page rendered."""
    from io import BytesIO

    from docling.datamodel.backend_options import HTMLBackendOptions
    from docling.datamodel.base_models import DocumentStream, InputFormat
    from docling.document_converter import DocumentConverter, HTMLFormatOption
    from docling_core.types.doc import ContentLayer

    offline = HTMLBackendOptions(
        enable_remote_fetch=False, enable_local_fetch=False, fetch_images=False, render_page=False
    )
    converter = DocumentConverter(
        allowed_formats=[InputFormat.DOCX, InputFormat.HTML],
        format_options={InputFormat.HTML: HTMLFormatOption(backend_options=offline)},
    )

    def convert(name: str, data: bytes) -> Any:
        return converter.convert(DocumentStream(name=name, stream=BytesIO(data)), raises_on_error=False)

    return convert, {ContentLayer.BODY}


def read_flow(
    path: Path, convert: ConvertBytes, layers: Collection[Any]
) -> tuple[list[FlowItem], Counter[DropReason]]:
    """The items of the DOCX or HTML page at ``path``, its hidden text taken out first, and the signs taken by
    why; ``layers``: the body's (Docling's ContentLayer.BODY). UnreadablePdf where the file cannot be read, or
    Docling does not read it whole."""
    data = path.read_bytes()
    if path.suffix.lower() == ".docx":
        cleaned, dropped = clean_docx(data)
    else:
        try:
            page = data.decode("utf-8-sig")  # a byte order mark of its own is none of its text
        except UnicodeDecodeError:
            raise UnreadablePdf("the HTML page is not in UTF-8") from None
        written, dropped = clean_html(page)
        # with its byte order mark: Docling's parser takes it for UTF-8, whatever encoding the page once named
        cleaned = ("\ufeff" + written).encode("utf-8")
    result = convert(path.name, cleaned)
    if result.status.value != "success":
        raise UnreadablePdf(f"Docling read the file {result.status.value}")
    return flow_items(result.document, layers), dropped


def flow_items(document: Any, layers: Collection[Any]) -> list[FlowItem]:
    """The document's body - ``layers`` - as items, in its order."""
    items: list[FlowItem] = []
    numbered: defaultdict[str, int] = defaultdict(int)  # by list: the items counted
    waiting: tuple[str | None, FlowItem] | None = (
        None  # an item without text, its reference: its parts follow
    )
    for group, owner, members in _grouped(document, layers):
        if group is not None:
            joined = _joined(members)
            if waiting is not None and owner is not None and owner == waiting[0]:
                items.append(replace(waiting[1], text=joined.text, bold=joined.bold, italic=joined.italic))
            else:
                items.append(joined)
            waiting = None
            continue
        waiting = None
        [each] = members
        if (found := _item(each, numbered)) is None:
            continue
        if found.kind != "table" and not found.text.strip():
            waiting = (getattr(each, "self_ref", None), found)  # left out unless its parts follow
            continue
        items.append(found)
    return items


def _grouped(document: Any, layers: Collection[Any]) -> Iterator[tuple[str | None, str | None, list[Any]]]:
    """The items in their order, those of one inline group together: (the group, the item it belongs to, its
    items) - (None, None, [item]) for one of no inline group."""
    group: str | None = None
    owner: str | None = None
    members: list[Any] = []
    cells: dict[str, str] = {}  # by table: its cells' text
    for each, _level in document.iterate_items(included_content_layers=layers):
        if _held_by_cells(each, document, cells):
            continue  # a cell of paragraphs or a list: Docling hands its items over too, the cell holds them
        parent = each.parent
        node = parent.resolve(document) if parent is not None else None
        inline = node is not None and node.label.value == "inline"
        cref = parent.cref if inline else None
        if members and (cref is None or cref != group):
            yield group, owner, members
            members = []
        group = cref
        owner = node.parent.cref if node is not None and inline and node.parent is not None else None
        members.append(each)
        if cref is None:
            yield None, None, members
            members = []
    if members:
        yield group, owner, members


def _held_by_cells(each: Any, document: Any, cells: dict[str, str]) -> bool:
    """Whether the item stands within a table whose cells hold its text already: a cell's paragraphs and
    lists do, a table within a DOCX's cell does not (Docling's cell holds its paragraphs alone), an HTML
    cell's table does."""
    node, steps = each, 0
    while (parent := getattr(node, "parent", None)) is not None and steps < _DEEPEST:
        node = parent.resolve(document)
        if node.label.value == "table":
            key = parent.cref
            if key not in cells:
                cells[key] = _single(" ".join(cell.text for cell in node.data.table_cells))
            return _single(_text_of(each)) in cells[key]
        steps += 1
    return False


def _single(text: str) -> str:
    return " ".join(_plain(text).split())


def _text_of(each: Any) -> str:
    if each.label.value == "table":
        return " ".join(cell.text for cell in each.data.table_cells)
    return getattr(each, "text", "") or ""


def _plain(text: str) -> str:
    """The text without Docling's own sign for a line break (U+E000), a space in its place."""
    return " ".join(text.replace(_BREAK, " ").split()) if _BREAK in text else text


def _joined(members: list[Any]) -> FlowItem:
    text = ""
    weighed: Counter[str] = Counter()
    for each in members:
        part = _plain(getattr(each, "text", "") or "").strip()
        if not part:
            continue
        text = part if not text else f"{text}{'' if part.startswith(_NO_SPACE_BEFORE) else ' '}{part}"
        formatting = getattr(each, "formatting", None)
        weighed["signs"] += len(part)
        weighed["bold"] += len(part) if formatting is not None and formatting.bold else 0
        weighed["italic"] += len(part) if formatting is not None and formatting.italic else 0
    half = weighed["signs"] / 2
    return FlowItem("text", text, bold=weighed["bold"] > half, italic=weighed["italic"] > half)


def _item(each: Any, numbered: defaultdict[str, int]) -> FlowItem | None:
    label = each.label.value
    text = _plain(getattr(each, "text", "") or "")
    formatting = getattr(each, "formatting", None)
    bold = bool(formatting is not None and formatting.bold)
    italic = bool(formatting is not None and formatting.italic)
    if label == "title":
        return FlowItem("title", text)
    if label == _HEADING:
        return FlowItem("heading", text, level=int(getattr(each, "level", 1) or 1))
    if label == "list_item":
        return FlowItem("list_item", text, bold=bold, italic=italic, marker=_marker(each, numbered))
    if label == "table":
        return FlowItem("table", "", rows=_rows(each.data))
    if label in _TEXT:
        return FlowItem("text", text, bold=bold, italic=italic)
    return None  # a picture, a chart, a form's field: no text of the document's own


def _marker(each: Any, numbered: defaultdict[str, int]) -> str:
    given = (getattr(each, "marker", "") or "").strip()
    if given:
        return given
    if not getattr(each, "enumerated", False):
        return "•"
    parent = each.parent.cref if each.parent is not None else ""
    numbered[parent] += 1
    return f"{numbered[parent]}."


def _rows(data: Any) -> tuple[tuple[FlowCell | None, ...], ...]:
    """The table's grid, a cell at the first place it takes: None at the others a span covers."""
    grid: list[list[FlowCell | None]] = [[None] * data.num_cols for _ in range(data.num_rows)]
    for cell in data.table_cells:
        grid[cell.start_row_offset_idx][cell.start_col_offset_idx] = FlowCell(
            _plain(cell.text), bool(cell.column_header)
        )
    return tuple(tuple(row) for row in grid)
