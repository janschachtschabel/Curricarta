"""Freeze one MEM plan's answers on the developer's disk (data/mem-local/, which git ignores).

Asks the MEM endpoint - the network - the queries the import asks (app/sources/mem/queries.py), page by
page as it does, and writes their rows as they came, sorted, with the graph, the plan and when they were
read. What it writes is MEM-Schule's data, a Land's wordings: it stays local, for development alone, and
never goes into the repository or an image (audit 2026-11-14). The tests replay synthetic plans made of
such an answer (tools/mem_synth.py, tests/sources/fixtures/mem/HERKUNFT.md).

    PYTHONPATH=backend python backend/tools/mem_freeze.py <graph> <plan-iri> data/mem-local/<name>.json
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.sources.mem.queries import closure_count, closure_page, reference_count, reference_page
from app.sources.mem.sparql import MemEndpoint, MemSparql

ENDPOINT = "https://sparql.mem.edufeed.org/sparql"


async def freeze(graph: str, plan: str) -> dict[str, object]:
    sparql = MemSparql(MemEndpoint(ENDPOINT))
    closure = await sparql.select_pages(
        lambda limit, offset: closure_page(sparql, graph, plan, limit, offset),
        closure_count(sparql, graph, plan),
    )
    references = await sparql.select_pages(
        lambda limit, offset: reference_page(sparql, graph, plan, limit, offset),
        reference_count(sparql, graph, plan),
    )
    return {
        "endpoint": ENDPOINT,
        "graph": graph,
        "plan": plan,
        "read_at": datetime.now(UTC).date().isoformat(),
        "closure": sorted(closure, key=lambda row: row["n"]),
        "references": sorted(references, key=lambda row: (row["x"], row["v"])),
    }


def main() -> None:
    graph, plan, out = sys.argv[1:4]
    frozen = asyncio.run(freeze(graph, plan))
    written = json.dumps(frozen, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    Path(out).write_text(written, encoding="utf-8")
    print(f"{out}: {len(frozen['closure'])} Teile, {len(frozen['references'])} Verweise")  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
