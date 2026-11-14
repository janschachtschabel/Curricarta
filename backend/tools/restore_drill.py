"""Back up and restore the whole service once, as docs/uebergabe/sicherung.md has it, and check that nothing
was lost: the drill for an operator who must trust the backup before the day it is needed.

    python backend/tools/restore_drill.py

It runs Compose (deploy/docker-compose.yml, its images built) as a project of its own, curricarta-drill,
and refuses while the project curricarta runs: both would take port 18080 and the same subnet. Steps: start,
make an admin and upload a generated PDF; back up the database, then the objects (under data/backup/, which
git and the images never read); remove the project with its volumes; restore the objects, then the
database; check every API replica is ready, the old token still signs in, the file comes back with its
SHA-256 and the rows of source, source_file, audit_log and schema_migration are as many as before. Then the
way back from a lost pepper: a new one, every key revoked, a second bootstrap whose token signs in. At the
end - passed or not - the drill's project goes with its volumes. Tokens stay in memory: they never reach a
command line or the output, which holds counts and, last, "restore drill passed". Exit code 0 or 1.

Standard library only: it runs on the host, beside docker, not in an image.
"""

import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "data" / "backup"
COMPOSE_FILE = "deploy/docker-compose.yml"
_COMPOSE_TEXT = (ROOT / COMPOSE_FILE).read_text(encoding="utf-8")
_NAME = re.search(r"^name: (\S+)$", _COMPOSE_TEXT, re.MULTILINE)
_POSTGRES = re.search(r"^  postgres:\n(?:    .*\n)*?    image: (\S+)$", _COMPOSE_TEXT, re.MULTILINE)
_USER = re.search(r"^      POSTGRES_USER: (\S+)$", _COMPOSE_TEXT, re.MULTILINE)
_DB = re.search(r"^      POSTGRES_DB: (\S+)$", _COMPOSE_TEXT, re.MULTILINE)
assert _NAME and _POSTGRES and _USER and _DB  # noqa: S101 - the Compose file of this repository
REAL_PROJECT = _NAME.group(1)
# the archive is made by the image Compose pins for PostgreSQL: no further image to trust
IMAGE = _POSTGRES.group(1)
# the superuser and the database the postgres image makes on its first start
DB_USER = _USER.group(1)
DB_NAME = _DB.group(1)
PROJECT = "curricarta-drill"
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", COMPOSE_FILE]
OBJECTS = f"{PROJECT}_miniodata"
BASE_URL = "http://127.0.0.1:18080"
TABLES = ("source", "source_file", "audit_log", "schema_migration")
WAIT_S = 240
READY = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/ready', timeout=5)"
# a token as app.core.tokens makes it, wherever a command's error output might show one
_TOKEN = re.compile(r"curricarta_[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class Ran:
    code: int
    out: bytes
    err: bytes = b""


Runner = Callable[[list[str], bytes | None], Ran]
# method, path, token, body, content type -> status (0: no answer), body
Http = Callable[[str, str, str | None, bytes | None, str | None], tuple[int, bytes]]


def _tar(options: list[str], *arguments: str) -> list[str]:
    """tar in the image Compose pins for PostgreSQL, with the docker options that mount the volume."""
    return ["docker", "run", "--rm", *options, IMAGE, "tar", "--numeric-owner", *arguments]


class DrillFailed(Exception):
    """A step did not do what it should; the message names the step, never a token."""


class Drill:
    def __init__(self, run: Runner, http: Http, backup: Path, sleep: Callable[[float], None]) -> None:
        self._run, self._http, self._sleep = run, http, sleep
        self.folder = backup / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    def must(self, args: list[str], stdin: bytes | None = None) -> bytes:
        ran = self._run(args, stdin)
        if ran.code != 0:
            tail = "\n".join(ran.err.decode(errors="replace").splitlines()[-10:])
            print(_TOKEN.sub("[token]", tail), file=sys.stderr)
            raise DrillFailed(f"{' '.join(args)} ended with {ran.code}")
        return ran.out

    def sql(self, statement: str) -> str:
        psql = ["psql", "-U", DB_USER, "-d", DB_NAME, "-At", "-v", "ON_ERROR_STOP=1", "-c"]
        return self.must([*COMPOSE, "exec", "-T", "postgres", *psql, statement]).decode().strip()

    def rows(self) -> str:
        counted = ", ".join(f"(SELECT count(*) FROM {table})" for table in TABLES)  # noqa: S608 - TABLES
        counts = self.sql(f"SELECT {counted}")
        return " ".join(f"{table}={count}" for table, count in zip(TABLES, counts.split("|"), strict=True))

    def wait(self, what: str, check: Callable[[], bool]) -> None:
        deadline = time.monotonic() + WAIT_S
        while not check():
            if time.monotonic() > deadline:
                raise DrillFailed(f"{what} not within {WAIT_S} s")
            self._sleep(2)

    def ready(self) -> None:
        """The web server answers, and /ready on every API replica's internal port."""
        self.wait(
            "the API behind the web server",
            lambda: self._http("GET", "/api/v1/info", None, None, None)[0] == 200,
        )
        replicas = len(self.must([*COMPOSE, "ps", "-q", "api"]).split())
        if replicas == 0:
            raise DrillFailed("no API replica runs")
        for index in range(1, replicas + 1):
            self.wait(f"/ready of API replica {index}", partial(self.replica_ready, index))

    def replica_ready(self, index: int) -> bool:
        probe = [*COMPOSE, "exec", "-T", "--index", str(index), "api", "python", "-c", READY]
        return self._run(probe, None).code == 0

    def bootstrap(self, name: str, compose: list[str]) -> str:
        lines = self.must([*compose, "run", "--rm", "-T", "migrate", "python", "-m", "app.bootstrap", name])
        token = (lines.decode().strip().splitlines() or [""])[-1].strip()
        if not token.startswith("curricarta_"):
            raise DrillFailed(f"the bootstrap of {name} gave no token")
        return token

    def status(self, method: str, path: str, token: str) -> tuple[int, bytes]:
        return self._http(method, path, token, None, None)

    def upload(self, token: str) -> tuple[str, str]:
        """A generated PDF uploaded: the source's id and the file's SHA-256."""
        pdf = (
            b"%PDF-1.7\n"
            + b"% a page of the restore drill, filled with nothing but this line\n" * 64
            + b"%%EOF\n"
        )
        boundary = "drill" + secrets.token_hex(8)
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="drill.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode()
            + pdf
            + f"\r\n--{boundary}--\r\n".encode()
        )
        kind = f"multipart/form-data; boundary={boundary}"
        status, answer = self._http("POST", "/api/v1/sources", token, body, kind)
        if status != 201:
            raise DrillFailed(f"the upload answered {status}")
        source = json.loads(answer)
        digest = hashlib.sha256(pdf).hexdigest()
        if source["file"]["sha256"] != digest:
            raise DrillFailed("the upload stored other bytes than were sent")
        return str(source["id"]), digest

    def archive(self, name: str, data: bytes) -> int:
        if not data:
            raise DrillFailed(f"{name} is empty")
        # named only once whole, as the document's script does: an interrupted write leaves a .part
        part = self.folder / f"{name}.part"
        part.write_bytes(data)
        part.replace(self.folder / name)
        return len(data)

    def pepper_lost(self, old: str) -> int:
        """A new pepper, every key revoked, a second bootstrap: its token signs in, the old one no more."""
        folder = self.folder / "pepper"
        folder.mkdir()
        secret = folder / "api_key_pepper"
        secret.write_text(secrets.token_urlsafe(48), encoding="ascii")
        secret.chmod(0o644)  # the containers run as other users (deploy/make-secrets.py)
        override = folder / "compose.yml"
        # a JSON string is a YAML string: a folder named with " #" or ": " stays one path
        file = json.dumps(secret.as_posix())
        override.write_text(f"secrets:\n  api_key_pepper:\n    file: {file}\n", encoding="utf-8")
        compose = [*COMPOSE, "-f", override.as_posix()]
        self.must([*compose, "up", "-d", "--no-deps", "--force-recreate", "api", "worker"])
        revoked = self.sql("UPDATE api_key SET revoked_at = now() WHERE revoked_at IS NULL")
        new = self.bootstrap("drill-admin-2", compose)
        self.ready()
        self.wait("the new token", lambda: self.status("GET", "/api/v1/me", new)[0] == 200)
        if self.status("GET", "/api/v1/me", old)[0] != 401:
            raise DrillFailed("the old token signs in after the pepper changed")
        return int(revoked.split()[-1])

    def run(self) -> None:
        self.must([*COMPOSE, "up", "-d"])
        old = self.bootstrap("drill-admin", COMPOSE)
        self.ready()
        source, digest = self.upload(old)
        before = self.rows()
        print(f"rows before the backup: {before}")

        self.folder.mkdir(parents=True)
        dumped = self.archive(
            "db.dump",
            self.must([*COMPOSE, "exec", "-T", "postgres", "pg_dump", "-U", DB_USER, "-Fc", DB_NAME]),
        )
        self.must([*COMPOSE, "stop", "minio"])
        packed = self.archive(
            "objects.tar", self.must(_tar(["-v", f"{OBJECTS}:/data:ro"], "-cf", "-", "-C", "/data", "."))
        )
        print(f"backup: db.dump {dumped} bytes, objects.tar {packed} bytes")
        self.must([*COMPOSE, "down", "-v"])

        self.must([*COMPOSE, "up", "-d", "--wait", "postgres"])
        # the volume with Compose's labels, MinIO not started: it would write a fresh state into it
        self.must([*COMPOSE, "create", "minio"])
        archive = (self.folder / "objects.tar").read_bytes()
        self.must(_tar(["-i", "-v", f"{OBJECTS}:/data"], "-xf", "-", "-C", "/data"), archive)
        restore = ["pg_restore", "-U", DB_USER, "--clean", "--if-exists", "-d", DB_NAME]
        self.must([*COMPOSE, "exec", "-T", "postgres", *restore], (self.folder / "db.dump").read_bytes())
        self.must([*COMPOSE, "up", "-d"])
        self.ready()

        if self.status("GET", "/api/v1/me", old)[0] != 200:
            raise DrillFailed("the old token no longer signs in")
        status, data = self.status("GET", f"/api/v1/sources/{source}/file", old)
        if status != 200 or hashlib.sha256(data).hexdigest() != digest:
            raise DrillFailed(f"the file came back otherwise ({status})")
        after = self.rows()
        print(f"rows after the restore: {after}")
        if after != before:
            raise DrillFailed("the restore holds other rows than the backup")
        print(f"keys revoked after the pepper was lost: {self.pepper_lost(old)}")


def drill(run: Runner, http: Http, backup: Path, *, sleep: Callable[[float], None] = time.sleep) -> int:
    label = f"label=com.docker.compose.project={REAL_PROJECT}"
    running = run(["docker", "ps", "-q", "--filter", label], None)
    if running.code != 0:
        print("docker does not answer", file=sys.stderr)
        return 1
    if running.out.strip():
        print(
            f"the project {REAL_PROJECT} runs: it holds port 18080 and the subnet; stop it first",
            file=sys.stderr,
        )
        return 1
    # stopped but not removed, its network still holds the subnet the drill's would take
    networks = run(["docker", "network", "ls", "-q", "--filter", label], None)
    if networks.code != 0:
        print("docker does not answer", file=sys.stderr)
        return 1
    if networks.out.strip():
        print(
            f"the network of the project {REAL_PROJECT} remains: it holds the subnet; remove it first"
            f" (docker compose -f {COMPOSE_FILE} down)",
            file=sys.stderr,
        )
        return 1
    steps = Drill(run, http, backup, sleep)
    passed = False
    try:
        steps.run()
        passed = True
    except DrillFailed as failure:
        print(f"restore drill failed: {failure}", file=sys.stderr)
    finally:
        removed = run([*COMPOSE, "down", "-v"], None).code == 0
        shutil.rmtree(steps.folder / "pepper", ignore_errors=True)
    if not removed:
        # its network would keep the subnet, and the next start of the real project would fail on it
        print(
            f"the project {PROJECT} remains; remove it with: {' '.join([*COMPOSE, 'down', '-v'])}",
            file=sys.stderr,
        )
        return 1
    if not passed:
        return 1
    print("restore drill passed")
    return 0


def run_command(args: list[str], stdin: bytes | None) -> Ran:
    """docker, from the repository root; what it writes is kept, for the drill to judge."""
    if stdin is None:
        ran = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, cwd=ROOT, check=False)  # noqa: S603
    else:
        ran = subprocess.run(args, input=stdin, capture_output=True, cwd=ROOT, check=False)  # noqa: S603
    return Ran(ran.returncode, ran.stdout, ran.stderr)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # the drill's own machine, no proxy


def request(
    method: str, path: str, token: str | None, body: bytes | None, kind: str | None
) -> tuple[int, bytes]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if kind:
        headers["Content-Type"] = kind
    asked = urllib.request.Request(BASE_URL + path, data=body, method=method, headers=headers)  # noqa: S310
    try:
        with _OPENER.open(asked, timeout=30) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except OSError:
        return 0, b""


if __name__ == "__main__":
    sys.exit(drill(run_command, request, BACKUP))
