# MEM-Fixtures: synthetische Pläne

Diese Dateien enthalten **keine Daten von MEM-Schule**. Es sind erfundene Pläne in der Form, in der der
MEM-Endpunkt antwortet, erzeugt mit `backend/tools/mem_synth.py` aus lokal eingefrorenen Antworten
(`backend/tools/mem_freeze.py`, Ablage `data/mem-local/`, von git ignoriert):

- **Erhalten** ist die Form: welcher Teil unter welchem liegt, die Klassen der Lehrplan-Ontologie, Jahrgänge,
  Seiten, Positionen, Stunden und die Verweise.
- **Erfunden** ist jeder Wortlaut. Ein Label behält nur seine Gestalt (Wortzahl, Groß- und Kleinschreibung,
  Zahlen, Satzzeichen); jedes Wort stammt aus einer festen Liste und hängt nur von seiner Stelle ab.
- **Umbenannt** ist jede Instanz-IRI (`https://example.org/mem/<name>/t<nnnn>`).

| Datei | Graph | Form |
|---|---|---|
| `rp.json` | `https://w3id.org/lehrplan/rp` | 9 Teile, ohne Position und Nummer |
| `sn.json` | `https://w3id.org/lehrplan/sn` | 58 Teile, 20 Verweise, Seiten, Stunden |
| `by.json` | `https://w3id.org/lehrplan/by` | 10 Teile mit Position |
| `be.json` | `https://w3id.org/lehrplan/graph/be` | 56 Teile, 14 Verweise, mehrzeilige Labels |
| `kmk.json` | `https://w3id.org/lehrplan/graph/bista` | 10 Standards, flach |

Die Klassen-IRIs (`https://w3id.org/lehrplan/ontology/LP_…`) stammen aus der Lehrplan-Ontologie des FWU
(CC BY-SA 4.0, siehe `ontology/mem/LIZENZ.md`).

**Regel:** Instanzdaten von MEM-Schule (Lehrplaninhalte vom Endpunkt) gehören weder ins Repository noch in
ein Image. Die App ruft sie zur Laufzeit ab; zum Entwickeln dürfen sie lokal unter `data/mem-local/`
liegen. Neue Fixtures entstehen nur über `mem_synth.py`.
