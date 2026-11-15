"""What the runs of a document cost, as the ledger holds it (plan H-3, A3): its requests summed by purpose
(``llm_usage`` by its run, ``extraction_run.document_id``), the reservations left of them, the runs by
stage, the conversion's pages, and how many answers each run was booked for - the number of its answers
the store keeps (app/llm/raw.py). Counts alone."""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.db.runs import STAGE_PREFIX

# The requests of the document's runs by purpose. Tokens as the answers reported them; a booking at what
# was held for a request (estimated: sent and never answered, or an answer that reported nothing) counted
# apart - in charged_tokens with the rest, what the budget was charged
_BY_PURPOSE = """
SELECT u.purpose, sum(u.requests)::int AS requests, sum(u.unanswered_requests)::int AS unanswered_requests,
    coalesce(sum(u.input_tokens) FILTER (WHERE NOT u.estimated), 0)::bigint AS input_tokens,
    coalesce(sum(u.cached_input_tokens) FILTER (WHERE NOT u.estimated), 0)::bigint AS cached_input_tokens,
    coalesce(sum(u.output_tokens) FILTER (WHERE NOT u.estimated), 0)::bigint AS output_tokens,
    sum(u.charged_tokens)::bigint AS charged_tokens,
    count(*) FILTER (WHERE u.estimated)::int AS estimated_rows,
    coalesce(sum(u.charged_tokens) FILTER (WHERE u.estimated), 0)::bigint AS estimated_charged_tokens,
    coalesce(max(u.output_tokens) FILTER (WHERE NOT u.estimated), 0)::bigint AS max_output_tokens,
    count(*) FILTER (WHERE NOT u.estimated AND u.requests > 0 AND u.output_tokens >= %(cap)s)::int
        AS cut_answers
FROM llm_usage u JOIN extraction_run r ON r.id = u.run_id
WHERE r.document_id = %(document)s
GROUP BY u.purpose ORDER BY u.purpose
"""
_RESERVED = """
SELECT v.purpose, count(*)::int FROM usage_reservation v JOIN extraction_run r ON r.id = v.run_id
WHERE r.document_id = %s GROUP BY v.purpose
"""
_RUNS = """
SELECT stage_iri, coalesce(outcome, 'unended'), count(*)::int,
    sum(extract(epoch FROM finished_at - started_at))::float
FROM extraction_run WHERE document_id = %s GROUP BY 1, 2 ORDER BY 1, 2
"""
_CONVERSION = """
SELECT u.engine, u.pages, u.billable FROM document d
JOIN conversion_usage u ON u.conversion_id = d.conversion_id
WHERE d.id = %s
"""
# How many answers each run of the document was booked for, in the order the runs began: a request booked
# as answered - reported, or at what was held where the answer reported nothing (app/llm/booking.py
# answered) -, not one refused (no tokens), cut off unanswered, or abandoned with its job; whether the
# retention took its answers (python -m app.retention clears the key); the tokens the answers reported, as
# _BY_PURPOSE sums them
_ANSWERED = """
SELECT r.id, r.stage_iri, count(u.id) FILTER (
    WHERE u.requests > 0 AND u.unanswered_requests = 0 AND (u.input_tokens > 0 OR u.estimated)
)::int, r.raw_response_key IS NULL,
    coalesce(sum(u.input_tokens) FILTER (WHERE NOT u.estimated), 0)::bigint,
    coalesce(sum(u.cached_input_tokens) FILTER (WHERE NOT u.estimated), 0)::bigint,
    coalesce(sum(u.output_tokens) FILTER (WHERE NOT u.estimated), 0)::bigint
FROM extraction_run r JOIN llm_usage u ON u.run_id = r.id
WHERE r.document_id = %s
GROUP BY r.id, r.stage_iri, r.started_at ORDER BY r.started_at, r.id
"""


@dataclass(frozen=True)
class PurposeUsage:
    purpose: str  # as the ledger books it: "x4.unit"
    requests: int
    unanswered_requests: int
    input_tokens: int  # of the answers that reported their usage
    cached_input_tokens: int
    output_tokens: int
    charged_tokens: int  # every booking, the estimated ones with them
    estimated_rows: int
    estimated_charged_tokens: int
    max_output_tokens: int  # the largest answer reported
    cut_answers: int  # answers reported at the cap given (today's) or beyond it
    reservations_left: int  # held and never booked


@dataclass(frozen=True)
class StageRuns:
    outcomes: dict[str, int]  # done, failed, budget_exhausted, unended
    seconds: float | None  # over the runs that ended


@dataclass(frozen=True)
class RunAnswers:
    run_id: UUID
    stage: str  # by its notation: "X4"
    answers: int  # booked as answered
    swept: bool  # its answers taken from the store by the retention, its key cleared
    tokens: tuple[int, int, int]  # input, of it cached, output, as its answers reported them to the ledger


async def usage_by_purpose(
    connection: psycopg.AsyncConnection, document_id: UUID, *, cap: int
) -> list[PurposeUsage]:
    """The requests of the document's runs, by purpose; ``cap``, the answers' (LLM_MAX_OUTPUT_TOKENS)."""
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(_BY_PURPOSE, {"document": document_id, "cap": cap})
        rows = await cursor.fetchall()
    reserved = await _reserved(connection, document_id)
    found = [PurposeUsage(**row, reservations_left=reserved.pop(row["purpose"], 0)) for row in rows]
    # a reservation of a purpose nothing was booked for yet
    found += [_held_alone(purpose, count) for purpose, count in sorted(reserved.items())]
    return sorted(found, key=lambda usage: usage.purpose)


def _held_alone(purpose: str, count: int) -> PurposeUsage:
    return PurposeUsage(purpose, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, count)


async def _reserved(connection: psycopg.AsyncConnection, document_id: UUID) -> dict[str, int]:
    cursor = await connection.execute(_RESERVED, (document_id,))
    return {purpose: count for purpose, count in await cursor.fetchall()}


async def runs_summary(connection: psycopg.AsyncConnection, document_id: UUID) -> dict[str, StageRuns]:
    """The document's runs by stage notation: how many ended how, and how long the ended ones took."""
    cursor = await connection.execute(_RUNS, (document_id,))
    found: dict[str, StageRuns] = {}
    for stage_iri, outcome, count, seconds in await cursor.fetchall():
        stage = stage_iri.removeprefix(STAGE_PREFIX)
        runs = found.setdefault(stage, StageRuns({}, None))
        runs.outcomes[outcome] = count
        if seconds is not None:
            found[stage] = StageRuns(runs.outcomes, (runs.seconds or 0.0) + seconds)
    return found


async def conversion_usage_of(
    connection: psycopg.AsyncConnection, document_id: UUID
) -> Mapping[str, object] | None:
    """The conversion's booking: its engine, pages, whether billable; None where none is booked."""
    cursor = await connection.execute(_CONVERSION, (document_id,))
    found = await cursor.fetchone()
    return None if found is None else {"engine": found[0], "pages": found[1], "billable": found[2]}


async def answered_runs(connection: psycopg.AsyncConnection, document_id: UUID) -> list[RunAnswers]:
    """The document's runs that were booked a request, in the order they began, each with how many
    answers - the ones the store keeps, numbered from 1, until the retention takes them."""
    cursor = await connection.execute(_ANSWERED, (document_id,))
    return [
        RunAnswers(run, stage.removeprefix(STAGE_PREFIX), count, swept, (input_tokens, cached, output))
        for run, stage, count, swept, input_tokens, cached, output in await cursor.fetchall()
    ]
