"""The research cues the editors decide on and their decisions (app/db/cue_review.py, plan M1 10.3, 10c C3,
C5): the active cues the research gave - never the sectors' own -, one decision for each, made again over
the last, with what was judged as the cue said it then; a decision outlives its cue's retirement."""

import uuid
from collections import Counter
from collections.abc import AsyncIterator
from decimal import Decimal

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.db.cue_review import SOURCE, decide, decisions, research_cues
from tests.db.test_nodes import url

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["url"]  # the database with the vocabularies of the ontology, shared with test_nodes

CV = "https://w3id.org/wlo/curriculum/vocab#"
OWN = "https://w3id.org/wlo/curriculum/profile/school#cue-dt-kernlehrplan"  # the school's own "Kernlehrplan"


@pytest.fixture
async def connection(url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as opened:
        yield opened


async def an_account(connection: psycopg.AsyncConnection, name: str = "Redaktion") -> uuid.UUID:
    account = uuid.uuid4()
    await connection.execute("INSERT INTO account (id, name) VALUES (%s, %s)", (account, f"{name} {account}"))
    return account


async def test_the_research_cues_are_the_active_ones_the_research_gave_by_sector(
    connection: psycopg.AsyncConnection,
) -> None:
    cues = await research_cues(connection)

    assert Counter(cue.sector for cue in cues) == {
        "school": 660,
        "elementary": 580,
        "vocational": 118,
        "higher": 60,
        "adult": 73,
    }
    assert all(source.startswith("recherche-ergebnisse/") for cue in cues for source in cue.sources)
    assert OWN not in {cue.iri for cue in cues}
    assert [cue.iri for cue in cues] == sorted(cue.iri for cue in cues)


async def test_a_research_cue_says_what_the_editors_judge(connection: psycopg.AsyncConnection) -> None:
    turned = (await research_cues(connection))[0].iri  # its regions as no release writes them: out of order
    await connection.execute(
        "UPDATE lexical_cue SET scope_regions = %s WHERE iri = %s",
        (
            ["https://w3id.org/wlo/curriculum/region/DE-NW", "https://w3id.org/wlo/curriculum/region/DE-BY"],
            turned,
        ),
    )
    cues = await research_cues(connection)
    cue = next(
        cue for cue in cues if cue.surface_form == "Abiturprüfung" and cue.regions[0].endswith("/DE-NW")
    )

    assert cue.stratum == ("school", cue.regions)
    assert cue.sources == ("recherche-ergebnisse/01-schule-DE-NW.md",)
    assert (cue.verified, cue.strength) == (False, Decimal("0.7"))
    assert any(note.startswith("Länderrecherche, Beleg E: ") for note in cue.notes)
    assert all(
        len(cue.regions) == len(set(cue.regions)) and cue.regions == tuple(sorted(cue.regions))
        for cue in cues
    )
    assert sum(bool(cue.recognition_hints) for cue in cues) > 100  # the research's erkennungsmerkmal
    assert sum(bool(cue.examples) for cue in cues) > 100


async def test_a_cue_with_another_source_or_of_a_retired_profile_or_sector_is_none(
    connection: psycopg.AsyncConnection,
) -> None:
    await connection.execute(
        "UPDATE lexical_cue SET properties = %s WHERE iri = %s",
        (Jsonb({SOURCE: [{"value": "Kernlehrplan Physik NRW"}]}), OWN),
    )
    await connection.execute(
        "UPDATE terminology_profile SET retired_in = 1 WHERE iri = %s",
        ("https://w3id.org/wlo/curriculum/profile/higher-education#Terminology",),
    )
    await connection.execute("UPDATE vocab_concept SET retired_in = 1 WHERE iri = %s", (CV + "sec_adult",))

    cues = await research_cues(connection)

    assert OWN not in {cue.iri for cue in cues}
    assert {cue.sector for cue in cues} == {"school", "elementary", "vocational"}


async def test_a_retired_cue_is_no_research_cue_to_decide_on(connection: psycopg.AsyncConnection) -> None:
    first = (await research_cues(connection))[0]
    await connection.execute("UPDATE lexical_cue SET retired_in = 1 WHERE iri = %s", (first.iri,))

    assert first.iri not in {cue.iri for cue in await research_cues(connection)}
    assert (
        await decide(connection, await an_account(connection), first.iri, "rejected", None, None, None)
        is None
    )


async def test_a_confirmed_cue_keeps_what_was_judged_and_by_whom(connection: psycopg.AsyncConnection) -> None:
    cue = (await research_cues(connection))[0]
    account = await an_account(connection)

    made = await decide(connection, account, cue.iri, "confirmed", Decimal("0.9"), "KLP S. 14", "passt")

    assert made is not None
    assert (made.cue, made.decision, made.strength, made.evidence, made.note) == (
        cue.iri,
        "confirmed",
        Decimal("0.90"),
        "KLP S. 14",
        "passt",
    )
    assert made.decided_by == f"Redaktion {account}"
    assert (made.retired, made.applied) == (False, False)  # verified and raised only by the next release
    assert made.content == {
        "surface_form": cue.surface_form,
        "pattern": cue.pattern,
        "maps_to": list(cue.maps_to),
        "scope_regions": list(cue.regions),
        "role": cue.role,
        "kind": cue.kind,
        "profile": cue.profile,
    }
    assert await decisions(connection) == [made]


async def test_a_cue_decided_again_keeps_the_last_decision_only(connection: psycopg.AsyncConnection) -> None:
    cue = (await research_cues(connection))[0]
    await decide(connection, await an_account(connection), cue.iri, "confirmed", Decimal("0.8"), "S. 3", None)

    (first,) = await decisions(connection)
    regions = ["https://w3id.org/wlo/curriculum/region/DE-SN", "https://w3id.org/wlo/curriculum/region/DE-BY"]
    await connection.execute(
        "UPDATE lexical_cue SET surface_form = 'Neues Wort', scope_regions = %s WHERE iri = %s",
        (regions, cue.iri),
    )
    again = await decide(
        connection, await an_account(connection, "Admin"), cue.iri, "rejected", None, None, None
    )

    assert again is not None
    assert (again.decision, again.strength, again.evidence) == ("rejected", None, None)
    assert again.decided_by.startswith("Admin ")
    assert again.decided_at > first.decided_at
    assert (again.content["surface_form"], again.content["scope_regions"]) == ("Neues Wort", sorted(regions))
    assert await decisions(connection) == [again]


async def test_a_decided_cue_is_decided_on_again_also_once_retired(
    connection: psycopg.AsyncConnection,
) -> None:
    cue, undecided = (await research_cues(connection))[:2]
    account = await an_account(connection)
    await decide(connection, account, cue.iri, "rejected", None, None, None)
    await connection.execute(
        "UPDATE lexical_cue SET retired_in = 1 WHERE iri = ANY (%s)", ([cue.iri, undecided.iri],)
    )

    again = await decide(connection, account, cue.iri, "confirmed", Decimal("0.8"), "S. 2", "doch richtig")

    assert again is not None
    assert (again.decision, again.retired, again.applied) == ("confirmed", True, False)
    # its own decision, not any: a retired cue nobody decided on stays none to decide on
    assert await decide(connection, account, undecided.iri, "rejected", None, None, None) is None


async def test_only_a_research_cue_is_decided_on(connection: psycopg.AsyncConnection) -> None:
    account = await an_account(connection)

    assert await decide(connection, account, OWN, "rejected", None, None, None) is None
    assert await decide(connection, account, OWN + "-unknown", "rejected", None, None, None) is None
    assert await decisions(connection) == []


async def test_a_decision_outlives_its_cue_and_a_rejection_is_then_applied(
    connection: psycopg.AsyncConnection,
) -> None:
    rejected, confirmed = (await research_cues(connection))[:2]
    account = await an_account(connection)
    await decide(connection, account, rejected.iri, "rejected", None, None, None)
    await decide(connection, account, confirmed.iri, "confirmed", Decimal("0.9"), "S. 1", None)
    await connection.execute(  # the confirmed one as its release said it last: verified at 0.9
        "UPDATE lexical_cue SET verified = true, strength = 0.9 WHERE iri = %s", (confirmed.iri,)
    )
    await connection.execute(
        "UPDATE lexical_cue SET retired_in = 1 WHERE iri = ANY (%s)", ([rejected.iri, confirmed.iri],)
    )

    made = await decisions(connection)

    assert {each.cue: (each.retired, each.applied) for each in made} == {
        rejected.iri: (True, True),
        confirmed.iri: (True, False),
    }
    assert [each.cue for each in made] == sorted([rejected.iri, confirmed.iri])


async def test_a_confirmation_is_applied_once_the_cue_is_verified_at_its_strength(
    connection: psycopg.AsyncConnection,
) -> None:
    cue = (await research_cues(connection))[0]
    await decide(connection, await an_account(connection), cue.iri, "confirmed", Decimal("0.9"), "S. 1", None)
    found = []
    for verified, strength in [(False, "0.9"), (True, "0.8"), (True, "0.9")]:
        await connection.execute(
            "UPDATE lexical_cue SET verified = %s, strength = %s WHERE iri = %s",
            (verified, strength, cue.iri),
        )
        (made,) = await decisions(connection)
        found.append(made.applied)

    assert found == [False, False, True]
