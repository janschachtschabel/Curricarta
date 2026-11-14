"""``python -m app.quality.mem_report <document> --label <label> [--endpoint-counts]``: what an import from
the MEM endpoint found (plan M2, E15; plan H-3, A10), as one line of JSON - counts and rates alone, the
document named by the label, never by its title, nor its plan by its IRI:

- ``import``: what the run IM counted - parts, references, rows by typing rule, rows of no storable IRI,
  rows by search stage for nodes and statements, rows past the search's time, rows on the title pages;
- ``hits``: the anchor search's hit rate, over all rows and without the title pages, by the anchor sample's
  strata (app/quality/mem_hits.py, which says where the two figures still differ by construction);
- ``run``: how long the run took, beside MEM_SEARCH_BUDGET_S and the job's lease as configured now;
- ``findings`` by rule and ``shacl``, as X5 left them;
- ``rare_word_hidden``: the not-found wordings the fuzzy stage looked for whose rarest word (of three
  letters and more) the searched text holds more often than the stage tries places (``FUZZY_PLACES``) - its
  place may lie past them -, an estimate mostly from above (``rare_word_hidden_by``), and apart the
  not-found wordings longer than the fuzzy stage takes (``too_long_for_fuzzy``); rows past the search's
  time in neither (app/quality/mem_rare.py says how, and what the estimate rests on);
- ``label_is_iri_tail``: parts titled by their IRI's tail, their label saying nothing once cleaned as the
  import cleans it (app/sources/mem/tree.py ``clean_label``);
  ``cut``: node titles longer than ``MAX_TITLE`` and statement wordings longer than ``MAX_WORDING``, which
  the import cut - both from the plan's answers kept under the run (null where they are gone), typed by the
  rules as they stand now (``cut`` null too where the catalogue names the plan no more);
- with ``--endpoint-counts`` alone the endpoint is asked (``endpoint``: app/sources/mem/queries.py
  ``label_shape_count``) - only on the operator's word, as every query there.

Without the switch the database and the object store are all it reads, through one snapshot that refuses
every write (app/db/snapshot.py).
Exit code 1 for a document that is not there or no import, an endpoint refused or away, or an output that
is not counts and codes alone (``report_not_closed``); 2 for a call amiss."""

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.core.storage import Storage, open_storage
from app.db.documents import document_for_job
from app.db.gold_report import head_of
from app.db.mem_measures import findings_by_rule, import_run
from app.db.mem_plans import MemPlan, plan_by_iri
from app.db.runs import stage_result
from app.db.snapshot import snapshot
from app.llm.raw import kept_answers
from app.quality.closed import NOT_CLOSED, closed, token
from app.quality.mem_hits import hits
from app.quality.mem_rare import rare_words, rows_left
from app.quality.sample import LABEL, matching
from app.sources.mem.classes import MemRules, typed
from app.sources.mem.drafts import MAX_TITLE, MAX_WORDING, rows_in_order
from app.sources.mem.queries import LABEL_SHAPES, label_shape_count
from app.sources.mem.rules_db import load_rules
from app.sources.mem.sparql import KMK_GRAPH, MemEndpoint, MemRefused, MemSparql, MemUnavailable
from app.sources.mem.tree import MemTree, build_tree, clean_label

log = logging.getLogger("app.quality.mem_report")  # also when run as __main__

IMPORT_COUNTS = ("rules", "parts", "references", "typed", "untraced", "stages", "unsearched", "front")


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Kept:
    tree: MemTree
    no_label: int  # parts whose label says nothing, titled by their IRI's tail


async def _kept(storage: Storage, run_id: UUID) -> Kept | None:
    """The plan's tree as the run read it, from its answers kept raw, and how many of its parts had no
    label; None where the answers are gone or unread."""
    [data, *_] = await kept_answers(storage, run_id, "im", 1)
    if data is None:
        return None
    try:
        kept = json.loads(data)
        tree = build_tree(kept["closure"], kept["references"])
        raw = {row["n"]: row.get("label") for row in kept["closure"]}
        for row in kept["references"]:  # a reference's label as the tree takes it: its first row's
            raw.setdefault(row["v"], row.get("label"))
    except (ValueError, KeyError, TypeError, AttributeError, MemRefused):
        return None
    return Kept(tree, sum(not clean_label(raw.get(iri)) for iri in tree.parts))


def _cut(tree: MemTree, rules: MemRules) -> dict[str, int]:
    titles = wordings = 0
    for part in tree.parts.values():
        if typed(part, rules).node:
            titles += len(part.label) > MAX_TITLE
        else:
            wordings += len(part.label) > MAX_WORDING
    return {"titles": titles, "wordings": wordings}


async def _endpoint_counts(settings: Settings, plan: MemPlan | None, transport: Any) -> dict[str, int]:
    if plan is None:
        raise Refused("unknown_plan", "the catalogue names the document's plan no more")
    sparql = MemSparql(MemEndpoint(settings.mem_sparql_url), transport)
    try:
        rows = await sparql.select(label_shape_count(sparql, plan.graph, plan.iri))
        counted = {row["measure"]: int(row["count"]) for row in rows if row.get("measure") in LABEL_SHAPES}
    except MemUnavailable:
        raise Refused("mem_unavailable", "the endpoint is out of reach") from None
    except (MemRefused, KeyError, ValueError):
        raise Refused("mem_refused", "the endpoint's answer was refused") from None
    return {measure: counted.get(measure, 0) for measure in LABEL_SHAPES}


async def mem_report(
    connection: psycopg.AsyncConnection,
    storage: Storage,
    settings: Settings,
    document_id: UUID,
    label: str,
    *,
    endpoint_counts: bool = False,
    transport: Any = None,
) -> dict[str, Any]:
    """The report as the module says; ``transport`` is the network (tests), used with ``endpoint_counts``
    alone. Refused where the document is not there or no import of it is done."""
    document = await document_for_job(connection, document_id)
    if document is None:
        raise Refused("unknown_document", f"no document {document_id}")
    run = await import_run(connection, document.id)
    if run is None:
        raise Refused("not_an_import", "the document has no import done")
    head = await head_of(connection, document.id)
    plan = None if document.mem_iri is None else await plan_by_iri(connection, document.mem_iri)
    findings: dict[str, int] = {}
    for rule, count in (await findings_by_rule(connection, document.id)).items():
        key = token(rule) or "other"  # a rule's name is a code; one that is not is counted, not printed
        findings[key] = findings.get(key, 0) + count
    checked = await stage_result(connection, document.id, "X5")
    kept = await _kept(storage, run.id)
    tree = None if kept is None else kept.tree
    rules = None
    if tree is not None and plan is not None:
        rules = await load_rules(connection, settings.ontology_dir, kmk=plan.graph == KMK_GRAPH)
    rows = (
        None
        if tree is None or plan is None or rules is None
        else rows_in_order(tree, rules, plan.iri, plan.title)
    )
    left = rows_left(rows, run.result.get("unsearched") or 0)
    made: dict[str, Any] = {
        "label": label,
        "regions": [token(region) for region in head.regions],
        "sector": token(head.sector),
        "pages": head.pages,
        "import": {name: run.result.get(name) for name in IMPORT_COUNTS},
        "hits": hits(run.result),
        "run": {
            "duration_s": None if run.duration_s is None else round(run.duration_s, 3),
            "search_budget_s": settings.mem_search_budget_s,
            "lease_s": settings.job_lease_s,
        },
        "findings": findings,
        "shacl": None if checked is None else token(checked.get("shacl")),
        **await rare_words(connection, document, left),
        "label_is_iri_tail": None if kept is None else kept.no_label,
        "cut": None if tree is None or rules is None else _cut(tree, rules),
    }
    if endpoint_counts:
        made["endpoint"] = await _endpoint_counts(settings, plan, transport)
    return made


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.quality.mem_report", description=__doc__.splitlines()[0]
    )
    parser.add_argument("document", type=UUID)
    parser.add_argument("--label", required=True, type=matching(LABEL, "a label"))
    parser.add_argument("--endpoint-counts", action="store_true")
    return parser


async def _report(settings: Settings, args: argparse.Namespace) -> dict[str, Any]:
    async with snapshot(settings.database_url.get_secret_value()) as connection:  # read only, one snapshot
        return await mem_report(
            connection,
            open_storage(settings),
            settings,
            args.document,
            args.label,
            endpoint_counts=args.endpoint_counts,
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))  # a call amiss exits with 2
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        made = asyncio.run(_report(settings, args), loop_factory=asyncio.SelectorEventLoop)
    except Refused as refused:
        log.error("%s", refused)
        return 1
    try:
        closed(made)  # the keys and codes come from the database and the run's result
    except ValueError:
        log.error("%s: a key or leaf is no count, rate or code", NOT_CLOSED)
        return 1
    sys.stdout.buffer.write((json.dumps(made) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
