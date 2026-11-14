"""backend/tools/restore_drill.py restores a backup once, the way docs/uebergabe/sicherung.md has it, in a
Compose project of its own. Here it runs against a stand-in for docker and the API: every command is an
argument list the tests read, and none reaches docker. What they guard is what would hurt: a `down -v`
of the wrong project removes a developer's data, and a token printed lands in a terminal's history."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
COMPOSE: dict[str, Any] = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
OLD = "curricarta_" + "o" * 43
NEW = "curricarta_" + "n" * 43


def tool() -> Any:
    """backend/tools/restore_drill.py, which is no package: loaded by its path."""
    spec = importlib.util.spec_from_file_location(
        "restore_drill", Path(__file__).parents[2] / "tools" / "restore_drill.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


restore_drill = tool()


class World:
    """Docker and the API as the drill sees them: a stand-in that answers each command and request."""

    def __init__(self, *, real_project_running: bool = False) -> None:
        self.real_project_running = real_project_running
        self.commands: list[list[str]] = []
        self.valid = set[str]()
        self.bootstraps = [OLD, NEW]
        self.files: dict[str, bytes] = {}

    def run(self, args: list[str], stdin: bytes | None) -> Any:
        self.commands.append(list(args))
        text = " ".join(args)
        out = b""
        if args[:2] == ["docker", "ps"]:
            out = b"0123456789ab\n" if self.real_project_running else b""
        elif "app.bootstrap" in args:
            token = self.bootstraps.pop(0)
            self.valid.add(token)
            out = f"{token}\n".encode()
        elif "UPDATE api_key" in text:
            out = f"UPDATE {len(self.valid)}\n".encode()
            self.valid.clear()
        elif "count(*)" in text:
            out = b"1|1|4|31\n"
        elif args[-2:] == ["-q", "api"]:
            out = b"aaaa\nbbbb\n"
        elif "pg_dump" in args:
            out = b"PGDMP-stand-in"
        elif "-cf" in args:
            out = b"tar-stand-in"
        return restore_drill.Ran(0, out)

    def http(self, method: str, path: str, token: str | None, body: bytes | None, kind: str | None) -> Any:
        if path == "/api/v1/info":
            return 200, b"{}"
        if token not in self.valid:
            return 401, b"{}"
        if method == "POST" and path == "/api/v1/sources":
            assert body is not None and kind is not None and kind.startswith("multipart/form-data")
            pdf = body[body.index(b"%PDF-1.7") : body.rindex(b"\r\n--")]
            self.files["s1"] = pdf
            answer = {"id": "s1", "file": {"sha256": hashlib.sha256(pdf).hexdigest()}}
            return 201, json.dumps(answer).encode()
        if path == "/api/v1/me":
            return 200, b"{}"
        if path == "/api/v1/sources/s1/file":
            return 200, self.files["s1"]
        return 404, b"{}"


def drill(world: World, backup: Path) -> int:
    code: int = restore_drill.drill(world.run, world.http, backup, sleep=lambda _seconds: None)
    return code


@pytest.fixture
def ran(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[World, int, str]:
    world = World()
    code = drill(world, tmp_path)
    captured = capsys.readouterr()
    return world, code, captured.out + captured.err


def test_the_drill_passes_where_every_step_answers(ran: tuple[World, int, str]) -> None:
    _world, code, output = ran

    assert code == 0
    assert output.strip().splitlines()[-1] == "restore drill passed"


def test_every_compose_call_is_the_drill_s_own_project(ran: tuple[World, int, str]) -> None:
    world, _code, _output = ran
    compose = [args for args in world.commands if args[:2] == ["docker", "compose"]]

    assert len(compose) > 10
    for args in compose:
        assert args[2:6] == ["-p", "curricarta-drill", "-f", "deploy/docker-compose.yml"], args


def test_volumes_are_removed_for_the_drill_s_project_alone(ran: tuple[World, int, str]) -> None:
    world, _code, _output = ran
    removing = [args for args in world.commands if "down" in args and "-v" in args]

    assert len(removing) >= 2  # between backup and restore, and at the end
    for args in removing:
        assert args[:4] == ["docker", "compose", "-p", "curricarta-drill"], args
    assert not [args for args in world.commands if args[:3] == ["docker", "volume", "rm"]]


def test_it_refuses_to_run_beside_the_real_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World(real_project_running=True)

    code = drill(world, tmp_path)

    assert code == 1
    assert world.commands == [
        ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={COMPOSE['name']}"]
    ]
    assert "curricarta" in capsys.readouterr().err


def test_the_archive_is_made_with_an_image_compose_pins(ran: tuple[World, int, str]) -> None:
    world, _code, _output = ran
    archives = [args for args in world.commands if args[:2] == ["docker", "run"] and "tar" in args]
    pinned = COMPOSE["services"]["postgres"]["image"]

    assert len(archives) == 2  # made, unpacked
    for args in archives:
        assert pinned in args, args
        assert "@sha256:" in pinned
        assert any(arg.startswith("curricarta-drill_miniodata:/data") for arg in args), args


def test_the_token_is_never_printed(ran: tuple[World, int, str]) -> None:
    world, code, output = ran

    assert code == 0
    assert "curricarta_" not in output
    # nor handed to a command, where a process list would show it
    assert not [args for args in world.commands if any(token in " ".join(args) for token in (OLD, NEW))]


def test_the_token_is_never_printed_when_a_step_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    world.http = lambda method, path, token, body, kind: (  # type: ignore[method-assign]
        (200, b"{}") if path == "/api/v1/info" else (500, f"echo {token}".encode())
    )

    code = drill(world, tmp_path)

    captured = capsys.readouterr()
    assert code == 1
    assert "curricarta_" not in captured.out + captured.err
    assert world.commands[-1][-2:] == ["down", "-v"]  # it cleans up after a failure too


def test_the_backup_lies_where_git_and_the_images_never_look() -> None:
    backup = restore_drill.BACKUP
    relative = backup.relative_to(ROOT).as_posix()
    dump = f"{relative}/20261114T120000Z/db.dump"
    ignored = subprocess.run(  # noqa: S603 - git of this machine, a path of the repository
        ["git", "check-ignore", "-q", dump],  # noqa: S607
        cwd=ROOT,
        check=False,
    )
    rules = [line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()]

    assert relative.startswith("data/")
    assert ignored.returncode == 0
    assert "data" in rules
    assert [rule for rule in rules if rule.startswith("!data")] == ["!data/seed"]
