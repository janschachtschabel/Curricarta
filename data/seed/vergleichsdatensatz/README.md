# Saat des Quellregisters (Vergleichsdatensatz v62.493)

Zwei Tabellen, abgeleitet aus einem offen bereitgestellten Datensatz zu deutschen Lehrplänen
(Länder-Auszug Deutschland, Modellversion `62.493-at-luecken`, Stand 2026-09-30).

**Lizenz:** Der Deutschland-Auszug steht unter **CC0 1.0 Universal**; diese Dateien dürfen ohne
Namensnennung kopiert, verändert und verbreitet werden. Andere Länder-Auszüge desselben Angebots
haben eigene Lizenzen und sind hier nicht enthalten.

**Abgeleitet heißt:**
- `lehrplan_dokumente_de.csv` enthält nur die Spalten, die die App liest (17 von 35):
  `Land_Kuerzel`, `Land`, `Schulform`, `Fach_Schluessel`, `Fach`, `Bildungsstufe`, `Jahrgang_von`, `Jahrgang_bis`, `Verbindlichkeit`, `URL`, `URL_Original`, `URL_Archiv`, `Wayback_Zeitstempel`, `Quelltyp`, `Verifikation`, `ESA-Ableitung`, `Beispiel_ID`.
  Titel, Beschreibungen, Themenauszüge, Knotenzahlen und Prüfsummen der Quelle sind entfernt; Zeilen
  und Reihenfolge sind unverändert.
- `umgehungshinweise_de.csv` ist unverändert.
- Beide sind Semikolon-CSV mit BOM und CRLF.

**Verwendung:**
- **Saat:** Jede nicht ausgelassene Zeile wird ein Kandidat im Quellregister mit Herkunft
  `vergleichsdatensatz-v62.493` und Status `unchecked` (`python -m app.sources.seed`).
- **Übernommene Felder:** URL, Archiv-URL, Land, Schulform, Fach, Jahrgänge, Verbindlichkeit und
  Quelltyp, dazu Bildungsstufe, Fach-Schlüssel und Wayback-Zeitstempel der Archivkopie.
- **Ausgelassen:** ESA-Ableitungen und „kanonisch“ modellierte Zeilen, außerdem Zeilen mit
  falscher Feldzahl oder unbrauchbarer Adresse (in v62.493 keine); der Befehl zählt sie.
- **Zugangsnotizen:** Die Hinweise der zweiten Tabelle werden Zugangsnotizen je Land, Schulform und
  Fach; ohne Schulform oder Fach gelten sie für alle des Landes. Sie sagen, wo ein Dokument öffentlich
  liegt (Archivkopie, Zweitquelle) oder dass ein Portal Abrufe ablehnt. Technische Sperren umgeht die
  App nicht: Sie prüft robots.txt, hält Abstand je Host und nimmt 403 und 429 als Antwort.

Die Dateien bleiben byte-gleich (`.gitattributes`: `-text`). Ein Test vergleicht sie mit dieser
Tabelle (`backend/tests/sources/test_seed_files.py`).

| Datei | Bytes | SHA-256 |
|---|---|---|
| `lehrplan_dokumente_de.csv` | 611.427 | 8497307bf55d9100218558d49dfd08c6abd82bbdced8a562e7337bc55062a655 |
| `umgehungshinweise_de.csv` | 107.686 | b72b7098cc0d11cebc229a037eeb33807938fd6d2e827ae39a1fd1482321196a |

**Inhalt:**
- **`lehrplan_dokumente_de.csv`:** 1.831 Dokumente je Land × Schulform × Fach. Nach dem
  Auslassen bleiben 1.498 Einträge mit 1.278 Adressen (1.279 Zeichenketten: eine trägt einen
  Vermerk in Klammern) auf 34 Hosts.
- **`umgehungshinweise_de.csv`:** 355 Hinweise zu Portalen und Zweitquellen: Wayback-Archiv,
  Sekundärquelle, Sperre 403/429, Spiegel, GEI.
