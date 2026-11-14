"""A frozen MEM import's export made and kept (plan M2-6; Nachtrag M2-1: a synchronous GET, no job).

The rows (app/exports/mem_rows.py) are read by the caller, who lets its database connection go before the
check: building the graph (app/exports/mem_ttl.py), checking it against the MEM shapes in a child process
within MEM_EXPORT_TIMEOUT_S (app/pipeline/shacl.py) and keeping its Turtle in the store under a key of the
document and a fingerprint of what may change its output - the exporter's version, the rights status, the
licence and attribution of the MEM data, the shapes, the class chain and the base-type table. Asked again,
the kept bytes go out unchecked: a frozen document's rows change no more. A state the shapes refuse is no
export and leaves nothing but its violations, kept beside where the export would be - the state stays
refused for its key, and is not checked again (``Invalid``); a check past its time or broken in its child
is none (``ExportUnavailable``). One export of a key is made at a time in a process, two checks at most
beside each other: the children take memory beside the API's workers. A request waits for its turn at most
what the proxy leaves beside the check (REQUEST_S), else it is none either: an answer the API words, not
the proxy's 504. The gate's version is part of the fingerprint, as the output's is.

The class chain and the base-type table are read once a process: a deployment that changes them restarts
it.

simplify: a key's bytes kept once stay, though a changed rights status leaves them unused; nothing
clears ``exports/<document>/`` yet.
"""

import asyncio
import hashlib
import json
import logging
import weakref
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from uuid import UUID

from app.core.child import ChildLog
from app.core.logging import current_request_id
from app.core.settings import Settings
from app.core.storage_async import AsyncStorage
from app.exports import mem_gate
from app.exports.kern_rows import Row
from app.exports.mem_gate import Violation, violations
from app.exports.mem_rows import MemRows
from app.exports.mem_ttl import MEM_EXPORT
from app.exports.mem_ttl import mem_graph as mem_graph  # the build a test watches here
from app.pipeline.shacl import ShaclCrashed, ShaclTimeout
from app.pipeline.shacl import shacl_check as shacl_check  # the check a test watches here
from app.pipeline.shacl_child import MEM_MODEL, MEM_SHAPE_FILES
from app.sources.mem import classes
from app.sources.mem.classes import MemModel, model_from
from app.sources.mem.rules_db import mem_files

log = logging.getLogger(__name__)
CHECKS_AT_ONCE = 2
_PYSHACL = version("pyshacl")  # the checker's: another may refuse what this one passed, or the other way
REQUEST_S = 55.0  # what the proxy gives a request (60 s), short of a margin: the wait and the check share it
MIN_WAIT_S = 5.0
# what the export reads beside the rows: a deployment that changes one changes the output
_INPUTS = (*MEM_SHAPE_FILES, MEM_MODEL, "mem/grundtypen.json")


@dataclass(frozen=True)
class Exported:
    key: str  # the Turtle's key in the store


@dataclass(frozen=True)
class Invalid:
    violations: list[Violation]


class ExportUnavailable(Exception):
    """The check did not end in its time, or broke in its child: try again later."""


def fingerprint(document: Row, ontology_dir: Path) -> str:
    """What the export's output depends on beside its rows, as a digest."""
    versions = (MEM_EXPORT, mem_gate.GATE_VERSION, classes.RULES, _PYSHACL)
    digest = hashlib.sha256("\x00".join(versions).encode())
    for value in (document["rights_status"], document["mem_licence"], document["mem_attribution"]):
        digest.update(b"\x00" + (value or "").encode())
    for name in _INPUTS:
        path = ontology_dir / name
        found = path.stat()
        digest.update(_file_digest(str(path), found.st_mtime_ns, found.st_size))
    return digest.hexdigest()


@lru_cache(maxsize=64)
def _file_digest(path: str, mtime_ns: int, size: int) -> bytes:  # by its time and size: read once while kept
    return hashlib.sha256(Path(path).read_bytes()).digest()


def export_key(document_id: UUID, fingerprint: str) -> str:
    """``exports/<document>/mem-<version>-<16 hex>.ttl``."""
    return f"exports/{document_id}/mem-{MEM_EXPORT.rsplit('/', 1)[1]}-{fingerprint[:16]}.ttl"


class MemExporter:
    """The exports of one process, as the module says."""

    def __init__(self, storage: AsyncStorage, settings: Settings) -> None:
        self._storage, self._settings = storage, settings
        self._checks = asyncio.Semaphore(CHECKS_AT_ONCE)
        self._making: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._model: MemModel | None = None

    async def export(self, rows: MemRows) -> Exported | Invalid:
        """The kept export of ``rows`` - a frozen import's, read in one snapshot -, made where none is."""
        ontology_dir = self._settings.ontology_dir
        key = export_key(
            rows.document["id"], await asyncio.to_thread(fingerprint, rows.document, ontology_dir)
        )
        refused = key.removesuffix(".ttl") + ".invalid.json"
        lock = self._making.get(key) or self._making.setdefault(key, asyncio.Lock())
        # one deadline for both waits, for the key and for a check: the check's own time comes on top
        deadline = asyncio.get_running_loop().time() + max(
            MIN_WAIT_S, REQUEST_S - self._settings.mem_export_timeout_s
        )
        try:
            async with asyncio.timeout_at(deadline):
                await lock.acquire()
        except TimeoutError:
            raise ExportUnavailable("another export of the document took too long") from None
        try:
            if await self._storage.exists(key):
                return Exported(key)
            if await self._storage.exists(refused):
                return Invalid([_violation(found) for found in json.loads(await self._storage.get(refused))])
            return await self._made(rows, key, refused, deadline)
        finally:
            lock.release()

    async def _made(self, rows: MemRows, key: str, refused: str, deadline: float) -> Exported | Invalid:
        ontology_dir = self._settings.ontology_dir
        if self._model is None:  # parsing the chain takes a moment: once, beside the loop
            self._model = model_from(*await asyncio.to_thread(mem_files, ontology_dir))
        told = ChildLog(
            level=self._settings.log_level,
            format=self._settings.log_format,
            request_id=current_request_id(),
        )
        try:
            async with asyncio.timeout_at(deadline):
                await self._checks.acquire()
        except TimeoutError:
            raise ExportUnavailable("the checks of the process are busy") from None
        try:
            try:
                # built once its check may run: graphs waiting for a slot would fill the API's memory
                export = await asyncio.to_thread(mem_graph, rows, self._model)
                results = await shacl_check(
                    export.graph,
                    ontology_dir=ontology_dir,
                    timeout_s=self._settings.mem_export_timeout_s,
                    told=told,
                    shapes="mem",
                )
            finally:
                self._checks.release()
        except (ShaclTimeout, ShaclCrashed) as failed:
            log.warning("the MEM export of document %s was not checked: %s", rows.document["id"], failed)
            raise ExportUnavailable(str(failed)) from failed
        found = violations(results, export)
        if found:
            kept = [violation_dict(each) for each in found]
            await self._storage.put(refused, json.dumps(kept, ensure_ascii=False).encode())
            return Invalid(found)
        data = await asyncio.to_thread(export.graph.serialize, format="turtle", encoding="utf-8")
        await self._storage.put(key, data)
        return Exported(key)


def violation_dict(found: Violation) -> dict[str, str | None]:
    """A violation as the store keeps it and the API names it."""
    return {"focus": found.focus, "row_kind": found.row_kind,
            "row_id": None if found.row_id is None else str(found.row_id), "shape": found.shape,
            "path": found.path, "message": found.message}  # fmt: skip


def _violation(kept: dict[str, str | None]) -> Violation:
    row = kept["row_id"]
    return Violation(
        str(kept["focus"]), kept["row_kind"], None if row is None else UUID(row), str(kept["shape"]),
        kept["path"], str(kept["message"]),
    )  # fmt: skip
