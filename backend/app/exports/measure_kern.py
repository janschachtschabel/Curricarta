"""How long the Kern export of a long frozen document takes, and how much memory its child (plan M3a C1, the
rule of E6: under 20 s and under 1 GB, the export stays a synchronous GET).

A synthetic document - 500 nodes, 5,000 statements, 5,500 anchors by default, every wording made up of a
fixed list of words, every IRI under example.org - is built and written as the export's child does it, in a
child process of its own; it says the seconds on the clock from its start to its answer, the size of the
Turtle and the child's peak memory (resident: Linux's VmHWM, Windows' peak working set).

    python -m app.exports.measure_kern [nodes] [statements]

The tests build their documents here too (``synthetic_rows``).
"""

import asyncio
import ctypes
import pickle
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from app.core.child import run_in_child
from app.exports.kern_child import turtle
from app.exports.kern_rdf import KERN_GRAPH_VERSION
from app.exports.kern_rows import KernRows, Row

CV = "https://w3id.org/wlo/curriculum/vocab#"
SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"
BASE = "https://example.org/kk/doc/de-nw/ministerium/lp-synth/2024"
WORDS = (
    "Beispiel", "Thema", "Inhalt", "Verfahren", "Aufgabe", "Ergebnis", "Begriff", "Methode", "Material",
    "beschreiben", "erklären", "untersuchen", "vergleichen", "die", "Lernenden", "mit", "und", "an",
)  # fmt: skip
MIB = 1024 * 1024
_ACCEPTED = {"origin_iri": CV + "orig_model", "review_status_iri": CV + "rev_accepted"}
_UNSET = dict.fromkeys(("scope_share_iri", "extraction_depth_iri", "lead_in", "subkind_iri"))
_PLACE = dict.fromkeys(("page_end", "printed_page", "match_score", "char_start", "char_end", "table_cell"))


def _words(seed: int, count: int) -> str:
    return " ".join(WORDS[(seed * 7 + at * 5) % len(WORDS)] for at in range(count)) + "."


def synthetic_rows(
    nodes: int = 500,
    statements: int = 5_000,
    *,
    base: str = BASE,
    revision: int = 1,
    rights_status: str = "unklar",
    source_url: str | None = None,
    mem_iri: str | None = None,
    mem_attribution: str | None = "MEM-Schule",
    mem_licence: str | None = None,
) -> KernRows:
    """A frozen school document under ``base``: a tenth of the nodes roots, the rest their children in turn;
    the statements spread over the nodes; an anchor for each node and each statement. An import of MEM-Schule
    where ``mem_iri`` names its plan (its attribution and licence then)."""
    ids = uuid.UUID(int=0x5EED << 64)  # the ids follow from the sizes: the same rows each call

    def next_id() -> uuid.UUID:
        nonlocal ids
        ids = uuid.UUID(int=ids.int + 1)
        return ids

    document, specification, file = next_id(), next_id(), next_id()
    roots = max(1, nodes // 10)
    node_rows: list[Row] = []
    for at in range(nodes):
        parent = None if at < roots else node_rows[at % roots]
        node_rows.append({
            "id": next_id(), "iri": f"{base}/{at + 1}" if parent is None else f"{parent['iri']}-{at + 1}",
            "parent_id": None if parent is None else parent["id"], "position": at + 1,
            "function_iri": CV + "fn_area", "node_type_iri": SCHOOL + "Inhaltsbereich", "code": str(at + 1),
            "code_assigned": False, "original_title": _words(at, 4), "title_language": "de",
            "obligation_iri": CV + "obl_binding", "applies_to": [], "checked_absent": [],
            **_ACCEPTED, **_UNSET,
        })  # fmt: skip
    statement_rows: list[Row] = []
    for at in range(statements):
        node, position = node_rows[at % nodes], at // nodes + 1
        statement_rows.append({
            "id": next_id(), "iri": f"{node['iri']}/s-{position}", "node_id": node["id"],
            "position": position, "verbatim": _words(at, 20), "language": "de",
            "statement_kind_iri": CV + "kind_learningOutcome", "obligation_iri": CV + "obl_binding",
            "text_hash": f"{at:064x}", "details": {"levelText": _words(at, 2)}, "layout_markers": [],
            "addressees": [CV + "addr_learner"], **_ACCEPTED, **_UNSET,
        })  # fmt: skip
    held = [(row, "node_id") for row in node_rows] + [(row, "statement_id") for row in statement_rows]
    anchors = [
        {"id": next_id(), "node_id": None, "statement_id": None, holder: row["id"],
         "page_start": at // 40 + 1, "quote": row.get("verbatim") or row["original_title"],
         "match_kind_iri": CV + "match_exact", "section_path": None,
         "blocks": [f"p{at // 40 + 1}-b{at % 40 + 1}"], **_PLACE}
        for at, (row, holder) in enumerate(held)
    ]  # fmt: skip
    document_row: Row = {
        "id": document, "iri": base, "revision": revision, "frozen_at": datetime(2026, 11, 1, tzinfo=UTC),
        "rights_status": rights_status, "violations": 0, "checked_graph": KERN_GRAPH_VERSION,
        "title": "Lehrplan Synthese",
        "issuer": "Ministerium", "edition": "2024", "supersedes_iri": None, "source_url": source_url,
        "mem_iri": mem_iri, "mem_attribution": mem_attribution if mem_iri else None,
        "mem_licence": mem_licence if mem_iri else None,
        "document_type_iri": SCHOOL + "dt-Lehrplan", "sector_iri": CV + "sec_school", "region_iris": [],
        **dict.fromkeys(("legal_form_iri", "binding_iri", "lifecycle_iri", "valid_from", "valid_until",
                         "issued")),
    }  # fmt: skip
    specification_row = {
        "id": specification, "iri": f"{base}/spec/s1", "spec_kind": "curriculum", "title": "Synthese",
        "field_text": "Synthese",
    }  # fmt: skip
    return KernRows(
        document_row, [specification_row], [], node_rows, statement_rows, anchors, work=None,
        file={"id": file, "sha256": "ab" * 32},
    )  # fmt: skip


def _peak_mib() -> int:
    """This process's peak resident memory in MiB: Windows' peak working set, else the kernel's maxrss."""
    if sys.platform == "win32":
        names = ("cb", "PageFaultCount", "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                 "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                 "PagefileUsage", "PeakPagefileUsage")  # fmt: skip

        class Counters(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS: two DWORDs, then SIZE_Ts
            _fields_ = [
                (name, ctypes.c_ulong if at < 2 else ctypes.c_size_t) for at, name in enumerate(names)
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.PeakWorkingSetSize) // MIB
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) // 1024  # KiB on Linux


def _measured(rows: str, out: str) -> None:
    """The child: the export's build of the pickled rows, its size and peak memory left in ``out``."""
    data = turtle(pickle.loads(Path(rows).read_bytes()))  # noqa: S301 - this tool's own file
    (Path(out) / "measured.txt").write_text(f"{len(data)} {_peak_mib()}", encoding="ascii")


def _read(_: int | None, out: Path) -> tuple[int, int]:
    size, peak = (out / "measured.txt").read_text(encoding="ascii").split()
    return int(size), int(peak)


async def measure(nodes: int, statements: int) -> tuple[float, int, int]:
    """Seconds, bytes of Turtle and peak MiB of the child for a synthetic document of that size."""
    rows = synthetic_rows(nodes, statements)
    with tempfile.TemporaryDirectory(prefix="kern-measure-") as folder:
        handed = Path(folder) / "rows.pickle"
        handed.write_bytes(pickle.dumps(rows, pickle.HIGHEST_PROTOCOL))
        started = time.perf_counter()
        size, peak = await run_in_child(
            _measured, (str(handed),), prefix="kern-measure-", read=partial(_read)
        )
        return time.perf_counter() - started, size, peak


def main(arguments: list[str]) -> None:
    nodes = int(arguments[0]) if arguments else 500
    statements = int(arguments[1]) if len(arguments) > 1 else 5_000
    seconds, size, peak = asyncio.run(measure(nodes, statements))
    print(
        f"nodes={nodes} statements={statements} anchors={nodes + statements}: {seconds:.1f} s, "
        f"{size // 1024} KiB of Turtle, peak {peak} MiB"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
