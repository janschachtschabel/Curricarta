"""The MEM typing rules as the import loads them (app/sources/mem/rules_db.py, Teilplan M2-5a): the school
lexicon's cues and the vocabulary's concepts from the database, the class chain and the base types from the
ontology's files - typing every part of the Länder's frozen plans as the rules read from the files do."""

import dataclasses
import json
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest

from app.db.migrate import migrate
from app.sources.mem.classes import RULES, typed
from app.sources.mem.rules_db import load_rules
from app.sources.mem.tree import MemPart, build_tree
from app.vocab.store import load_vocabulary
from tests.sources.test_mem_classes import rules as file_rules
from tests.support import ONTOLOGY, ontology_vocabulary

pytestmark = [pytest.mark.pg, pytest.mark.anyio]

LP = "https://w3id.org/lehrplan/ontology/"
FIXTURES = Path(__file__).parents[1] / "sources" / "fixtures" / "mem"


@pytest.fixture
async def connection(database_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as opened:
        yield opened


@pytest.mark.parametrize("land", ["rp", "sn", "by", "be"])
async def test_the_rules_from_the_database_type_a_plan_as_those_from_the_files(
    connection: psycopg.AsyncConnection, land: str
) -> None:
    answers = json.loads((FIXTURES / f"{land}.json").read_text(encoding="utf-8"))
    tree = build_tree(answers["closure"], answers["references"])

    loaded = await load_rules(connection, ONTOLOGY)

    assert loaded.version == RULES
    for part in tree.parts.values():
        assert typed(part, loaded) == typed(part, file_rules()), part.iri


async def test_a_retired_cue_types_no_more(connection: psycopg.AsyncConnection) -> None:
    lp = "https://w3id.org/lehrplan/ontology/LP_0000345"  # Teilthema (RP), the lexicon maps it by a cue
    before = await load_rules(connection, ONTOLOGY)
    await connection.execute(
        "UPDATE lexical_cue SET retired_in = (SELECT max(id) FROM vocab_release)"
        " WHERE properties -> 'http://www.w3.org/2004/02/skos/core#exactMatch'"
        " @> jsonb_build_array(jsonb_build_object('iri', %s::text))",
        (lp,),
    )

    after = await load_rules(connection, ONTOLOGY)

    assert lp in before.targets and lp not in after.targets


async def test_a_cue_whose_target_is_retired_types_no_more(connection: psycopg.AsyncConnection) -> None:
    lp = "https://w3id.org/lehrplan/ontology/LP_0000345"  # Teilthema (RP): a cue to schul:Inhaltsbereich
    await connection.execute(
        "UPDATE vocab_concept SET retired_in = (SELECT max(id) FROM vocab_release) WHERE iri = %s",
        ("https://w3id.org/wlo/curriculum/profile/school#Inhaltsbereich",),
    )

    loaded = await load_rules(connection, ONTOLOGY)

    assert typed(MemPart("https://w3id.org/p/x", "Teil", (lp,)), loaded).rule != "cue"


async def test_a_subkind_s_default_addressee_is_loaded(connection: psycopg.AsyncConnection) -> None:
    loaded = await load_rules(connection, ONTOLOGY)

    assert loaded.addressees["https://w3id.org/wlo/curriculum/profile/school#Kompetenzerwartung"] == (
        "https://w3id.org/wlo/curriculum/vocab#addr_learner"
    )


async def test_the_rules_for_the_kmk_s_graph_type_its_plan_as_those_from_the_files(
    connection: psycopg.AsyncConnection,
) -> None:
    answers = json.loads((FIXTURES / "kmk.json").read_text(encoding="utf-8"))
    tree = build_tree(answers["closure"], answers["references"])
    files = dataclasses.replace(file_rules(), kmk=True)

    loaded, plain = await load_rules(connection, ONTOLOGY, kmk=True), await load_rules(connection, ONTOLOGY)

    assert (loaded.kmk, plain.kmk) == (True, False)
    cued = MemPart("https://w3id.org/p/x", "Teil", (LP + "LP_0000536", LP + "LP_0030264"))  # a cue's
    for part in [*tree.parts.values(), cued]:
        assert typed(part, loaded) == typed(part, files), part.iri
    assert typed(cued, loaded).rule == "cue"
