"""Reading the research results' tables (ontology/werkzeuge/recherche_tabellen.py, plan M1 10a R1): a table
is known by its header line, not by a heading; its fields split at every ";". A row with another number of
fields than its header - an unescaped ";" in a field, a row broken over two lines - is shifted: kept apart,
never read as data."""

from pathlib import Path

from recherche_tabellen import read_report, read_tables

FENCE = "`" * 3
REPORT = f"""<!-- Recherche 01 Schule DE-NW, Welle 2; Rohbericht ungeprueft -->
Zusammenfassung mit einem ; im Text.

### T1 Dokumente
{FENCE}csv
land;titel;beleg
DE-NW;Kernlehrplan Physik ;E
{FENCE}

Ohne Ueberschrift:
{FENCE}csv
land;begriff_woertlich;ziel_id;beleg
DE-NW;Inhaltsfeld;schul:Inhaltsbereich;E
DE-NW;„Zitat"mit Anfuehrung;schul:Kompetenz;S

DE-NW;Marker; mit Semikolon;schul:x;E
DE-NW;Umbruch;schul:y
;E
{FENCE}
"""


def line_of(text: str, start: str) -> int:
    return next(number for number, line in enumerate(text.split("\n"), 1) if line.startswith(start))


def test_each_csv_block_is_a_table_known_by_its_header_whatever_stands_above_it() -> None:
    tables = read_tables(REPORT)

    assert [table.header for table in tables] == [
        ("land", "titel", "beleg"),
        ("land", "begriff_woertlich", "ziel_id", "beleg"),
    ]
    assert tables[1].has("begriff_woertlich", "ziel_id")
    assert not tables[0].has("begriff_woertlich")


def test_a_row_s_fields_are_named_by_the_header_stripped_and_its_line_kept() -> None:
    first, second = read_tables(REPORT)

    (row,) = first.rows
    assert row.values == {"land": "DE-NW", "titel": "Kernlehrplan Physik", "beleg": "E"}
    assert row.line == line_of(REPORT, "DE-NW;Kernlehrplan")
    assert [one["begriff_woertlich"] for one in second.rows] == ["Inhaltsfeld", '„Zitat"mit Anfuehrung']
    assert second.rows[0]["fehlt"] == ""  # a column the table does not have reads as empty


def test_a_quotation_mark_is_text_not_csv_quoting() -> None:
    _, table = read_tables(REPORT)

    assert table.rows[1]["ziel_id"] == "schul:Kompetenz"


def test_a_row_with_another_number_of_fields_is_shifted_never_data() -> None:
    _, table = read_tables(REPORT)

    assert table.shifted == (
        line_of(REPORT, "DE-NW;Marker"),
        line_of(REPORT, "DE-NW;Umbruch"),
        line_of(REPORT, ";E"),
    )
    assert len(table.rows) == 2  # the blank line is no row at all


def test_a_report_is_read_from_its_file_with_any_line_ends(tmp_path: Path) -> None:
    path = tmp_path / "01-schule-DE-NW.md"
    path.write_bytes(REPORT.replace("\n", "\r\n").encode("utf-8"))

    tables = read_report(path)

    assert [len(table.rows) for table in tables] == [1, 2]
    assert tables[0].rows[0]["beleg"] == "E"
