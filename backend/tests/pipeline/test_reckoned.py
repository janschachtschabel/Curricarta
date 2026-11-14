"""The reckoning core (app/pipeline/reckoned.py): what the rest of a run is expected to charge, in tokens
weighed as the quota counts them, and the requests X3 and X4 still owe a document - exactly those the
stages would ask. A model stands in (FunctionModel), never a provider."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.db.conversions import all_blocks, printed_pages
from app.db.documents import document_for_job
from app.jobs.outcome import PermanentError
from app.llm.metering import FULL, Weights
from app.pipeline.ground import ground_of
from app.pipeline.reckoned import Request, expected_charge, owed_requests
from app.pipeline.run import extract_document
from tests.pipeline.test_estimate import Reserved, reserved
from tests.pipeline.test_run import Model, a_document, a_job, context_of, setup
from tests.pipeline.test_x4_cut import cutting
from tests.pipeline.test_x4_statements import FIELDS

__all__ = ["reserved", "setup"]  # fixtures, shared with test_estimate and test_run

LUNA = Weights(Decimal("0.1"), Decimal(5))


def a_request(input_tokens: int, shared_tokens: int, output_tokens: int = 16_000) -> Request:
    return Request("x4.unit", input_tokens, shared_tokens, output_tokens)


def test_the_shared_part_is_read_from_the_cache_after_the_first_requests() -> None:
    requests = [a_request(1_100, 1_000)] * 3

    expected = expected_charge(requests, LUNA, uncached_first=1, answer_tokens=100)

    # the first whole: 1,100 + 100 x 5; the others 100 + 1,000 x 0.1 + 100 x 5
    assert expected == 1_600 + 2 * 700 == 3_000


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
        == (1_000 + 400 + 2_500 + 900 + 20_000)
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
