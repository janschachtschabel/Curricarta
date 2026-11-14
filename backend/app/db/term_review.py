"""The terms X1 found no type for and the editors' decisions on them (migration term_review, plan M1
10.4): each new term of each document's profile, as X1 gave it (app/lexicon/new_terms.py gathers them), and
one decision for each term - a sector, its regions, its key -, made again over the last. A new cue says
whether the files hold it yet (`applied`): an active cue of the profile with its word, target, role and
exactly its regions."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.db.anchors import CV
from app.db.cue_review import SOURCE
from app.lexicon.held import HeldCue
from app.lexicon.new_terms import Occurrence
from app.sources.register import EDUCATION_SECTORS
from app.vocab.lookup import REGIONS

TermDecision = Literal["cue", "document", "error"]  # a new cue; peculiar to its document; misread

CUE_ROLES = CV + "CueRoles"
ROLE = CV + "role_"  # a cue role is this and its notation: role_alt
_OCCURRENCES = """
SELECT d.id, d.title, d.created_at, s.notation AS sector, d.sector_iri, d.regions,
    term ->> 'documentTerm' AS text, term ->> 'evidenceBlockId' AS block,
    term ->> 'suggestedFunction' AS function
FROM document d
JOIN document_profile p ON p.document_id = d.id
JOIN vocab_concept s ON s.iri = d.sector_iri
CROSS JOIN jsonb_array_elements(p.new_terms) AS term
WHERE s.retired_in IS NULL AND jsonb_typeof(term -> 'documentTerm') = 'string'
    AND (%(sector)s::text IS NULL OR d.sector_iri = %(sector)s)
"""
_HELD = """
SELECT c.iri, p.sector_iri, c.surface_form, c.pattern, c.maps_to, c.role_iri,
    ARRAY(SELECT r FROM unnest(c.scope_regions) AS r ORDER BY r COLLATE "C") AS regions,
    NOT EXISTS (
        SELECT FROM jsonb_array_elements(c.properties -> %(source)s) AS source
        WHERE starts_with(source ->> 'value', 'recherche-ergebnisse/')
    ) AS own
FROM lexical_cue c
JOIN terminology_profile p ON p.iri = c.profile_iri
JOIN vocab_concept s ON s.iri = p.sector_iri
WHERE c.retired_in IS NULL AND p.retired_in IS NULL AND s.retired_in IS NULL
"""
_DECIDE = """
INSERT INTO term_review (sector_scheme, sector_iri, regions, term_key, surface_form, decision, profile_iri,
    maps_to, role_scheme, role_iri, note, content, decided_by)
VALUES (%(sectors)s, %(sector)s, %(regions)s, %(key)s, %(form)s, %(decision)s, %(profile)s, %(maps_to)s,
    %(roles)s, %(role)s, %(note)s, %(content)s, %(account)s)
ON CONFLICT (sector_iri, regions, term_key) DO UPDATE SET surface_form = excluded.surface_form,
    decision = excluded.decision, profile_iri = excluded.profile_iri, maps_to = excluded.maps_to,
    role_scheme = excluded.role_scheme, role_iri = excluded.role_iri, note = excluded.note,
    content = excluded.content, decided_by = excluded.decided_by, decided_at = now()
"""
_REVIEWS = """
SELECT s.notation AS sector, r.sector_iri, r.regions, r.term_key, r.surface_form, r.decision, r.profile_iri,
    r.maps_to, r.role_iri, r.note, r.content, a.name AS decided_by, r.decided_at,
    CASE WHEN r.decision = 'cue' THEN EXISTS (
        SELECT FROM lexical_cue c
        JOIN terminology_profile p ON p.iri = c.profile_iri
        WHERE c.profile_iri = r.profile_iri AND c.retired_in IS NULL AND p.retired_in IS NULL
            AND c.surface_form = r.surface_form AND r.maps_to = ANY (c.maps_to) AND c.role_iri = r.role_iri
            AND c.scope_regions @> places.iris AND c.scope_regions <@ places.iris
    ) END AS applied
FROM term_review r
JOIN account a ON a.id = r.decided_by
JOIN vocab_concept s ON s.iri = r.sector_iri
CROSS JOIN LATERAL (
    SELECT ARRAY(
        SELECT iri FROM vocab_concept
        WHERE scheme_iri = %(regions)s AND notation = ANY (r.regions) AND retired_in IS NULL
    ) AS iris
) AS places
"""


@dataclass(frozen=True)
class Judged:
    """The term a decision is on, as the editors saw it."""

    sector_iri: str
    regions: tuple[str, ...]  # sorted
    key: str
    surface_form: str
    profile: str | None  # the sector's active profile, which a new cue's target is of
    content: dict[str, Any]  # what else was judged: the functions suggested, how many documents named it


@dataclass(frozen=True)
class Choice:
    decision: TermDecision
    maps_to: str | None = None  # a new cue's: a node type of the profile
    role: str | None = None  # a new cue's: a cv:CueRoles IRI
    note: str | None = None


@dataclass(frozen=True)
class TermReview:
    sector: str  # the notation of the sector
    sector_iri: str
    regions: tuple[str, ...]
    key: str
    surface_form: str
    decision: TermDecision
    profile: str | None
    maps_to: str | None
    role: str | None
    note: str | None
    content: dict[str, Any]
    decided_by: str  # the account's name
    decided_at: datetime
    applied: bool | None  # a new cue: whether an active cue says it; None, nothing to apply


async def occurrences(connection: psycopg.AsyncConnection, sector_iri: str | None = None) -> list[Occurrence]:
    """Each new term of each document's profile, of the active sectors or of this one."""
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_OCCURRENCES, {"sector": sector_iri})
        rows = await cursor.fetchall()
    return [
        Occurrence(
            document=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            sector=row["sector"],
            sector_iri=row["sector_iri"],
            regions=tuple(row["regions"]),
            text=row["text"],
            block=row["block"],
            function=row["function"],
        )
        for row in rows
    ]


async def decide_term(
    connection: psycopg.AsyncConnection, account: uuid.UUID, judged: Judged, choice: Choice
) -> TermReview:
    """Decide on the term, over any decision before; the decision as term_reviews gives it."""
    await connection.execute(
        _DECIDE,
        {
            "sectors": EDUCATION_SECTORS,
            "sector": judged.sector_iri,
            "regions": list(judged.regions),
            "key": judged.key,
            "form": judged.surface_form,
            "decision": choice.decision,
            "profile": judged.profile,
            "maps_to": choice.maps_to,
            "roles": None if choice.role is None else CUE_ROLES,
            "role": choice.role,
            "note": choice.note,
            "content": Jsonb(judged.content),
            "account": account,
        },
    )
    made = await review_of(connection, judged.sector_iri, judged.regions, judged.key)
    assert made is not None  # noqa: S101 - written just before
    return made


async def review_of(
    connection: psycopg.AsyncConnection, sector_iri: str, regions: tuple[str, ...], key: str
) -> TermReview | None:
    """The decision on this term, if any."""
    found = await _reviews(
        connection,
        " WHERE r.sector_iri = %(sector)s AND r.regions = %(of)s AND r.term_key = %(key)s",
        {"sector": sector_iri, "of": list(regions), "key": key},
    )
    return found[0] if found else None


async def term_reviews(connection: psycopg.AsyncConnection) -> list[TermReview]:
    """Every decision, in the order of their terms: sector, regions, key."""
    return await _reviews(
        connection, ' ORDER BY s.notation COLLATE "C", r.regions COLLATE "C", r.term_key COLLATE "C"', {}
    )


async def _reviews(
    connection: psycopg.AsyncConnection, rest: str, values: dict[str, Any]
) -> list[TermReview]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_REVIEWS + rest, {"regions": REGIONS} | values)
        rows = await cursor.fetchall()
    return [
        TermReview(
            sector=row["sector"],
            sector_iri=row["sector_iri"],
            regions=tuple(row["regions"]),
            key=row["term_key"],
            surface_form=row["surface_form"],
            decision=row["decision"],
            profile=row["profile_iri"],
            maps_to=row["maps_to"],
            role=row["role_iri"],
            note=row["note"],
            content=row["content"],
            decided_by=row["decided_by"],
            decided_at=row["decided_at"],
            applied=row["applied"],
        )
        for row in rows
    ]


async def held_cues(connection: psycopg.AsyncConnection) -> list[HeldCue]:
    """The active cues of the active profiles, as app/lexicon/held.py asks whether one holds a new term."""
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_HELD, {"source": SOURCE})
        rows = await cursor.fetchall()
    return [
        HeldCue(
            iri=row["iri"],
            sector_iri=row["sector_iri"],
            own=row["own"],
            surface_form=row["surface_form"],
            pattern=row["pattern"],
            maps_to=tuple(row["maps_to"]),
            role=row["role_iri"],
            regions=tuple(row["regions"]),
        )
        for row in rows
    ]
