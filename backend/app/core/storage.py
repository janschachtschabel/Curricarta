"""Object storage for source files, raw model answers and exports.

The interface is S3's (app/core/storage_s3.py is that backend): an object is bytes under a key
such as ``sources/ab/<sha256>.pdf``. A key is plain segments of letters, digits and ``._-``
joined by ``/`` - nothing that could leave the root on a file system, whatever the caller
passed in. The file system backend writes to a temporary file beside the target and renames
it, so an object is either the old or the new one, never half of it - from bytes or from a
stream (``put_file``), which is read in pieces and never held whole.

simplify: a process killed between the two leaves a ``.tmp-*`` file, which no key can name and
nothing removes yet; a sweep at start would, should the file system backend serve more than
development and a single node (a cluster uses S3).
"""

import os
import re
import tempfile
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.settings import Settings

MAX_KEY_CHARS = 512
MAX_SEGMENT_CHARS = 255  # a file name's limit on the common file systems
CHUNK_BYTES = 2**20  # the most a read in pieces hands out at a time
_SEGMENT = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")
# The names Windows takes for devices, with any extension, in any case
_DEVICE = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", re.IGNORECASE)


class InvalidKey(ValueError):
    """The key is not plain segments joined by ``/``."""


class ObjectNotFound(KeyError):
    """No object under this key."""


class StorageNotConfigured(ValueError):
    """The settings name no usable store; the message says which setting is missing."""


class ObjectStream:
    """An object read in pieces of at most CHUNK_BYTES, with its size where the store knows it.
    Read to its end, it closes itself; a reader that stops before calls ``close``, after which
    it yields nothing more."""

    def __init__(self, size: int | None, pieces: Iterator[bytes], close: Callable[[], None]) -> None:
        self.size = size
        self._pieces = pieces
        self._close = close
        self._closed = False

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        try:
            return next(self._pieces)
        except BaseException:  # its end (StopIteration) or a failed read: either way, let go
            self.close()
            raise

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._close()

    @property
    def closed(self) -> bool:
        return self._closed


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def put_file(self, key: str, source: BinaryIO, size: int) -> None:
        """The ``size`` bytes of ``source`` from where it stands, read in pieces; ``source`` must
        be seekable (a retried S3 PUT reads them again from that place). Whole or not at all, as
        ``put``."""
        ...

    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None:
        """ObjectNotFound when the object was missing as the store looked; on S3 another process
        may delete it between the look and the deletion, so treat deleting as idempotent."""
        ...

    def open_stream(self, key: str) -> ObjectStream:
        """The object to read in pieces; ObjectNotFound as ``get`` raises it, before any piece."""
        ...

    def list(self, prefix: str) -> Iterator[str]:
        """The keys under ``prefix`` (it ends in "/"), in no promised order; InvalidKey at the call for a
        prefix no key could begin with. An object written meanwhile may be missing, or one deleted named."""
        ...


def check_key(key: str) -> str:
    """``key``, if it is plain segments joined by ``/`` that every file system holds as written.

    A segment has at most 255 signs, does not end in a dot (Windows drops it) and is no device
    name (``CON``, ``nul.json``). Keys that differ in case only are two objects in S3 but one
    file on Windows and macOS: keep keys lower case, as hashes and ids are.
    """
    segments = key.split("/")
    if not key or len(key) > MAX_KEY_CHARS or not all(_plain(segment) for segment in segments):
        raise InvalidKey(f"not a storage key: {key[:80]!r}")
    return key


def is_key(key: str) -> bool:
    """Whether a store could hold ``key``: a listing names no other (a half-written file, a folder marker)."""
    try:
        check_key(key)
    except InvalidKey:
        return False
    return True


def check_prefix(prefix: str) -> str:
    """``prefix``, if it is a key's beginning ending in "/": a place no key outside it lies under."""
    if not prefix.endswith("/"):
        raise InvalidKey(f"not a storage prefix: {prefix[:80]!r}")
    check_key(prefix[:-1])
    return prefix


def _plain(segment: str) -> bool:
    return (
        _SEGMENT.fullmatch(segment) is not None
        and len(segment) <= MAX_SEGMENT_CHARS
        and not segment.endswith(".")
        and _DEVICE.fullmatch(segment) is None
    )


def without_long_prefix(path: str) -> str:
    """A Windows path in its plain form: ``\\\\?\\C:\\…`` as ``C:\\…``, ``\\\\?\\UNC\\server\\…`` as
    ``\\\\server\\…``. CPython's resolve keeps the long form where another thread makes a missing
    path's folder between the two lookups of its realpath - they fail with other errors, and only
    alike errors drop the prefix (ntpath.realpath) - though it names the same file."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[len("\\\\?\\UNC\\") :]
    return path.removeprefix("\\\\?\\")


class FileSystemStorage:
    def __init__(self, root: Path) -> None:
        # in the long form where STORAGE_DIR names it so: its files are reached past MAX_PATH
        self.root = root.resolve()
        self._plain_root = _plain_form(self.root)

    def _path(self, key: str) -> Path:
        path = (self.root / check_key(key)).resolve()
        # a checked key has no "..", but a link inside the root may lead out of it
        if not _plain_form(path).is_relative_to(self._plain_root):
            raise InvalidKey(f"not a storage key: {key[:80]!r}")
        return path

    def put(self, key: str, data: bytes) -> None:
        """Raises InvalidKey for a key below an object or one that holds other keys: S3 keeps
        ``a`` and ``a/b`` side by side, a file system cannot."""
        self._write(key, lambda file: file.write(data))

    def put_file(self, key: str, source: BinaryIO, size: int) -> None:
        self._write(key, partial(_copy, source, size))

    def _write(self, key: str, fill: Callable[[BinaryIO], object]) -> None:
        """The object under ``key``, as ``fill`` writes it into a temporary file beside it."""
        path = self._path(key)
        made = [folder for folder in (path.parent, *path.parent.parents) if not folder.exists()]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError):
            raise InvalidKey(f"a key below an object: {key[:80]!r}") from None
        if path.is_dir():
            raise InvalidKey(f"a key that holds other keys: {key[:80]!r}")
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as file:
                fill(file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        # the object's entry, and the entry of each folder made for it, in the folder above
        for folder in [path.parent, *(made_folder.parent for made_folder in made)]:
            _sync_folder(folder)

    def get(self, key: str) -> bytes:
        path = self._object(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:  # deleted in between
            raise ObjectNotFound(key) from None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def open_stream(self, key: str) -> ObjectStream:
        path = self._object(key)
        try:
            file = path.open("rb")
        except FileNotFoundError:  # deleted in between
            raise ObjectNotFound(key) from None
        size = os.fstat(file.fileno()).st_size
        return ObjectStream(size, iter(partial(file.read, CHUNK_BYTES), b""), file.close)

    def delete(self, key: str) -> None:
        path = self._object(key)
        try:
            path.unlink()
        except FileNotFoundError:  # deleted in between
            raise ObjectNotFound(key) from None

    def list(self, prefix: str) -> Iterator[str]:
        """Only names a key could have: a temporary file a killed write left (``.tmp-*``) is no object. A
        folder that cannot be read raises (OSError) - none there lists nothing, a root that is not there
        too. Folders emptied by deleting their objects stay behind (this store serves development and a
        single node)."""
        folder = self._path(check_prefix(prefix)[:-1])
        return self._keys(prefix, folder)

    def _keys(self, prefix: str, folder: Path) -> Iterator[str]:
        # links are not followed: one inside the root may lead out of it; each key begins with the prefix
        for parent, _, files in os.walk(folder, onerror=_unless_missing, followlinks=False):
            for name in files:
                key = prefix + (Path(parent) / name).relative_to(folder).as_posix()
                if is_key(key):
                    yield key

    def _object(self, key: str) -> Path:
        """The object's file; ObjectNotFound for none, a folder of other keys, or below a file."""
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path


def _unless_missing(error: OSError) -> None:
    """os.walk's onerror: a folder gone, never there or an object's file holds no keys; any other error is
    raised."""
    if not isinstance(error, FileNotFoundError | NotADirectoryError):
        raise error


def _copy(source: BinaryIO, size: int, target: BinaryIO) -> None:
    """``size`` bytes of ``source`` into ``target``, CHUNK_BYTES at a time; OSError for a source
    that ends before its size."""
    left = size
    while left:
        piece = source.read(min(left, CHUNK_BYTES))
        if not piece:
            raise OSError(f"the stream ended {left} bytes before its size")
        target.write(piece)
        left -= len(piece)


def _plain_form(path: Path) -> Path:
    """``path`` in its plain form on Windows, to compare: resolve keeps the long form of a root
    named in it, and may take it in a race (``without_long_prefix``)."""
    return Path(without_long_prefix(str(path))) if os.name == "nt" else path


def _sync_folder(folder: Path) -> None:
    """A rename is durable once the folder's entry is on disk; Windows opens no folder for it."""
    if os.name != "posix":
        return
    descriptor = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def open_storage(settings: Settings) -> Storage:
    """The store the settings name. S3 is imported only here: boto3 is slow to load.

    For S3 it asks the service once whether the bucket exists - a network call, so an async
    caller runs it in a thread - and raises StorageNotConfigured if not.
    """
    if settings.storage_backend == "s3":
        from app.core import storage_s3

        assert settings.s3_bucket is not None  # noqa: S101 - the settings refuse s3 without a bucket
        storage = storage_s3.S3Storage(storage_s3.s3_client(settings), settings.s3_bucket)
        storage.check_bucket()
        return storage
    if settings.storage_dir is None:
        raise StorageNotConfigured("STORAGE_DIR is needed for the file system store")
    return FileSystemStorage(settings.storage_dir)
