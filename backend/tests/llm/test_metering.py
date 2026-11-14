"""What a request is reckoned to cost before it is sent (plan M1, costs): its input counted with
tiktoken and a tenth beside, for providers whose tokenizer counts more; and what the budget charges
for it, its cached input and its output weighed by their price."""

import json
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.llm.budget import count_tokens
from app.llm.metering import FULL, MARGIN, Spent, Weights, estimate_input

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
REQUEST = ModelRequest(parts=[UserPromptPart("Lies das Dokument und nenne seinen Titel.")])


def test_a_request_is_reckoned_at_its_tokens_with_a_tenth_beside_and_never_below() -> None:
    estimate = estimate_input([], REQUEST, instructions="Antworte knapp.", schema=SCHEMA)

    counted = count_tokens(json.dumps(SCHEMA)) + count_tokens("Antworte knapp.")
    assert MARGIN == 1.1
    assert estimate >= (counted + count_tokens("Lies das Dokument und nenne seinen Titel.")) * MARGIN


def test_what_a_retry_replays_is_reckoned_with_it() -> None:
    history: list[ModelMessage] = [REQUEST, ModelResponse(parts=[TextPart("Ein langer Titel " * 50)])]

    first = estimate_input([], REQUEST, instructions=None, schema=SCHEMA)
    again = estimate_input(history, REQUEST, instructions=None, schema=SCHEMA)

    assert again > first + count_tokens("Ein langer Titel " * 50)


def test_spent_adds_up_and_tells_an_estimate() -> None:
    total = Spent(input_tokens=10, cached_input_tokens=4, output_tokens=3, requests=1) + Spent(
        input_tokens=5, output_tokens=2, unanswered_requests=1, estimated=True
    )

    assert total == Spent(15, 4, 5, 1, 1, estimated=True)
    assert total.tokens == 20


LUNA = Weights(Decimal("0.1"), Decimal("5"))  # gpt-6-luna's prices beside uncached input


def test_full_weights_charge_as_the_budget_counted_before() -> None:
    assert FULL.held(300, 200) == 500
    assert FULL.charged(Spent(250, 100, 50)) == 300  # the cached input is input


def test_a_reservation_holds_its_input_whole_and_its_output_weighed() -> None:
    # before it is sent, nobody knows what the cache will hold
    assert LUNA.held(300, 200) == 1300
    # a part of a token held is a token, as the ledger's column rounds it (migration 0029)
    assert Weights(Decimal("0.1"), Decimal("0.3")).held(10, 7) == 10 + 3


def test_a_booking_charges_its_cached_input_and_its_output_by_their_weights() -> None:
    assert LUNA.charged(Spent(250, 100, 50)) == 150 + 10 + 250


@pytest.mark.parametrize(
    ("spent", "charged"),
    [
        (Spent(100, 100, 0), 10),
        (Spent(3, 3, 0), 1),  # a part of a token is charged a token
        (Spent(0, 0, 0), 0),
    ],
)
def test_weights_charge_exactly_and_round_up(spent: Spent, charged: int) -> None:
    assert LUNA.charged(spent) == charged


def test_weights_count_as_the_ledger_s_numeric_does_not_as_floats_would() -> None:
    # 50 * 1.1 in floats is 55.000000000000007, which a ceiling makes 56
    assert Weights(Decimal(1), Decimal("1.1")).charged(Spent(0, 0, 50)) == 55
