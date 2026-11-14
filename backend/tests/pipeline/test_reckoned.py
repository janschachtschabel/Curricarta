"""The reckoning core (app/pipeline/reckoned.py): what the rest of a run is expected to charge, in tokens
weighed as the quota counts them, and the requests X3 and X4 still owe a document - exactly those the
stages would ask. A model stands in (FunctionModel), never a provider."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import CachePoint

from app.db.conversions import all_blocks, printed_pages
from app.db.documents import document_for_job
from app.jobs.outcome import PermanentError
from app.llm.budget import count_tokens
from app.llm.calls import StageAgent
from app.llm.metering import FULL, Spent, Weights
from app.pipeline.ground import ground_of
from app.pipeline.reckoned import (
    EXPECTED_ANSWER_TOKENS,
    Request,
    expected_charge,
    owed_requests,
    request_of,
    room_for,
)
from app.pipeline.run import extract_document
from app.pipeline.side_by_side import at_once
from tests.pipeline.test_estimate import Reserved, reserved
from tests.pipeline.test_run import Model, a_document, a_job, context_of, setup
from tests.pipeline.test_x4_cut import cutting
from tests.pipeline.test_x4_statements import FIELDS
from tests.support import make_settings

__all__ = ["reserved", "setup"]  # fixtures, shared with test_estimate and test_run

LUNA = Weights(Decimal("0.1"), Decimal(5))


def a_request(
    input_tokens: int,
    shared_tokens: int,
    output_tokens: int = 16_000,
    *,
    purpose: str = "x4.unit",
    window: str = "",
) -> Request:
    return Request(purpose, input_tokens, shared_tokens, output_tokens, window)


def prefix_of(tokens: int) -> str:
    """A synthetic document of about ``tokens`` tokens, its lines as the prefix writes blocks."""
    line = '[p1-b{n}] Die Lernenden "beschreiben" Vorgänge, ordnen sie ein und begründen ihre Wahl.\n'
    lines = tokens // count_tokens(line.format(n=1))
    return "=== DOKUMENT ===\n" + "".join(line.format(n=n) for n in range(lines))


def test_a_cached_request_is_expected_near_what_its_plain_count_is_charged() -> None:
    # counted as the meter counts it - JSON, the margin of a tenth -, the request is expected within a
    # fifth of its plain count charged (the prefix from the cache): the margin on the prefix is cached too
    # (before, 1.37 times). What stays at full weight is the margin on the request's own part and the
    # JSON's escapes in the prefix - here a quote pair and a line break every line, more than a plan has
    prefix = prefix_of(20_000)
    task = "=== AUFTRAG ===\n" + "Lies die Einheit und gib ihre Aussagen an.\n" * 40
    stage = StageAgent(None, {"type": "object"}, "Antworte im Schema. " * 60, 16_000)  # type: ignore[arg-type]
    request = request_of("x4.unit", [prefix, CachePoint(), task], stage)
    plain = sum(map(count_tokens, (prefix, task, stage.instructions, '{"type": "object"}')))
    at_plain = LUNA.charged(Spent(plain, count_tokens(prefix), EXPECTED_ANSWER_TOKENS))

    cached = expected_charge([request] * 2, LUNA, uncached_first=1) - expected_charge(
        [request], LUNA, uncached_first=1
    )

    assert request.shared_tokens == count_tokens(prefix) > 19_000
    assert at_plain <= cached <= 1.2 * at_plain


def test_each_prefix_s_first_requests_are_read_whole() -> None:
    # X3's prefix is not X4's, and each window of a document read in windows is a prefix of its own
    frame = a_request(1_100, 1_000, purpose="x3.frame")
    in_a, in_b = a_request(1_100, 1_000, window="A"), a_request(1_100, 1_000, window="B")

    owed = [frame, in_a, in_a, in_a, in_b, in_b]

    expected = expected_charge(owed, LUNA, uncached_first=2, answer_tokens=100)

    assert expected == 1_600 + (2 * 1_600 + 610) + 2 * 1_600


def test_a_run_going_on_after_x3_reads_its_first_units_whole_alone() -> None:
    units = [a_request(1_100, 1_000)] * 5

    assert expected_charge(units, LUNA, uncached_first=4, answer_tokens=100) == 4 * 1_600 + 610


def test_the_units_at_once_are_the_gate_x4_asks_by() -> None:
    assert at_once(make_settings(extract_concurrency=4)) == 4
    assert at_once(make_settings(extract_concurrency=4, db_pool_max_size=3)) == 2  # the pool leaves two
    assert at_once(make_settings(extract_concurrency=4, db_pool_max_size=1)) == 1


def test_the_room_is_the_most_a_request_read_from_the_cache_holds_beyond_its_charge() -> None:
    # six units, two at once: each holds 1,100 + 16,000 x 5 = 81,100 while it waits; the first two of the
    # prefix are expected whole (1,600), the others from the cache (610) - and those hold the most beyond
    units = [a_request(1_100, 1_000)] * 6

    room = room_for(units, LUNA, at_once=2, units=6, answer_tokens=100)

    assert room == 2 * (81_100 - 610) == 160_980


def test_a_frame_owed_alone_has_the_room_of_its_own_reservation() -> None:
    # no unit left, or one: X3's request alone waits, and its reservation must fit beside the rest
    frame = a_request(1_100, 1_000, purpose="x3.frame")

    assert room_for([frame], LUNA, at_once=4, units=0) == 81_100 - (1_100 + 5_500) == 74_500
    assert room_for([frame], LUNA, at_once=4, units=1) == 74_500


def test_nothing_owed_needs_no_room() -> None:
    assert room_for([], LUNA, at_once=4, units=0) == 0


def test_the_shared_part_is_read_from_the_cache_after_the_first_requests() -> None:
    requests = [a_request(1_100, 1_000)] * 3

    expected = expected_charge(requests, LUNA, uncached_first=1, answer_tokens=100)

    # the first whole: 1,100 + 100 x 5; the others read the shared part with its margin from the cache,
    # 1,100 x 0.1 + 100 x 5, and nothing at full weight: the margin lies on the shared part
    assert expected == 1_600 + 2 * 610 == 2_820


def test_a_request_without_a_shared_part_is_charged_whole() -> None:
    requests = [a_request(2_000, 0), a_request(3_000, 0)]

    assert expected_charge(requests, LUNA, uncached_first=0, answer_tokens=100) == 2_500 + 3_500


def test_weights_of_one_charge_every_token_alike() -> None:
    # a cached token costs what an uncached one does: the cache changes nothing
    requests = [a_request(1_100, 1_000)] * 3

    assert expected_charge(requests, FULL, uncached_first=1, answer_tokens=100) == 3 * 1_200


def test_the_expected_charge_never_exceeds_what_the_reservations_hold() -> None:
    # an answer is expected at most at its cap, the input at most whole: never above what is held
    requests = [a_request(5_000, 4_000, output_tokens=500), a_request(900, 0, output_tokens=4_000)]
    held = sum(LUNA.held(request.input_tokens, request.output_tokens) for request in requests)

    for weights in (LUNA, FULL):
        for answer in (0, 100, 500, 1_100, 50_000):
            for uncached in (0, 1, 2):
                charged = expected_charge(requests, weights, uncached_first=uncached, answer_tokens=answer)
                assert charged <= sum(weights.held(r.input_tokens, r.output_tokens) for r in requests)
    assert (
        expected_charge(requests, LUNA, uncached_first=0, answer_tokens=50_000)
        == (600 + 440 + 2_500 + 900 + 20_000)
        <= held
    )


def test_more_uncached_requests_than_there_are_charge_them_all_whole() -> None:
    requests = [a_request(1_100, 1_000)] * 3

    assert expected_charge(requests, LUNA, uncached_first=10, answer_tokens=100) == 3 * 1_600
    assert expected_charge([], LUNA, uncached_first=10) == 0


def test_an_answer_is_expected_at_the_measured_mean_by_default() -> None:
    assert expected_charge([a_request(1_000, 0)], FULL, uncached_first=1) == 1_000 + 1_100


@pytest.mark.pg
@pytest.mark.anyio
async def test_a_unit_held_back_after_a_cut_is_not_reckoned(
    setup: Any, tmp_path: Path, database_url: str, reserved: Reserved
) -> None:
    # E3's answer was cut at the cap: no job asks it again under that cap, so no request is owed for it
    pool, connection = setup
    document = await a_document(connection, blocks=FIELDS)
    context = context_of(pool, tmp_path, cutting(Model(), "E3"), database_url)
    with pytest.raises(PermanentError):
        await extract_document(context, await a_job(connection, document.id, document.owner_id))
    current = await document_for_job(connection, document.id)
    assert current is not None and context.llm is not None and context.model is not None
    blocks = await all_blocks(connection, current.conversion_id)
    printed = await printed_pages(connection, current.conversion_id)
    ground = await ground_of(connection, current)
    reserved.clear()

    owed = await owed_requests(
        connection,
        context.llm,
        current,
        blocks,
        printed,
        ground,
        context.model(),
        context.settings.ontology_dir,
    )
    with pytest.raises(PermanentError) as ended:
        await extract_document(context, await a_job(connection, document.id, document.owner_id))

    assert ended.value.code == "answer_cut"
    assert owed == ([], 0)
    assert reserved == []  # the next job asked nothing either
