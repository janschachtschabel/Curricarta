# Gold-Fixtures: synthetischer Urteilsbogen

`bogen.csv` ist **kein Bogen eines echten Lehrplans**. Er ist die Ausgabe von `python -m app.quality.sheet`
für das Testdokument `a_document` aus `backend/tests/quality/gold_documents.py`, dessen Wortlaute
`backend/tools/mem_synth.py` aus seiner festen Wortliste erzeugt – und danach so bearbeitet, wie eine
Tabellenkalkulation ihn zurückgibt:

- UTF-8 mit BOM, `;` als Trennzeichen, CRLF (in `.gitattributes` als `-text` vor dem Umschreiben geschützt);
- Spalten umgestellt, `page`, `path`, `kind`, `lead_in`, `quote` und `link` gestrichen;
- Leerzeichen am Zellenende, eine Zeile ohne Urteil, eine Notiz mit `;` und Zeilenumbruch, eine leere
  Schlusszeile.

`item` und `mark` passen zur Stichprobe dieses Dokuments in einer frischen Testdatenbank (Seed
`curricarta-h3`). Jedes Wort in `wording` und `note` stammt aus `mem_synth.NOUNS`/`WORDS`
(`tests/quality/test_instance_data_guard.py` prüft es).

**Regel:** Echte Urteilsbögen halten Wortlaute Dritter. Sie entstehen nur als Ausgabe von
`app.quality.sheet` und liegen nur unter `data/gold-local/` (von git und den Images ausgeschlossen); kein
Bogen mit der Kopfzeile des Werkzeugs liegt im Repository außerhalb dieses Ordners.
