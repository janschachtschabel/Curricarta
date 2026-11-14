# Sicherung, Wiederherstellung, Rollback

[Antworten für das IT-Team](anforderungen.md) · Stand 14.11.2026

Curricarta hält keinen Zustand im Prozess: Was zählt, liegt in PostgreSQL und im Objektspeicher,
dazu in den Geheimnissen, mit denen der Dienst beides liest. Diese Seite sagt, was davon zu sichern
ist, in welcher Reihenfolge, wie es zurückkommt und wie ein Release zurückgenommen wird. Die Befehle
gelten für Compose (`deploy/docker-compose.yml`); im Cluster nimmt der Betrieb seine eigenen Mittel
(unten). Ein Test hält die Namen auf dieser Seite mit Compose und dem Code gleich
(`backend/tests/deploy/test_backup_doc.py`).

## Umfang

| Was | Warum |
|---|---|
| PostgreSQL, die ganze Datenbank | Konten, Tokens (als HMAC), Register, Dokumente, Läufe, Jobs, Kontingente, Audit-Log und der Stand der Migrationen (`schema_migration`). Ein Abzug mit `pg_dump -Fc` reicht; Rollen gehören nicht dazu, sie legt der Betrieb an |
| Objektspeicher, Präfix `sources/` | die hochgeladenen und abgerufenen Dateien, je Inhalt einmal (`sources/<SHA-256>`) |
| Objektspeicher, Präfix `runs/` | die Rohantworten des Sprachmodells und des MEM-Endpunkts je Lauf und Stufe |
| Objektspeicher, Präfix `exports/` | die Turtle-Ausgaben festgeschriebener Dokumente |
| Geheimnis `API_KEY_PEPPER` | ohne es passt kein Token mehr (unten, „Pepper verloren“) |
| Geheimnis `DATABASE_URL` | Zugang zur Datenbank; in Compose dazu `db_password`, mit dem der Container die Rolle anlegt |
| Geheimnisse `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Zugang zum Bucket (fehlen sie, gilt die Standardkette von boto3) |
| Geheimnis `OPENAI_API_KEY` | der Schlüssel des Sprachmodells, nur im Worker |

Nicht zu sichern: das Volume mit den Modellen des Konverters (ein Lauf von
`app.conversion.fetch_models` holt und prüft sie neu) und `/tmp` der Container (ein `tmpfs`, das
nichts über eine Anfrage oder einen Job hinaus hält). In Compose liegen die Geheimnisse als Dateien
in `deploy/secrets/`; der ganze Ordner gehört in die Sicherung, getrennt von den Daten aufbewahrt.

## Reihenfolge

- **Sichern: erst die Datenbank, dann die Objekte.** Jede Zeile der Datenbank, die auf ein Objekt
  zeigt, findet es dann in der Sicherung der Objekte, die später entsteht.
- **Zurück: erst die Objekte, dann die Datenbank.** Sobald die Datenbank zurück ist, kann der Dienst
  starten, und jedes Objekt, das sie nennt, liegt schon da.

Eine ältere Datenbank mit neueren Objekten hinterlässt nur Waisen: Objekte, die keine Zeile mehr
nennt; sie kosten Platz und sonst nichts. Umgekehrt nennt die Datenbank Objekte, die fehlen: Der
Download einer solchen Datei antwortet 404 `file_gone`, Jobs, die sie lesen, scheitern.

## Pepper verloren

Die Tokens sind als HMAC mit `API_KEY_PEPPER` gespeichert. Ist der Pepper weg, ist jedes Token
ungültig, auch das der Admins; ein neuer Pepper macht keines wieder gültig. Der Weg zurück:

1. Einen neuen Pepper setzen (in Compose die Datei `deploy/secrets/api_key_pepper`) und API und
   Worker neu starten.
2. Alle Schlüssel widerrufen, in der Datenbank:
   `UPDATE api_key SET revoked_at = now() WHERE revoked_at IS NULL`
3. `python -m app.bootstrap NAME` mit einem **neuen** Namen: Ohne gültigen Admin-Schlüssel nimmt der
   Befehl wieder an, der alte Name gehört aber noch dem alten Konto. Das Token geht einmal auf stdout.
4. Mit diesem Token über die API jedem Konto einen neuen Schlüssel ausgeben.

Die Übung unten spielt die Schritte 1 bis 3 durch.

## Rollback

- **Migrationen laufen nur vorwärts**; es gibt keine Rücknahme einer Migration. Jede Migration
  ergänzt erst und entfernt erst in einem späteren Release, was das Release davor noch las.
- **Ein Image zurücknehmen** heißt: das vorige Image starten, die Datenbank bleibt. Das vorige Image
  läuft gegen das neuere Schema, denn `/ready` nimmt eine Datenbank, die voraus ist, als bereit an;
  nur ein fehlender Stand macht es unbereit. Im Rolling Update ist das ohnehin der Zustand, solange
  alte Pods noch bedienen.
- **Daten zurück** gibt es nur per Wiederherstellung aus der Sicherung, mit allem, was seitdem
  geschrieben wurde, verloren.
- **Migrationen auf großen Tabellen:** Der Runner gibt jeder Datei eine Transaktion. Baut eine
  Migration einen Index auf einer großen Tabelle oder füllt sie Zeilen nach, hält sie die Sperre bis
  zum Commit; die Tabelle ist so lange für Lesen und Schreiben gesperrt, auch für die alten Pods
  (audit 2026-11-14). Solche Migrationen laufen in einem Wartungsfenster mit vorheriger Sicherung,
  bis der Runner Migrationen ohne Transaktion kennt (`CREATE INDEX CONCURRENTLY`, Nachfüllen in
  Stapeln getrennt vom Schema).

## Befehle für Compose

Vom Wurzelordner des Repositorys, mit Bash. Die Sicherung landet unter `data/backup/`, den weder git
noch die Images lesen (`.gitignore`, `.dockerignore`). Während das Archiv der Objekte entsteht, ist
MinIO gestoppt: Uploads und Jobs, die den Speicher brauchen, scheitern so lange. Das Archiv macht das
Postgres-Image, das Compose schon per Digest festlegt; kein weiteres Image kommt ins Spiel.

Sichern und Zurückspielen sind je ein eigenes Skript (etwa `bash sichern.sh`), nicht Zeilen für eine
offene Shell, die `set -e` beim ersten Fehler selbst beenden würde. Beide beginnen gleich: `set -eu`
hält beim ersten Fehler und bei einer nie gesetzten Variable an; ohne es folgten auf ein
gescheitertes Entpacken `pg_restore` und `up -d`, und der Dienst liefe mit einer Datenbank, der
Objekte fehlen. `MSYS_NO_PATHCONV=1` hält Git Bash unter Windows davon ab, `/data` in den Argumenten
an docker in einen Windows-Pfad umzuschreiben; unter Linux ändert es nichts. Beim Sichern entsteht
jede Datei erst als `.part` und bekommt ihren Namen erst, wenn sie ganz geschrieben ist: Ein
abgebrochenes Archiv hinterlässt kein `objects.tar`, das das Zurückspielen annähme. Scheitert ein
Schritt, startet `trap … EXIT` MinIO wieder; sonst startet das Skript es selbst, und „MinIO läuft
wieder“ erscheint nur, wenn Compose den Dienst danach als laufend meldet.

```bash
set -eu
export MSYS_NO_PATHCONV=1
# Sichern: erst die Datenbank, dann die Objekte
dir="data/backup/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$dir"
docker compose -f deploy/docker-compose.yml exec -T postgres pg_dump -U curricarta -Fc curricarta > "$dir/db.dump.part"
mv "$dir/db.dump.part" "$dir/db.dump"
docker compose -f deploy/docker-compose.yml stop minio
trap 'docker compose -f deploy/docker-compose.yml start minio' EXIT
docker run --rm -v curricarta_miniodata:/data:ro pgvector/pgvector:pg17@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f tar --numeric-owner -cf - -C /data . > "$dir/objects.tar.part"
mv "$dir/objects.tar.part" "$dir/objects.tar"
docker compose -f deploy/docker-compose.yml start minio
trap - EXIT
docker compose -f deploy/docker-compose.yml ps --status running --services | grep -qx minio
echo "MinIO läuft wieder"
```

Zum Zurückspielen in der dritten Zeile den Ordner der Sicherung eintragen. Die beiden `test -s`
brechen ab, bevor etwas gelöscht wird, wenn `db.dump` oder `objects.tar` fehlt oder leer ist; je
eine Zeile, denn `set -e` hält bei einem scheiternden Glied vor dem letzten einer `&&`-Kette nicht an.

```bash
set -eu
export MSYS_NO_PATHCONV=1
dir="data/backup/<Zeitstempel>"
test -s "$dir/db.dump"
test -s "$dir/objects.tar"
# Zurück: erst die Objekte, dann die Datenbank
docker compose -f deploy/docker-compose.yml down
docker volume rm curricarta_pgdata curricarta_miniodata
docker compose -f deploy/docker-compose.yml up -d --wait postgres
docker compose -f deploy/docker-compose.yml create minio
docker run --rm -i -v curricarta_miniodata:/data pgvector/pgvector:pg17@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f tar --numeric-owner -xf - -C /data < "$dir/objects.tar"
docker compose -f deploy/docker-compose.yml exec -T postgres pg_restore -U curricarta --clean --if-exists -d curricarta < "$dir/db.dump"
docker compose -f deploy/docker-compose.yml up -d
```

`docker volume rm` löscht die Daten des Projekts `curricarta`; die Sicherung unter `data/backup/`
bleibt. `create minio` legt das Volume von MinIO an, ohne
MinIO zu starten: Auf dem leeren Volume schriebe es sonst einen frischen Zustand, den das Archiv nur
teilweise überschreibt. `pg_restore` legt auch die Erweiterungen
(`vector`, `pg_trgm`, `unaccent`) an und braucht dafür die Rechte eines Superusers; in Compose hat
die Rolle `curricarta` sie. Die Rolle selbst legt der Container beim ersten Start mit `db_password`
an, daher müssen die Geheimnisse aus `deploy/secrets/` dieselben sein wie bei der Sicherung.

## Cluster

Im Cluster sichert der Betrieb mit seinen eigenen Mitteln, in derselben Reihenfolge:

- PostgreSQL mit Point-in-Time-Recovery (Basissicherung und WAL-Archiv) oder dem Verfahren des
  Datenbankdienstes; `pg_restore` mit Erweiterungen braucht dort die Rechte des DBA.
- Den Bucket mit Versionierung (und einer Lebenszeit für alte Versionen), sodass ein Stand zu einem
  Zeitpunkt zurückgeholt werden kann, der zu dem der Datenbank passt: Objekte zum selben oder einem
  späteren Zeitpunkt als die Datenbank, nie zu einem früheren.
- Die Geheimnisse dort, wo der Betrieb seine Secrets verwahrt.

## Übung

Eine Sicherung, die nie zurückgespielt wurde, ist eine Vermutung. `backend/tools/restore_drill.py`
spielt den Weg dieser Seite einmal ganz durch, in einem eigenen Compose-Projekt `curricarta-drill`
aus derselben Datei, mit eigenen Volumes:

1. startet es, legt einen Admin an (`app.bootstrap`; das Token bleibt im Speicher des Skripts) und
   lädt ein erzeugtes PDF hoch;
2. sichert erst die Datenbank, dann die Objekte nach `data/backup/<Zeitstempel>/` (`db.dump`,
   `objects.tar`) und entfernt das Projekt samt Volumes;
3. startet nur PostgreSQL, legt MinIOs Container und Volume an, ohne MinIO zu starten, spielt erst
   die Objekte, dann die Datenbank zurück und startet alles;
4. prüft `/ready` an jeder API-Replica, dass das alte Token sich anmeldet, dass die Datei mit
   demselben SHA-256 zurückkommt und dass `source`, `source_file`, `audit_log` und
   `schema_migration` so viele Zeilen haben wie vor der Sicherung;
5. spielt „Pepper verloren“ durch: neuer Pepper (nur für das Übungsprojekt, `deploy/secrets/` bleibt
   unberührt), alle Schlüssel widerrufen, ein zweiter Bootstrap, dessen Token sich anmeldet, während
   das alte abgewiesen wird;
6. entfernt am Ende, bestanden oder nicht, das Übungsprojekt samt Volumes.

Es läuft nicht neben dem Projekt `curricarta` (beide bräuchten Port 18080 und dasselbe Subnetz) und
bricht mit Exit-Code 1 ab, bevor es etwas anfasst, wenn dessen Container laufen oder dessen Netz nach
einem `stop` noch besteht; `down -v` nennt immer `-p curricarta-drill`. Ausgegeben werden nur
Zählwerte, zuletzt `restore drill passed` (Exit-Code 0); ein Fehler nennt den Schritt (Exit-Code 1).
Lässt sich das Übungsprojekt am Ende nicht entfernen, sagt das Skript es mit dem Befehl, der es
entfernt, und endet mit 1. Die Images müssen gebaut, die Geheimnisse geschrieben sein:

```bash
python deploy/make-secrets.py
(cd frontend && npm ci && npm run build)
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml down
python backend/tools/restore_drill.py
```

Die Tests des Skripts (`backend/tests/deploy/test_restore_drill.py`) laufen ohne Docker gegen einen
Ersatz, der jedes Kommando nur liest. **Mit Docker ist die Übung noch nicht gelaufen**: Jeder ihrer
Schritte ist unbewiesen, auch das Anlegen von MinIOs Volume per `create minio` vor dem Entpacken. Ihr
erster Lauf und seine Zählwerte werden hier nachgetragen.
