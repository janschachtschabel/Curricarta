"""The job source.mem_catalog: every plan of MEM's allowed graphs read into the catalogue (plan M2, E11).

An admin starts it, one at a time (``POST /api/v1/mem/catalog``; the queue's unique key holds a second
back). Per graph in GRAPHS it counts the plans - a Land's Lehrplan (LP_0000438) or the KMK's
Bildungsstandard (LP_0000571) - reads them in pages, and replaces the graph's plans in mem_plan
(app/db/mem_plans.py). A plan's class is its Land's class where it has one, else its base class; its
title is its German label, else an untagged one, else its preferred label, on one line and at most 2000
signs. The endpoint states no licence on a plan (probe of 2026-11-09): ``licence`` is the one the
operators checked for the data (MEM_DATA_LICENCE, E14), else empty; the attribution names the endpoint and
the ontology. A plan whose
IRI the table cannot take is skipped and counted; a NUL or a lone surrogate, which the database cannot
hold, is dropped.

A graph that gives no plan - none answered, or each skipped - while the catalogue holds some keeps
them (``kept``): a store reloading a graph answers with none for a while, and the import picks its
plans from the catalogue. A graph the endpoint truly empties keeps its plans too, their ``read_at``
growing old; the import asks the endpoint for the plan and refuses one it no longer has (M2-5).
A plan of the KMK's graph is a Bildungsstandard and no other plan is: one that is not as both tell is
counted per graph (``mismatched``) and logged (plan M2-7).
An endpoint out of reach for now (MemUnavailable) leaves the job to another attempt, which reads every
graph again; at the last attempt the job ends ``mem_unavailable``. An answer it cannot take for one
graph does not hold the others up: they are read, and then the job ends (``mem_refused``, naming each
graph with the client's reason).
"""

import logging
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any
from uuid import UUID

import httpx2
import psycopg

from app.db.mem_plans import MemPlan, graph_size, replace_graph
from app.jobs.context import JobContext
from app.jobs.outcome import PermanentError
from app.jobs.queue import Job, OpenJob, enqueue
from app.sources.mem.queries import GERMAN, LABELS, LP, PREFIXES, SEPARATOR
from app.sources.mem.sparql import GRAPHS, KMK_GRAPH, MemEndpoint, MemRefused, MemSparql, MemUnavailable
from app.sources.mem.tree import UNSTORABLE, storable_iri

KIND = "source.mem_catalog"
log = logging.getLogger(__name__)
LEHRPLAN, BILDUNGSSTANDARD = LP + "LP_0000438", LP + "LP_0000571"
MAX_TITLE = 2000  # as mem_plan.title takes one
ATTRIBUTION = (
    "MEM-Schule, SPARQL-Endpunkt {endpoint}; Struktur nach der Lehrplan Ontology 1.0.0rc3 (FWU), "
    "https://w3id.org/lehrplan/ontology"
)
_PLANS = (
    f"VALUES ?base {{ lp:{LEHRPLAN.removeprefix(LP)} lp:{BILDUNGSSTANDARD.removeprefix(LP)} }} ?p a ?base ."
)


def catalog_count(sparql: MemSparql, graph: str) -> str:
    """The number of ``graph``'s plans."""
    return (
        f"{PREFIXES}SELECT (COUNT(DISTINCT ?p) AS ?count)\n{sparql.from_clauses(graph)}\nWHERE {{ {_PLANS} }}"
    )


def catalog_page(sparql: MemSparql, graph: str, limit: int, offset: int) -> str:
    """One page of ``graph``'s plans, a row each: label, classes, Land, subjects and school types. No name
    it projects is a variable of its pattern (SPARQL 1.1, 18.2.1)."""
    pref_label = GERMAN.format(var="?pl")
    return (
        f"{PREFIXES}"
        "SELECT ?p (MIN(?l) AS ?label)\n"
        f'       (GROUP_CONCAT(DISTINCT ?c; separator="{SEPARATOR}") AS ?classes)\n'
        "       (MIN(?ld) AS ?land)\n"
        f'       (GROUP_CONCAT(DISTINCT ?s; separator="{SEPARATOR}") AS ?subjects)\n'
        f'       (GROUP_CONCAT(DISTINCT ?st; separator="{SEPARATOR}") AS ?schoolTypes)\n'
        f"{sparql.from_clauses(graph)}\n"
        "WHERE {\n"
        f"  {{ SELECT DISTINCT ?p WHERE {{ {_PLANS} }}"
        f" ORDER BY ?p LIMIT {int(limit)} OFFSET {int(offset)} }}\n"
        f"{LABELS.format(node='?p')}"
        f"  OPTIONAL {{ ?p skos:prefLabel ?pl . FILTER({pref_label}) }}\n"
        "  BIND(COALESCE(?de, ?plain, ?pl) AS ?l)\n"
        f'  OPTIONAL {{ ?p a ?c . FILTER(STRSTARTS(STR(?c), "{LP}")) }}\n'
        "  OPTIONAL { ?p lp:LP_0000029 ?ld . }\n"
        "  OPTIONAL { ?p lp:LP_0000537 ?s . }\n"
        "  OPTIONAL { ?p lp:LP_0000812 ?st . }\n"
        "}\n"
        "GROUP BY ?p"
    )


def mismatched(plans: Sequence[MemPlan]) -> int:
    """How many plans the graph and the class tell apart on the KMK: the import knows the KMK by its graph,
    the export by the class Bildungsstandard (plan M2-7) - one of the graph that is none, or one that is
    elsewhere, would be imported as the one and exported as the other."""
    return sum((plan.graph == KMK_GRAPH) != (plan.class_iri == BILDUNGSSTANDARD) for plan in plans)


def plans_from(
    rows: Sequence[Mapping[str, str]], graph: str, attribution: str, licence: str | None = None
) -> tuple[list[MemPlan], int]:
    """The plans of a graph's rows (``catalog_page``), each with ``licence``, and how many were skipped for
    their IRI."""
    plans, skipped = [], 0
    for row in rows:
        iri = row["p"]
        if not storable_iri(iri):
            skipped += 1
            continue
        classes = sorted(_split(row.get("classes", "")))
        own = [klass for klass in classes if klass != LEHRPLAN]
        title = (
            " ".join(UNSTORABLE.sub("", row.get("label", "")).split()) or iri.rstrip("/").rsplit("/", 1)[-1]
        )
        land = row.get("land") or None
        plans.append(
            MemPlan(
                iri=iri,
                graph=graph,
                land_iri=land if land is not None and not UNSTORABLE.search(land) else None,
                title=title[:MAX_TITLE],
                class_iri=(own or classes or [LEHRPLAN])[0],
                subjects=tuple(sorted(_split(row.get("subjects", "")))),
                school_types=tuple(sorted(_split(row.get("schoolTypes", "")))),
                licence=licence,
                attribution=attribution,
            )
        )
    return plans, skipped


async def enqueue_catalog(connection: psycopg.AsyncConnection, lane: str) -> tuple[UUID | None, UUID | None]:
    """A new catalogue job of ``lane``, unless one waits or runs: (the new one, the one there)."""
    try:
        return await enqueue(connection, KIND, lane, {}, unique_key=KIND), None
    except OpenJob as open_job:
        return None, open_job.job_id


async def read_catalog(
    context: JobContext, job: Job, *, transport: httpx2.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """Every allowed graph's plans into mem_plan; ``transport`` is the network (tests). Per graph: the
    plans written, those dropped, those skipped, those kept where the graph answered with none, and those
    whose graph and class disagree on the KMK (``mismatched``, logged)."""
    endpoint = context.settings.mem_sparql_url
    sparql = MemSparql(MemEndpoint(endpoint), transport)
    attribution = ATTRIBUTION.format(endpoint=endpoint)
    graphs: dict[str, dict[str, int]] = {}
    refused: list[str] = []  # each graph with the client's reason
    for graph in GRAPHS:
        try:
            rows = await sparql.select_pages(
                partial(catalog_page, sparql, graph), catalog_count(sparql, graph)
            )
        except MemRefused as refusal:
            refused.append(f"{graph}: {refusal}")
            continue
        except MemUnavailable as away:
            if job.attempts < job.max_attempts:
                raise  # another attempt reads every graph again
            before = f"; refused before - {'; '.join(refused)}" if refused else ""
            raise PermanentError(
                "mem_unavailable", f"the endpoint stayed out of reach - {graph}: {away}{before}"
            ) from None
        plans, skipped = plans_from(rows, graph, attribution, context.settings.mem_data_licence or None)
        if odd := mismatched(plans):
            log.warning("%d plans of the graph %s: graph and class disagree on the KMK", odd, graph)
        async with context.pool.connection() as connection:
            held = await graph_size(connection, graph) if not plans else 0
            if held:
                graphs[graph] = {
                    "plans": 0,
                    "removed": 0,
                    "skipped": skipped,
                    "kept": held,
                    "mismatched": odd,
                }
                continue
            written, dropped = await replace_graph(connection, graph, plans)
        graphs[graph] = {
            "plans": written,
            "removed": dropped,
            "skipped": skipped,
            "kept": 0,
            "mismatched": odd,
        }
    if refused:
        raise PermanentError("mem_refused", f"the endpoint's answers were refused - {'; '.join(refused)}")
    return {"graphs": graphs}


def _split(joined: str) -> tuple[str, ...]:
    """The values joined, those the database cannot hold left out."""
    return tuple(part for part in joined.split(SEPARATOR) if part and not UNSTORABLE.search(part))
