"""The memory of the app's child processes (audit 2026-11-14): CHILD_MEMORY_LIMIT_MB, opt-in, bounds a
child's address space (RLIMIT_AS) as it starts - on Linux alone; elsewhere the limit is passed over, and
without it the child is left alone. Each child says its peak memory as one line, numbers only.

The tests of the limit itself run on Linux (the CI); the others run everywhere."""

import logging
import re
import sys
from pathlib import Path

import pytest

from app.conversion.runners import convert_in_child
from app.core import child
from app.core.child import ChildLog, limit_memory, log_peak, run_in_child, stand_alone, write
from tests.support import make_settings

pytestmark = pytest.mark.anyio
MIB = 1024 * 1024
FIXTURES = Path(__file__).resolve().parents[1] / "conversion" / "fixtures"
LINUX = pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS is applied on Linux alone")
PEAK = re.compile(r"peak memory: rss=\d+ MiB, virtual=\d+ MiB")


def allocating(told: ChildLog, out: str) -> None:
    """The child: two GiB at once, and what came of it."""
    stand_alone(told, ())
    try:
        held = bytearray(2 * 1024 * MIB)
    except MemoryError:
        write(Path(out) / "said.txt", "MemoryError")
        return
    write(Path(out) / "said.txt", f"allocated {len(held)}")


def telling_its_limit(told: ChildLog, out: str) -> None:
    """The child: its address space's soft limit, as it stands once it started."""
    stand_alone(told, ())
    if sys.platform != "win32":  # the test runs on Linux alone
        import resource

        write(Path(out) / "said.txt", str(resource.getrlimit(resource.RLIMIT_AS)[0]))


def said(_: int | None, out: Path) -> str:
    return (out / "said.txt").read_text(encoding="utf-8")


def told(memory_mb: int | None) -> ChildLog:
    return ChildLog(level="WARNING", format="text", request_id="-", memory_mb=memory_mb)


@LINUX
async def test_a_child_past_its_memory_limit_fails_inside_itself() -> None:
    # the allocation fails in the child, which may say so; the kernel kills no process for it
    assert await run_in_child(allocating, (told(512),), prefix="memory-", read=said) == "MemoryError"


@LINUX
async def test_the_limit_reaches_the_child_as_it_starts() -> None:
    assert await run_in_child(telling_its_limit, (told(512),), prefix="memory-", read=said) == str(512 * MIB)


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The limits set on the address space, the system's call left out: the test's process keeps its own."""
    set_: list[int] = []
    monkeypatch.setattr(child, "_set_address_space", set_.append)
    return set_


def test_a_limit_is_set_in_bytes_on_linux(monkeypatch: pytest.MonkeyPatch, limits: list[int]) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    limit_memory(512)

    assert limits == [512 * MIB]


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_without_a_limit_the_child_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, limits: list[int], caplog: pytest.LogCaptureFixture, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    with caplog.at_level(logging.INFO, logger="app.core.child"):
        limit_memory(None)

    assert (limits, caplog.messages) == ([], [])


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_where_the_platform_has_no_such_limit_it_is_passed_over(
    monkeypatch: pytest.MonkeyPatch, limits: list[int], caplog: pytest.LogCaptureFixture, platform: str
) -> None:
    # Windows has no RLIMIT_AS, macOS does not hold to it: the containers' limits are the first line.
    # The child says nothing of it: the service says it once (below)
    monkeypatch.setattr(sys, "platform", platform)

    with caplog.at_level(logging.INFO, logger="app.core.child"):
        limit_memory(512)

    assert (limits, caplog.messages) == ([], [])


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_the_service_says_once_that_the_limit_is_not_applied_on_its_platform(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(child, "_unapplied_said", False)
    bounded = make_settings(child_memory_limit_mb=1024)

    with caplog.at_level(logging.WARNING, logger="app.core.child"):
        ChildLog.of(bounded)
        ChildLog.of(bounded)

    assert caplog.messages == [f"CHILD_MEMORY_LIMIT_MB is not applied on {platform}"]


@pytest.mark.parametrize(("platform", "memory_mb"), [("linux", 1024), ("win32", None)])
def test_where_the_limit_holds_or_none_is_set_the_service_says_nothing_of_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, platform: str, memory_mb: int | None
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(child, "_unapplied_said", False)

    with caplog.at_level(logging.WARNING, logger="app.core.child"):
        ChildLog.of(make_settings(child_memory_limit_mb=memory_mb))

    assert caplog.messages == []


def test_the_child_s_start_hands_its_limit_on(monkeypatch: pytest.MonkeyPatch) -> None:
    # in the test's process: as win32, stand_alone starts no group and leaves the OOM score alone
    handed: list[int | None] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(child, "configure_logging", lambda *_, **__: None)
    monkeypatch.setattr(child, "limit_memory", handed.append)

    stand_alone(told(768), ())

    assert handed == [768]


def test_the_service_s_settings_reach_the_child() -> None:
    settings = make_settings(log_level="DEBUG", log_format="json", child_memory_limit_mb=2048)

    assert ChildLog.of(settings) == ChildLog(level="DEBUG", format="json", request_id="-", memory_mb=2048)
    assert ChildLog.of(make_settings()).memory_mb is None


def test_the_peak_is_said_as_the_kernel_states_it(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    status = tmp_path / "status"
    status.write_text(
        "Name:\tpython\nVmPeak:\t 2097152 kB\nVmSize:\t 1048576 kB\n"
        "VmHWM:\t  524288 kB\nVmRSS:\t 262144 kB\n",
        encoding="ascii",
    )

    with caplog.at_level(logging.INFO, logger="app.core.child"):
        log_peak(status)

    assert caplog.messages == ["peak memory: rss=512 MiB, virtual=2048 MiB"]


@pytest.mark.parametrize("text", [None, "Name:\tpython\n", "VmPeak:\t many kB\nVmHWM:\t 1 kB\n"])
def test_no_peak_is_said_where_the_kernel_states_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, text: str | None
) -> None:
    status = tmp_path / "status"
    if text is not None:
        status.write_text(text, encoding="ascii")

    with caplog.at_level(logging.INFO, logger="app.core.child"):
        log_peak(status)

    assert caplog.messages == []


def test_a_peak_the_full_heap_cannot_read_is_said_by_no_line_and_raises_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # at the limit the status file's reading fails as the conversion did: the outcome in flight stays
    def wanting(*_: object, **__: object) -> str:
        raise MemoryError

    monkeypatch.setattr(Path, "read_text", wanting)

    with caplog.at_level(logging.INFO, logger="app.core.child"):
        log_peak(Path("status"))

    assert caplog.messages == []


@pytest.mark.skipif(sys.platform != "linux", reason="Linux's /proc states the peak")
async def test_a_child_says_its_peak_memory_and_nothing_of_the_file(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    secret = tmp_path / "geheim-lehrplan.pdf"
    secret.write_bytes((FIXTURES / "prose.pdf").read_bytes())
    logged = ChildLog(level="INFO", format="text", request_id="-")

    await convert_in_child(secret, engine="pdfplumber", max_pages=10, child_log=logged)

    err = capfd.readouterr().err
    [line] = [line for line in err.splitlines() if "peak memory" in line]
    assert PEAK.search(line)
    assert "geheim" not in err
