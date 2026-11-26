"""How long the Kern export of a long frozen document takes, and how much memory its child (plan M3a C1, the
rule of E6: under 20 s and under 1 GB, the export stays a synchronous GET) - and X5 on the same document.

A synthetic document - 500 nodes, 5,000 statements, 5,500 anchors by default, every wording made up of a
fixed list of words, every IRI under example.org - is built and written as the export's child does it, in a
child process of its own. With ``values`` it holds the second layer too (app/exports/synthetic_layer.py,
plan M3a L1): that many level assignments, time spans and workloads each, and rules, assessments and
placements a tenth of the nodes each. The child says the seconds of the export (the graph under the frozen
names and its Turtle), of the graph as X5 builds it and of X5's check of that graph, the size of the Turtle,
the violations X5 found, and its peak memory after the export and at its end (resident: Linux's VmHWM,
Windows' peak working set); the parent the seconds on the clock from the child's start to its answer.

    python -m app.exports.measure_kern [nodes] [statements] [values]

The tests build their documents here too (``synthetic_rows``).
"""

import asyncio
import ctypes
import json
import pickle
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple

from app.core.child import run_in_child
from app.core.settings_work import REPOSITORY_ONTOLOGY
from app.exports.kern_child import turtle
from app.exports.kern_rdf import KERN_GRAPH_VERSION, kern_graph
from app.exports.kern_rows import KernRows, Row
from app.exports.synthetic_layer import second_layer

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
_PLACE = dict.fromkeys(
    ("page_end", "printed_page", "match_score", "char_start", "char_end", "table_cell", "frame_part_id")
)


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
    values: int = 0,
) -> KernRows:
    """A frozen school document under ``base``: a tenth of the nodes roots, the rest their children in turn;
    the statements spread over the nodes; an anchor for each node and each statement. An import of MEM-Schule
    where ``mem_iri`` names its plan (its attribution and licence then); the second layer with ``values``."""
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
        "field_text": "Synthese", "applicability": {}, "has_contexts": False,
    }  # fmt: skip
    rows = KernRows(
        document_row, [specification_row], [], node_rows, statement_rows, anchors, work=None,
        file={"id": file, "sha256": "ab" * 32},
    )  # fmt: skip
    return second_layer(rows, values, next_id, _words) if values else rows


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


class Measured(NamedTuple):
    """What one measurement of a synthetic document of ``nodes``, ``statements`` and ``values`` found."""

    nodes: int
    statements: int
    values: int
    seconds: float  # on the parent's clock, the child's start to its answer
    export_s: float  # the graph under the frozen names and its Turtle, as the export's child builds them
    graph_s: float  # the graph under the draft's names, as X5 builds it
    x5_s: float  # X5's check of that graph
    turtle_bytes: int
    violations: int  # X5's
    export_peak_mib: int  # the child's peak after the export
    peak_mib: int  # and at its end, after X5


def _measured(rows: str, ontology: str, out: str) -> None:
    """The child: the export's build of the pickled rows, then X5's graph and check of them; what each took,
    the Turtle's size, X5's violations and the peak memory left in ``out``."""
    from app.pipeline.shacl_child import validate_graph  # pyshacl in the child alone

    read = pickle.loads(Path(rows).read_bytes())  # noqa: S301 - this tool's own file
    started = time.perf_counter()
    size = len(turtle(read))
    export_s, export_peak = time.perf_counter() - started, _peak_mib()
    started = time.perf_counter()
    graph = kern_graph(read)
    graph_s, started = time.perf_counter() - started, time.perf_counter()
    found = validate_graph(Path(ontology), graph)
    x5_s = time.perf_counter() - started
    violations = sum(result.severity == "violation" for result in found)
    measured = {
        "export_s": export_s, "graph_s": graph_s, "x5_s": x5_s, "turtle_bytes": size,
        "violations": violations, "export_peak_mib": export_peak, "peak_mib": _peak_mib(),
    }  # fmt: skip
    (Path(out) / "measured.json").write_text(json.dumps(measured), encoding="ascii")


def _read(_: int | None, out: Path) -> dict[str, Any]:
    return dict(json.loads((out / "measured.json").read_text(encoding="ascii")))


async def measure(
    nodes: int, statements: int, values: int = 0, ontology: Path = REPOSITORY_ONTOLOGY
) -> Measured:
    """One measurement of a synthetic document of that size, in a child of its own."""
    rows = synthetic_rows(nodes, statements, values=values)
    with tempfile.TemporaryDirectory(prefix="kern-measure-") as folder:
        handed = Path(folder) / "rows.pickle"
        handed.write_bytes(pickle.dumps(rows, pickle.HIGHEST_PROTOCOL))
        started = time.perf_counter()
        found = await run_in_child(
            _measured, (str(handed), str(ontology)), prefix="kern-measure-", read=partial(_read)
        )
        seconds = time.perf_counter() - started
    return Measured(nodes, statements, values, seconds, **found)


def main(arguments: list[str]) -> None:
    nodes = int(arguments[0]) if arguments else 500
    statements = int(arguments[1]) if len(arguments) > 1 else 5_000
    values = int(arguments[2]) if len(arguments) > 2 else 0
    found = asyncio.run(measure(nodes, statements, values))
    print(
        f"nodes={nodes} statements={statements} anchors={nodes + statements} values={values}: "
        f"{found.seconds:.1f} s in all; export {found.export_s:.1f} s, {found.turtle_bytes // 1024} KiB "
        f"of Turtle, peak {found.export_peak_mib} MiB; X5 graph {found.graph_s:.1f} s, check "
        f"{found.x5_s:.1f} s, {found.violations} violations, peak {found.peak_mib} MiB"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
