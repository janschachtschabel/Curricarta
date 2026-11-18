"""The store for coroutines: a call of the blocking store runs in a thread, never in the loop.

A held loop answers no request and renews no lease; a file's fsync or an S3 request takes long
enough for that.
"""

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

import pytest

from app.core.storage import FileSystemStorage, ObjectNotFound, ObjectStream
from app.core.storage_async import AsyncStorage
from tests.support import loop_watch

# How long a slow call holds its thread. The loop's longest pause is held under half of it: a call in
# the loop would hold it that long, while the loop's own pauses, a few milliseconds, stay under the
# bound on a busy runner too - a time is what the test holds, with a margin of a hundred times them
SLOW_S = 1.0


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


class SlowStore:
    """Each call holds its thread, as a slow disk or service would."""

    def put(self, key: str, data: bytes) -> None:
        time.sleep(SLOW_S)

    def put_file(self, key: str, source: BinaryIO, size: int) -> None:
        time.sleep(SLOW_S)

    def get(self, key: str) -> bytes:
        time.sleep(SLOW_S)
        return b""

    def exists(self, key: str) -> bool:
        time.sleep(SLOW_S)
        return True

    def delete(self, key: str) -> None:
        time.sleep(SLOW_S)

    def open_stream(self, key: str) -> ObjectStream:
        time.sleep(SLOW_S)
        return ObjectStream(0, iter([]), lambda: None)

    def list(self, prefix: str) -> Iterator[str]:
        time.sleep(SLOW_S)  # a call, as S3 answers it
        yield from ()


class ThreadNotingStore(FileSystemStorage):
    """A file system store that notes the thread each opening and each piece is read in."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.threads: list[int] = []
        self.closed_in: list[int] = []

    def open_stream(self, key: str) -> ObjectStream:
        self.threads.append(threading.get_ident())
        stream = super().open_stream(key)

        def noted() -> Iterator[bytes]:
            for piece in stream:
                self.threads.append(threading.get_ident())
                yield piece

        def close() -> None:
            self.closed_in.append(threading.get_ident())
            stream.close()

        return ObjectStream(stream.size, noted(), close)


def test_an_object_is_streamed_each_piece_in_a_thread(tmp_path: Path) -> None:
    store = ThreadNotingStore(tmp_path)
    data = b"x" * (2 * 2**20 + 7)
    store.put("sources/big.pdf", data)

    async def streamed() -> tuple[int | None, bytes, int]:
        stream = await AsyncStorage(store).open_stream("sources/big.pdf")
        return stream.size, b"".join([piece async for piece in stream]), threading.get_ident()

    size, read, loop_thread = run(streamed())

    assert (size, read) == (len(data), data)
    assert len(store.threads) == 1 + 3 and loop_thread not in store.threads
    store.delete("sources/big.pdf")  # closed at the end: Windows deletes no open file


def test_a_stream_let_go_early_closes_its_object_in_a_thread(tmp_path: Path) -> None:
    # closing an S3 body may wait on its connection: not in the loop
    store = ThreadNotingStore(tmp_path)
    store.put("sources/big.pdf", b"x" * (2 * 2**20))

    async def one_piece() -> int:
        stream = await AsyncStorage(store).open_stream("sources/big.pdf")
        async for _ in stream:
            break
        await stream.aclose()
        await stream.aclose()  # once is enough, twice does no harm
        return threading.get_ident()

    loop_thread = run(one_piece())

    assert len(store.closed_in) == 1 and loop_thread not in store.closed_in
    store.delete("sources/big.pdf")  # Windows deletes no open file


def test_a_missing_object_is_not_found_before_its_stream(tmp_path: Path) -> None:
    with pytest.raises(ObjectNotFound):
        run(AsyncStorage(FileSystemStorage(tmp_path)).open_stream("sources/missing.txt"))


def test_the_calls_reach_the_store(tmp_path: Path) -> None:
    store = AsyncStorage(FileSystemStorage(tmp_path))

    async def calls() -> tuple[bool, bytes, bytes]:
        await store.put("sources/ab.txt", b"text")
        await store.put_file("sources/cd.txt", BytesIO(b"streamed"), 8)
        read = await store.get("sources/cd.txt")
        return await store.exists("sources/ab.txt"), await store.get("sources/ab.txt"), read

    assert run(calls()) == (True, b"text", b"streamed")
    run(store.delete("sources/ab.txt"))
    assert not (tmp_path / "sources" / "ab.txt").exists()


def test_the_keys_under_a_prefix_come_whole(tmp_path: Path) -> None:
    # read to their end in the thread: S3 lists a page a request
    sync = FileSystemStorage(tmp_path)
    for key in ("runs/a/x4/1.json", "runs/a/x4/3.json", "runs/ab/1.json"):
        sync.put(key, b"{}")

    assert sorted(run(AsyncStorage(sync).list("runs/a/"))) == ["runs/a/x4/1.json", "runs/a/x4/3.json"]


def test_the_store_s_errors_come_through_as_they_are(tmp_path: Path) -> None:
    with pytest.raises(ObjectNotFound):
        run(AsyncStorage(FileSystemStorage(tmp_path)).get("sources/missing.txt"))


@pytest.mark.parametrize("call", ["put", "put_file", "get", "exists", "delete", "list"])
def test_a_slow_store_does_not_hold_the_loop(call: str) -> None:
    store = AsyncStorage(SlowStore())
    calls: dict[str, Callable[[], Awaitable[object]]] = {
        "put": lambda: store.put("a", b"x"),
        "put_file": lambda: store.put_file("a", BytesIO(b"x"), 1),
        "get": lambda: store.get("a"),
        "exists": lambda: store.exists("a"),
        "delete": lambda: store.delete("a"),
        "list": lambda: store.list("a/"),
    }

    async def measured() -> float:
        async with loop_watch() as longest:
            await calls[call]()
        return longest[0]

    assert run(measured()) < SLOW_S / 2
