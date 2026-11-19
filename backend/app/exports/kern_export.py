"""A frozen document's Kern export made and kept (plan M3a C1, E6: a synchronous GET, no job).

The rows (app/exports/kern_rows.py) are read by the caller, who lets its database connection go before the
build: the graph under the document's stored IRIs, written as Turtle in a child process
(app/exports/kern_child.py) within KERN_EXPORT_TIMEOUT_S, its rows handed over as a file - a pickle of a
long document as an argument of the spawn would fill the pipe the child drains only once it has started
(app/pipeline/shacl.py). The Turtle is kept in the store under a key of the document, its revision and a
fingerprint of what may change its output once the document is frozen: the builder's version, rdflib's, the
rights status, the violations the editors accepted, where it came from and its regions (``_MAY_CHANGE``).
Asked again, the kept bytes go out: a frozen revision's rows change no more. No SHACL check runs here: X5
checked the same graph under its draft names, and freezing asks for that check (plan M3a E6;
test_kern_naming.py holds the two graphs alike).

A document frozen before its specifications and variants were named is ``ExportUnnamed`` until
``python -m app.db.name_frozen`` named them; a build past its time or broken in its child is
``ExportUnavailable``. One build of a key at a time in a process, two children at most beside each other,
a request's waits and the build within REQUEST_S, as the MEM export's (app/exports/mem_export.py). Two
replicas building the same key write the same bytes.
"""

import asyncio
import hashlib
import logging
import pickle
import shutil
import tempfile
import weakref
from importlib.metadata import version
from pathlib import Path
from uuid import UUID

from app.core.child import ChildLog, said_out_of_memory
from app.core.child import run_in_child as run_in_child  # the start a test counts here
from app.core.settings import Settings
from app.core.storage_async import AsyncStorage
from app.exports import mem_export
from app.exports.kern_child import ANSWER, KERN_EXPORT, run_child
from app.exports.kern_rows import KernRows
from app.exports.mem_export import Exported, ExportUnavailable

log = logging.getLogger(__name__)
CHILDREN_AT_ONCE = 2
REQUEST_S = mem_export.REQUEST_S  # the same edge in front of both exports
MIN_WAIT_S = mem_export.MIN_WAIT_S
_RDFLIB = version("rdflib")  # the serializer's: another may write other bytes
build_child = run_child  # the child's target (a test starts another)
# what a frozen revision's rows may still say otherwise: its rights status and an import's licence (migration
# 0031), its register entry's address, the violations counted - and its regions, read off the vocabulary
_MAY_CHANGE = ("rights_status", "violations", "source_url", "mem_attribution", "mem_licence", "region_iris")


class ExportUnnamed(Exception):
    """A row of the frozen document has no IRI yet: python -m app.db.name_frozen gives it one."""


class _Crashed(Exception):
    """The build raised in its child, or the child ended without its file."""


def unnamed(rows: KernRows) -> bool:
    """Whether a row the frozen naming names by its IRI has none (app/exports/kern_naming.py)."""
    named = [rows.document, *filter(None, [rows.work]), *rows.specifications, *rows.variants]
    return any(row["iri"] is None for row in [*named, *rows.nodes, *rows.statements])


def fingerprint(rows: KernRows) -> str:
    """What the export's output depends on beside the rows a frozen revision keeps, as a digest."""
    document = rows.document
    parts = (KERN_EXPORT, _RDFLIB, *(str(document[name]) for name in _MAY_CHANGE))
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def export_key(document_id: UUID, revision: int, fingerprint: str) -> str:
    """``exports/<document>/kern-<version>-r<revision>-<16 hex>.ttl``."""
    return f"exports/{document_id}/kern-{KERN_EXPORT.rsplit('/', 1)[1]}-r{revision}-{fingerprint[:16]}.ttl"


class KernExporter:
    """The Kern exports of one process, as the module says."""

    def __init__(self, storage: AsyncStorage, settings: Settings) -> None:
        self._storage, self._settings = storage, settings
        self._timeout_s = settings.kern_export_timeout_s
        self._children = asyncio.Semaphore(CHILDREN_AT_ONCE)
        self._making: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    async def export(self, rows: KernRows) -> Exported:
        """The kept export of ``rows`` - a frozen document's, read in one snapshot -, made where none is."""
        document = rows.document
        if document["frozen_at"] is None:
            raise ValueError(f"the document {document['id']} is not frozen: a draft is not exported")
        if unnamed(rows):
            raise ExportUnnamed(f"a row of the document {document['id']} has no IRI")
        key = export_key(document["id"], document["revision"], fingerprint(rows))
        lock = self._making.get(key) or self._making.setdefault(key, asyncio.Lock())
        # one deadline for both waits, for the key and for a child: the build's own time comes on top
        deadline = asyncio.get_running_loop().time() + max(MIN_WAIT_S, REQUEST_S - self._timeout_s)
        try:
            async with asyncio.timeout_at(deadline):
                await lock.acquire()
        except TimeoutError:
            raise ExportUnavailable("another export of the document took too long") from None
        try:
            if not await self._storage.exists(key):
                await self._storage.put(key, await self._built(rows, deadline))
            return Exported(key)
        finally:
            lock.release()

    async def _built(self, rows: KernRows, deadline: float) -> bytes:
        try:
            async with asyncio.timeout_at(deadline):
                await self._children.acquire()
        except TimeoutError:
            raise ExportUnavailable("the children of the process are busy") from None
        told = ChildLog.of(self._settings)
        # one mkdir, made here: in a thread, a cancel meanwhile would leave the folder behind
        folder = Path(tempfile.mkdtemp(prefix="kern-rows-"))
        try:
            handed = folder / "rows.pickle"
            await asyncio.to_thread(handed.write_bytes, pickle.dumps(rows, pickle.HIGHEST_PROTOCOL))
            async with asyncio.timeout(self._timeout_s):
                return await run_in_child(
                    build_child,
                    (str(handed), told),
                    prefix="kern-",
                    read=lambda code, out: _read(told, code, out),
                )
        except TimeoutError:
            log.warning(
                "the Kern export of document %s took longer than %s s", rows.document["id"], self._timeout_s
            )
            raise ExportUnavailable(f"the build took longer than {self._timeout_s} s") from None
        except _Crashed as crashed:
            log.warning("the Kern export of document %s was not built: %s", rows.document["id"], crashed)
            raise ExportUnavailable(str(crashed)) from crashed
        finally:
            self._children.release()
            shutil.rmtree(folder, ignore_errors=True)


def _read(told: ChildLog, exit_code: int | None, out: Path) -> bytes:
    if (out / ANSWER).exists():
        return (out / ANSWER).read_bytes()
    if (out / "crashed.txt").exists():
        error = (out / "crashed.txt").read_text(encoding="utf-8")
        if error == "MemoryError":
            said_out_of_memory(told)
        raise _Crashed(f"the build raised {error} in its process")
    raise _Crashed(f"the build's process ended without an answer (exit code {exit_code})")
