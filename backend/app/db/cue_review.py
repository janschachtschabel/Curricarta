"""The editors' decisions on the research cues (migration cue_review, plan M1 10.3): the cues the research
gave - active, with a source among recherche-ergebnisse/, never a sector's own - and one decision for each,
made again over the last. What was judged is kept with it, as the cue said it then; a decision outlives its
cue's retirement, and says whether the files hold it yet (`applied`)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from app.lexicon.sample import Stratum

CueDecision = Literal["confirmed", "rejected"]

SOURCE = "http://purl.org/dc/terms/source"
NOTE = "http://www.w3.org/2004/02/skos/core#editorialNote"
_FROM_RESEARCH = """
FROM lexical_cue c
JOIN terminology_profile p ON p.iri = c.profile_iri
JOIN vocab_concept s ON s.iri = p.sector_iri
WHERE EXISTS (
    SELECT FROM jsonb_array_elements(c.properties -> %(source)s) AS source
    WHERE starts_with(source ->> 'value', 'recherche-ergebnisse/')
)
"""
_ACTIVE = "c.retired_in IS NULL AND p.retired_in IS NULL AND s.retired_in IS NULL"
_RESEARCH = f"{_FROM_RESEARCH} AND {_ACTIVE}"
_CUES = f"""
SELECT c.iri, c.profile_iri, s.notation AS sector, c.scope_regions, c.surface_form, c.pattern, c.role_iri,
    c.kind_iri, c.maps_to, c.strength, c.verified, c.recognition_hints, c.positive_examples,
    ARRAY(SELECT value ->> 'value' FROM jsonb_array_elements(c.properties -> %(source)s)) AS sources,
    ARRAY(SELECT value ->> 'value' FROM jsonb_array_elements(c.properties -> %(notes)s)) AS notes
{_RESEARCH}
ORDER BY c.iri COLLATE "C"
"""  # noqa: S608 - fixed parts
_DECIDE = f"""
INSERT INTO cue_review (cue_iri, decision, strength, evidence, note, content, decided_by)
SELECT c.iri, %(decision)s, %(strength)s, %(evidence)s, %(note)s,
    jsonb_build_object(
        'surface_form', c.surface_form, 'pattern', c.pattern, 'maps_to', to_jsonb(c.maps_to),
        'scope_regions', to_jsonb(ARRAY(SELECT r FROM unnest(c.scope_regions) AS r ORDER BY r COLLATE "C")),
        'role', c.role_iri, 'kind', c.kind_iri, 'profile', c.profile_iri
    ),
    %(account)s
{_FROM_RESEARCH}
AND c.iri = %(cue)s
AND ({_ACTIVE} OR EXISTS (SELECT FROM cue_review WHERE cue_iri = c.iri))  -- decided before: undone again
ON CONFLICT (cue_iri) DO UPDATE SET decision = excluded.decision, strength = excluded.strength,
    evidence = excluded.evidence, note = excluded.note, content = excluded.content,
    decided_by = excluded.decided_by, decided_at = now()
RETURNING cue_iri
"""  # noqa: S608 - fixed parts
_DECISIONS = """
SELECT r.cue_iri, r.decision, r.strength, r.evidence, r.note, r.content, a.name AS decided_by, r.decided_at,
    c.retired_in IS NOT NULL AS retired,
    CASE r.decision
        WHEN 'confirmed' THEN c.retired_in IS NULL AND c.verified
            AND c.strength IS NOT DISTINCT FROM r.strength
        ELSE c.retired_in IS NOT NULL
    END AS applied
FROM cue_review r
JOIN lexical_cue c ON c.iri = r.cue_iri
JOIN account a ON a.id = r.decided_by
"""


@dataclass(frozen=True)
class ResearchCue:
    iri: str
    profile: str
    sector: str  # the notation of the profile's sector ("school")
    regions: tuple[str, ...]  # in their order
    surface_form: str | None
    pattern: str | None
    role: str
    kind: str
    maps_to: tuple[str, ...]
    strength: Decimal | None
    verified: bool
    sources: tuple[str, ...]
    notes: tuple[str, ...]  # where the research found it, and what it proposed
    recognition_hints: tuple[str, ...]
    examples: tuple[str, ...]

    @property
    def stratum(self) -> Stratum:
        return (self.sector, self.regions)


@dataclass(frozen=True)
class Decision:
    cue: str
    decision: CueDecision
    strength: Decimal | None
    evidence: str | None
    note: str | None
    content: dict[str, Any]  # what was judged: the cue's form, targets, regions, role, kind and profile then
    decided_by: str  # the account's name
    decided_at: datetime
    retired: bool  # the cue, since
    applied: bool  # confirmed: the cue active, verified at its strength; rejected: the cue retired


async def research_cues(connection: psycopg.AsyncConnection) -> list[ResearchCue]:
    """The active research cues, by IRI."""
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_CUES, {"source": SOURCE, "notes": NOTE})
        rows = await cursor.fetchall()
    return [
        ResearchCue(
            iri=row["iri"],
            profile=row["profile_iri"],
            sector=row["sector"],
            regions=tuple(sorted(row["scope_regions"])),
            surface_form=row["surface_form"],
            pattern=row["pattern"],
            role=row["role_iri"],
            kind=row["kind_iri"],
            maps_to=tuple(row["maps_to"]),
            strength=row["strength"],
            verified=row["verified"],
            sources=tuple(row["sources"]),
            notes=tuple(row["notes"]),
            recognition_hints=tuple(row["recognition_hints"].get("de", ())),
            examples=tuple(row["positive_examples"]),
        )
        for row in rows
    ]


async def decide(
    connection: psycopg.AsyncConnection,
    account: uuid.UUID,
    cue: str,
    decision: CueDecision,
    strength: Decimal | None,
    evidence: str | None,
    note: str | None,
) -> Decision | None:
    """The account's decision on the research cue, over any before it; None where `cue` names no active
    research cue nor one decided before - a cue the files left out on a rejection is decided on again, so it
    comes back. The table's rules hold: a confirmation with a strength and evidence, a rejection without
    a strength (psycopg.errors.CheckViolation otherwise)."""
    values = {
        "cue": cue,
        "decision": decision,
        "strength": strength,
        "evidence": evidence,
        "note": note,
        "account": account,
        "source": SOURCE,
    }
    cursor = await connection.execute(_DECIDE, values)
    if await cursor.fetchone() is None:
        return None
    (made,) = await _decisions(connection, " WHERE r.cue_iri = %s", (cue,))
    return made


async def decisions(connection: psycopg.AsyncConnection) -> list[Decision]:
    """Every decision, by its cue's IRI - retired cues' too."""
    return await _decisions(connection, ' ORDER BY r.cue_iri COLLATE "C"', ())


async def _decisions(
    connection: psycopg.AsyncConnection, clause: str, params: tuple[str, ...]
) -> list[Decision]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_DECISIONS + clause, params)
        rows = await cursor.fetchall()
    return [
        Decision(
            cue=row["cue_iri"],
            decision=row["decision"],
            strength=row["strength"],
            evidence=row["evidence"],
            note=row["note"],
            content=row["content"],
            decided_by=row["decided_by"],
            decided_at=row["decided_at"],
            retired=row["retired"],
            applied=row["applied"],
        )
        for row in rows
    ]
