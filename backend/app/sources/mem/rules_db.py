"""The MEM typing rules ``mem-rules/2`` as the import loads them (plan M2, E2/E8): the school lexicon's cues
that name a state class (``skos:exactMatch`` on ``lp:``) and the vocabulary's concepts - their first broader
and default addressee - from the database, as the lexicon stands now (retired ones left out); the class
chain (``mem/lp-klassen.ttl``) and the base types (``mem/grundtypen.json``) from the ontology's files.
"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import psycopg
from rdflib import Graph

from app.sources.mem.classes import MemRules, rules_from
from app.sources.mem.queries import LP

_CUES = """
SELECT match ->> 'iri', c.maps_to[1]
FROM lexical_cue c
JOIN terminology_profile p ON p.iri = c.profile_iri
JOIN vocab_concept s ON s.iri = p.sector_iri
CROSS JOIN LATERAL jsonb_array_elements(
    coalesce(c.properties -> 'http://www.w3.org/2004/02/skos/core#exactMatch', '[]')
) AS match
WHERE s.notation = 'school' AND s.retired_in IS NULL AND p.retired_in IS NULL AND c.retired_in IS NULL
    AND starts_with(match ->> 'iri', %s)
"""
_CONCEPTS = """
SELECT iri, broader[1], properties -> 'https://w3id.org/wlo/curriculum/core#defaultAddressee' -> 0 ->> 'iri'
FROM vocab_concept WHERE retired_in IS NULL
"""


async def load_rules(
    connection: psycopg.AsyncConnection, ontology_dir: Path, *, kmk: bool = False
) -> MemRules:
    """The rules as the database and the ontology's files hold them now; with the KMK's table for a plan of
    its graph (plan M2-7, E13)."""
    cursor = await connection.execute(_CUES, (LP,))
    cues: Sequence[tuple[str, str]] = await cursor.fetchall()
    cursor = await connection.execute(_CONCEPTS)
    concepts: Sequence[tuple[str, str | None, str | None]] = await cursor.fetchall()
    chain, base_types = await asyncio.to_thread(mem_files, ontology_dir)  # parsing the chain takes a moment
    return rules_from(cues, concepts, chain, base_types, kmk=kmk)


def mem_files(ontology_dir: Path) -> tuple[Graph, Mapping[str, list[str]]]:
    """The class chain (``mem/lp-klassen.ttl``) and the base-type table (``mem/grundtypen.json``)."""
    folder = ontology_dir / "mem"
    chain = Graph().parse(folder / "lp-klassen.ttl", format="turtle")
    base_types: Mapping[str, list[str]] = json.loads(
        (folder / "grundtypen.json").read_text(encoding="utf-8")
    )["grundtypen"]
    return chain, base_types
