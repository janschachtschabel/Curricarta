"""The engine docling's reading of a DOCX and an HTML page (app/conversion/docling_flow.py, plan M1 3b-3), on
stand-ins shaped as Docling 2.117 hands them over (probed in the converter's image on 2026-11-08): no page, no
place; a paragraph of an HTML page with a word set bold read as several items of one inline group. Docling
itself runs in tests/conversion/test_docling_e2e.py."""

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace as Shape
from typing import Any

import pytest

from app.conversion.docling_flow import MOST_GRID_CELLS, flow_items, read_flow
from app.conversion.flow import FlowCell, FlowItem
from app.conversion.text_layer import TooDense, UnreadablePdf
from tests.conversion.test_docx_hidden import docx, paragraph, run


class Parent:
    """A reference to an item's parent; ``owner`` the parent's own."""

    def __init__(self, cref: str, label: str, owner: "Parent | None" = None, data: Any = None) -> None:
        self.cref, self._label, self._owner, self._data = cref, label, owner, data

    def resolve(self, document: Any) -> Shape:
        return Shape(label=Shape(value=self._label), parent=self._owner, data=self._data)


BODY = Parent("#/body", "unspecified")
LAYERS = frozenset({"body"})  # Docling's ContentLayer.BODY, which is a str


def item(label: str, text: str = "", parent: Parent = BODY, **given: Any) -> Shape:
    return Shape(label=Shape(value=label), text=text, parent=parent, **given)


def bold(value: bool = True, italic: bool = False) -> Shape:
    return Shape(bold=value, italic=italic)


class Document:
    def __init__(self, *items: Shape) -> None:
        self.items, self.asked = items, None

    def iterate_items(self, *, included_content_layers: Any) -> list[tuple[Shape, int]]:
        self.asked = included_content_layers
        return [(each, 1) for each in self.items]


def test_a_title_a_heading_with_its_level_and_text_with_its_weight() -> None:
    document = Document(
        item("title", "Lehrplan Physik"),
        item("section_header", "1 Ziele", level=1),
        item("text", "Ein Absatz.", formatting=bold(False)),
        item("text", "Fett ohne Formatvorlage", formatting=bold()),
        item("paragraph", "Kursiv.", formatting=bold(False, italic=True)),
        item("caption", "Ein Diagramm", formatting=None),
    )

    assert flow_items(document, LAYERS) == [
        FlowItem("title", "Lehrplan Physik"),
        FlowItem("heading", "1 Ziele", level=1),
        FlowItem("text", "Ein Absatz."),
        FlowItem("text", "Fett ohne Formatvorlage", bold=True),
        FlowItem("text", "Kursiv.", italic=True),
        FlowItem("text", "Ein Diagramm"),
    ]
    assert document.asked == LAYERS  # a page's head, foot and navigation: none


def test_a_paragraph_docling_parts_at_its_words_set_bold_is_one_item_again() -> None:
    inline, other = Parent("#/groups/3", "inline"), Parent("#/groups/4", "inline")
    document = Document(
        item("text", "Die Schülerinnen und Schüler erwerben", parent=inline),
        item("text", "grundlegende", parent=inline, formatting=bold()),
        item("text", "Kenntnisse und", parent=inline),
        item("text", "Fähigkeiten", parent=inline, formatting=bold(False, italic=True)),
        item("text", ".", parent=inline),
        item("text", "Ein zweiter", parent=other),
        item("text", "Absatz, ganz fett", parent=other, formatting=bold()),
    )

    assert flow_items(document, LAYERS) == [
        FlowItem("text", "Die Schülerinnen und Schüler erwerben grundlegende Kenntnisse und Fähigkeiten."),
        FlowItem("text", "Ein zweiter Absatz, ganz fett", bold=True),  # most of its signs are bold
    ]


def test_a_list_item_keeps_its_mark_a_numbered_one_counted_where_docling_gives_none() -> None:
    bullets, numbers = Parent("#/groups/1", "list"), Parent("#/groups/2", "ordered_list")
    document = Document(
        item("list_item", "Sie planen.", parent=bullets, enumerated=False, marker=""),
        item("list_item", "Erstens.", parent=numbers, enumerated=True, marker=None),
        item("list_item", "Zweitens.", parent=numbers, enumerated=True, marker=None),
        item("list_item", "Drittens.", parent=BODY, enumerated=True, marker="c)"),
    )

    assert [(each.text, each.marker) for each in flow_items(document, LAYERS)] == [
        ("Sie planen.", "•"),
        ("Erstens.", "1."),
        ("Zweitens.", "2."),
        ("Drittens.", "c)"),
    ]


def test_a_list_item_or_heading_docling_parts_at_its_words_set_bold_keeps_its_kind_and_mark() -> None:
    # Docling hands such an item over without text, its parts in an inline group under it (probed, image)
    bullets = Parent("#/groups/1", "list")
    first, heading = Parent("#/texts/1", "list_item", bullets), Parent("#/texts/5", "section_header", BODY)
    inline, under_heading = Parent("#/groups/2", "inline", first), Parent("#/groups/3", "inline", heading)
    document = Document(
        item("list_item", "", parent=bullets, enumerated=False, marker="", self_ref="#/texts/1"),
        item("text", "Planen:", parent=inline, formatting=bold()),
        item("text", "Sie planen Experimente.", parent=inline),
        item("list_item", "Sie bewerten.", parent=bullets, enumerated=False, marker="", self_ref="#/texts/4"),
        item("section_header", "", level=2, self_ref="#/texts/5"),
        item("text", "Teil", parent=under_heading),
        item("text", "A", parent=under_heading, formatting=bold(False, italic=True)),
    )

    assert flow_items(document, LAYERS) == [
        FlowItem("list_item", "Planen: Sie planen Experimente.", marker="•"),
        FlowItem("list_item", "Sie bewerten.", marker="•"),
        FlowItem("heading", "Teil A", level=2),
    ]


def test_an_item_without_text_whose_parts_do_not_follow_is_left_out() -> None:
    bullets, elsewhere = Parent("#/groups/1", "list"), Parent("#/groups/9", "inline", BODY)
    document = Document(
        item("list_item", "", parent=bullets, enumerated=False, marker="", self_ref="#/texts/1"),
        item("text", "Ein Absatz", parent=elsewhere),
        item("text", "für sich.", parent=elsewhere),
    )

    assert flow_items(document, LAYERS) == [FlowItem("text", "Ein Absatz für sich.")]


def test_what_a_table_s_cell_holds_is_read_with_the_cell_alone() -> None:
    # Docling hands a cell of paragraphs or a list over as items under the table too, after it (probed)
    cells = [Shape(start_row_offset_idx=0, start_col_offset_idx=0, text="Planen Eins", column_header=False)]
    table_ref = Parent("#/tables/0", "table", BODY, Shape(num_rows=1, num_cols=1, table_cells=cells))
    in_cell = Parent("#/groups/5", "list", table_ref)
    document = Document(
        item("table", data=Shape(num_rows=1, num_cols=1, table_cells=cells)),
        item("text", "Planen", parent=table_ref),
        item("list_item", "Eins", parent=in_cell, enumerated=False, marker=""),
        item("text", "Danach."),
    )

    assert [(each.kind, each.text) for each in flow_items(document, LAYERS)] == [
        ("table", ""),
        ("text", "Danach."),
    ]


def test_docling_s_mark_of_a_line_break_is_a_space() -> None:
    # Docling leaves its own sign for <br> (U+E000) in a list item's and a heading's text
    document = Document(
        item("list_item", "Planenund Prüfen", enumerated=False, marker=""),
        item("section_header", "Teil  A", level=1),
    )

    assert [each.text for each in flow_items(document, LAYERS)] == ["Planen und Prüfen", "Teil A"]


def test_an_html_page_with_its_own_byte_order_mark_is_read_without_it(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.html"
    path.write_bytes("﻿<p>Ziele</p>".encode())
    converting = Converting()

    read_flow(path, converting, LAYERS)

    [(_, handed)] = converting.handed
    assert handed.decode("utf-8").count("﻿") == 1  # the one written before the page


def test_a_table_is_its_grid_its_header_row_marked_a_spanned_place_empty() -> None:
    cells = [
        Shape(start_row_offset_idx=0, start_col_offset_idx=0, text="Kompetenz", column_header=True),
        Shape(start_row_offset_idx=0, start_col_offset_idx=1, text="Stunden", column_header=True),
        Shape(start_row_offset_idx=1, start_col_offset_idx=0, text="Planen und Prüfen", column_header=False),
    ]
    table = item("table", data=Shape(num_rows=2, num_cols=2, table_cells=cells))

    [read] = flow_items(Document(table), LAYERS)

    assert read == FlowItem(
        "table",
        "",
        rows=(
            (FlowCell("Kompetenz", True), FlowCell("Stunden", True)),
            (FlowCell("Planen und Prüfen", False), None),
        ),
    )


class Unlaid:
    """Cells of a table no test reads: a grid refused is never laid out."""

    def __iter__(self) -> Any:
        raise AssertionError("the grid was laid out")


def test_a_table_that_states_a_grid_past_any_page_s_is_refused_before_it_is_laid_out() -> None:
    # a million rows by a million columns, stated by the file: laid out, its rows would take all memory
    table = item("table", data=Shape(num_rows=10**6, num_cols=10**6, table_cells=Unlaid()))

    with pytest.raises(TooDense) as dense:
        flow_items(Document(table), LAYERS)

    assert MOST_GRID_CELLS == 200_000
    assert str(dense.value) == "the file holds 1000000000000 places of a table, more than the 200000 taken"


def test_a_table_of_as_many_places_as_taken_is_read() -> None:
    table = item("table", data=Shape(num_rows=MOST_GRID_CELLS, num_cols=1, table_cells=[]))

    [read] = flow_items(Document(table), LAYERS)

    assert len(read.rows) == MOST_GRID_CELLS


def test_a_picture_is_no_item_its_caption_one() -> None:
    document = Document(item("picture"), item("caption", "Abbildung 1: Ein Diagramm"))

    assert flow_items(document, LAYERS) == [FlowItem("text", "Abbildung 1: Ein Diagramm")]


class Converting:
    """Docling's conversion of a file's bytes by its name stood in for: what it was handed, and a document of
    what it read."""

    def __init__(self, status: str = "success") -> None:
        self.status = status
        self.handed: list[tuple[str, bytes]] = []

    def __call__(self, name: str, data: bytes) -> Shape:
        self.handed.append((name, data))
        return Shape(status=Shape(value=self.status), document=Document(item("text", "Gelesen.")))


def test_a_docx_is_handed_to_docling_cleaned_its_hidden_signs_counted(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.docx"
    path.write_bytes(docx(paragraph(run("Sichtbar. "), run("Versteckt.", "<w:vanish/>"))))
    converting = Converting()

    items, dropped = read_flow(path, converting, LAYERS)

    [(name, handed)] = converting.handed
    with zipfile.ZipFile(io.BytesIO(handed)) as package:
        assert b"Versteckt." not in package.read("word/document.xml")
    assert (name, items, dropped) == ("lehrplan.docx", [FlowItem("text", "Gelesen.")], {"hidden": 10})


def test_an_html_page_is_handed_to_docling_without_its_hidden_text_in_utf_8(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.html"
    path.write_text('<p>Sichtbar.</p><p style="font-size:0">Versteckt.</p>', encoding="utf-8")
    converting = Converting()

    _, dropped = read_flow(path, converting, LAYERS)

    [(name, handed)] = converting.handed
    assert name == "lehrplan.html"
    # with its byte order mark: UTF-8, whatever it named; the element set at no size stays, its text not
    assert handed.decode("utf-8") == "﻿<html><head></head><body><p>Sichtbar.</p><p></p></body></html>"
    assert dropped == {"hidden": 10}


@pytest.mark.parametrize("status", ["failure", "partial_success"])
def test_a_file_docling_cannot_read_whole_is_unreadable(tmp_path: Path, status: str) -> None:
    path = tmp_path / "lehrplan.html"
    path.write_text("<p>Text.</p>", encoding="utf-8")

    with pytest.raises(UnreadablePdf):
        read_flow(path, Converting(status), LAYERS)


def test_an_html_page_not_in_utf_8_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.html"
    path.write_bytes("<p>Prüfen</p>".encode("latin-1"))

    with pytest.raises(UnreadablePdf):
        read_flow(path, Converting(), LAYERS)


def test_a_table_within_a_cell_whose_text_the_cell_lacks_is_read_as_a_table_of_its_own() -> None:
    # Docling's DOCX cell holds its paragraphs' text, not a table within it; an HTML cell holds both
    cells = [Shape(start_row_offset_idx=0, start_col_offset_idx=0, text="Planen", column_header=False)]
    inner_cells = [Shape(start_row_offset_idx=0, start_col_offset_idx=0, text="Innen", column_header=False)]
    grid, inner_grid = (
        Shape(num_rows=1, num_cols=1, table_cells=cells),
        Shape(num_rows=1, num_cols=1, table_cells=inner_cells),
    )
    outer = Parent("#/tables/0", "table", BODY, grid)
    inner = Parent("#/tables/1", "table", outer, inner_grid)
    document = Document(
        item("table", data=grid, self_ref="#/tables/0"),
        item("text", "Planen", parent=outer),
        item("table", parent=outer, data=inner_grid, self_ref="#/tables/1"),
        item("text", "Innen", parent=inner),
    )

    tables = [each for each in flow_items(document, LAYERS) if each.kind == "table"]

    assert [[cell.text for row in each.rows for cell in row if cell] for each in tables] == [
        ["Planen"],
        ["Innen"],
    ]
