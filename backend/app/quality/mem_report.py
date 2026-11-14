"""``python -m app.quality.mem_report <document> --label <label> [--endpoint-counts]``: what an import from
the MEM endpoint found (plan M2, E15; plan H-3, A10), as one line of JSON - counts and rates alone, the
document named by the label, never by its title, nor its plan by its IRI:

- ``import``: what the run IM counted - parts, references, rows by typing rule, rows of no storable IRI,
  rows by search stage for nodes and statements, rows past the search's time, rows on the title pages;
- ``hits``: the anchor search's hit rate, over all rows and without the title pages, by the anchor sample's
  strata (app/quality/mem_hits.py, which says where the two figures still differ by construction);
- ``run``: how long the run took, beside MEM_SEARCH_BUDGET_S and the job's lease as configured now;
- ``findings`` by rule and ``shacl``, as X5 left them;
- ``rare_word_hidden``: the not-found wordings whose rarest word (of three letters and more) the searched
  text holds more often than the fuzzy stage tries places (``FUZZY_PLACES``) - its place may lie past them;
- ``label_is_iri_tail``: parts titled by their IRI's tail - of no label, or of one that says no more -;
  ``cut``: node titles longer than ``MAX_TITLE`` and statement wordings longer than ``MAX_WORDING``, which
  the import cut - both from the plan's answers kept under the run (null where they are gone), typed by the
  rules as they stand now (``cut`` null too where the catalogue names the plan no more);
- with ``--endpoint-counts`` alone the endpoint is asked (``endpoint``: app/sources/mem/queries.py
  ``label_shape_count``) - only on the operator's word, as every query there.

Without the switch the database and the object store are all it reads, through one snapshot that refuses
every write (app/db/snapshot.py). The searched text and the title pages for ``rare_word_hidden`` are found
as the import found them (app/pipeline/ground.py ``contents_of``), by the document's cues as they stand now.
Exit code 1 for a document that is not there or no import, an endpoint refused or away, or an output that
is not counts and codes alone (``report_not_closed``); 2 for a call amiss."""

import argparse
import asyncio
import json
import logging
import re
import sys
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.core.storage import Storage, open_storage
from app.db.conversions import all_blocks
from app.db.documents import Document, document_for_job
from app.db.gold_report import head_of
from app.db.mem_measures import findings_by_rule, import_run, not_found_wordings
from app.db.mem_plans import MemPlan, plan_by_iri
from app.db.runs import stage_result
from app.db.snapshot import snapshot
from app.llm.raw import kept_answers
from app.pipeline.anchor_fuzzy import FUZZY_PLACES, FUZZY_QUOTE
from app.pipeline.anchor_match import needle
from app.pipeline.anchor_search import search_text
from app.pipeline.ground import contents_of, ground_of
from app.quality.closed import NOT_CLOSED, closed, token
from app.quality.mem_hits import hits
from app.quality.sample import LABEL, matching
from app.sources.mem.classes import typed
from app.sources.mem.drafts import MAX_TITLE, MAX_WORDING
from app.sources.mem.queries import LABEL_SHAPES, label_shape_count
from app.sources.mem.rules_db import load_rules
from app.sources.mem.sparql import KMK_GRAPH, MemEndpoint, MemRefused, MemSparql, MemUnavailable
from app.sources.mem.tree import MemTree, build_tree, iri_tail

log = logging.getLogger("app.quality.mem_report")  # also when run as __main__

IMPORT_COUNTS = ("rules", "parts", "references", "typed", "untraced", "stages", "unsearched", "front")
_WORD = re.compile(r"\w{3,}")  # a word as the fuzzy stage picks its places by (app/pipeline/anchor_fuzzy.py)


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def rarest_too_often(wording: str, text: str) -> bool:
    """Whether the rarest of the words the fuzzy stage looks for the wording's places by stands in ``text``
    more often than it tries places; a wording none of whose words stand there is not."""
    counts = [text.count(word) for word in set(_WORD.findall(needle(wording)[:FUZZY_QUOTE]))]
    held = [count for count in counts if count]
    return bool(held) and min(held) > FUZZY_PLACES


async def _rare_word_hidden(connection: psycopg.AsyncConnection, document: Document) -> int:
    blocks = await all_blocks(connection, document.conversion_id)
    ground = await ground_of(connection, document)
    contents = await asyncio.to_thread(contents_of, ground, blocks, document.document_type_iri)
    text = search_text(blocks, contents.positions).text
    wordings = await not_found_wordings(connection, document.id)
    return sum(rarest_too_often(wording, text) for wording in wordings)


async def _kept_tree(storage: Storage, run_id: UUID) -> MemTree | None:
    """The plan's tree as the run read it, from its answers kept raw; None where they are gone or unread."""
    [data, *_] = await kept_answers(storage, run_id, "im", 1)
    if data is None:
        return None
    try:
        kept = json.loads(data)
        return build_tree(kept["closure"], kept["references"])
    except (ValueError, KeyError, TypeError, MemRefused):
        return None


async def _cut(connection: psycopg.AsyncConnection, settings: Settings, tree: MemTree, plan: MemPlan) -> Any:
    rules = await load_rules(connection, settings.ontology_dir, kmk=plan.graph == KMK_GRAPH)
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
    tree = await _kept_tree(storage, run.id)
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
        "rare_word_hidden": await _rare_word_hidden(connection, document),
        "label_is_iri_tail": None
        if tree is None
        else sum(part.label == iri_tail(part.iri) for part in tree.parts.values()),
        "cut": None if tree is None or plan is None else await _cut(connection, settings, tree, plan),
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
