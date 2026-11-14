"""Work in a child process of its own (plan M1 3.4, 8.4): what may take minutes, memory without end or
the process down - a PDF parser on an untrusted file, a SHACL validation - would stop the worker's
event loop there, and with it the job's lease.

The child is started fresh (``spawn``: the worker has threads and a loop a fork would copy half of) and
leaves its answer as files in a folder of its own, each written whole before it is renamed; the parent
reads them (``read``, given the child's exit code) and removes the folder. Whatever ends the waiting -
the job cancelled, its deadline (``asyncio.timeout`` around the call), its lease lost - kills the child
at once. On POSIX the child leads a process group of its own, which is killed whole, so nothing it
started outlives it; on Linux the kernel takes it before the worker when memory runs out. Windows has no
process groups: there a grandchild would outlive it.

The containers' memory limits are the first line against a child that takes memory without end. Beside
them CHILD_MEMORY_LIMIT_MB (opt-in, no default; audit 2026-11-14) bounds each child's address space
(RLIMIT_AS) as it starts, on Linux alone: an allocation past it fails in the child, which ends by its own
outcome rather than the kernel's kill. RLIMIT_AS counts virtual memory, not what is resident: the limit is
sized at twice the virtual peak measured, which each child says as it ends (``log_peak``), never by RSS.
"""

import asyncio
import contextlib
import logging
import multiprocessing
import os
import shutil
import signal
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from app.core.logging import configure_logging, current_request_id, set_request_id

if TYPE_CHECKING:
    from app.core.settings import Settings

log = logging.getLogger(__name__)
POLL_S = 0.2  # how often the waiting asks whether the child is done
KILLED = -9  # the exit code of a process ended by SIGKILL, which Windows does not name
KILL_WAIT_S = 5.0
MIB = 1024 * 1024
STATUS = Path("/proc/self/status")  # where Linux states a process's peaks
_unapplied_said = False  # whether this process said CHILD_MEMORY_LIMIT_MB does not hold on its platform


@dataclass(frozen=True)
class ChildLog:
    """How the child logs: the service's level and format, and the request of the job it serves."""

    level: str
    format: str
    request_id: str
    memory_mb: int | None = None  # CHILD_MEMORY_LIMIT_MB: the child's address space, None for no bound

    @classmethod
    def of(cls, settings: "Settings") -> Self:
        """As the service logs, under the current request, bounded as the service's settings say - where
        the platform holds no such bound, said once by the service, not by each child."""
        global _unapplied_said  # once a process, as the module's logger is
        if settings.child_memory_limit_mb is not None and sys.platform != "linux" and not _unapplied_said:
            _unapplied_said = True
            log.warning("CHILD_MEMORY_LIMIT_MB is not applied on %s", sys.platform)
        return cls(
            settings.log_level, settings.log_format, current_request_id(), settings.child_memory_limit_mb
        )


async def run_in_child[T](
    target: Callable[..., None], args: tuple[Any, ...], *, prefix: str, read: Callable[[int | None, Path], T]
) -> T:
    """``target(*args, out)`` in a child process; what ``read(exit_code, out)`` makes of the folder
    ``out`` it leaves its answer in - read in a thread, before the folder goes."""
    # one mkdir, made here: in a thread, a cancel meanwhile would leave the folder behind
    out = Path(tempfile.mkdtemp(prefix=prefix))
    child = multiprocessing.get_context("spawn").Process(target=target, args=(*args, str(out)), daemon=True)
    try:
        child.start()
        try:
            while child.is_alive():
                await asyncio.sleep(POLL_S)
        except BaseException:
            _kill(child)  # cancelled, past its deadline, or the lease lost
            raise
        child.join()
        return await asyncio.to_thread(read, child.exitcode, out)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def stand_alone(told: ChildLog, quiet: Iterable[str]) -> None:
    """The child's first act: log as the service does - the ``quiet`` libraries no more than warnings,
    their DEBUG may quote what they read - in a process group of its own, first for the kernel's OOM."""
    configure_logging(told.level, told.format, stream=sys.stderr)
    quietest = max(logging.WARNING, logging.getLogger().level)
    for name in quiet:
        logging.getLogger(name).setLevel(quietest)
    set_request_id(told.request_id)
    if sys.platform != "win32":
        os.setsid()  # a group of its own, killed whole
    if sys.platform == "linux":
        with contextlib.suppress(OSError):
            # the kernel takes this process first when memory runs out, not the worker
            Path("/proc/self/oom_score_adj").write_text("1000", encoding="ascii")
    limit_memory(told.memory_mb)


def limit_memory(memory_mb: int | None) -> None:
    """Bound this process's address space to ``memory_mb`` MiB, on Linux; elsewhere passed over - the
    service says so once (ChildLog.of)."""
    if memory_mb is None or sys.platform != "linux":  # Windows has no RLIMIT_AS, macOS does not hold to it
        return
    _set_address_space(memory_mb * MIB)


def _set_address_space(limit: int) -> None:
    if sys.platform != "win32":  # the type checker reads it; limit_memory calls this on Linux alone
        import resource

        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        # the soft limit, below a hard one the operator set: above it setrlimit refuses
        soft = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))


def said_out_of_memory(told: ChildLog) -> None:
    """In the parent, where a child's outcome is a MemoryError: the limit it ran under, if one was set -
    no word of what it worked on."""
    if told.memory_mb is not None:
        log.warning("out of memory under CHILD_MEMORY_LIMIT_MB=%d", told.memory_mb)


def log_peak(status: Path = STATUS) -> None:
    """The process's peak memory as one line at INFO, numbers only: resident (VmHWM) and virtual (VmPeak),
    the measure of CHILD_MEMORY_LIMIT_MB. Where the kernel states neither - not Linux - nothing. It never
    raises: called last, however the child ends, an error here - a MemoryError, the heap still full at the
    limit - would replace the child's outcome in flight (died, its exit code 4)."""
    try:
        stated = dict(
            line.split(":", 1) for line in status.read_text(encoding="ascii").splitlines() if ":" in line
        )
        rss, virtual = (int(stated[name].split()[0]) * 1024 // MIB for name in ("VmHWM", "VmPeak"))
        log.info("peak memory: rss=%d MiB, virtual=%d MiB", rss, virtual)
    except Exception:  # a log line, never the outcome
        return


def write(path: Path, text: str) -> None:
    """Whole or not at all: the parent reads only a renamed file."""
    part = path.with_suffix(".part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


def _kill(child: multiprocessing.process.BaseProcess) -> None:
    # sys.platform, not os.name: the type checker reads it, and checks each platform's calls
    if sys.platform != "win32" and child.pid is not None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(child.pid, signal.SIGKILL)  # the child leads its group: what it started too
    child.kill()
    child.join(KILL_WAIT_S)
    if child.is_alive():
        log.warning("the child process %s outlived its kill", child.pid)
