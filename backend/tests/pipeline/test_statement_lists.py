"""The lists a statement question names its lexicon's targets by (app/pipeline/unit_question.py): a
cue for a statement's wording field reaches the task as that field (Rahmencurriculum
Integrationskurse: "Möchte …" in a column of its own is the purpose of its row's statement)."""

from collections.abc import AsyncIterator

import psycopg
import pytest

from app.db.migrate import migrate
from app.domain.lexicon import ActiveCue, Cue
from app.pipeline.lexicon_excerpt import lexicon_excerpt
from app.pipeline.unit_question import statement_lists
from app.vocab.store import load_vocabulary
from tests.support import ontology_vocabulary

CUR = "https://w3id.org/wlo/curriculum/core#"
CV = "https://w3id.org/wlo/curriculum/vocab#"

pytestmark = [pytest.mark.pg, pytest.mark.anyio]


@pytest.fixture
async def connection(database_url: str, preloaded_vocabulary: None) -> AsyncIterator[psycopg.AsyncConnection]:
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as opened:
        yield opened


async def test_a_cue_for_a_statement_s_purpose_reaches_the_task_as_its_field(
    connection: psycopg.AsyncConnection,
) -> None:
    lists = await statement_lists(connection, "adult")
    wish = Cue(iri="cue-wish", role=CV + "role_cue", kind=CV + "ck_sentencePattern",
               maps_to=(CUR + "purpose",), pattern=r"^Möchte\s", strength=0.8)  # fmt: skip

    excerpt = lexicon_excerpt([ActiveCue(wish, tie=False)], ["Möchte eine Wohnung finden."], lists.names)

    assert lists.names[CUR + "purpose"] == "purposeText"
    assert "purposeText" in excerpt.text
