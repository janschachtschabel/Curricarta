"""What a model call spends and how it is metered (plan M1, costs), without a database: the call
(app/llm/calls.py) asks a ``Meter`` to reserve before each request and to book after it; the
ledger's meter (app/usage/meter.py) holds the budget.

A request is reckoned before it is sent at its input as tiktoken counts it - the conversation so
far, the instructions and the output schema, as JSON - and a tenth beside: a gateway's model may
count with another tokenizer, and a reckoning too high costs nothing, the booking replaces it.

The budget counts tokens weighed by their price beside an uncached input token (``Weights``): a
cached input token at a tenth, an output token at five, for gpt-6-luna. A reservation holds its
input whole - before it is sent nobody knows what the cache will hold - and its output weighed;
the booking charges what the answer reports.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelRequest

from app.llm.budget import count_tokens

MARGIN = 1.1


class BudgetExhausted(Exception):
    """The account's budget does not hold the request: nothing is sent."""


@dataclass(frozen=True)
class Spent:
    """What requests cost: input (of it read from the cache), output, requests answered and
    sent unanswered; ``estimated`` where a reservation stands for what nobody told."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    unanswered_requests: int = 0
    estimated: bool = False

    def __add__(self, other: "Spent") -> "Spent":
        return Spent(
            self.input_tokens + other.input_tokens,
            self.cached_input_tokens + other.cached_input_tokens,
            self.output_tokens + other.output_tokens,
            self.requests + other.requests,
            self.unanswered_requests + other.unanswered_requests,
            self.estimated or other.estimated,
        )

    @property
    def tokens(self) -> int:
        """Input and output as reported, unweighed (the cached input is input); the budget counts
        them weighed (``Weights``)."""
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Weights:
    """What a cached input token and an output token cost beside an uncached input token, in
    Decimal, as the ledger's numeric counts: in floats 50 output tokens at 1.1 come to 56."""

    cached_input: Decimal
    output: Decimal

    def held(self, input_tokens: int, output_tokens: int) -> int:
        """What a reservation of these tokens holds: its input whole, its output weighed."""
        return input_tokens + math.ceil(output_tokens * self.output)

    def charged(self, spent: Spent) -> int:
        """What ``spent`` is charged: its uncached input, its cached input and output weighed,
        a part of a token a token - as the ledger's column counts it (migration 0029), which books
        it; this one reckons it."""
        cached = spent.cached_input_tokens
        weighed = cached * self.cached_input + spent.output_tokens * self.output
        return spent.input_tokens - cached + math.ceil(weighed)


FULL = Weights(Decimal(1), Decimal(1))  # every token alike, as the budget counted before weights


class Meter(Protocol):
    """Reserves a request's tokens before it is sent, books what it spent after; ``reserve``
    raises BudgetExhausted where the budget does not hold them. ``book`` may be asked again for
    a reservation whose booking failed or was cancelled, and takes a reservation once."""

    async def reserve(self, input_tokens: int, output_tokens: int) -> Any: ...

    async def book(self, reservation: Any, spent: Spent) -> None: ...


def estimate_input(
    history: Sequence[ModelMessage],
    request: ModelRequest,
    *,
    instructions: str | None,
    schema: Mapping[str, Any] | None,
) -> int:
    """The input tokens a request is reckoned at: ``history`` - the messages before it - and the
    request, the instructions and the schema, with MARGIN beside."""
    messages = ModelMessagesTypeAdapter.dump_json([*history, request]).decode("utf-8")
    counted = count_tokens(messages) + count_tokens(instructions or "")
    if schema is not None:
        counted += count_tokens(json.dumps(schema, ensure_ascii=False))
    return math.ceil(counted * MARGIN)
