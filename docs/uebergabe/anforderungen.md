# Antworten für das IT-Team

Stand M2 (bis Paket M2-8b), 14.11.2026; was für einen Betrieb noch fehlt, steht am Ende. Diese Seite
beantwortet die Betriebsvorgaben der Plattform (kurz „T6“) Frage für Frage, in der Variante **ohne B-API**: Der
Dienst prüft eigene Zugangstokens und ruft das Sprachmodell mit einem eigenen Schlüssel. Was
noch offen ist, steht am Ende; die Antworten wachsen mit jedem Meilenstein.

Kurz: Curricarta erfasst Lehrpläne nach Curriculum-Kern 1.0, dockt sie an Kompetenz-,
Niveau- und Normdatenschemata an und bildet daraus eine Wissenslandkarte. Ein Image läuft als
API und als Worker, dazu ein Web-Image für die Oberfläche; Daten liegen in PostgreSQL und einem
S3-Objektspeicher.

## 1. API und Endpunkte

| Frage | Antwort |
|---|---|
| OpenAPI-Spec? | Ja, OpenAPI 3.1 aus dem Code (FastAPI), nie von Hand gepflegt, unter `GET /openapi.json` am öffentlichen Port. `info.title`, `info.summary` (für den Produktkatalog) und `info.description` sind gesetzt; jede Operation hat Gruppe und Kurztitel, jede Gruppe eine Beschreibung (`tests/api/test_openapi.py`) |
| Swagger UI, ReDoc? | Abgeschaltet: Beide laden Skripte und Schriften von Fremdservern in den Browser. Eine Doku-Seite nur mit eigenen Dateien kann folgen |
| Zwei Ports? | Ja. `PUBLIC_PORT` (8000) ist die API für den Ingress; `INTERNAL_PORT` (9000) liefert `/health`, `/ready` und `/metrics`. Am öffentlichen Port antworten diese Pfade mit 404, entschieden nach dem Socket, nicht nach Headern; sie stehen nicht in der Spec |
| Proben in Kubernetes? | Liveness `GET /health`, Readiness `GET /ready` (prüft die Datenbank und den Stand der Migrationen, wartet je bis 2 s auf Verbindung und Abfrage, also `timeoutSeconds` ≥ 5), beide am Port 9000 ([Helm-Beispiel](../../deploy/helm-values.example.yaml)). `HEAD /health` antwortet 405; eine Probe muss GET senden |
| Header vom Client? | `Authorization: Bearer curricarta_…` für alles außer `GET /api/v1/info` und dem öffentlichen Lesen, das `PUBLIC_ACCESS` freigibt. Optional `X-Request-ID`, `x-client-trace-id` und die B3-Header |
| Header zurück? | `X-Request-ID` an jeder Antwort; `WWW-Authenticate` bei 401, `Retry-After` bei 429 und 503. Dazu an jeder Antwort `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `X-Frame-Options: DENY` und `Referrer-Policy: no-referrer`; HSTS setzt der Ingress, an dem TLS endet |
| Content-Types? | `application/json`, jeder JSON-Body bis 1 MiB; `/metrics` im Textformat für Prometheus. Uploads als `multipart/form-data` (`POST /api/v1/sources`, bis `MAX_UPLOAD_MB` und 1 MiB für das Formular; ein Body über seiner Grenze wird mit 413 abgewiesen, bevor er gelesen wird). Dateien gehen als Download hinaus (`GET /api/v1/sources/{id}/file`, nächste Zeile): die Abweichung, die mit T6 abzustimmen ist. Seit M2 gibt `GET /api/v1/documents/{id}/export.ttl` ein festgeschriebenes Dokument aus MEM-Schule als Turtle aus, ebenfalls als Download; weitere Dateiausgaben (Kern-RDF als TTL) folgen mit ihren Paketen |
| Datei-Download? | `GET /api/v1/sources/{id}/file` gibt die Datei eines Registereintrags in Stücken von 1 MiB aus, nie zum Anzeigen im Browser: `Content-Type` ist ihr Typ (PDF, DOCX, RTF nach den ersten Bytes; Markdown, HTML, Text, Turtle nach dem Namen, mit dem sie kam), dazu `Content-Disposition: attachment` mit einem ASCII-Namen und dem ganzen Namen als `filename*` (UTF-8), `Content-Length`, `Cache-Control: private, no-store` und `X-Content-Type-Options: nosniff`. Die Datei bekommen ihr Eigentümerkonto, Redaktion und Admin. Die eines Eintrags ohne Eigentümer (Saat, Recherche) bekommen daneben, wen `THIRD_PARTY_MARKDOWN` nennt: `hidden` niemand (403 `file_hidden`), `accounts` jedes Konto, `public` auch Besucher ohne Token, diese aber nur bei `PUBLIC_ACCESS` ≠ `off`. Der Upload eines anderen Kontos ist 404 wie ein Eintrag, den es nicht gibt; ohne Datei 404 `no_file`, fehlt sie im Speicher 404 `file_gone` (im Log mit Schlüssel und Eintrag) |
| Fehler? | Einheitlich `{"code", "message", "details"}`; Validierungsfehler nennen Feld und Art, nie die Eingabe; keine Stacktraces nach außen |
| Antwortzeiten? | Lesende Anfragen kurz; alles über 30 s läuft ab M1 als Job (`202` mit Job-ID, Stand über `GET /api/v1/jobs/{id}`): Konvertierung, Extraktion, Prüfung. Ausnahme: der Export eines MEM-Imports prüft in der Anfrage, Warten und Prüfung zusammen unter 60 s (gemessen 4 s für 2.400 Teile). Messung unter Last in M6 |

## 2. Authentifizierung (ohne B-API)

| Frage | Antwort |
|---|---|
| Wer authentifiziert? | Der Dienst selbst: Tokens, die ein Admin ausgibt, gespeichert als HMAC-SHA-256 mit dem Geheimnis `API_KEY_PEPPER`; sperrbar und widerrufbar |
| Rollen? | `admin`, `redaktion`, `nutzer`. Ohne Token nur, was `PUBLIC_ACCESS` (`off` \| `lookup` \| `search`) erlaubt, nie das Sprachmodell |
| Schutz gegen Raten? | `AUTH_FAILURE_LIMIT` Fehlversuche je Adresse (IPv6: je /64) in `AUTH_FAILURE_WINDOW_S`, danach 429; ein gültiges Token kommt immer durch. Die Client-Adresse kommt nur von Proxys aus `FORWARDED_ALLOW_IPS` |
| Schlüssel des Sprachmodells? | `OPENAI_API_KEY` als Secret (Datei über `OPENAI_API_KEY_FILE`), nur im Worker. `OPENAI_BASE_URL` erlaubt jeden OpenAI-kompatiblen Endpunkt, auch ein Gateway im Cluster; keine B-API |
| Erster Admin? | `python -m app.bootstrap NAME` einmal interaktiv (`kubectl exec -it`); das Token geht auf stdout, nie in ein Log |

## 3. Monitoring und Logging

| Frage | Antwort |
|---|---|
| Metriken? | Prometheus am internen Port, `GET /metrics`: Anfragen und Dauer je Route-Vorlage (`curricarta_http_requests_total`, `curricarta_http_request_duration_seconds`). Der Worker bedient denselben internen Port mit `/health` (Liveness) und `/metrics`: Jobs nach Art und Ausgang (`curricarta_jobs_total`, Ausgänge `done`, `failed`, `error`, `cancelled`, `released`, `lost`; gezählt, wie der Ausgang geschrieben wurde: `lost` auch, wenn der Handler oder das Ende den Verlust der Lease bemerkt) und ihre Dauer (`curricarta_job_duration_seconds`), dazu abgelaufene Leases, die ein Sweep weitergibt (`curricarta_job_leases_expired_total`, nach dem, was aus dem Job wurde: `queued`, `failed`, `cancelled`); er hat keinen Service, daher ein PodMonitor. Dazu Konvertierungen nach Engine und Ausgang und ihre Seiten (`curricarta_conversions_total`, `curricarta_conversion_pages_total`), Anfragen an das Sprachmodell nach Ausgang und ihre Tokens nach Art (`curricarta_llm_requests_total`, `curricarta_llm_tokens_total`) und die Reservierungen des Budgets (`curricarta_usage_reservations_total`). Die API liest beim Scrape die Warteschlange aus der Datenbank (höchstens alle 15 s, eine Abfrage über die Teilindizes, Frist wie `/ready`): wartende und laufende Jobs je Art (`curricarta_queue_jobs{kind,status}`), das Wartealter des ältesten fälligen Jobs (`curricarta_queue_oldest_waiting_seconds`); jede Replica meldet denselben Wert, daher `max`, nie `sum`. Ist die Datenbank weg, bleiben die letzten Werte stehen und `curricarta_queue_reads_failed_total` zählt hoch; `curricarta_queue_read_timestamp_seconds` nennt den letzten erfolgreichen Lesezeitpunkt, und die Regeln lassen eine Replica aus, deren Werte älter als 30 s sind. Dazu der Verbindungspool (`curricarta_db_pool_size`, `curricarta_db_pool_available`, `curricarta_db_pool_requests_waiting`) und der laufende Build (`curricarta_build_info{version,revision}`, die Revision aus dem Build-Argument `REVISION` des Images) |
| Logs? | Eine Zeile je Ereignis auf stdout, mit `LOG_FORMAT=json` als JSON mit `time`, `level`, `logger`, `request_id`, `trace_id`, `message`; eine Zeile je Anfrage ohne Query-Werte; nie ein Geheimnis |
| Tracing? | `x-client-trace-id` und B3 (`X-B3-TraceId`, `b3`) werden übernommen, ungültige Werte verworfen. Die Trace-ID steht in jeder Logzeile der Anfrage (der Rauchtest in CI prüft es). Die Aufrufe des Sprachmodells tragen die Trace-Header und die Request-ID weiter (`outgoing_headers`). Abrufe fremder Adressen senden sie nicht – der Abruf von Quell-URLs (`source.fetch`), der Prüfjob (`source.check`), sein Abruf von robots.txt und die Abfragen am MEM-Endpunkt: Diese Hosts gehen unsere Kennungen nichts an, und die Kennung wählt der Aufrufer. Ein Job trägt die Trace-ID der Anfrage, die ihn anlegte, ohne Tracing-Header (die Oberfläche sendet keinen) deren Request-ID; der Worker schreibt seine Zeilen damit |
| Alarme? | Prometheus-Regeldatei `deploy/alerts/curricarta.rules.yaml` (in Helm `monitoring.prometheusRule`): stehende Warteschlange (`CurricartaQueueStalled`, ältester fälliger Job > 15 min), tiefe Warteschlange (`CurricartaQueueDeep`, > 100 wartende je Art), ablaufende Leases (`CurricartaLeasesExpiring`), scheiternde Jobs (`CurricartaJobsFailing`, > 20 % `error`/`lost` je Art), Ablehnungen des Sprachmodells (`CurricartaModelRefusing`, > 20 %), Serverfehler der API (`CurricartaApiErrors`, > 5 % 5xx), gesättigter Pool (`CurricartaPoolSaturated`) und ungelesene Warteschlange (`CurricartaQueueUnread`). Jede Regel wartet vor dem Auslösen, nennt ihre Schwere und sagt, was zu tun ist; Tests halten sie an die exportierten Reihen und Label-Werte. Die Schwellen sind Vorgaben, noch nicht gemessen. Kontingente und Speicherplatz folgen in M6 |

## 4. Repository, Build und Versionierung

| Frage | Antwort |
|---|---|
| Repository? | github.com/janschachtschabel/Curricarta |
| Abhängigkeiten? | `backend/uv.lock` für alle Plattformen, mit Prüfsummen; das Image installiert den Export `deploy/requirements-api.txt` per `pip --require-hashes`, nur Wheels |
| Images? | `deploy/api.Dockerfile` (API und Worker, python:3.13-slim per Digest, Nutzer 10001, 244 MB, Stand M1) und `deploy/web.Dockerfile` (SPA hinter nginx-unprivileged per Digest, Nutzer 101, 61 MB, Stand M1). Dasselbe Dockerfile baut mit `VENV=convert` das Image des Konverters (Docling und OCR auf der CPU, `deploy/docker-compose.converter.yml`); es ist deutlich größer und läuft als eigener Dienst. Kein Code-Volume, keine Daten im Image: von der Ontologie nur die Modelle, Vokabulare und Profile, die der Dienst liest. Das Web-Image nennt keinen API-Host; im Cluster routet der Ingress `/api/v1/` und `/openapi.json` zur API |
| CI? | `.github/workflows/ci.yml`: Ontologie-Prüfung, ruff, mypy, Tests mit PostgreSQL und MinIO in zwei parallelen Teilen, deren Abdeckung ein dritter Job zusammenführt und an der Grenze misst, Frontend-Tests und -Build, beide Images und ein Rauchtest des ganzen Dienstes in Compose (Vokabular geladen, beide Worker laufen, `/ready` je API-Replica, Trace-ID im Log); grün auf main seit 2026-10-31. `.github/workflows/converter.yml` (nur bei Änderungen am Konverter, sonst von Hand): Konverter-Image, Modelle, Docling-Tests im Image und der Dienst mit Konverter |
| Versionen? | `app.__version__` folgt der Paketversion; Image-Tags `sha-<12 Zeichen>` je Commit und SemVer je Git-Tag sind geplant (mit der Registry) |

## 5. Deployment und Betrieb

| Frage | Antwort |
|---|---|
| Zustandslos? | Ja: kein Zustand im Prozess, der über eine Anfrage hinaus gilt. Jobs, Sperren, Zähler und Kontingente liegen in PostgreSQL, Dateien im Objektspeicher. API und Worker skalieren über Replicas |
| Warteschlange? | Eine Tabelle in PostgreSQL: Worker holen Jobs mit `FOR UPDATE SKIP LOCKED`, halten eine Lease mit Lebenszeichen, geben sie bei SIGTERM nach `JOB_SHUTDOWN_GRACE_S` zurück; ein abgestürzter Worker verliert sie nach `JOB_LEASE_S`. Faire Bedienung je Konto. Kein eigener Broker |
| Datenbank? | PostgreSQL 17 mit `vector`, `pg_trgm`, `unaccent` (anlegen durch die Migration oder vorab durch den DBA). Migrationen einmal je Release per `python -m app.db.migrate` (Helm-Hook), unter Advisory-Lock; API und Worker migrieren nie selbst, `/ready` meldet einen fehlenden Stand |
| Objektspeicher? | S3-kompatibel (`STORAGE_BACKEND=s3`), Bucket von T6; API und Worker fragen ihn beim Start ab und starten ohne ihn nicht. Rechte: `s3:ListBucket` auf den Bucket (ohne sie meldet S3 ein fehlendes Objekt als 403), `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` auf seine Objekte. Ohne Schlüssel gilt die Standardkette von boto3 (`AWS_*`-Variablen, Web-Identity/IRSA, Rolle der Instanz) |
| Volumes? | Eines: Der Konverter liest seine Modelle (rund 600 MB) aus einem Volume, das ein einmaliger Lauf befüllt und prüft (`app.conversion.fetch_models`, Größe und SHA-256 je Datei). API, Worker und Web brauchen keines. Ab M3 kommen lesend eingebundene Volumes für lokale Abzüge (Wikidata, GND, ESCO) und Modelle, befüllt von Sidecars bzw. CronJobs |
| Sicherung? | PostgreSQL ganz, der Bucket mit den Präfixen `sources/`, `runs/`, `exports/` und die Geheimnisse; gesichert erst die Datenbank, dann die Objekte, zurück umgekehrt. Migrationen laufen nur vorwärts, ein Rollback nimmt das Image zurück, Daten kommen nur aus der Sicherung zurück. Befehle für Compose, Mittel im Cluster und der Weg bei verlorenem Pepper: [sicherung.md](sicherung.md) |
| Ressourcen? | Noch nicht gemessen; das Helm-Beispiel nennt vorläufige Werte. Die Konvertierung (ab M1 eigener Worker, ein Job je Pod) braucht deutlich mehr Speicher; die Baseline unter Last kommt in M6 |
| Konfiguration? | Nur Umgebungsvariablen, Geheimnisse als Dateien (`*_FILE`); vollständige Liste in [konfiguration.md](konfiguration.md), aus dem Code erzeugt |
| Härtung? | Nicht-root, nur lesendes Wurzeldateisystem, keine Capabilities, keine neuen Privilegien, `seccomp RuntimeDefault`; in Compose so betrieben und geprüft |
| Lokal ausprobieren? | `deploy/docker-compose.yml` startet alles auf einem Rechner (README, „Compose") |

## 6. Übergabepaket

- [x] Images und Build-Dateien (`deploy/`)
- [x] Konfiguration ([konfiguration.md](konfiguration.md)), erzeugt und geprüft
- [x] Helm-Werte als Vorlage ([helm-values.example.yaml](../../deploy/helm-values.example.yaml))
- [x] Compose für den lokalen Betrieb
- [ ] CI-Lauf grün und Images in der Registry
- [ ] Alarmregeln, Ressourcen-Baseline, Lasttest (M6)
- [ ] Steckbrief für den Produktkatalog (mit dem ersten nutzbaren Stand, M1)

## 7. Kosten, Wartung und Lebenszyklus

| Frage | Antwort |
|---|---|
| Laufende Kosten? | Das Sprachmodell je Aufruf (Kontingente je Konto ab M1); sonst CPU, Speicher, PostgreSQL und Objektspeicher. Keine GPU |
| Wartung? | Abhängigkeiten über `uv.lock`, Basis-Images über ihren Digest; ein Update ist ein eigener, geprüfter Commit |
| Dritte zur Anfragezeit? | Keine in der API. Live nur in Jobs des Workers: das Sprachmodell, der SPARQL-Endpunkt von MEM-Schule (`MEM_SPARQL_URL`: der Katalog-Job eines Admins und der Import-Job je Plan; die abgerufenen Pläne bleiben in der Datenbank und im Objektspeicher der Instanz und werden nie mit der App ausgeliefert), der Abruf von Quell-URLs, die ein Konto nennt (`source.fetch`), und der Prüfjob, den ein Admin startet (`source.check`): er fragt jede Adresse der Einträge ohne Konto und ohne Datei einmal ab (nach beiden Saaten rund 1.800 Adressen auf über 140 Hosts), prüft jede Adresse und jedes Weiterleitungsziel gegen die robots.txt seines Hosts, hält je Host `CHECK_HOST_INTERVAL_S` Abstand über alle Worker, wartet die `Retry-After` eines 429 oder 503 ab, stellt sich mit `FETCH_USER_AGENT` vor und umgeht kein 403 oder 429. Abgerufen wird nur von öffentlichen Adressen (kein privates, Loopback-, Link-Local-, CGNAT-, Multicast- oder NAT64-Netz), verbunden genau zur geprüften Adresse, ohne Proxy der Umgebung; die NetworkPolicy des Workers erlaubt dafür 80/443 ins öffentliche Netz (`public-web` im [Helm-Beispiel](../../deploy/helm-values.example.yaml): `0.0.0.0/0` und `::/0` ohne die privaten, CGNAT- und Link-Local-Netze, also auch ohne die Metadaten-Adresse 169.254.169.254, und ohne die Netze des Clusters, die der Betrieb einträgt). Fremddaten kommen ab M3 als lokale Abzüge |

## Offene Punkte

- Registry mit versionierten Images; gemessene Schwellen der Alarmregeln; Sicherung und Aufbewahrung.
- Abstimmung der Content-Types für Uploads und Dateiausgaben (M1).
- Prüfsummen beim Objektspeicher: boto3 schickt seit 1.36 bei jedem Schreiben eine CRC32-Prüfsumme
  mit (`x-amz-checksum-crc32`, über HTTPS als `aws-chunked`), die manche S3-kompatiblen Dienste
  ablehnen. Getestet ist MinIO. Nimmt T6s Dienst sie nicht an, schalten botocores eigene Variablen
  `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` und `AWS_RESPONSE_CHECKSUM_VALIDATION=when_required`
  sie auf „nur wo verlangt" um; der Dienst setzt keinen der beiden Werte selbst (getestet).
- Ressourcen, Alarme und Lastmessung (M6).
