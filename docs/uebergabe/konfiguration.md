# Konfiguration

[Antworten für das IT-Team](anforderungen.md) · Stand 19.11.2026 (Betrieb)

Der Dienst liest seine Einstellungen beim Start aus Umgebungsvariablen; API und Worker lesen
dieselben. Ein Geheimnis kann stattdessen aus der Datei kommen, die `<NAME>_FILE` nennt
(Kubernetes- oder Docker-Secret); die Datei gewinnt dann. Fehlermeldungen nennen nie einen Wert.
Ohne Vorgabe („Pflicht") startet der Dienst nicht; „Pflicht bei …" und „Pflicht für …" gelten
nur unter dieser Bedingung bzw. für diesen Teil. Ein Muster ist ein regulärer Ausdruck, dem der
ganze Wert genügen muss; die Endpunkte (`S3_ENDPOINT_URL`, `OPENAI_BASE_URL`) nehmen zudem keinen
Nutzer, keine Query und kein Fragment an. Eine `.env`-Datei liest er nicht.

Was jede Einstellung bewirkt, steht im [README](../../README.md), Abschnitt „Betrieb". Die
Tabelle unten ist aus dem Code erzeugt (`python -m app.core.config_doc` im Ordner `backend/`);
ein Test schlägt an, wenn sie veraltet.

<!-- settings:start (python -m app.core.config_doc) -->
| Variable | Werte | Vorgabe | Geheim | Teil |
|---|---|---|---|---|
| `DATABASE_URL` | Text | Pflicht | ja, auch `DATABASE_URL_FILE` | Dienst |
| `DB_POOL_MIN_SIZE` | Zahl ≥ 0 | 1 | – | Dienst |
| `DB_POOL_MAX_SIZE` | Zahl ≥ 1 | 10 | – | Dienst |
| `DB_POOL_TIMEOUT_S` | Zahl > 0, ≤ 60 | 5 | – | Dienst |
| `DB_IDLE_IN_TRANSACTION_TIMEOUT_S` | Zahl ≥ 0, ≤ 3600 | 300 | – | Dienst |
| `DB_STATEMENT_TIMEOUT_S` | Zahl ≥ 0, ≤ 3600 | 0 | – | Dienst |
| `HOST` | Text | `127.0.0.1` | – | Dienst |
| `PUBLIC_PORT` | Zahl ≥ 1, ≤ 65535 | 8000 | – | Dienst |
| `INTERNAL_PORT` | Zahl ≥ 1, ≤ 65535 | 9000 | – | Dienst |
| `ROOT_PATH` | Text nach Muster `^(/[A-Za-z0-9._~-]+)*$` | leer | – | Dienst |
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | `INFO` | – | Dienst |
| `API_KEY_PEPPER` | Text, mindestens 32 Zeichen | –; Pflicht für die API und `app.bootstrap` | ja, auch `API_KEY_PEPPER_FILE` | Dienst |
| `PUBLIC_ACCESS` | `off` \| `lookup` \| `search` | `off` | – | Dienst |
| `FORWARDED_ALLOW_IPS` | Text | `127.0.0.1,::1` | – | Dienst |
| `AUTH_FAILURE_LIMIT` | Zahl ≥ 1 | 10 | – | Dienst |
| `AUTH_FAILURE_WINDOW_S` | Zahl > 0 | 900 | – | Dienst |
| `JOB_LEASE_S` | Zahl ≥ 3, ≤ 3600 | 60 | – | Dienst |
| `JOB_POLL_S` | Zahl > 0, ≤ 60 | 1 | – | Dienst |
| `JOB_SHUTDOWN_GRACE_S` | Zahl ≥ 0, ≤ 3600 | 20 | – | Dienst |
| `MAX_UPLOAD_MB` | Zahl ≥ 1, ≤ 500 | 50 | – | Dienst |
| `UPLOADS_PER_MINUTE` | Zahl ≥ 1 | 20 | – | Dienst |
| `MAX_CONCURRENT_UPLOADS` | Zahl ≥ 1, ≤ 64 | 2 | – | Dienst |
| `UPLOAD_READ_TIMEOUT_S` | Zahl ≥ 5, ≤ 3600 | 120 | – | Dienst |
| `THIRD_PARTY_MARKDOWN` | `hidden` \| `accounts` \| `public` | `hidden` | – | Dienst |
| `URL_IMPORTS_PER_MINUTE` | Zahl ≥ 1 | 20 | – | Dienst |
| `CONVERSIONS_PER_MINUTE` | Zahl ≥ 1 | 20 | – | Dienst |
| `MAX_JOBS_IN_FLIGHT` | Zahl ≥ 1, ≤ 1000 | 20 | – | Dienst |
| `MODEL_STARTS_PER_MINUTE` | Zahl ≥ 1 | 10 | – | Dienst |
| `EXPORTS_PER_MINUTE` | Zahl ≥ 1 | 10 | – | Dienst |
| `EXTRACT_CONCURRENCY` | Zahl ≥ 1, ≤ 16 | 4 | – | Dienst |
| `EXTRACT_BUDGET_WATCH` | `true` \| `false` | `true` | – | Dienst |
| `SHACL_TIMEOUT_S` | Zahl ≥ 10, ≤ 1800 | 300 | – | Dienst |
| `X5_ANCHOR_BUDGET_S` | Zahl ≥ 10, ≤ 3600 | 300 | – | Dienst |
| `CHILD_MEMORY_LIMIT_MB` | Zahl ≥ 256, ≤ 262144 | – | – | Dienst |
| `FETCH_USER_AGENT` | Text nach Muster `^[A-Za-z0-9._-]+(/[!-~]+)?( [ -~]*[!-~])?$`, höchstens 200 Zeichen | `Curricarta (+https://github.com/janschachtschabel/Curricarta)` | – | Dienst |
| `CHECK_HOST_INTERVAL_S` | Zahl ≥ 0.5, ≤ 60 | 2 | – | Dienst |
| `MEM_SEARCH_BUDGET_S` | Zahl ≥ 10, ≤ 3600 | 300 | – | Dienst |
| `MEM_EXPORT_TIMEOUT_S` | Zahl ≥ 5, ≤ 45 | 30 | – | Dienst |
| `MEM_DATA_LICENCE` | Text nach Muster `^(https://[^\s\x00-\x1f\x7f<>\"{}\|\\^\x60]+)?$`, höchstens 2000 Zeichen | leer | – | Dienst |
| `MEM_SPARQL_URL` | Text nach Muster `^https://[!-"$->A-~]+$`, höchstens 2000 Zeichen | `https://sparql.mem.edufeed.org/sparql` | – | Dienst |
| `MAX_PDF_PAGES` | Zahl ≥ 1, ≤ 5000 | 800 | – | Dienst |
| `CONVERT_TIMEOUT_S` | Zahl ≥ 1, ≤ 7200 | 900 | – | Dienst |
| `CONVERSION_ENGINES` | Text | `pdfplumber` | – | Dienst |
| `WORKER_KINDS` | Text nach Muster `^([a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*(,[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*)*)?$` | leer | – | Dienst |
| `RETENTION_JOBS_DAYS` | Zahl ≥ 0, ≤ 3650 | 90 | – | Dienst |
| `RETENTION_AUDIT_DAYS` | Zahl ≥ 0, ≤ 3650 | 365 | – | Dienst |
| `RETENTION_RAW_ANSWERS_DAYS` | Zahl ≥ 0, ≤ 3650 | 30 | – | Dienst |
| `ONTOLOGY_DIR` | Pfad | `ontology/` des Repositorys | – | Dienst |
| `IRI_BASE` | Text | – | – | Dienst |
| `LOG_FORMAT` | `text` \| `json` | `text` | – | Dienst |
| `STORAGE_BACKEND` | `fs` \| `s3` | `fs` | – | Dienst |
| `STORAGE_DIR` | Pfad | –; Pflicht bei `STORAGE_BACKEND=fs` | – | Dienst |
| `S3_ENDPOINT_URL` | Text nach Muster `^https?://[^\s/]+(/\S*)?$` | – | – | Dienst |
| `S3_BUCKET` | Text nach Muster `^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$` | –; Pflicht bei `STORAGE_BACKEND=s3` | – | Dienst |
| `S3_REGION` | Text nach Muster `^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$` | `us-east-1` | – | Dienst |
| `S3_ACCESS_KEY` | Text | –; nur zusammen mit `S3_SECRET_KEY` | ja, auch `S3_ACCESS_KEY_FILE` | Dienst |
| `S3_SECRET_KEY` | Text | –; nur zusammen mit `S3_ACCESS_KEY` | ja, auch `S3_SECRET_KEY_FILE` | Dienst |
| `OPENAI_API_KEY` | Text | – | ja, auch `OPENAI_API_KEY_FILE` | Sprachmodell |
| `OPENAI_BASE_URL` | Text nach Muster `^https?://[^\s/]+(/\S*)?$` | `https://api.openai.com/v1` | – | Sprachmodell |
| `OPENAI_MODEL` | Text | `gpt-6-luna` | – | Sprachmodell |
| `OPENAI_REASONING_EFFORT` | `none` \| `minimal` \| `low` \| `medium` \| `high` \| `xhigh` \| `max` | `low` | – | Sprachmodell |
| `OPENAI_TEXT_VERBOSITY` | `low` \| `medium` \| `high` | `low` | – | Sprachmodell |
| `LLM_PROVIDER` | `openai` \| `openai-compatible` | `openai` | – | Sprachmodell |
| `LLM_CONTEXT_TOKENS` | Zahl ≥ 8000 | – | – | Sprachmodell |
| `LLM_MAX_OUTPUT_TOKENS` | Zahl ≥ 1000, ≤ 1000000 | 16000 | – | Sprachmodell |
| `LLM_CACHED_INPUT_WEIGHT` | Zahl ≥ 0, ≤ 1 | – | – | Sprachmodell |
| `LLM_OUTPUT_WEIGHT` | Zahl > 0, ≤ 100 | – | – | Sprachmodell |
<!-- settings:end -->

## Auf einem Rechner

- `INTERNAL_PORT` gilt für API und Worker: Beide bedienen dort `/health` und `/metrics`. Läuft
  ein Worker neben der API auf demselben Rechner, braucht er ein eigenes `INTERNAL_PORT` (etwa
  `9001`); sonst startet der zweite Prozess nicht, oder beide teilen sich den Port still
  (Windows). Im Cluster und in Compose hat jeder Pod bzw. Container seinen eigenen.

## Für einen Cluster

- `HOST` setzt das Image auf `0.0.0.0`; außerhalb des Images bleibt der Dienst auf Loopback.
- `STORAGE_BACKEND=s3` mit `S3_BUCKET`; für einen eigenen S3-Dienst dazu `S3_ENDPOINT_URL` und
  `S3_REGION`. Ein leerer oder fehlender `S3_ENDPOINT_URL` heißt AWS selbst; ohne `S3_REGION` gilt
  `us-east-1` (leer wird es abgewiesen). Der Bucket muss bestehen: API und Worker öffnen den
  Speicher beim Start und fragen ihn dabei ab; ohne Bucket (bzw. ohne `STORAGE_DIR`) starten sie
  nicht.
- `WORKER_KINDS` beschränkt einen Worker auf Job-Arten (kommagetrennt), etwa eigene Pods für die
  Konvertierung mit einem Job je Pod; leer nimmt er alle, die er kennt. Eine Art ohne Handler
  beendet den Start mit Code 1.
- Schlüssel: `S3_ACCESS_KEY_FILE` und `S3_SECRET_KEY_FILE`, beide oder keiner. Ohne sie nimmt
  boto3 seine Standardkette (`AWS_*`-Variablen, Web-Identity/IRSA, die Rolle der Instanz). Wohin
  der Dienst geht, sagt nur `S3_ENDPOINT_URL`: `AWS_ENDPOINT_URL` und ein `endpoint_url` in
  `~/.aws/config` übergeht er. Profile und Anmeldedaten von boto3 gelten weiter.
- Rechte der Rolle: `s3:ListBucket` auf den Bucket (ohne sie antwortet S3 auf ein fehlendes
  Objekt mit 403 statt 404), `s3:GetObject`, `s3:PutObject` und `s3:DeleteObject` auf seine Objekte.
- `FORWARDED_ALLOW_IPS`: die Adressen oder Netze des Ingress, nie `*` und nie ein Netz `/0`.
- Uploads: Das Formular eines Uploads liegt ab 1 MiB als temporäre Datei in `/tmp` (bzw.
  `TMPDIR`), bis zu `MAX_UPLOAD_MB` + 1 MiB; aus dieser Datei prüft die API sie und legt sie ab,
  stückweise, ohne sie ganz in den Arbeitsspeicher zu laden. Ein Upload braucht dabei unter
  9 MiB Arbeitsspeicher, unabhängig von seiner Größe (gemessen mit beiden Speichern: PDF 2 MiB,
  Text aus 4-Byte-Zeichen 6 MiB, DOCX mit dem ungünstigsten Verzeichnis, das die Grenze zulässt,
  8,05 MiB; das Verzeichnis eines Archivs ist auf 1,22 MiB begrenzt, 256 Byte je Teil, ein
  größeres lehnt die API mit `archive_too_large` ab). Je gleichzeitigem Upload braucht eine
  API-Replica also bis zu `MAX_UPLOAD_MB` + 1 MiB in `/tmp` und bis zu 9 MiB mehr
  Arbeitsspeicher. Unter Compose ist
  `/tmp` ein tmpfs: Dort zählt die temporäre Datei ebenfalls zum Arbeitsspeicher. Gleichzeitig
  nimmt ein API-Prozess höchstens `MAX_CONCURRENT_UPLOADS` Uploads an (Standard 2); ein weiterer
  wartet bis zu 10 s auf einen freien Platz und bekommt dann 503 `uploads_busy` mit
  `Retry-After`. `/tmp` braucht daher mindestens `MAX_CONCURRENT_UPLOADS` × (`MAX_UPLOAD_MB` + 1)
  MiB je API-Prozess (Standard: 2 × 51 = 102 MiB). Compose gibt der API ein tmpfs von 256 MiB, das
  Helm-Beispiel jedem Pod außer dem Konverter (1Gi) ein `emptyDir` von 256Mi; wer die Werte erhöht, vergrößert beide (und unter
  Compose `mem_limit`, zu dem das tmpfs zählt). `UPLOADS_PER_MINUTE` zählt je Konto; ein Konto
  kann alle Plätze einer Replica belegen.
- Der Rand vor der API (Proxy, Ingress) muss den Body einer Anfrage ganz puffern, bevor er ihn
  weitergibt: Ein Upload hält seinen Platz, während sein Body ankommt, und ein Client, der
  langsam sendet, hielte ihn sonst in seinem Tempo. nginx und ingress-nginx puffern von sich aus;
  `proxy_request_buffering off` bzw. die Annotation
  `nginx.ingress.kubernetes.io/proxy-request-buffering: "off"` darf vor der API nicht stehen
  (`tests/deploy/test_upload_edge.py`). Ein Rand, der Bodies durchreicht (etwa Traefik ohne
  Puffer-Middleware oder der Port der API direkt), ist dafür nicht geeignet. Als zweite Linie
  dahinter liest die API das Formular eines Uploads, sobald er einen Platz hat, höchstens
  `UPLOAD_READ_TIMEOUT_S` lang (Standard 120 s, 5 bis 3600; das Warten auf den Platz zählt nicht
  mit). Hinter einem puffernden Rand kommt der Body auf einmal an, die Frist greift dann nie. Wer
  länger braucht, bekommt 408 `upload_too_slow`; die API gibt den Platz frei, behält nichts vom
  Upload und schließt die Verbindung, statt den Rest des Bodies weiterzulesen. Wo der Browser
  diese Antwort zustellt, sagt die Oberfläche, die Datei sei zu langsam angekommen, und rät zu
  einer schnelleren Verbindung oder einer kleineren Datei. Weil der Server die Verbindung beendet,
  während der Browser noch sendet, kann die Antwort auch verloren gehen; dann sieht der Nutzer
  einen Netzwerkfehler. Mit den Standardwerten (120 s, `MAX_UPLOAD_MB` 50) braucht die größte
  Datei hinter einem Rand, der Bodies durchreicht, rund 3,5 Mbit/s im Upload (50 MiB × 8 / 120 s =
  3,495 Mbit/s, auf eine Nachkommastelle gerundet). Wo Nutzer große Dateien über langsamere
  Leitungen hochladen und der Rand nicht puffert, die Frist erhöhen.
- Konvertierung: Der Worker legt die Datei für die Dauer der Umwandlung in `/tmp` ab (bis
  `MAX_UPLOAD_MB`) und hält sie einmal im Arbeitsspeicher; der Kindprozess, der sie umwandelt,
  braucht je nach PDF ein Vielfaches davon (gemessen wird in M6). Unter Linux nimmt der Kernel
  bei Speichermangel zuerst ihn (`oom_score_adj` 1000), nicht den Worker; die Konvertierung
  endet dann mit `died`. Eine Tabelle, deren Raster mehr als 200.000 Plätze hat, lehnt die
  Konvertierung mit `too_dense` ab, bevor sie das Raster anlegt. Bloß angegebene Spannen einer
  HTML-Tabelle (`colspan`, `rowspan`) zählen dabei nicht: Docling hält das Raster seit 2.150 an
  den vorhandenen Zellen fest, eine Seite mit einer Zelle und einer Million angegebener Spalten
  wird als die eine Zelle gelesen.
- Speichergrenze der Kindprozesse (`CHILD_MEMORY_LIMIT_MB`, ohne Standard): Die Grenzen der
  Container sind die erste Linie. Zusätzlich begrenzt die Einstellung unter Linux den Adressraum
  jedes Kindprozesses (Konvertierung, SHACL-Prüfung; `RLIMIT_AS`); auf anderen Systemen wird sie
  mit einer Warnung übergangen. Eine Anforderung über der Grenze scheitert im Kind selbst. Scheitert
  sie in Python (`MemoryError`), endet die Konvertierung mit `died` – auch beim Laden der Modelle,
  ohne weiteren Versuch –, die Prüfung mit `ShaclCrashed` (`MemoryError`, vom Job wiederholt).
  Scheitert eine Bibliothek auf andere Weise (ein `RuntimeError` ihres Allokators, ein Signal),
  endet die Konvertierung mit `unreadable` oder `crashed` oder als wiederholter Handler-Fehler.
  `RLIMIT_AS` zählt virtuellen Speicher, nicht den belegten: Jedes Kind schreibt am Ende eine Zeile
  `peak memory: rss=… MiB, virtual=… MiB` (INFO); die Grenze auf das Doppelte des gemessenen
  `virtual` setzen, nie nach `rss`. Gemessen im Konverter-Image mit Docling 2.150.1 auf einem
  gehosteten CI-Läufer (zwei Testdateien von wenigen Seiten, also die Untergrenze, die das Laden
  der Modelle setzt): Text-PDF `rss` 1.227 MiB, `virtual` 4.051 MiB; Scan mit Texterkennung `rss`
  3.308 MiB, `virtual` 6.745 MiB – für den Konverter also nicht unter 13.500 MiB. Echte
  Lehrpläne sind damit nicht gemessen. Zu knapp, und eine Konvertierung mit Docling endet meist schon
  beim Laden seiner Modelle mit `died` (pdfplumber lädt keine); scheitert das Laden anders als in
  Python, wird der Job wiederholt.
- Prüfung (X5): Gegen die SHACL-Formen prüft ein Kindprozess des Workers, mit derselben Regel für
  Speichermangel; seinen Speicherbedarf misst M6. Gemessen (CPU, ohne Last): rund 2 s für ein
  Dokument mit 100 Knoten und Aussagen (mit Fundstellen 200 Zeilen), 9 s mit 400, 43 s mit 1.200
  (300 Knoten, 900 Aussagen); `SHACL_TIMEOUT_S` (Standard 300 s) begrenzt ihn, danach bleibt das
  Tor mit dem Befund `x5.shacl_timeout` zu. Die Fundstellen prüft X5 in Stapeln innerhalb
  `X5_ANCHOR_BUDGET_S` (Standard 300 s); was die Frist nicht erreicht, bleibt ungeprüft, und X5 endet
  fertig mit dem Verstoß `x5.anchors_unchecked`. Ein neuer Start der Extraktion setzt diese Prüfung
  nicht fort, „Erneut prüfen“ (`POST /api/v1/documents/{id}/check`) prüft die übrigen. Ein neuer
  Start der Extraktion prüft ein Dokument,
  dessen X5 fertig ist, nur dann erneut, wenn seither eine Reparatur oder eine Bearbeitung eine
  Prüfung schuldet: Eine höhere Frist gilt also für Dokumente, deren X5 noch aussteht, und für die
  Prüfung nach einer Reparatur (`extract.repair`) oder einer Bearbeitung (`extract.check` oder ein
  neuer Start der Extraktion). Der Befund `x5.shacl_timeout` allein
  ist kein Anlass für eine Reparatur. Stirbt der Kindprozess oder bricht er ab, scheitert
  der Lauf X5 (`ShaclCrashed`), und der Job wird bis zu seiner Versuchsgrenze wiederholt.
- Export eines MEM-Imports (`GET /api/v1/documents/{id}/export.ttl`): Hier startet die API selbst
  SHACL-Kindprozesse, höchstens zwei je Prozess, mit derselben Regel für Speichermangel. Gemessen: 4 s
  im Kind für 2.400 Teile. Die Prüfung begrenzt `MEM_EXPORT_TIMEOUT_S` (Standard 30 s, höchstens 45 s);
  das Warten davor teilt sich mit ihr 55 s. Das setzt eine Lesefrist von Proxy oder Ingress über
  `DB_STATEMENT_TIMEOUT_S` der API (60 s) hinaus voraus, mit Abstand: 75 s in Compose
  (`deploy/nginx-api.conf`) und im Helm-Beispiel. Den Speicher der API bei zwei gleichzeitigen
  Prüfungen misst M6. Die Ergebnisse bleiben im Speicher unter `exports/<Dokument>/`, bis ihr Dokument
  gelöscht wird (`DELETE /api/v1/documents/{id}` leert den Ort in der Anfrage, war der Speicher fort, der
  nächste Lauf `python -m app.retention`); eine Frist haben sie nicht, auch nicht für einen Export, den ein
  geänderter Rechtestatus nicht mehr nutzt.
- Sitzungen der Datenbank: API und Worker öffnen ihre Verbindungen mit `options` (`-c …`); ein `options=`
  aus `DATABASE_URL` bleibt und steht davor (beim selben Parameter gilt der Wert des Dienstes). Eine
  Transaktion, die `DB_IDLE_IN_TRANSACTION_TIMEOUT_S` lang (Standard 300 s) nichts tut, beendet der
  Server; ihre Sperren werden frei, auch die Zeile des Jobs eines hängenden Workers. Die Anfrage der API
  antwortet dann 500; ein Job-Schritt endet mit `handler_error` und wird wiederholt, und seine Anfragen an
  das Sprachmodell können dabei ein zweites Mal kosten. Eine Anweisung, die länger als
  `DB_STATEMENT_TIMEOUT_S` läuft (Standard aus; Compose und die Helm-Werte setzen 60 s für die API), bricht
  er ab, das Warten auf eine Sperre eingeschlossen: Die Anfrage antwortet 500. Im Worker gilt diese Frist
  nie, auch wenn die Variable dort gesetzt ist: Sie bräche einen Herzschlag ab, der hinter der Lease
  wartet, und eine Buchung, die auf die Zeile der Quote wartet - jedes Mal ein bezahlter neuer Versuch.
  Solange eine der beiden Fristen gilt, kommen die Keepalives des Servers dazu (`tcp_keepalives_idle=30`,
  `tcp_keepalives_interval=10`, `tcp_keepalives_count=3`): Ein Client ohne Lebenszeichen fällt ihm nach
  rund 60 s auf, und die Sperren seiner offenen Transaktion werden frei. Gilt keine, schickt der Dienst sie
  nicht; der Worker nimmt die Anweisungsfrist nie, also verliert er sie schon mit
  `DB_IDLE_IN_TRANSACTION_TIMEOUT_S=0` - und damit die rund 60 s, nach denen der Server einen toten Worker
  bemerkt und die Zeile seines Jobs freigibt. Wer die Frist dort abschaltet, setzt die Keepalives an der
  Rolle (`ALTER ROLE … SET tcp_keepalives_idle = 30` usw., wie unten für den Pooler). Die Kommandos
  (Migration, Bootstrap, Vokabular, Lizenznachtrag, das Aufräumen `app.retention`, die Messbefehle unter
  `app.quality` und `app.pipeline.estimate`/`replay`) setzen nichts davon: Eine Migration wartet auf die
  Sperre einer anderen, solange diese läuft. Das Aufräumen arbeitet in kurzen Stapeln, jeder eine eigene
  Transaktion, und hält keine offen, während es den Objektspeicher liest und löscht. Nur `--dry-run`
  zählt in einer einzigen Transaktion, die es am Ende zurückrollt: Sie hält ihre Zeilensperren (alte
  beendete Jobs, alte Läufe) bis dahin, liest den Objektspeicher aber erst danach. Nutzungsbericht, Nachspielen, Goldbericht und MEM-Bericht halten für
  ihren ganzen Lauf eine Transaktion offen (ein Schnappschuss, nur lesend), auch während sie den
  Objektspeicher lesen und, mit `--endpoint-counts`, den Endpunkt fragen. Eine an der Rolle gesetzte
  `idle_in_transaction_session_timeout` (der Weg hinter einem Pooler, unten) begrenzt die Pause
  zwischen zwei Anweisungen eines solchen Berichts: Dauert eine länger, bricht der Bericht ab.
  Gemessen wurde mit `backend/tools/measure_sessions.py` neben den Datenbanktests, auf deren synthetischen
  Daten, mit Platzhaltern für Sprachmodell und Konverter: längste Pause in einer Transaktion 2 s, längste
  Anweisung der API 2 s, beides Sperren, die ein Test absichtlich hält. Das sagt nichts über echte Last
  und echte Dokumente; die Frage nach der längsten Transaktion des Workers beantwortet es nicht (der größte
  Testplan hat 58 Teile; bei 2.400 Teilen läge die Schreibtransaktion des MEM-Imports linear geschätzt
  bei rund 27 s). Bevor man den 60 s traut: langsame Anweisungen der Rolle der API beobachten
  (`log_min_duration_statement` oder `pg_stat_statements`), 500er mit `QueryCanceled` (57014) im Log der
  API und Jobs, die nach `IdleInTransactionSessionTimeout` wiederholt werden.
  Hinter einem Pooler wie PgBouncer, der `options` beim Verbindungsaufbau ablehnt („unsupported startup
  parameter“): beide Fristen auf 0 setzen, dann schickt der Dienst keine `options` (die Keepalives des
  Clients bleiben), und dieselben Werte an der Datenbank festlegen:
  `ALTER ROLE <Rolle> SET idle_in_transaction_session_timeout = '300s';`,
  `ALTER ROLE <Rolle> SET tcp_keepalives_idle = 30;` (ebenso `tcp_keepalives_interval = 10`,
  `tcp_keepalives_count = 3`) und nur für eine eigene Rolle der API
  `ALTER ROLE <Rolle der API> SET statement_timeout = '60s';`. Die Keepalives des Servers wirken dann
  zwischen Server und Pooler.
- Aufbewahrung (`RETENTION_JOBS_DAYS`, `RETENTION_AUDIT_DAYS`, `RETENTION_RAW_ANSWERS_DAYS`; 0 behält
  alles): `python -m app.retention` löscht beendete Jobs nach 90 Tagen, außer dem letzten Job je Dokument
  (er sagt, wie die Arbeit daran endete), einem Job, auf den eine Konvertierung wartet, und einem Job mit
  offener Reservierung; ein gelöschter Job antwortet unter `GET /api/v1/jobs/{id}` mit 404. Einträge des
  Audit-Logs gehen nach 365 Tagen, die Rohantworten eines Laufs 30 Tage nach seinem Ende; der Lauf zeigt
  das (`raw_response_key` leer). Ein Lauf, der nie endete (mit seinem Versuch abgebrochen), zählt ab seinem
  Start, sobald sein Job nicht mehr wartet oder läuft. Auch die Läufe festgeschriebener Dokumente verlieren
  ihre Rohantworten so, mit Absicht: Ihre Aussagen bleiben, wie sie festgeschrieben sind. Die Buchungen des Kostenbuchs (`llm_usage`, `conversion_usage`) gehen nie:
  Das Budget ist ihre Summe über die ganze Zeit. Ein Lauf hält eine Sitzungssperre (Exit-Code 3, wenn
  schon einer läuft); sie wirkt nur auf einer direkten Verbindung, nicht hinter einem Pooler im
  Transaktionsmodus. `--dry-run` zählt nur. Ausgabe: eine JSON-Zeile mit Zählwerten. Dazu nimmt er
  Dateien, die kein Eintrag mehr hält, und leert, was eine Löschung über die API notierte und der Speicher
  nicht gleich nahm. Die Fristen setzt der Betrieb dort, wo der Lauf sie liest: im Helm-Beispiel unter `env`
  aller Container oder unter `retention`, in Compose am Dienst `retention`, nie an API oder Worker allein
  (`docs/uebergabe/sicherung.md`, „Aufbewahrung und Löschen“).
- `JOB_SHUTDOWN_GRACE_S` mindestens 8 s unter `terminationGracePeriodSeconds` des Workers: 2 s zum
  Aufräumen des Handlers, bis zu 5 s für zurückgegebene Reservierungen, 1 s Reserve.
- `LLM_MAX_OUTPUT_TOKENS` für API und Worker gleich setzen und nach einer Änderung beide neu starten:
  Die API bietet eine Reparatur nur an, wo die Worker unter diesem Wert fragen würden.
- `IRI_BASE`: die Basis der IRIs, die ein Dokument beim Festschreiben bekommt (Werk, Dokument,
  Spezifikationen, Varianten, Knoten, Aussagen; http(s), mit Schrägstrich am Ende). Ohne sie schreibt der
  Dienst nichts fest (409 `no_iri_base`). Der Namensraum `w3id.org/wlo/` ist noch nicht registriert
  (`ontology/konzept.md`); eine einmal vergebene IRI bleibt, also die Basis vor dem ersten
  Festschreiben festlegen. Dokumente, die vor Migration 0034 festgeschrieben wurden, haben noch keine
  IRIs für Spezifikationen und Varianten: einmal nach der Migration
  `docker compose -f deploy/docker-compose.yml exec -T api python -m app.db.name_frozen` (im Cluster als
  einmaliger Job mit dem Image der API) vergibt sie unter dem Dokument-IRI, ohne `IRI_BASE` zu lesen –
  erst, wenn keine Replica des vorigen Images mehr läuft. Hat eine solche nach der Migration noch
  festgeschrieben, den Lauf wiederholen (gefahrlos: ein zweiter Lauf ändert nur, was fehlt); bis dahin
  verweigert die festgeschriebene Benennung des Kern-Graphen solche Dokumente.
- `THIRD_PARTY_MARKDOWN=public` gibt die Dateien der Einträge ohne Eigentümer (Saat, Recherche:
  Texte Dritter) jedem Besucher ohne Token aus, sobald `PUBLIC_ACCESS` nicht `off` ist. Nur setzen, wo
  die Rechte an diesen Texten eine öffentliche Weitergabe erlauben; der Standard `hidden` gibt sie nur
  Redaktion und Admin.
- `LOG_FORMAT=json` für die zentrale Logsammlung.
