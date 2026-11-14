"""docs/uebergabe/sicherung.md tells the operators what to back up, in which order, how to restore and how
to roll back (audit 2026-11-14). What it names - Compose's services and volumes, the secrets, the store's
prefixes - is read here against the code, so the document cannot drift from what a restore needs.
tests/deploy/test_restore_drill.py guards the script that runs the restore once."""

import re
import shlex
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from app.core.config_doc import setting_rows

ROOT = Path(__file__).resolve().parents[3]
DOC = (ROOT / "docs" / "uebergabe" / "sicherung.md").read_text(encoding="utf-8")
COMPOSE: dict[str, Any] = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
# the subcommands whose arguments name services, and the options among theirs that take a value
SERVICE_VERBS = {"create", "exec", "run", "start", "stop", "restart", "up"}
VALUED = {"--index", "-e", "-u", "--user", "-w", "--workdir"}


SETUP = ["set -eu", "export MSYS_NO_PATHCONV=1"]


def _blocks() -> tuple[list[str], list[str]]:
    """The commands of the document's two scripts for Compose: the backup, the restore."""
    section = DOC[DOC.index("## Befehle für Compose") :].split("\n## ", 1)[0]
    blocks = [
        [line for line in block.splitlines() if line.strip() and not line.startswith("#")]
        for block in re.findall(r"```bash\n(.*?)```", section, re.DOTALL)
    ]
    assert len(blocks) == 2
    return blocks[0], blocks[1]


def _block() -> list[str]:
    """Every command of both scripts, those a trap runs among them."""
    lines: list[str] = []
    for line in [*_blocks()[0], *_blocks()[1]]:
        words = shlex.split(line, posix=True)
        lines.append(shlex.join(shlex.split(words[1])) if words[0] == "trap" else line)
    return lines


def _services(words: list[str]) -> set[str]:
    """The services a ``docker compose -f … <verb> …`` line names."""
    verb = next(index for index, word in enumerate(words) if word in SERVICE_VERBS)
    named: set[str] = set()
    skip = False
    for word in words[verb + 1 :]:
        if word in {">", "<", "|"}:
            break
        if skip:
            skip = False
        elif word in VALUED:
            skip = True
        elif not word.startswith("-"):
            named.add(word)
            if words[verb] in {"exec", "run"}:
                break  # what follows is the command run in it
    return named


def test_every_service_and_volume_the_commands_name_is_one_compose_has() -> None:
    project = COMPOSE["name"]
    services: set[str] = set()
    volumes: set[str] = set()
    images: set[str] = set()
    for line in _block():
        words = shlex.split(line, posix=True)
        if words[:2] == ["docker", "compose"]:
            assert words[2:4] == ["-f", "deploy/docker-compose.yml"], line
            if any(word in SERVICE_VERBS for word in words):
                services |= _services(words)
        volumes |= {name for name in re.findall(r"\b(\S+?)(?=:/)", line) if name.startswith(f"{project}_")}
        volumes |= {word for word in words if word.startswith(f"{project}_") and ":" not in word}
        if words[:3] == ["docker", "run", "--rm"]:
            images |= {word for word in words if "@sha256:" in word}

    assert {"postgres", "minio"} <= services
    assert services <= set(COMPOSE["services"])
    assert volumes == {f"{project}_{volume}" for volume in ("pgdata", "miniodata")}
    assert {volume.removeprefix(f"{project}_") for volume in volumes} <= set(COMPOSE["volumes"])
    # the archive is made by an image Compose pins already: no further image to trust
    assert images == {COMPOSE["services"]["postgres"]["image"]}


def test_the_block_stops_at_the_first_failure_and_hands_docker_its_paths_unchanged() -> None:
    # without set -e a failed unpack is followed by pg_restore and up -d: a restore silently partial;
    # set -u stops at a folder never named; Git Bash rewrites "/data" in docker's arguments to a
    # Windows path unless told not to. Each script runs alone, so each says so itself.
    backup, restore = _blocks()

    assert backup[:2] == SETUP
    assert restore[:2] == SETUP


def test_the_restore_checks_the_backup_before_it_removes_anything() -> None:
    _backup, restore = _blocks()
    destructive = next(
        index for index, line in enumerate(restore) if line.endswith(" down") or "volume rm" in line
    )
    # two lines, not joined by &&: set -e does not stop at a failing member before the last
    checks = [restore.index('test -s "$dir/db.dump"'), restore.index('test -s "$dir/objects.tar"')]

    assert restore[2].startswith('dir="data/backup/')
    assert max(checks) < destructive


def test_minio_starts_again_whatever_becomes_of_the_archive() -> None:
    backup, _restore = _blocks()
    compose = "docker compose -f deploy/docker-compose.yml"
    stop = backup.index(f"{compose} stop minio")

    assert backup[stop + 1] == f"trap '{compose} start minio' EXIT"
    assert f"{compose} start minio" not in backup


def test_the_database_s_user_and_name_are_those_compose_gives_it() -> None:
    environment = COMPOSE["services"]["postgres"]["environment"]
    clients = [shlex.split(line) for line in _block() if re.search(r"\b(pg_dump|pg_restore|psql)\b", line)]

    assert len(clients) >= 2
    for words in clients:
        assert words[words.index("-U") + 1] == environment["POSTGRES_USER"], words
        named = words[words.index("-d") + 1] if "-d" in words else words[words.index(">") - 1]
        assert named == environment["POSTGRES_DB"], words


def test_the_document_names_every_secret_a_restore_needs() -> None:
    secrets = {row.variable for row in setting_rows() if row.secret}
    scope = DOC[DOC.index("## Umfang") :].split("\n## ", 1)[0]

    assert secrets == {"DATABASE_URL", "API_KEY_PEPPER", "S3_ACCESS_KEY", "S3_SECRET_KEY", "OPENAI_API_KEY"}
    for secret in secrets:
        assert f"`{secret}`" in scope, secret


def test_the_document_names_every_prefix_the_store_holds() -> None:
    app = ROOT / "backend" / "app"
    written = {
        prefix
        for path in ("api/sources.py", "db/runs.py", "exports/mem_export.py")
        for prefix in re.findall(r'f"([a-z]+/)\{', (app / path).read_text(encoding="utf-8"))
    }
    scope = DOC[DOC.index("## Umfang") :].split("\n## ", 1)[0]

    assert written == {"sources/", "runs/", "exports/"}
    for prefix in written:
        assert f"`{prefix}`" in scope, prefix
