# Curricarta

Curricarta turns curricula and educational standards (PDF, HTML, DOCX) into structured, source-anchored
competency data: every statement links back to the passage it came from. It is built on an open curriculum
ontology (Curriculum Core 1.0) with SHACL validation, editorial review and RDF export.

**Status: pre-release, under active development.** Interfaces and the data model still change.

What works today:

- a **source register** of curricula with their rights status, upload and fetch by URL (public addresses
  only, robots.txt respected);
- **conversion** of PDF, DOCX and HTML into blocks with stable ids (pdfplumber; Docling and OCR in an
  optional converter service, CPU only);
- **extraction** in stages by a language model behind an OpenAI-compatible API, with token budgets per
  account - and a check of every extracted wording against the blocks it claims to come from;
- **validation** with SHACL, findings stored row by row; an **editor** with review states; **frozen
  revisions** with stable identifiers;
- **MEM-Schule**: import of a plan from its SPARQL endpoint into a document, export as RDF in the
  Lehrplan ontology of FWU, the KMK's educational standards included.

Not there yet: public read access, linking to competence frameworks and norm data, the knowledge map
across curricula, released images.

Good to know:

- The user interface and most of the documentation are **German**; code, comments and commit messages
  are English. The rest of this README is the German guide for development and operation.
- **Licences:** © 2026 Jan Schachtschabel. Code under Apache-2.0 ([LICENSE](LICENSE)): whoever passes
  Curricarta or a work derived from it on keeps the [NOTICE](NOTICE) and names its author. The project's
  own data - the ontology, its vocabularies and profiles, the research notes - under CC BY 4.0. Parts by
  others (the Lehrplan ontology of FWU under CC BY-SA 4.0, the seed, the tokenizer encoding) carry their
  own licences; NOTICE lists them by path. The repository holds **no curriculum texts of third parties
  and no data of MEM-Schule** - the application fetches them at run time, the tests use synthetic plans.
- The ontology lives in [`ontology/`](ontology/) (core, vocabularies, profiles, shapes); its IRIs are
  provisional until the namespace is registered.
- Comments cite the project's design notes as "plan M1 ...", "Gesamtplan ..." or "audit ...". These
  planning documents are not part of the repository.
- Security reports: [SECURITY.md](SECURITY.md). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).
  Answers for operators: [`docs/uebergabe/`](docs/uebergabe/) (German).

## Entwicklung

Backend (Python 3.13, uv):

```bash
cd backend
uv sync --frozen
.venv/Scripts/python.exe -m pytest
```

`uv.lock` legt alle Versionen für jede Plattform fest, mit Prüfsummen. Wer eine Abhängigkeit
ändert, sperrt neu (`uv lock`) und schreibt die Exporte für die Images neu:
`uv export --frozen --no-dev --format requirements-txt -o ../deploy/requirements-api.txt` und, mit
der Gruppe `convert` (Docling für das Konverter-Image),
`uv export --frozen --no-dev --group convert --format requirements-txt -o ../deploy/requirements-convert.txt`
(Tests vergleichen sie mit dem Lock). torch und torchvision kommen ohne CUDA vom CPU-Index von
PyTorch (`tool.uv.index` `pytorch-cpu`). Der Workflow `.github/workflows/audit.yml` prüft beide Exporte
und `frontend/package-lock.json` wöchentlich, von Hand und in jedem Pull Request, der einen Lock ändert, auf
bekannte Sicherheitslücken (Ausnahmen mit Begründung und Prüfdatum in `deploy/audit-allowlist.toml`).

Datenbank-Tests (Marker `pg`) brauchen einen PostgreSQL-Server nur für Tests, etwa diesen
Container (Daten nur im Arbeitsspeicher, Port nur lokal):

```bash
docker run -d --name curricarta-test-pg -e POSTGRES_USER=curricarta -e POSTGRES_PASSWORD=curricarta-test -e POSTGRES_DB=curricarta -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql/data pgvector/pgvector:pg17
```

Dann legt jeder Test eine eigene Datenbank `curricarta_t_…` an und entfernt sie wieder; jede Sitzung
legt dazu ein oder zwei Vorlagen `curricarta_tpl_…` an und entfernt sie am Ende, nur ein abgebrochener
Lauf kann beide zurücklassen:

```bash
CURRICARTA_TEST_DATABASE_URL=postgresql://curricarta:curricarta-test@127.0.0.1:55432/curricarta .venv/Scripts/python.exe -m pytest
```

Ohne `CURRICARTA_TEST_DATABASE_URL` werden die Datenbank-Tests übersprungen; mit `CURRICARTA_REQUIRE_PG=1`
(oder in CI) scheitern sie stattdessen.

Die S3-Tests (Marker `s3`) laufen gegen einen MinIO-Container nur für Tests (Chainguard-Build,
weil MinIO seit Oktober 2025 keine Community-Images mehr veröffentlicht; Zugangsdaten erfunden,
Daten nur im Arbeitsspeicher). Unter Git Bash vorher `export MSYS_NO_PATHCONV=1`, sonst werden
`/data` und `server /data` zu Windows-Pfaden:

```bash
docker run -d --name curricarta-test-minio -e MINIO_ROOT_USER=curricarta-test -e MINIO_ROOT_PASSWORD=curricarta-test-secret -p 127.0.0.1:59000:9000 --tmpfs /data:rw,uid=65532,gid=65532 cgr.dev/chainguard/minio@sha256:fe57367a6bfc78779367b86ad0cdd3d5df32965b7cb3c000c94032f138627c41 server /data
CURRICARTA_TEST_S3_URL=http://127.0.0.1:59000 CURRICARTA_TEST_S3_ACCESS_KEY=curricarta-test CURRICARTA_TEST_S3_SECRET_KEY=curricarta-test-secret .venv/Scripts/python.exe -m pytest -m s3
```

Ohne `CURRICARTA_TEST_S3_URL` werden sie übersprungen; mit `CURRICARTA_REQUIRE_S3=1` (oder in CI) scheitern sie.

Frontend (Vite, Vue 3, TypeScript; Node 22.22 oder 24.15 und neuer):

```bash
cd frontend
npm ci
npm run dev
```

`npm run dev` dient unter `http://localhost:5173` und reicht `/api` an das Backend auf Port
8000 weiter. `npm test` startet die Tests, `npm run lint` ESLint, `npm run build` prüft die
Typen und baut nach `dist/`, mit den Lizenzen der Schriften und Bibliotheken in
`dist/licenses.txt`.

## Betrieb

`python -m app.db.migrate` wendet die Migrationen an (einmal je Release, nie aus API
oder Worker), `python -m app.vocab.load` lädt die Vokabulare und das Lexikon (die
Terminologieprofile der Bereiche mit ihren Erkennungshinweisen, auch aus Unterordnern wie
`profile/laender/`) aus `ONTOLOGY_DIR` (Standard: `ontology/` dieses Repositorys), `python -m app.serve` startet die API auf `PUBLIC_PORT` und
`INTERNAL_PORT` (`/health`, `/ready`, `/metrics`), `python -m app.jobs.worker` den Worker
(`WORKER_KINDS` beschränkt ihn auf Job-Arten, kommagetrennt). Beide starten nur mit einem
nutzbaren Objektspeicher (lokal etwa `STORAGE_DIR=../data/store`). Der Worker bedient
`/health` und `/metrics` ebenfalls auf `INTERNAL_PORT`; im Cluster hat jeder Pod seinen eigenen.
Die Messgrößen der Warteschlange liest nur die API, die Alarmregeln für Prometheus liegen in
`deploy/alerts/curricarta.rules.yaml`; `docker build --build-arg REVISION=<commit>` nennt den Commit
in `curricarta_build_info`.
Läuft ein Worker neben der API auf demselben Rechner, braucht er ein eigenes `INTERNAL_PORT`
(etwa `INTERNAL_PORT=9001`): Sonst startet der zweite Prozess nicht, oder beide teilen sich den
Port still (Windows).

Anmeldung: Es gibt nur API-Tokens (`curricarta_…`), die ein Admin ausgibt; die Datenbank hält ihren
HMAC unter `API_KEY_PEPPER` (Geheimnis, mindestens 32 Zeichen, auch als Datei über
`API_KEY_PEPPER_FILE`). Ohne Pepper startet die API nicht; ein neuer Pepper macht alle Tokens
ungültig.

- Saat des Quellregisters: `python -m app.sources.seed` legt die 1.498 Kandidaten des
  Vergleichsdatensatzes an (`data/seed/vergleichsdatensatz/`, auch im API-Image), ohne Konto
  und ungeprüft, dazu 353 Zugangsnotizen zu gesperrten Portalen und Umwegen (je Land, Schulform
  und Fach; eine Notiz ohne Fach gilt für alle Fächer; die Einzelansicht eines Eintrags nennt
  sie). Ein zweiter Lauf ändert nichts. Vorher muss das Vokabular geladen sein. In Compose:
  `docker compose -f deploy/docker-compose.yml run --rm migrate python -m app.sources.seed`.
- Zweite Saat aus der eigenen Länderrecherche: `python -m app.sources.research_t1` legt die
  668 Dokumente der T1-Tabellen an (`ontology/recherche-ergebnisse/`, auch im API-Image), mit
  Bildungsbereich je Auftrag, Beleg E/S und gekennzeichneten Archiv-, Spiegel- und
  Sekundärquellen (nach Host oder Vermerk; ein Vermerk gilt für jeden Eintrag derselben
  Adresse). Danach meldet der Befehl, wie viele Adressen nur der Vergleichsdatensatz
  kennt, nur die Recherche oder beide. Ein zweiter Lauf ändert nichts. Vorher muss das
  Vokabular geladen sein (alle fünf Bildungsbereiche, sonst Exit-Code 1). In Compose:
  `docker compose -f deploy/docker-compose.yml run --rm migrate python -m app.sources.research_t1`.
- Prüfung der Saat: `POST /api/v1/sources/checks` (nur Admin) startet den Job `source.check`.
  Er fragt jede Adresse der Einträge ohne Konto und ohne Datei einmal ab – nach beiden Saaten
  rund 1.800 Adressen auf über 140 Hosts – und streamt und hasht den Inhalt, ohne ihn zu
  speichern. Jede Adresse, auch jedes Weiterleitungsziel, prüft er zuerst gegen die robots.txt
  ihres Hosts und fragt jeden Host höchstens alle `CHECK_HOST_INTERVAL_S` Sekunden, über alle
  Worker. Nichts wird umgangen: kein anderer User-Agent, kein Archiv oder Spiegel statt der
  Adresse. Ausgänge und Registerstand: 2xx erreichbar; 4xx (auch 403), 5xx, keine Antwort, die
  es geben kann, und ein Verbot laut robots.txt nicht erreichbar; 429 und 503 („später“)
  lassen den Eintrag ungeprüft und halten den Host für die verlangte Zeit (`Retry-After`,
  höchstens ein Tag) zurück; 502, 504, Zeitüberschreitung und Verbindungsabbruch gelten als
  vorübergehend nicht erreichbar. Diese beiden fragt eine spätere Prüfung erneut, und der Host
  wartet bis dahin: seine übrigen Adressen und jede Weiterleitung zu ihm. Ebenso wartet ein
  Host, dessen Name gerade nicht aufgelöst wird oder dessen robots.txt gerade nicht zu haben
  ist; seine Adressen bleiben ungeprüft. Ein Weiterleitungsziel über 2.000 Zeichen wird nicht
  gefragt; die Adresse, die dorthin führt, gilt als nicht erreichbar (endgültig, ohne Status).
  Ein neuer Start prüft nur, was noch offen ist; ein
  Kandidat, der später mit einer schon geprüften Adresse dazukommt, übernimmt deren Ergebnis.
  Ein zweiter Start, solange einer wartet oder läuft, gibt 409 `check_running` mit der Job-ID.
  Der Lauf dauert Stunden (allein ein Host trägt 400 Adressen) und belegt einen Worker; dafür
  einen eigenen Worker mit `WORKER_KINDS=source.check` vorsehen.
- Katalog von MEM-Schule: `POST /api/v1/mem/catalog` (nur Admin) startet den Job
  `source.mem_catalog`. Er liest aus jedem erlaubten Graphen des Endpunkts `MEM_SPARQL_URL`
  (öffentliche https-Adresse; BY, RP, SN, BE und die KMK-Bildungsstandards) alle Pläne seitenweise
  in die Tabelle `mem_plan`: Titel, Klasse, Land, Fächer und Schularten. Was der Endpunkt nicht
  mehr hat, fällt heraus; antwortet ein Graph mit gar keinem Plan, bleiben seine bisherigen stehen
  (`kept` im Ergebnis). Pläne, bei denen Graph und Klasse über die KMK uneins sind (KMK-Graph
  ohne Bildungsstandard oder Bildungsstandard anderswo), zählt `mismatched` und das Log. Ist der
  Endpunkt gerade nicht erreichbar, versucht es der Job erneut, beim letzten Versuch endet er mit
  `mem_unavailable` (ebenso der Import); eine
  Antwort, die er nicht annehmen kann, hält die übrigen Graphen nicht auf, beendet den Job danach aber
  (`mem_refused`, mit den Graphen). `MEM_SPARQL_URL` nennt nur Host und Pfad (ohne `@`, `?`, `#`), denn
  sie steht in jeder Namensnennung. Ein zweiter Start, solange einer
  wartet oder läuft, gibt 409 `catalog_running` mit der Job-ID. `GET /api/v1/mem/plans` (Redaktion
  und Admin) sucht im Katalog nach Region (`region`, `DE-SN`; `DE` für die KMK-Bildungsstandards,
  eine unbekannte gibt 422 `unknown_region`), Land (`land`, die IRI aus `LP_0000029`), Fach
  (`subject`, IRI) und Titel (`title`, Teil des Titels in beliebiger Schreibung), seitenweise (`limit`
  bis 200, `offset`); jeder Plan nennt seine Region und wann der Katalog ihn zuletzt gelesen hat
  (`read_at`), die Seite, wann der Katalog zuletzt gelesen wurde (`catalog_read_at`, leer: nie).
- Import eines MEM-Plans: `POST /api/v1/sources/{id}/mem-import` (Redaktion und Admin) mit
  `{plan_iri, conversion_id}` legt in einer Transaktion ein Dokument der fertigen Umwandlung des
  Eintrags an – Bereich Schule, Region aus dem Land des Plans (KMK: `DE`), Typ Lehrplan bzw.
  Bildungsstandards, eine Spezifikation mit dem Plantitel – und reiht den Job `extract.mem_import`
  unter dem Schlüssel der Extraktion ein (202). Der Job fragt den Plan am Endpunkt ab, legt die
  Antworten roh unter dem Lauf ab, schreibt den Baum als Lauf `IM` (Herkunft Import, Prüfstatus
  vorgeschlagen, Anker im Text der Umwandlung, Suchzeit `MEM_SEARCH_BUDGET_S`) und prüft ihn wie X5;
  sein Fortschritt: `mem_read`, `mem_anchor`, dann `check_document`.
  Weigerungen: 422 `mem_unknown_plan` (nicht im Katalog), 404 `mem_no_conversion`, 409 `mem_plan_taken`
  (die Umwandlung hat den Plan schon; `details.document_id`), 503 `service_unavailable` (das Dokument wurde
  gerade entfernt, erneut versuchen). Endete der Job vor `IM`, startet derselbe
  Aufruf ihn auf demselben Dokument neu. Ein Import wird nicht extrahiert oder repariert (409
  `not_extractable`); nach `IM` ist er bearbeitbar und darf neu geprüft werden (`/check`), auch wenn
  sein X5 scheiterte. Die Kostenschätzung nennt für ihn keine Modellanfragen.
- Export eines MEM-Imports: `GET /api/v1/documents/{id}/export.ttl` gibt ein festgeschriebenes Import-Dokument
  als RDF von MEM-Schule aus (Turtle, als Download). Unveränderte Zeilen stehen unter ihrer MEM-IRI und mit
  MEMs Klassen; bearbeitete oder neue Zeilen stehen unter ihrer eigenen IRI. Das Dokument nennt den
  MEM-Plan als Quelle, die Namensnennung und den Rechtestatus; eine Lizenz nur, wo eine für die Daten
  eingetragen ist. Ein bearbeiteter Knoten behält die Grundklasse, die seine MEM-Klassen erreichen; ein
  Verweis ohne Ziel und ohne Halter, den die Redaktion anlegte oder zu einem machte, geht als Hinweis hinaus
  (beides Entscheidungen im Plan, Gesamtreview nach M2-6).
  - **Prüfung:** Vor der Ausgabe prüft ein Kindprozess die Daten gegen die MEM-Shapes, innerhalb von
    `MEM_EXPORT_TIMEOUT_S` (30 s). Das Ergebnis bleibt im Speicher unter `exports/<Dokument>/`, bis sich
    Version, Rechtestatus, Lizenz oder die Shapes ändern.
  - **Weigerungen:** 409 `export_not_frozen`, `not_mem_import` und `export_invalid` (Verletzungen je Zeile in
    `details.violations`); 503 `export_unavailable` mit `Retry-After`; 429 `too_many_exports`
    (`EXPORTS_PER_MINUTE`, Standard 10). Zugriff hat, wer das Dokument und den Inhalt seines Eintrags
    lesen darf.
  - **Oberfläche:** Den Import bietet die Seite des Eintrags Redaktion und Admin unter „Import aus
    MEM-Schule“ an, sobald die Umwandlung fertig ist: Suche nach Land (Bund für die KMK) und Titel, der
    Stand des Katalogs (Admins lesen ihn dort ein), Namensnennung und Lizenz des gewählten Plans. Die
    Dokumentseite eines Imports nennt seine Herkunft, verfolgt den Import (Neustart, solange `IM` nicht
    fertig ist) und bietet nach dem Festschreiben den Export an: Die Datei wird mit dem Token geladen und
    gespeichert; Verletzungen stehen als Tabelle, mit Links auf die Zeilen im Baum, wo sie eine Zeile treffen.
- Konvertierung (X0): `POST /api/v1/sources/{id}/conversions` startet für die Datei eines
  Eintrags den Job `source.convert` (pdfplumber) oder `source.convert_docling` (Docling) (202) oder
  gibt die vorhandene Konvertierung zurück (200, eine gescheiterte startet neu). Welche Engines
  angeboten sind, sagt `CONVERSION_ENGINES` (kommagetrennt, Standard `pdfplumber`; eine andere im Body:
  422 `engine_not_offered`). Fehlt `engine` im Body (die Oberfläche nennt keine), gilt die Engine einer
  vorhandenen, nicht gescheiterten Konvertierung der Datei (kostenlos), sonst die erste angebotene, deren
  Seiten das Konto bezahlen kann – pdfplumber ist frei, Docling nicht, wo es für diese Datei an
  Seitenmangel scheiterte. Fehlt `engine` im Abruf, gilt die erste vorhandene, nicht gescheiterte
  Konvertierung in der angebotenen Reihenfolge, dann eine einer nicht mehr angebotenen Engine, eine
  gescheiterte nur, wo keine andere ist. Docling-Seiten kosten: Sie zählen gegen `page_limit` des
  Kontingents und werden gebucht, wenn die Konvertierung fertig ist; ein Konto ohne Seiten oder ohne
  Kontingent startet keine (403 `no_pages`). Der Job hält die Datei beim Start an die Restseiten: keine
  übrig oder eine längere Datei endet mit `no_pages`, bevor Docling liest (eine auch über
  `MAX_PDF_PAGES`: `too_many_pages`). Genau ist das, wo ein Konverter läuft; laufen mehrere nebeneinander,
  kann ein Konto je weiterem um eine Datei überziehen. `GET …/conversion` nennt Stand, Seiten, gedruckte Seiten und
  Befunde, `GET …/conversion/blocks?page=N` die Blöcke einer Seite (`p<Seite>-b<Block>`,
  Tabellenzellen `T<n>:r<i>c<j>`). Wer die Datei eines Eintrags lesen darf (Eigentümer,
  Redaktion, Admin; Einträge ohne Konto nach `THIRD_PARTY_MARKDOWN`), darf sie umwandeln lassen
  und die Blöcke lesen. Die Konvertierung gehört zur Datei (gleiche SHA-256), nicht zum Eintrag:
  Ein Konto, das dieselbe Datei hochlädt, findet die vorhandene und erfährt so, dass die Datei
  schon hier war – der Preis dafür, jede Datei nur einmal umzuwandeln. Die Job-ID nennt die
  Antwort nur dem Konto, das den Job gestartet hat, und Admins. Umgewandelt werden PDF, DOCX und
  HTML: Gefragt wird nur eine Engine, die den Typ des Eintrags liest – pdfplumber PDFs, Docling auch DOCX
  und HTML (unten) –, ohne `engine` die erste angebotene davon; liest keine angebotene den Typ (Markdown,
  Text, Turtle, RTF, ein DOCX oder eine HTML-Seite ohne Docling, ein anderes Paket wie XLSX oder ODT, das
  seiner Signatur nach als DOCX gilt, aber seine Endung behält), antwortet die API 422 `not_pdf`. Welche
  Engines die Datei eines Eintrags lesen, nennt `GET /api/v1/sources/{id}` in `conversion_engines`
  (`app/conversion/readers.py`); die Seite des Eintrags bietet die Umwandlung nur dort an. Ob irgendeine Engine
  sie liest, angeboten oder nicht, sagt `conversion_readable`: Eine Umwandlung, die Docling machte, als es
  angeboten war, bleibt so mit Blöcken und Dokumenten sichtbar, nur ohne Neustart. Der Job bekommt
  den Typ mit, schreibt die Datei mit dessen Endung und prüft sie an ihren Bytes (sonst `not_pdf`). pdfplumber liest
  keine Scans: Tragen weniger als vier Fünftel der Seiten Text, endet es mit `needs_ocr`, und eine
  Anfrage ohne Engine nimmt danach eine, die Scans liest. Docling liest jede Seite mit weniger als
  20 Zeichen Text und Bildern über mindestens 5 % der Fläche per Texterkennung (OCR, unten); mehr als
  200 solcher Seiten enden mit `too_many_ocr_pages`, bevor eine gelesen wird. Mehr als
  `MAX_PDF_PAGES` (800) Seiten enden mit `too_many_pages`, eine Seite mit mehr als 100.000 Zeichen
  mit `too_dense`, länger als `CONVERT_TIMEOUT_S` (900 s) mit `timed_out`. Die Umwandlung läuft
  in einem eigenen Kindprozess, den Abbruch, Frist und Lease-Verlust beenden; dafür eigene
  Worker mit `WORKER_KINDS=source.convert` vorsehen, ein Job je Pod, und für Docling Worker des
  Konverter-Images mit `WORKER_KINDS=source.convert_docling` (unten). Nur ein Worker, in dem Docling
  installiert ist, kennt diese Job-Art; ohne die Modelle unter `/models` startet er nicht.
- Formular: `GET /api/v1/profiles/{bereich}/form` (jedes Konto; `bereich` wie `school`) nennt die
  Felder eines Knotens und einer Aussage mit Art, Pflicht, Mehrfachwert und Höchstlänge und je
  Auswahlliste die aktiven Werte des Profils, nach Label geordnet – Knotentypen und Unterarten mit
  Label, weiteren Namen, Definition, Anmerkung, Abgrenzung und Beispielen; kein aktives Profil: 404
  `unknown_sector`. Die Felder sind nicht laxer als die SHACL-Formen des Kerns (Test).
- Dokumente: `POST /api/v1/documents` (`source_id`, `conversion_id`, `sector`, `regions`) legt aus der
  fertigen Umwandlung eines Eintrags ein Dokument an und startet seine Extraktion (202 mit Dokument und
  Job), als Modelljob zugelassen (403 `no_budget`, 429 `too_many_jobs` / `too_many_starts`). `POST
  /api/v1/documents/{id}/extraction` startet sie neu, nur durch den Eigentümer (403 `not_owner`) und solange
  er den Inhalt des Eintrags lesen darf (403 `file_hidden`), nicht für ein festgeschriebenes Dokument (409
  `frozen`), keine Entwurfskopie und kein Import aus MEM-Schule (409 `not_extractable`; wie die Reparatur); `GET
  /api/v1/documents?source_id=…`, `/documents/{id}`, `/documents/{id}/runs`, `/documents/{id}/units`,
  `/documents/{id}/findings` lesen sie (`units` und `findings` nur, wer auch den Inhalt des Eintrags lesen
  darf, sonst 403 `file_hidden` – ihre Pfade und Befunde nennen Titel und Wortlaut; jedes Dokument mit `issuer`, `edition`, `work` – Id, Titel, Land,
  Kurztitel, IRI –, `iri`, `revision`, `frozen_at` und `copy_of`, der Revision, die eine Entwurfskopie
  kopiert, und `mem` (Plan-IRI, Namensnennung und Lizenz eines Imports aus MEM-Schule, sonst leer); die Job-ID nur für Eigentümer und Admins, den Fehlercode des letzten Jobs,
  `extraction.error_code`, alle Leser; `units`: die Arbeitspakete mit Stand `done` samt Zahl der Aussagen,
  `open`, `frame` oder `none`, vor X2 leer; `findings`: die Befunde der Stufen, Verstöße zuerst, je mit Art,
  Wortlaut oder Titel der Zeile, die sie betreffen (gekürzt mit „…“), dem Arbeitspaket, das sie nennen, und
  der Sprache der Meldung, wo die Stufe sie kennt (`message_lang`: „de“ für die deutschen Meldungen der
  SHACL-Formen, sonst Englisch) – höchstens 500, die Zahlen je Schwere über alle). Je Dokument wartet oder
  läuft höchstens ein Extraktionsjob (`job.unique_key`, Migration 0018): ein Start dabei gibt den laufenden
  zurück (200); ebenso ein neues Dokument desselben Eintrags und derselben Konvertierung, solange eines des
  Kontos daraus extrahiert wird – dann 200 mit diesem (`made: false`).
- Reparatur: `POST /api/v1/documents/{id}/repair` startet den Job `extract.repair` (X6, dann X5
  erneut) – nur durch den Eigentümer und solange er den Inhalt lesen darf, wie ein Neustart,
  sobald X5 das Dokument geprüft hat (409 `not_checked`) und Befunde eines Arbeitspakets eine
  Reparatur verlangen (409 `nothing_to_repair`), zugelassen als Modelljob. Er teilt den
  Schlüssel der Extraktion: Ein Start, während eine Extraktion oder Reparatur wartet oder läuft,
  gibt diese zurück (200), in beide Richtungen. `findings` nennt dem Eigentümer nach X5 in
  `repairable` die Pakete, die eine Reparatur fragen würde; `extraction.kind` sagt jedem Leser,
  welcher Art der letzte Job ist.
- Baum: `GET /api/v1/documents/{id}/tree` liest die Knoten und Aussagen eines Dokuments, wie der Editor sie
  zeigt (wer das Dokument lesen darf, in einem Snapshot): je Zeile die Felder des Formulars unter dessen
  Schlüsseln, Herkunft, Prüfstand, Revision, `iri` (sobald das Dokument festgeschrieben wurde, sonst `null`;
  in einer Entwurfskopie tragen die übernommenen Zeilen ihre schon, neue erst nach dem Festschreiben) und
  Fundstellen (Seiten, gedruckte Seite, Zitat, Fundart, Wert, Blöcke in Dokumentreihenfolge), je Aussage
  `by_hand` (von Hand angelegt: `DELETE` löscht sie; aus einem Lauf: sie wird verworfen), je Knoten die
  Zahl der Befunde je Schwere an ihm, seinen Fundstellen, seinen Aussagen und deren Fundstellen (nicht an
  seinen Kindern), dazu die Zahl der Knoten und Aussagen je Prüfstand. `editable`: Eigentümer und
  Redaktion/Admin dürfen jetzt bearbeiten, `reviewable`: Redaktion/Admin dürfen den Prüfstand setzen –
  beides nicht, solange ein Job des Dokuments wartet oder läuft, nicht, bevor X4 jedes Arbeitspaket gelesen
  hat (eine Entwurfskopie gilt als gelesen, ein Import nach seinem Lauf `IM`), und nicht, sobald es festgeschrieben ist; `closed` nennt dann den
  Grund für alle Leser (`frozen` vor `job_open` vor `not_extracted`, sonst `null`). Lesen darf den Baum, wer
  das Dokument lesen darf (sonst 404 `no_document`) und den Inhalt des Eintrags (sonst 403 `file_hidden`):
  die Aussagen sind dieser Inhalt in den Worten des Dokuments. In der Oberfläche
  zeigt die Seite „Baum“ des Dokuments (`/dokumente/{id}/baum`, verlinkt von der Dokumentseite) den Baum mit
  Filter nach Prüfstand, daneben die gewählte Zeile mit Feldern und Fundstellen und unter ihr die Seite der
  Quelle mit den genannten Blöcken als „Beleg“; Zeile und Seite stehen in der Adresse (`?zeile=…&seite=…`),
  und wer über eine solche Adresse kommt, findet die Tastatur auf der Zeile – oder den Satz, dass der Baum sie
  nicht mehr hält.
  Ist der Baum offen (`editable`), steht die gewählte Zeile im Formular ihres Bildungsbereichs: Speichern
  sendet nur geänderte Felder mit der gelesenen Revision und liest den Baum neu; hat inzwischen jemand die
  Zeile geändert, übernimmt es dessen Felder und legt die von beiden geänderten zur Wahl vor („Meins
  behalten“ / „Gespeichertes nehmen“); ein Fehler steht am Feld; schließt sich der Baum (Job, festgeschrieben,
  X4) beim Speichern oder beim Neulesen, bleibt der Entwurf zum Abschreiben stehen. Sonst sagt die Seite,
  warum sie nur liest. Ein ungespeicherter Entwurf fragt nach, bevor eine andere Zeile oder eine andere Seite
  der App ihn verdrängt (eine andere Seite der Quelle nicht); der Browser fragt vor dem Schließen. Bei einer
  Aussage im offenen Baum sind die Blöcke der gezeigten Quellenseite Schalter: „Gewählte Blöcke als Fundstelle
  übernehmen“ legt sie als eine Fundstelle in den Entwurf, „Seite N als ‚nicht gefunden‘ übernehmen“ die
  Seite; der Entwurf listet seine Fundstellen mit „Entfernen“, und Speichern sendet sie – alle – nur, wenn
  sie sich geändert haben. Ein gewählter Knoten bietet „Unterknoten anlegen“ und „Aussage anlegen“, der Baum
  „Knoten anlegen“ (oberste Ebene); eine neue Aussage braucht eine Fundstelle; ein offener Entwurf fragt vorher
  nach; angelegt, wird der Baum neu gelesen und die neue Zeile gewählt. „Löschen“ (Knoten, mit Zahl der
  Unterknoten und Aussagen; eine von Hand angelegte Aussage, mit ihren Fundstellen) und „Verwerfen“ (die
  Aussage eines Laufs, die verworfen im Baum bleibt; einer schon verworfenen bietet die Seite es nicht mehr an)
  fragen vorher nach. Die Redaktion setzt in der gewählten Zeile ihren „Prüfstand“ („Vorgeschlagen“,
  „Bestätigt“, „Verworfen“, der gesetzte gedrückt); danach wird der Baum neu gelesen, eine inzwischen
  geänderte Zeile gesagt. „Erneut prüfen“ neben „Knoten anlegen“ startet die Prüfung (X5) und folgt ihr bis
  zum Ende; folgen dürfen ihr Eigentümer und Admins – die übrige Redaktion liest den Baum neu, wenn sie fertig
  ist.
- Blöcke des Dokuments: `GET /api/v1/documents/{id}/blocks?page=N` liest eine Seite der Konvertierung, aus
  der das Dokument gelesen wurde (Blöcke, fortlaufende Tabellen, gedruckte Seite, `pages`) – die Blöcke, die
  seine Fundstellen nennen, auch wenn die Datei des Eintrags seither neu geholt oder anders umgewandelt
  wurde. Lesen darf sie, wer das Dokument lesen darf (sonst 404 `no_document`) und den Inhalt des Eintrags
  (sonst 403 `file_hidden`); hinter der letzten Seite 404 `no_such_page`.
- Bearbeiten: `PATCH /api/v1/nodes/{id}` und `/statements/{id}` (`expected_revision`, `fields` unter
  den Schlüsseln des Formulars, ausgelassene bleiben; eine Aussage auch `anchors`, alle auf einmal:
  Blöcke der Konvertierung, die Seiten folgen aus ihnen, oder nur `page`, eine Seite der
  Konvertierung, wo kein Block sie hält),
  `POST /api/v1/documents/{id}/nodes` (`parent_id`, ans Ende der Geschwister) und
  `/nodes/{id}/statements` (ans Ende des Knotens, mindestens eine Fundstelle, sonst 422
  `anchor_missing`), `DELETE /api/v1/nodes/{id}` (samt Unterbaum und den Befunden darauf) und
  `/statements/{id}` (je `?expected_revision=`; die Aussage eines Laufs wird verworfen und bleibt,
  damit keine Reparatur sie neu vorschlägt, eine von Hand geschriebene gelöscht; die Antwort nennt
  `outcome` – `rejected` oder `deleted` – und die Revision danach, `null` nach dem Löschen) – durch
  Eigentümer und Redaktion/Admin. Eine Änderung macht die Zeile zum Vorschlag der Redaktion
  (`orig_human`, `rev_proposed`, Revision +1), ein neuer Titel oder Wortlaut lässt die Fundstellen mit Blöcken für
  X5 wieder ungeprüft, eine Änderung ohne geänderten Wert lässt die Zeile stehen; die Antwort ist die
  Zeile wie im Baum. Abgewiesen: 409 `stale_revision` (mit `details.current`, der Zeile, wie sie
  steht), `job_open` (solange ein Job des Dokuments wartet oder läuft; die Job-ID für Eigentümer und
  Admins), `not_extracted` (X4 hat noch nicht jedes Arbeitspaket gelesen: erst fortsetzen; ein Import: noch kein `IM`), `frozen`,
  `no_form`; 422 `invalid_field` (`details.field`, `details.problem`); 403 `file_hidden`, sobald der
  Inhalt des Eintrags nicht mehr der des Eigentümers ist – vor jeder anderen Prüfung, sodass auch eine
  veraltete Revision keine Zeile mehr zeigt (ebenso `GET …/findings`, deren Befunde Wortlaut und Titel
  nennen). Jede
  Änderung steht im Audit (`node.edit`, `node.add`, `node.drop`, `statement.edit`, `statement.add`,
  `statement.reject`, `statement.delete`).
- Prüfstand: `POST /api/v1/documents/{id}/review` (`status`: `proposed`, `confirmed` oder
  `rejected`; `items`: je `kind` – `node` oder `statement` –, `id` und gelesene `revision`, 1 bis
  2.000) setzt den Prüfstand vieler Zeilen auf einmal, nur durch Redaktion/Admin (sonst 403
  `not_editor`): alles oder nichts – steht eine Zeile anders oder nicht mehr da, 409 `stale_revision`
  mit `details.stale` (je Zeile `current`, die Revision jetzt oder `null`). Die Herkunft bleibt, die
  Revision zählt eins hoch, eine Zeile mit diesem Prüfstand bleibt, wie sie ist; die Antwort nennt die
  Revisionen danach. Eine Aussage zu oder von „verworfen“ ändert, was der Lehrplan sagt (Export und X5
  lassen verworfene aus) und schuldet X5 eine Prüfung; ein Knoten verworfen bleibt in beiden. Wie beim
  Bearbeiten nicht neben einem offenen Job, nicht vor X4 und nicht festgeschrieben; Audit `review.set`.
- Erneut prüfen: `POST /api/v1/documents/{id}/check` startet den Job `extract.check` (X5 erneut, ohne
  Modell) – durch Eigentümer und Redaktion/Admin, sobald X5 das Dokument einmal geprüft hat (sonst 409
  `not_checked`: die Extraktion fortsetzen) – ein Import nach `IM`, auch wenn sein X5 scheiterte – eine Entwurfskopie sofort, sie bringt keine Läufe ihrer
  Vorlage mit –, nicht, sobald es festgeschrieben ist (409 `frozen`), und wie Extraktion und Reparatur nur,
  wer den Inhalt des Eintrags lesen darf (403 `file_hidden`). Kein Modelljob: weder Budget noch
  Startgrenzen lassen ihn zu. Er läuft in der Spur des Eigentümers wie jeder Job des Dokuments: folgen (`GET
  /api/v1/jobs/{id}`) und abbrechen dürfen Eigentümer und Admins, wer ihn startete, sieht ihn in der Antwort
  (202). Er teilt den Schlüssel der Extraktion; wartet oder läuft ein Job des Dokuments, kommt dieser zurück
  (200), wo der Aufrufer ihm folgen darf (Eigentümer, Admin), sonst 409 `job_open`. Audit `check.start`.
  Geschuldet ist die Prüfung, sobald eine Reparatur oder eine Bearbeitung (`document.edited_at`) nach dem
  Start des letzten fertigen X5 begann.
- Werk: `PATCH /api/v1/documents/{id}/work` setzt das Werk des Dokuments – ein vorhandenes (`work_id`) oder
  ein neues (`title`, `region` wie `DE-NW`, `short_title` als Slug wie `lp-physik`) –, nur durch
  Redaktion/Admin (sonst 403 `not_editor`); 404 `no_work` für ein Werk, das es nicht gibt. Metadaten: `PATCH
  /api/v1/documents/{id}` setzt `issuer`, `edition` und `title` (ausgelassene bleiben, `null` oder leerer
  Text leert) – durch Eigentümer und Redaktion/Admin, 422 `invalid_field` wie beim Bearbeiten; eine Änderung
  schuldet X5 eine Prüfung; erst wenn X4 fertig ist, wie jede Bearbeitung des Baums (409 `not_extracted`;
  vor X1 überschriebe eine Extraktion sie mit dem, was X1 liest), ein neues Werk mit speicherbarem Titel und
  einem Land des Regionenvokabulars (422 `invalid_field`). Beide nicht neben einem offenen Job und nicht
  festgeschrieben; hat das Dokument schon seine IRI (festgeschrieben oder Entwurfskopie), bleiben Werk,
  Herausgeber und Fassung, aus denen sie besteht (409 `named`). Audit `document.work` bzw. `document.edit`;
  die Antwort ist das Dokument.
- Festschreiben: `POST /api/v1/documents/{id}/freeze` (`accept_violations`, Standard `false`), nur
  Redaktion/Admin. Abgewiesen, der Reihe nach: festgeschrieben (409 `frozen`), offener Job (`job_open`), X4
  nicht fertig, keine Entwurfskopie und kein Import nach `IM` (`not_extracted`), es fehlt Werk, dessen Land oder Kurztitel,
  Herausgeber oder Fassung, oder diese tragen keinen lateinischen Buchstaben und keine Ziffer, aus denen die
  IRI würde (`incomplete`, `details.missing`), keine `IRI_BASE` (`no_iri_base`), X5 lief nie (eine Kopie:
  vor ihrem Prüfjob), schuldet eine Prüfung oder eine Fundstelle ist ungeprüft (`check_owed`,
  `details.unchecked`; Fundstellen verworfener Aussagen zählen nicht), Verstöße unter den Befunden ohne
  `accept_violations` (`has_violations`, `details.violations`). Dann bekommen Werk
  (`…/work/<land>/<kurztitel>`), Dokument (`…/doc/<land des Werks>/<herausgeber>/<kurztitel des
  Werks>/<fassung>`), Knoten (Pfad ihrer Codes; ein Code wie „S 1“ zählt weiter, `s-<n>` gehört den
  Aussagen) und Aussagen (`<knoten>/s-<n>`, jede Nummer einmal, auch unter einem Knoten, der in einer Kopie
  neu am selben Pfad entstand) ihre IRIs; eine IRI, die ein anderes Werk oder Dokument hält – auch eines,
  das im selben Augenblick festgeschrieben wird –, weist ab (`iri_taken`, `details.iri`). Danach weist die
  Datenbank jede Änderung an den Zeilen des Dokuments ab, nur der Rechtestatus bleibt änderbar. Audit
  `document.freeze` mit Revision und angenommenen Verstößen; die Antwort ist das Dokument.
- Entwurfskopie: `POST /api/v1/documents/{id}/draft-copy` (nur Redaktion/Admin, 201 mit der Kopie)
  öffnet die nächste Revision eines festgeschriebenen Dokuments unter derselben IRI: alle Zeilen mit
  ihren IRIs, Herkunft, Prüfstand und Revisionen, ohne Läufe und Befunde – X5 schuldet ihr eine
  Prüfung (`POST …/check`). Bearbeiten und Festschreiben wie beim ersten Mal; die vorige Revision bleibt
  lesbar. Abgewiesen: kein festgeschriebenes Dokument (409 `not_frozen`), eine spätere Revision ist
  festgeschrieben (`not_latest`), ein Entwurf der IRI ist offen (`draft_open`, `details.document_id`),
  eine Zeile passt nicht mehr zum heutigen Vokabular, etwa ein Knotentyp, den eine spätere Ladung unter
  seiner Funktion herausnahm (`vocabulary_changed`, `details.check`: die Prüfung, an der sie scheitert).
  Audit `document.copy`.
  In der Oberfläche nennt die Dokumentseite unter „Werk und Fassung“ Herausgeber, Fassung, Werk, IRI und
  Revision; bis zum Festschreiben ändern Eigentümer und Redaktion dort Titel, Herausgeber und Fassung (mit IRI
  nur noch den Titel), und die Redaktion setzt das Werk, solange es keines hat – ein bekanntes aus den
  Dokumenten, die sie sieht, oder ein neues mit Titel, Land und Kurztitel; ein Wechsel geht nur über `PATCH
  …/work`. Festgeschrieben wird, was gespeichert ist; ein ungespeicherter Eintrag geht verloren.
  „Festschreiben“ (Redaktion) fragt vorher, mit den Folgen; nennen die Befunde Verstöße, fragt es noch einmal
  mit ihrer Zahl. Was der IRI fehlt, nennt es einzeln, eine ausstehende Prüfung mit dem Weg zum Baum.
  Festgeschrieben steht oben, wann und als welche Revision, dazu für die Redaktion „Als Entwurf kopieren“, das
  die Seite der Kopie öffnet; eine Entwurfskopie nennt ihre Vorlage. Extraktion und Reparatur bietet die Seite
  dort nicht mehr an. Unter „Herkunft“ nennt die Seite Herkunft, Rechte, Lizenz und Quelltyp des Eintrags und wie
  seine Datei geholt wurde; unter „Werk und Fassung“ die übrigen Revisionen derselben IRI. Ein Befund an einem
  Knoten oder einer Aussage führt in den Baum zu dieser Zeile.
- Lexikon prüfen: `GET /api/v1/lexicon/review` nennt der Redaktion (Redaktion/Admin, sonst 403 `not_editor`)
  die Stichprobe der aktiven Recherche-Cues – je Bereich und Regionen ein Zehntel, aufgerundet; dieselben Cues
  ergeben dieselbe Stichprobe (fester Seed), mustert eine Ladung einen aus, rückt in seiner Schicht der nächste
  nach – und jeden anderen entschiedenen: `strata` (je Schicht Cues, Stichprobe, Entscheidungen), `items` (der
  Cue mit Fundstellen der Recherche und seiner Entscheidung, `sampled`), `retired` (Entscheidungen zu Cues, die
  eine Ladung ausmusterte), `labels` (jedes Konzept darin mit seinem deutschen Namen; Klassen und Properties
  des Kerns haben keinen). `POST /api/v1/lexicon/review` entscheidet über einen aktiven Recherche-Cue oder
  einen schon entschiedenen, auch ausgemusterten (`cue`, seine IRI, sonst 404 `no_cue`) – so kommt ein
  verworfener zurück –, eine frühere Entscheidung ersetzt: `decision` `confirmed` mit `strength` (0,5 bis 0,9,
  zwei Stellen) und `evidence` (wo die Redaktion ihn fand) – keine Hochstufung ohne Fundstelle – oder `rejected`
  ohne `strength`; dazu frei `note` (sonst 422). Stärken kommen als Dezimaltext zurück (`"0.7"`, `"0.90"`).
  Audit `lexicon.review`. `applied` sagt, ob die Vokabulare die Entscheidung schon tragen. Zurück in die
  Dateien, in Git Bash oder sh (PowerShell 5.1 schreibt ein BOM oder UTF-16):
  `docker compose exec -T api python -m app.lexicon.export_reviews > ontology/recherche-ergebnisse/entscheidungen.json`
  schreibt jede Entscheidung – auch zu ausgemusterten Cues, ohne Namen und Zeiten –, `python -I
  ontology/werkzeuge/importiere_recherche.py ontology` erzeugt daraus die Länderdateien neu (bestätigte Cues
  `verified` mit der Stärke der Redaktion und ihrer Fundstelle, verworfene nicht mehr; jeder andere bleibt
  bytegleich, außer wo ein neuer Hinweis – unten – denselben Cue gibt), committet lädt
  `python -m app.vocab.load` sie.
- Neue Begriffe prüfen: `GET /api/v1/lexicon/terms` nennt der Redaktion (sonst 403 `not_editor`) jeden
  Begriff, für den X1 im Profil keinen Typ fand (`newTerms`): einmal je Bereich, Regionen (ohne Regionen:
  `DE`) und Wort – gleich geschrieben ohne Rücksicht auf Groß/klein, Leerraum und einen schließenden
  Doppelpunkt –, in der Form, die die Dokumente am häufigsten schreiben, mit der Zahl der Dokumente, den
  vorgeschlagenen Funktionen, den ersten fünf Fundstellen und der Entscheidung (ein Wort, das verglichen mehr
  als 500 Zeichen hat, nennt keine Ebene und steht nicht darin); `held` nennt die aktiven Cues des Bereichs,
  die das Wort schon führen – als Wort oder mit einem Muster, das „<Wort> 1“ von vorn trifft (wie der
  Importer vergleicht), gleich für welche
  Regionen –, die des eigenen Lexikons zuerst (`own`; `by_word`: das Wort selbst, sonst nur ein Muster, das
  beim Importer bloß für seine Ziele zählt); `gone` hält Entscheidungen zu Begriffen, die
  kein Dokument mehr nennt; `labels` wie oben. `POST /api/v1/lexicon/terms` (`sector`, `regions`, `term`)
  entscheidet über einen Begriff, den ein Dokument nennt oder der schon entschieden ist (sonst 404
  `no_term`), eine frühere Entscheidung ersetzt: `decision` `cue` (neuer Hinweis, mit `maps_to` – einem
  Knotentyp des aktiven Profils des Bereichs, sonst 422 `not_a_node_type` – und `role` `pref`, `alt` oder
  `cue`; ein Wort unter vier Zeichen, wie die Dokumente es schreiben, gibt keinen: 422 `too_short`),
  `document` (Besonderheit des Dokuments) oder `error` (falsch erkannt), beide ohne Ziel und Rolle; dazu
  frei `note` – die eines neuen Hinweises geht mit ihm in Git, also kein Dokumenttitel und kein Name darin.
  Audit `lexicon.term`. `applied` sagt bei
  einem neuen Hinweis, ob ein aktiver Cue des Profils ihn mit Wort, Ziel, Rolle und genau diesen Regionen
  schon trägt. Der Export oben schreibt die neuen Hinweise mit (`new_terms`, ohne Dokument und Namen); der
  Importer legt jeden ungeprüft mit Stärke 0,7 in die Länderdatei seines Bereichs – außer einem Wort des
  eigenen Lexikons, einem unter vier Zeichen und einem mit unbekanntem Ziel oder Land, die er zählt.
  In der Oberfläche steht beides unter „Lexikon“ (`/lexikon`, nur für Redaktion und Admin): die Stichprobe mit
  ihren Schichten und die neuen Begriffe mit ihren Fundstellen, je Eintrag die Entscheidung und ein Formular
  dafür; ein neuer Hinweis wählt einen Knotentyp aus dem Formular des Bereichs (`/profiles/{sector}/form`),
  und die Seite sagt vorher, wo der Import ihn übergehen würde. Eine nicht gespeicherte Entscheidung wird vor
  dem Verlassen erfragt. Ins Lexikon kommt alles erst mit Export und Import oben.
- Abbrechen: `POST /api/v1/jobs/{id}/cancel` (Eigentümer des Jobs oder Admin, in der Oberfläche
  der Knopf „Abbrechen“ an jedem Auftrag). Ein wartender Job endet sofort, ein laufender beim
  nächsten Herzschlag seines Workers (alle `JOB_LEASE_S`/3); hält der Handler dann nicht an,
  endet der Job nach `CANCEL_WAIT_S` (5 s, bei kürzerer Lease einem Drittel von ihr) trotzdem
  `cancelled`. Was der Handler danach noch schreibt, findet seine Lease nicht mehr, und eine
  Modellanfrage – auch eine Wiederholung – reserviert er nicht mehr (`check_lease` im Zähler).
  Ein Worker, der gar nicht mehr schlägt,
  endet über die Prüfung abgelaufener Leases ebenso `cancelled`.
- Extraktion (X1–X5): Der Job `extract.run` (`{"document_id": …}`) bestimmt für ein Dokument per
  Sprachmodell das Dokumentprofil (Titel, Typ, Geltung,
  Spezifikationen, eigene Begriffe), baut das Gerüst ohne Modell aus Verzeichnis, Layout und
  Lexikon, lässt nur die Überschriften ohne starkes Muster vom Modell einordnen und teilt den
  Text in Arbeitspakete (X2). X3 liest mit einer Anfrage die Rahmenteile – Kompetenz- und
  Niveaumodelle, Operatoren, Querschnittslegende und Regeln (Tabelle `frame_part`, Migration 0015) –
  und die Ziele und Aufträge der Rahmenabschnitte als Aussagen an deren Knoten. X4 liest je
  Arbeitspaket mit Aussagen eine Anfrage, hinter demselben Präfix (Dokument, Profil, Auswahllisten
  aus X3, Cache-Haltepunkt danach), wo das Dokument ins Kontextfenster passt, sonst hinter dem
  Fenster um den Abschnitt des Pakets, bis zu
  `EXTRACT_CONCURRENCY` (Standard 4, 1–16; nie mehr als `DB_POOL_MAX_SIZE` − 1) zugleich. Jedes
  Paket wird für sich geschrieben, sobald es beantwortet ist (`extraction_unit`, Migration 0019):
  Wortlautfelder nur, wenn sie in den Blöcken der Aussage stehen, Herkunft Modell, Prüfstand
  vorgeschlagen. X5 prüft ohne Modell: jeden noch ungeprüften Wortlaut (Aussage, Überschrift
  eines Knotens) gegen den Text der Blöcke seines Ankers – wörtlich, über Leerraum hinweg,
  normalisiert, mit Auslassung oder unscharf, wie die Ankersuche der alten App; die Fundart, bei
  unscharfen Treffern ihr Wert, der Text an der Stelle (`quote`) und die Zeichenspanne stehen dann
  am Anker –, die Plausibilität (Überschrift als Aussage, Arbeitspaket ohne Aussagen, Regelgrenzen,
  zurückgezogene Werte) und den Kern-Graphen des Dokuments gegen die SHACL-Formen des
  Curriculum-Kerns und der Profile, in einem eigenen Prozess mit der Frist `SHACL_TIMEOUT_S`
  (Standard 300 s, 10–1800). Die Befunde stehen in `validation_finding` (Verstoß, Warnung,
  Hinweis): ein Wortlaut, den seine Blöcke nicht enthalten, ist ein Verstoß, eine überschrittene
  Frist der Verstoß `x5.shacl_timeout`; X5 endet in beiden Fällen fertig. Ein neuer Start der
  Extraktion prüft ein Dokument, dessen X5 fertig ist, nicht erneut; das tut erst eine Reparatur,
  die Arbeitspakete neu schreibt, dann mit der geltenden Frist. Stirbt der Prüfprozess
  (Speichermangel) oder bricht
  er ab, scheitert der Lauf (`ShaclCrashed`), und der Job wird bis zu seiner Versuchsgrenze
  wiederholt (`handler_error`). Jede Stufe jedes Versuchs ist ein
  eigener Lauf (`extraction_run`); X1 bis X3 schreiben ihr Ergebnis auf einmal, X4 je Paket, X5
  erst die Anker, dann Befunde und Ende zusammen. Ein neuer Versuch oder ein neuer Job auf
  demselben Dokument macht nach der letzten fertigen Stufe weiter, in X4 mit den offenen Paketen;
  zwei gleichzeitige schreiben jede Stufe und jedes Paket einmal.
  Fortschritt: `extract_profile`, `extract_outline`, `extract_segments`, `extract_frame`,
  `extract_statements` (fertig/gesamt), `check_document`. Endet mit
  `budget_exhausted` (Budget aufgebraucht: in X4 beginnt kein Paket mehr, die laufenden werden
  fertig, Fertiges bleibt), `model_unanswered` (keine Antwort im Schema; in X4 bleiben nur solche
  Pakete offen), `model_not_configured` (kein `OPENAI_API_KEY` im Worker), `prefix_too_long`
  (nicht einmal ein Abschnitt passt neben Titelei und Rahmenteilen ins Kontextfenster),
  `document_gone` oder `document_has_tree` (Knoten oder Spezifikationen stehen schon, aber keine
  Extraktion schrieb sie). Der Worker startet auch ohne
  Schlüssel; das Modell entsteht beim ersten Job, der es braucht.
- Reparatur (X6): Der Job `extract.repair` (`{"document_id": …}`) fragt nur die Arbeitspakete
  erneut, deren Aussagen X5 oder das Lesen der Antwort beanstandet hat – ein Verstoß an einer
  Aussage, die X4 oder X6 schrieb und die seither niemand angefasst hat, oder eine Warnung oder ein
  Verstoß beim Lesen, der das Paket nennt (außer `*.pattern_timeout`) –, je Job einmal, je Paket
  höchstens zweimal (`extraction_unit.repairs`, Migration 0020). Hinweise, Warnungen der
  SHACL-Prüfung und die übrigen Befunde an Knoten oder am Dokument (etwa `x5.shacl_timeout`) sind
  kein Anlass. Die Frage ist die von X4 hinter demselben Präfix, dazu die Befunde in Worten – mit
  dem Block, Wert oder Schlüssel, der falsch war – und die Wortlaute, die die Redaktion hält oder
  verworfen hat (Promptversion `x6-repair/1`). Die Antwort ersetzt die unangetasteten Aussagen des
  Pakets; bestätigte, verworfene und von Hand geschriebene bleiben und kommen nicht doppelt, ein
  Verweis auf Inhalt geht dann auf die gehaltene Aussage. Eine Antwort außerhalb des Schemas lässt
  das Paket, wie es war, zählt aber als Reparatur (Warnung `x6.unanswered`), ebenso eine Antwort
  ohne Aussage für ein Paket, das welche hat (Warnung `x6.empty_answer`). Danach prüft X5 das
  Dokument erneut, seine Befunde ersetzen die des letzten X5 – auch wenn das Budget X6 beendet hat,
  bevor der Job mit `budget_exhausted` endet. Ein neuer Versuch fragt kein Paket, das der Job schon
  gefragt hat. Endet eine Reparatur, bevor X5 geprüft hat, was sie schrieb (abgebrochen, Versuche
  aufgebraucht), prüft die nächste Extraktion („Extraktion fortsetzen“) oder Reparatur das
  Dokument erneut. Ist nichts mehr zu reparieren, fragt der Job kein Modell. Fortschritt `repair_units` (fertig/gesamt); endet
  mit `document_not_checked`, wo X5 noch aussteht (bei einem Import: wo `IM` aussteht). In der Oberfläche bietet der Abschnitt
  „Befunde“ des Dokuments dem Eigentümer den Knopf „Reparieren“ an; ihr Stand steht unter
  „Extraktion“.
- Prüfung nach der Redaktion (X5): Der Job `extract.check` (`{"document_id": …}`) prüft ein
  Dokument erneut, nachdem die Redaktion es geändert hat; seine Befunde ersetzen die des letzten
  X5. Verworfene Aussagen prüft X5 nicht und der Kern-Export enthält sie nicht. Fortschritt
  `check_document`; endet mit `document_not_checked`, wo X5 noch aussteht (ein Import: wo `IM` aussteht); ein neuer Versuch prüft
  nicht doppelt.
- Erster Admin: `python -m app.bootstrap NAME` gibt das Token einmal auf stdout aus. Interaktiv
  ausführen (`docker compose run`, `kubectl exec -it`), nicht als Job, dessen Ausgabe ein
  Log-System sammelt. Exit-Code 0: angelegt; 2: es gibt schon einen Admin, der sich anmelden
  kann; 1: Fehler. Weitere Konten und Tokens legt ein Admin über `/api/v1/accounts` an.
  Lesen darf sie nur ein Admin: `GET /api/v1/accounts?limit=50&offset=0` (nach Namen, mit
  `total`), `GET /api/v1/accounts/{id}` mit Rollen und Sperre, `GET /api/v1/accounts/{id}/keys`
  mit Bezeichnung, Anlage, letzter Nutzung und Widerruf – nie Token oder Hash; ein unbekanntes
  Konto ist 404 `no_account`.
- `PUBLIC_ACCESS` (`off` | `lookup` | `search`, Standard `off`): was Besucher ohne Token dürfen.
  Das Sprachmodell braucht immer ein Token.
- `MAX_UPLOAD_MB` (Standard 50, höchstens 500): die größte Datei, die ein Upload oder ein
  URL-Import annimmt; größere weist der Upload mit 413 `file_too_large` ab, einen Body über
  `MAX_UPLOAD_MB` + 1 MiB schon vor dem Lesen mit 413 `content_too_large`. Ein DOCX darf
  entpackt höchstens 256 MiB in 5.000 Teilen halten (`archive_too_large`). Was ein Upload in
  `/tmp` und im Arbeitsspeicher braucht, steht in `docs/uebergabe/konfiguration.md`.
- `UPLOADS_PER_MINUTE`, `URL_IMPORTS_PER_MINUTE` und `CONVERSIONS_PER_MINUTE` (Standard je 20):
  Uploads, URL-Importe bzw. gestartete Konvertierungen je Konto und Minute, gezählt in
  PostgreSQL für alle Replicas; darüber 429 mit `Retry-After`. Eine Konvertierung, die wartet
  oder fertig ist, noch einmal anzufragen, startet und zählt nichts.
- `FETCH_USER_AGENT`: so stellen sich URL-Import und Prüfjob den Servern vor. Vorn steht das
  Produktkürzel, unter dem robots.txt uns kennt (`Curricarta`), dahinter, wo die
  Betreiber zu erreichen sind – hier den eigenen Kontakt eintragen (öffentliche Seite oder
  Postfach), denn der Standard nennt nur das Repository. Druckbares ASCII, ohne Leerzeichen am
  Ende. Der Prüfjob sendet fremden Hosts keine Trace-Header. `CHECK_HOST_INTERVAL_S`
  (Standard 2, mindestens 0,5): der kleinste Abstand zweier Anfragen des Prüfjobs an einen
  Host, über alle Worker.
- `THIRD_PARTY_MARKDOWN` (`hidden` | `accounts` | `public`, Standard `hidden`): wer außer
  Redaktion und Admin die Datei eines Registereintrags ohne Eigentümer (Saat, Recherche)
  bekommt, später auch seine Blöcke und sein Markdown: niemand, jedes Konto oder auch Besucher,
  diese nur bei `PUBLIC_ACCESS` ≠ `off`. Ein Upload bleibt bei seinem Konto.
- `FORWARDED_ALLOW_IPS` (Standard `127.0.0.1,::1`): Adressen oder Netze der Proxys, deren
  `X-Forwarded-For` die Client-Adresse nennt; nie `*`, sonst wählt jeder Client seine Adresse
  selbst und umgeht das Limit. Aus demselben Grund wird ein Netz `/0` abgewiesen, und ein Netz
  mit gesetzten Hostbits (`10.42.1.5/16`) ebenso, statt still erweitert zu werden.
- `AUTH_FAILURE_LIMIT` (Standard 10) Fehlversuche je IPv4-Adresse oder IPv6-/64 innerhalb
  `AUTH_FAILURE_WINDOW_S` (Standard 900 s), danach 429. Gezählt wird nur ein Header in Tokenform;
  jeder andere bekommt 401, ungezählt. Ein gültiges Token kommt immer durch.
- `DB_POOL_TIMEOUT_S` (Standard 5 s): so lange wartet eine Anfrage auf eine Verbindung, dann
  antwortet sie 503 mit `Retry-After`.

Worker: `JOB_LEASE_S` (Standard 60 s; ein Worker ohne Lebenszeichen verliert seinen Job danach),
`JOB_POLL_S` (Standard 1 s), `JOB_SHUTDOWN_GRACE_S` (Standard 20 s): Nach SIGTERM darf der
laufende Job so lange zu Ende laufen, dann geht er unverbraucht an den nächsten Worker zurück.
Mindestens 5 s unter der Frist des Deployments halten (Kubernetes: 30 s): Nach der Frist bekommt
der Handler noch bis zu 2 s zum Aufräumen, erst dann wird der Job zurückgegeben.

Sprachmodell (OpenAI-kompatibel): `OPENAI_API_KEY` (auch `OPENAI_API_KEY_FILE`; nur sichtbare
ASCII-Zeichen), `OPENAI_BASE_URL` (Standard `https://api.openai.com/v1`; `http(s)://Host[:Port][/Pfad]`
ohne Nutzer, Query oder Fragment, `http` für ein Gateway im Cluster), `OPENAI_MODEL` (Standard
`gpt-6-luna`), `LLM_PROVIDER` (`openai` spricht die Responses-API, `openai-compatible` Chat
Completions), `OPENAI_REASONING_EFFORT` und `OPENAI_TEXT_VERBOSITY` (Standard `low`). Nimmt das
Modell den Aufwand laut seinem Profil nicht an (gpt-6-luna kein `minimal`), starten API und
Worker nicht. Ohne Schlüssel starten beide, nur Aufrufe des Modells scheitern.
`LLM_MAX_OUTPUT_TOKENS` (Standard 16.000, mindestens 1.000) begrenzt die Ausgabe jeder Anfrage,
Reasoning eingeschlossen. Lässt sie im Kontextfenster neben den 17.000 Token, die eine Anfrage
außer dem Dokument braucht, keinen Platz, starten API und Worker nicht. Token zählt der Dienst
lokal mit tiktoken (`o200k_base`): Die Datei liegt mit ihrem SHA-256 in `backend/app/llm/` und
wird nie aus dem Netz geladen. Fehlt sie oder stimmt ihr Hash nicht, starten API und Worker nicht.

Kosten des Modells: Ein Konto ohne Quote darf nichts verbrauchen, auch ein Admin nicht.
- Ein Admin setzt die Quote mit `PUT /api/v1/accounts/{id}/quota`
  (`{"token_limit": …, "page_limit": …}`). Beide Grenzen müssen ausdrücklich genannt werden,
  `null` heißt unbegrenzt. Die Änderung wird als `account.quota` protokolliert.
- `GET /api/v1/me/usage` zeigt dem Konto Grenze, Verbrauch (davon geschätzt), Reserviertes und
  den Rest.
- Die Quote zählt Token nach ihrem Preis, gemessen an einer ungecachten Eingabe. Eine Eingabe aus
  dem Cache zählt `LLM_CACHED_INPUT_WEIGHT`, eine Ausgabe `LLM_OUTPUT_WEIGHT`. Ohne Einstellung
  gelten die Preise des Modells: für gpt-6-luna 0,1 und 5, für ein unbekanntes Modell 1 und 1.
  Jede Reservierung und Buchung speichert ihre Gewichte. Eine spätere Änderung bucht also nichts um;
  was vor den Gewichten gebucht wurde, zählt wie zuvor.
- Bestehende Quoten zählen ab jetzt gewichtete Token, und Betreiber sollten sie anpassen. Eine für
  rohe Token bemessene Grenze hält bei gpt-6-luna etwa zwei Drittel so viele gleichzeitige
  X4-Anfragen. Zugleich reicht sie für gut das Fünffache an Arbeit, weil der Großteil der Eingabe aus
  dem Cache kommt und zu 0,1 zählt (die Abnahme: 48,8 Mio. rohe, etwa 8,8 Mio. gewichtete Token).
- Während eines Updates summieren Worker des alten Release roh. Was ihr Aufräumen bucht, zählt jedes
  Token gleich. Das Fenster ist kurz.
- Vor jeder Anfrage reserviert der Aufruf die gezählte Eingabe (plus 10 %) ganz, denn vor dem Senden
  weiß niemand, was der Cache hält. Dazu kommt `LLM_MAX_OUTPUT_TOKENS` mal dem Ausgabegewicht. In der
  Abnahme hielt eine X4-Anfrage bei gpt-6-luna so im Mittel rund 110 000 + 80 000 Token (zuvor
  126 000), gebucht wurden rund 16 500 (zuvor 101 000). Wer nahe an der Grenze arbeitet, senkt
  `LLM_MAX_OUTPUT_TOKENS`. Danach ersetzt die gemeldete Nutzung die Reservierung. Als Verbrauch
  gebucht und als geschätzt gekennzeichnet wird die Reservierung einer gesendeten Anfrage ohne
  Antwort, einer Antwort ohne Nutzungsangabe und einer Antwort, die kein Modell lesen konnte. Die
  letzte lässt den Aufruf scheitern. Eine Anfrage, die nie hinausging (keine Verbindung), kostet
  nichts. In X4 hält ein Job bis zu `EXTRACT_CONCURRENCY` Reservierungen zugleich; reicht der Rest
  für die nächste nicht, beginnt kein Paket mehr.
- Bei 429, 5xx und einem nicht erreichten Anbieter wartet der Aufruf selbst, höchstens zweimal:
  so lange wie `Retry-After`, sonst 20 bzw. 40 s, nie länger als 60 s. Bei `insufficient_quota`
  wartet er nicht.
- Die Rohantworten legt er vor der Auswertung unter `runs/<Lauf>/<Stufe>/<n>.json` im
  Objektspeicher ab.
- Schätzung vor einem Lauf: `docker compose -f deploy/docker-compose.yml exec worker python -m
  app.pipeline.estimate <Dokument-ID>` zählt jede Anfrage, die die Stufen dem Dokument noch
  schulden, so wie der Aufruf sie vor dem Senden reserviert. Er fragt nichts und schreibt nichts.
  Ausgabe ist JSON: je Zweck (`x1.profile`, `x1.outline`, `x3.frame`, `x4.unit`) die Anfragen, die
  Eingabe mit dem Zuschlag von 10 %, ihr Anteil vor dem Cache-Haltepunkt (`shared_tokens`, ohne
  Zuschlag, ab der zweiten Anfrage aus dem Cache) und die Obergrenze der Antworten. Dazu kommen:
  - `reserved`: was der Aufruf für diese Anfragen reserviert, in rohen Token;
  - `charged_at_most`: das Höchste, was die Quote für sie halten muss, nach den Gewichten (`weights`).
  Für den ganzen Lauf gelten beide nur, wo die Zählung genau ist und `unreckoned` leer ist.
  - Vor X1 rechnet er X1 und nennt das Präfix von X3 (`prefix_tokens`, noch ohne Profil und Baum,
    also zu niedrig). Die Gliederung zählt er ohne die Spezifikationen, die X1 findet, und nach dem
    Typ der Redaktion oder ohne Typ. Das kann höher oder niedriger liegen als der Lauf.
  - Vor X1 schätzt er die Pakete (`guessed_units`). Dazu schneidet er das Gerüst, das X1 liest, wie
    X2 einen Baum schneidet. X1 kann Teile zu Rahmen- oder Nebenteilen machen, deshalb ist das eine
    obere Richtgröße: In den Abnahme-Dokumenten schnitt X2 das 0,5- bis 1-Fache.
  - Ist X1 allein fertig, zählt er die Pakete, die X4 fragen wird (`units`).
  - Nach X2 rechnet er X3 und jedes offene Paket von X4. Solange X3 offen ist, fehlen dem Präfix von
    X4 die Wahllisten von X3; das liegt etwas zu niedrig.
  - Was er nicht rechnen kann, nennt `unreckoned` mit Grund: `before_x2`; `prefix_too_long` oder
    `document_has_tree`, wo die Stufe den Job beendet, bevor sie fragt.
  - Gerechnet wird mit dem Modell der Einstellungen, ohne dessen Schlüssel. Wiederholungen nach
    einer Antwort außer Form kommen hinzu.
  - Geldbeträge nennt die App nicht, nur die Gewichte. Exit-Code 1: kein solches Dokument oder ein
    anderer Fehler (die Meldung steht auf stderr); 2: falscher Aufruf.
- Einen Modelljob darf ein Konto nur starten, solange es seine Grenze nicht verbraucht hat, sonst
  403 `no_budget`; was laufende Aufrufe reserviert halten, zählt dabei nicht. Höchstens
  `MAX_JOBS_IN_FLIGHT` (Standard 20) dürfen warten oder laufen, sonst 429 `too_many_jobs` mit
  `Retry-After: 60`. Höchstens `MODEL_STARTS_PER_MINUTE` (Standard 10) Starts je Minute, sonst 429
  `too_many_starts`.
- Modelljob ist `extract.run`. Endet ein Versuch eines Jobs (fertig, gescheitert, abgebrochen,
  zurückgegeben), bucht dieselbe Transaktion seine offenen Reservierungen als geschätzten
  Verbrauch. Starb ein Worker oder verlor er die Lease, bucht sie die Prüfung abgelaufener Leases:
  die Reservierungen jedes Jobs, der gerade nicht läuft.
- Metriken: `curricarta_llm_requests_total`, `curricarta_llm_tokens_total`, `curricarta_usage_reservations_total`.

Objektspeicher: `STORAGE_BACKEND` (`fs` | `s3`, Standard `fs`). Mit `fs` braucht der Speicher
`STORAGE_DIR` (für Entwicklung und einen einzelnen Knoten); im Cluster `s3` mit `S3_BUCKET`,
`S3_ENDPOINT_URL` (leer für AWS selbst), `S3_REGION` (Standard `us-east-1`) und den Schlüsseln
`S3_ACCESS_KEY`/`S3_SECRET_KEY` (beide oder keiner, auch als `*_FILE`; ohne sie nimmt boto3
seine Standardkette: `AWS_*`-Variablen, Web-Identity, die Rolle der Instanz). Wohin der Dienst
geht, sagt nur `S3_ENDPOINT_URL`: `AWS_ENDPOINT_URL` und ein `endpoint_url` in `~/.aws/config`
übergeht er. Beim Öffnen (beim Start von API und Worker) fragt der
Speicher einmal nach dem Bucket und bricht ab, wenn es ihn nicht gibt.
`python -m app.core.storage_bucket` legt den Bucket an, wo die Umgebung keinen mitbringt
(Compose).

### Compose

`deploy/docker-compose.yml` startet alles auf einem Rechner: PostgreSQL mit pgvector, MinIO
(Chainguard-Build), die einmaligen Schritte Bucket, Migration und Vokabular, je zwei API- und
Worker-Replicas und den Webserver davor. Vom Wurzelverzeichnis aus:

```bash
python deploy/make-secrets.py
(cd frontend && npm ci && npm run build)
docker compose -f deploy/docker-compose.yml up -d --build
```

Die App antwortet unter `http://127.0.0.1:18080`; sonst ist nichts am Host veröffentlicht. Der
Webserver reicht `/api` und die Spec an die API weiter (`deploy/nginx-api.conf`, nur in Compose
eingebunden); das Web-Image selbst antwortet dort mit 404, im Cluster routet der Ingress.
`deploy/make-secrets.py` schreibt die Geheimnisse als Dateien nach `deploy/secrets/` (nicht im
Repository, für alle Nutzer des Rechners lesbar, weil die Container unter anderen Nutzern
laufen; nur für Entwicklung). Ein vorhandenes Geheimnis bleibt stehen. Der erste Admin:
`docker compose -f deploy/docker-compose.yml run --rm migrate python -m app.bootstrap NAME`.
`down` hält die Daten, `down -v` löscht Datenbank und Objekte dieses Projekts (`curricarta`).
Veröffentlichte Images liegen in GitHubs Container-Registry (`ghcr.io/<owner>/curricarta`, `…-web`,
`…-convert`), getaggt `X.Y.Z` je Versions-Tag und `sha-<12 Zeichen des Commits>` je Lauf von
`.github/workflows/release.yml`, nie `latest`.

Konverter-Image (Paket 3b): dasselbe Image mit Docling, EasyOCR und torch ohne CUDA (rund 2 GB),
`docker build -f deploy/api.Dockerfile --build-arg VENV=convert -t curricarta-convert:local .`. Ohne Argument
entsteht weiter das API-Image ohne diese Pakete. Die Modelle liegen nicht im Image, sondern in einem
Volume unter `/models`, zusammen rund 600 MB: Layout, TableFormer und EasyOCR mit Deutsch.
`python -m app.conversion.fetch_models /models` lädt sie einmal im Konverter-Image (Hugging Face,
GitHub) und prüft jede Datei an Größe und SHA-256 (`app/conversion/models.py`); Exit-Code 0, 1 bei
einer Datei, die nicht stimmt, 2 bei falschem Aufruf. Zur Laufzeit fragt kein Teil Hugging Face
(`HF_HUB_OFFLINE=1`). Docling liest je acht Seiten auf einmal (rund 4 s je Seite auf vier Kernen,
Spitze rund 1,8 GB; gemessen mit Docling 2.117, für 2.150 nicht neu gemessen).

Texterkennung (Paket 3b-2): Seiten ohne Textebene liest Docling mit EasyOCR (Deutsch) in einer eigenen
Pipeline, die erst lädt, wenn eine Datei solche Seiten hat; sie liest die Bilder der Seite und lässt eine
vorhandene Textebene stehen. Rund 16 s je Seite auf vier Kernen (gemessen 14–30 s), Spitze bis rund 5 GB
(gemessen 2,5–4,9 GB). 200 solcher Seiten brauchen rund eine Stunde: Der Konverter braucht dafür
`CONVERT_TIMEOUT_S=3600` (die Compose-Datei setzt es); mit dem Standard von 900 s enden mehr als rund 50
gescannte Seiten mit `timed_out`, und die übrigen Seiten einer Datei kommen hinzu. EasyOCR liefert Zeilen ohne
Schrift und Größe: Die Wörter teilen die Zeile nach Zeichen, die Größe der Zeile ist der Median der x-Höhen
ihrer Wörter im Seitenbild (`app/conversion/ocr_words.py`; Wort für Wort, da ein leicht schräger Scan eine
ganze Zeile zu hoch misst), fett ist keines. Eine Zeile nur aus Großbuchstaben misst ihre Versalhöhe und gilt
so als größer gesetzt, wie eine Überschrift in Versalien; eine Zeile ohne Buchstaben oder ohne messbare Tinte
nimmt das Maß ihrer Box. Die Umwandlung meldet die so gelesenen Seiten als Befund `ocr_read` mit dem Mittel
der Zeilensicherheit auf der unsichersten Seite. EasyOCR legt beim Start
einen Ordner an; das Image setzt ihn auf das tmpfs (`EASYOCR_MODULE_PATH=/tmp/easyocr`), da der Dienstnutzer
kein Zuhause hat und die Wurzel schreibgeschützt ist.

DOCX und HTML (Paket 3b-3): Docling liest sie ohne Modell und ohne Seiten in Bruchteilen einer Sekunde
(`app/conversion/docling_flow.py`). Gelesen wird nur der Rumpf – Kopf- und Fußzeilen eines DOCX, Navigation,
Kopf und Fuß einer HTML-Seite nicht –: Titel, Überschriften mit Ebene, Absätze mit Fett und Kursiv (ein
Absatz, ein Listenpunkt oder eine Überschrift, die Docling an fett gesetzten Wörtern teilt, wird wieder einer),
Listenpunkte mit ihrem Zeichen (eine nummerierte HTML-Liste gezählt), Tabellen mit Kopfzeile; ein Bild nicht,
seine Bildunterschrift schon. Grenzen: Text einer HTML-Seite vor ihrer ersten Überschrift liest Docling als
Kopf der Seite, er fehlt in den Blöcken (in einem DOCX nicht); ein Wort, dessen Teile verschieden gesetzt sind
(`Schüler<i>innen</i>`), steht getrennt, da Docling die Teile ohne ihre Leerzeichen übergibt. Die
Blöcke haben keinen Platz auf einer Seite (`bbox` null) und eine Größe aus der Struktur: Titel 22, Überschriften
der Ebenen 1–4 20/18/16/14, tiefere 13, Text 11; Überschriften gelten als fett. Seiten macht die Umwandlung
selbst (`app/conversion/flow.py`): Abschnitte von rund 3000 Zeichen, ohne einen Absatz zu teilen, ohne
gedruckte Seitenzahl; das meldet der Befund `flow_pages`. Eine Tabelle läuft zeilenweise über die Seiten
wie eine über Seiten verbundene Tabelle eines PDFs, ihre Zellen auf ihren Seiten; eine Zelle wiegt ihre Zeichen
und eins, auch eine leere. Diese Seiten zählen wie die eines PDFs für `MAX_PDF_PAGES`, `too_dense` (ein Absatz
oder eine Tabellenzeile über 100.000 Zeichen) und das Seitenkontingent; ein Anker des Kern-Exports nennt sie
als `cur:pageStart` (offene Frage: die Form verlangt eine Seite, der Kern nennt sie „PDF-Seite“). Text, den die Datei
ihren Lesern verbirgt – der klassische Weg, ein Modell zu lenken –, kommt vorher heraus und wird gezählt
(`text_dropped` mit Grund `hidden` oder `tiny`, ohne Seiten): im DOCX ausgeblendete Läufe und solche unter 1 pt,
nach Lauf, Zeichen- und Absatzvorlage samt Erbe und Dokumentvorgabe, im Haupttext, in Fuß- und Endnoten, die
Teile so gefunden, wie Word sie über die Beziehungen des Pakets findet (`app/conversion/docx_hidden.py`); in
HTML Elemente mit `hidden` oder `aria-hidden`, `<template>`, ein nicht geöffneter `<dialog>` (ein Hinweis, den
erst ein Klick zeigt), ein eigener Stil mit `display:none`, `visibility:hidden`, Schriftgröße oder Deckkraft 0
und Klassen, die eine Regel eines `<style>`-Blocks für den Bildschirm so verbirgt – auch in `@media screen`,
nach dem letzten Wort und `!important` (`app/conversion/html_hidden.py`, `html_styles.py`; Docling überspringt
sie dann); eine Deckkraft unter 0,1 und eine Schrift unter 1 px oder 1 pt zählen wie 0. Ein Element mit
Schriftgröße 0 oder unsichtbar verbirgt seinen Text und den der Elemente darin, außer wo eines sich wieder
sichtbar setzt; eine relative Größe (`1em`, `100%`, `inherit`) erbt die 0. Doclings Parser (bs4 über
html.parser) baut eine Seite anders als ein Browser – ein `<div/>` schließt er sofort, offen gelassene Absätze,
Listenpunkte und Zellen beendet er nicht, ein Endtag außerhalb seines Bereichs schließt bei ihm doch, SVG und
MathML liest er wie HTML –, und darüber kam verborgener Text durch. Die Umwandlung baut die Seite deshalb mit
der Baumkonstruktion des HTML-Standards (html5rdf, die von rdflib schon mitgebrachte Fassung von html5lib;
`app/conversion/html_tree.py`), lässt das Verborgene weg – auch, was kein Browser darstellt: Ersatzinhalt von
Frames, Video, Audio und Canvas, `<datalist>`, `<rp>`, Titel und Definitionen von Zeichnungen, Annotationen von
Formeln – und schreibt den Rest neu, jedes Element mit seinem Endtag, jedes Attribut einmal, ohne Stile,
`aria-hidden`, Feldnamen und Passwörter, ohne Skripte, Kommentare und Angaben einer anderen Kodierung, in UTF-8
mit Byte-Order-Mark; Docling liest diesen Baum. Zwei Lücken von html5lib schließt die Umwandlung selbst:
Der Inhalt eines `<template>` fällt vor dem Bauen weg (gezählt), und die Seite wird wie im Browser mit
Skripten gebaut, ein `<noscript>` ist also Text, der wegfällt. Zeichen einer Zeichnung außerhalb ihrer
Textelemente und ein MathML-`<mphantom>` gelten als verborgen, `<xmp>` wird als `<pre>` geschrieben. Unter einem unsichtbaren Element fallen auch Bilder und
Felder weg, deren Alternativtext oder Wert Docling als Text läse. Eine Seite, die tiefer als 512 Ebenen schachtelt,
endet mit `unreadable` (Doclings Lesen scheitert wenig tiefer). Nicht erkannt werden Text in Hintergrundfarbe, aus dem Bild geschobener,
von einem verlinkten Stylesheet verborgener und für Screenreader gedachter (`sr-only`), im DOCX das Verbergen
durch eine Tabellenvorlage, und arabischer oder hebräischer Text ohne Markierung als komplexe Schrift wird
nach `w:sz` statt `w:szCs` bemessen. Ein DOCX in Strict Office Open XML endet mit `unreadable` (Docling liest
es mit umgeschriebenen Namensräumen, die die Bereinigung nicht sieht). Ein DOCX ohne Hauptteil, mit Dokumenttyp oder Entitäten, die Word nie schreibt, und
eine HTML-Seite, die Docling nicht ganz liest, enden mit `unreadable`. Eine HTML-Seite lädt nichts nach: keine Bilder,
Stylesheets oder Frames, von fern wie vom Datenträger, und sie wird nicht gerendert.
Eine per Adresse geholte Seite, deren Adresse keinen Dateityp nennt (`…/fachlehrplan/realschule/10/biologie`,
`index.php`), gilt als HTML-Seite, wo der Server `text/html` sagt und sie in UTF-8 steht (`answer_name` in
`app/sources/filetype.py`); Endungen von Seitenskripten (`.php`, `.aspx` …) nennen keinen Typ. Eine Adresse, die
einen anderen Typ nennt – eine PDF, ein `.doc` – und eine Seite liefert oder auf eine ohne Typ weiterleitet (eine
Anmeldung, eine Fehlerseite), bleibt `unsupported_type`; leitet sie auf eine `.html`-Adresse weiter, gilt diese.

Die Docling-Tests (`tests/conversion/test_docling_e2e.py`) laufen nur, wo Docling und die Modelle liegen,
und werden sonst übersprungen – mit `CURRICARTA_REQUIRE_DOCLING=1` scheitern sie stattdessen.
Der Workflow `.github/workflows/converter.yml` baut das Image, holt die Modelle und startet den Dienst mit
dem Konverter wie unten beschrieben (der Block wörtlich) und führt diese Tests im Image aus, ohne Netz und
mit schreibgeschützter Wurzel. Er läuft auf main und in Pull Requests, wo sich ändert, woraus der Konverter
gebaut wird oder was er ausführt (Pfadfilter in der Datei), sonst von Hand; jeder Lauf lädt rund 2 GB
Pakete und 600 MB Modelle.

In Compose bringt `deploy/docker-compose.converter.yml`, über die Hauptdatei gelegt, den Dienst
`converter` (Worker des Konverter-Images mit `WORKER_KINDS=source.convert_docling`,
`CONVERT_TIMEOUT_S=3600`, Modelle schreibgeschützt aus dem Volume `models`) und lässt die API Docling
zuerst anbieten (`CONVERSION_ENGINES=docling,pdfplumber`); ohne die Datei bietet sie nur pdfplumber an,
und kein Docling-Job wartet auf einen Worker, den es nicht gibt. Die API startet erst, wenn der
Konverter gesund ist (`depends_on … service_healthy`): Fehlen seine Modelle, endet er beim Start, und `up`
bricht ab, statt eine API anzubieten, deren Docling-Aufträge niemand nimmt – ohne gesunden Konverter
startet so auch pdfplumber nicht, die Datei ist dann wegzulassen. Einmalig bauen und die Modelle holen,
dann starten:

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.converter.yml build converter
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.converter.yml run --rm models
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.converter.yml up -d
```

Der Dienst `models` (Profil `models`, startet nie mit `up`) ist der einzige, der Hugging Face fragen
darf (`HF_HUB_OFFLINE=0`); er schreibt dessen Verwaltungsdateien auf das tmpfs (`HF_HOME=/tmp/huggingface`,
ohne hf-xet), da die Wurzel schreibgeschützt ist und der Dienstnutzer kein Zuhause hat. Läuft er erneut,
prüft er nur (Größe und SHA-256) und lädt, was fehlt oder abweicht.
