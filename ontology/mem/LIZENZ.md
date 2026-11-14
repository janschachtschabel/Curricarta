# MEM-Schule: Herkunft und Lizenz

Quelle: **Lehrplan Ontology. Version 1.0.0rc3, https://w3id.org/lehrplan/ontology** (so die
Zitierangabe der Ontologie, `dcterms:bibliographicCitation`). Repository:
<https://github.com/FWU-DE/lehrplan-ontologie>. Urheber laut `dcterms:creator`: Almut Steinlein, Cindy
Bloes, Johann Bergh, Laura Junghanns sowie <https://orcid.org/0000-0001-6378-2618> und
<https://orcid.org/0000-0001-7192-7143>. Lizenz laut `dcterms:license` der Ontologie: **CC BY-SA 4.0**
(<https://creativecommons.org/licenses/by-sa/4.0/>).

- `shapes/bereich.ttl`, `shapes/lehrplan.ttl`, `shapes/textual-entity.ttl` und `shapes/verweis.ttl` sind
  die Hand-Shapes des Repositorys (`shapes/<Name>/shape.ttl`), inhaltlich unverändert, nur umbenannt.
  Sie tragen selbst keine Lizenzangabe; die Lizenz ist die der Ontologie, deren Repository sie
  enthält. Eine eigene LICENSE-Datei des Repositorys ist noch zu prüfen (Plan M2, E14).
  `auto-shapes` ist nicht übernommen, es beschreibt nur Wertebereiche.
- `lp-klassen.ttl` ist ein Auszug aus `lp.ttl`: Klassen, ihre benannten Oberklassen und Labels, nichts
  hinzugefügt. Er wird von `werkzeuge/erzeuge_lp_klassen.py` aus `werkzeuge/quellen/lp.ttl` (der
  veröffentlichten Ontologie, unverändert) erzeugt. Nie von Hand ändern.
- `grundtypen.json` ist keine Aussage der Ontologie. Es nennt die Grundtypen der curricularen
  Landesklassen aus `werkzeuge/quellen/fwu-landesklassen.csv`, als Hilfe zur Typisierung beim Import.
  Für Klassen, deren Grundtyp aus ihrem Funktionswert folgt, folgt er nicht aus `lp.ttl`;
  `reasoned.ttl` folgert nur die Verweise. Er steht deshalb nicht als `rdfs:subClassOf` im
  FWU-Namensraum.

Änderungen gegenüber dem Original: Dateinamen der Shapes, der Auszug `lp-klassen.ttl`, die
abgeleitete Tabelle `grundtypen.json`. Weitergabe dieser Dateien und daraus abgeleiteter Werke unter
derselben Lizenz (ShareAlike).

Die Lizenz der **Instanzdaten** am MEM-Endpunkt (die Lehrpläne der Länder) ist damit nicht geklärt.
Deshalb gilt (Vorgabe des Betreibers vom 13.11.2026): Die App ruft diese Daten zur Laufzeit ab und
erzeugt daraus ihre Ansichten; **ausgeliefert werden sie nicht** – weder im Repository noch in einem
Image noch als Testdaten. Zum Entwickeln dürfen sie lokal unter `data/mem-local/` liegen (von git
ignoriert). Die Tests laufen auf synthetischen Plänen (`backend/tests/sources/fixtures/mem/HERKUNFT.md`).
