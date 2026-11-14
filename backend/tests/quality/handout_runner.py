"""How the rehearsal (tests/quality/test_rehearsal.py) runs the operator's handout (tests/quality/
handout.py): each command a process of the test's interpreter, the part after ``PREFIX`` in ``backend/``
as the worker's image runs it, several at once from threads.

The processes' environment is built once, on the thread that makes the runner, from a copy of the test's
environment without any settings variable (tests/support.py ``environment_without_settings``) and the
runner's own test values: no thread touches ``os.environ``, so no process can inherit the machine's keys
or start with half an environment, and the test's environment stays as it was. A failing command's words
reach an assertion cut to their last lines (``told``), a line naming an input value left out."""

import asyncio
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from app.quality.sheet import LOCAL_FOLDER
from tests.quality.handout import COMMANDS, PREFIX
from tests.support import environment_without_settings

BACKEND = Path(__file__).resolve().parents[2]
CAP = 4_000  # the stand-in's cap on an answer (tests/pipeline/test_run.py context_of), the estimate's too
# the MEM endpoint as the commands are told it: not public, so the pinned transport refuses it before
# anything is sent - the switch reaches for it, and nothing goes over the network
NOT_PUBLIC = "https://127.0.0.1/sparql"
_LAST_LINES = 8


def told(stderr: bytes) -> str:
    """A process's words for an assertion: the last lines, any naming an input value left out (a settings
    error quotes the value it refused)."""
    lines = stderr.decode("utf-8", errors="replace").splitlines()[-_LAST_LINES:]
    left_out = "[a line naming an input value, left out]"
    return "\n".join(left_out if "input_value" in line else line for line in lines)


@dataclass
class Operator:
    """Runs the handout's commands as an operator types them: the words in angle brackets filled in,
    ``> file`` and ``< file`` - which must lie under the local gold folder - in a temporary folder in its
    place; each command run is noted (``ran``)."""

    database_url: str
    store: Path
    folder: Path
    values: dict[str, str]
    ran: list[str] = field(default_factory=list)
    settings: dict[str, str] = field(init=False)  # the settings variables the processes get
    _environment: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.settings = {
            "DATABASE_URL": self.database_url, "STORAGE_DIR": str(self.store), "OPENAI_MODEL": "gpt-6-luna",
            "LLM_MAX_OUTPUT_TOKENS": str(CAP), "MEM_SPARQL_URL": NOT_PUBLIC,
        }  # fmt: skip
        self._environment = environment_without_settings() | self.settings

    def _filled(self, word: str, values: dict[str, str]) -> str:
        return re.sub(r"<([^<>\s]+)>", lambda name: values[name[1]], word)

    def _local(self, word: str, values: dict[str, str]) -> Path:
        path = PurePosixPath(self._filled(word, values))
        # the handout's rule: sheets lie there alone
        assert path.is_relative_to(LOCAL_FOLDER.as_posix()), path
        return self.folder / path.relative_to(LOCAL_FOLDER.as_posix())

    def _started(self, arguments: Sequence[str], data: bytes | None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - the interpreter running the tests, the handout's own words
            [sys.executable, *arguments],
            cwd=BACKEND,
            env=self._environment,
            input=data,
            capture_output=True,
            timeout=300,
            check=False,
        )

    def _run(self, name: str, values: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
        assert COMMANDS[name].startswith(PREFIX), name  # run as the worker's image runs it
        words = shlex.split(COMMANDS[name].removeprefix(PREFIX))
        assert words[:2] == ["python", "-m"], words
        written = read = None
        if ">" in words:
            at = words.index(">")
            written, words = self._local(words[at + 1], values), words[:at] + words[at + 2 :]
        if "<" in words:
            at = words.index("<")
            read, words = self._local(words[at + 1], values), words[:at] + words[at + 2 :]
        arguments = [self._filled(word, values) for word in words[1:]]
        done = self._started(arguments, None if read is None else read.read_bytes())
        if written is not None and done.returncode == 0:
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_bytes(done.stdout)  # what the shell's > would have written
        return done

    async def process(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        """The interpreter with ``arguments``, as the commands are started (tests of the runner)."""
        return await asyncio.to_thread(self._started, arguments, None)

    async def run(self, name: str, **values: str) -> subprocess.CompletedProcess[bytes]:
        self.ran.append(name)
        return await asyncio.to_thread(self._run, name, self.values | values)

    async def json(self, name: str, **values: str) -> Any:
        done = await self.run(name, **values)
        assert done.returncode == 0, (name, told(done.stderr))
        return json.loads(done.stdout)
