"""The configured language model, as pydantic-ai models it (after the old app's extraction/llm.py).

``openai`` is spoken to over the Responses API, which carries reasoning effort and text
verbosity; ``openai-compatible`` over Chat Completions, which carries the effort. Every request
caps its answer at LLM_MAX_OUTPUT_TOKENS, is counted into the call that sent it
(app/llm/attempts.py), carries the trace of its request or job, and is sent once: the SDK does
not ask again on its own. No network call happens here: the client connects on the first
request, so the app starts without the provider. The model's profile is the library's: since
pydantic-ai knows gpt-6-luna as it was measured (prompt cache breakpoint, reasoning context,
encrypted reasoning, no effort ``minimal``), no entry of ours lies over it; a test holds the
library to those flags (tests/llm/test_client.py). The library's first-run banner is turned off:
this process owns what it writes.
"""

import re
from decimal import Decimal
from typing import Any, cast

import httpx2
import pydantic_ai
from openai import AsyncOpenAI
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.tracing import outgoing_headers
from app.llm.attempts import count_attempt
from app.llm.metering import Weights
from app.llm.settings import LLMSettings

# An advertisement for a tracing service on stderr, to a terminal or a coding agent: a service's
# stderr is its operator's log
pydantic_ai.BANNER_ENABLED = False

# The smallest context window the app is meant for, for a model it does not know
DEFAULT_CONTEXT_TOKENS = 128_000
# gpt-6-luna holds 1,050,000 tokens, but a request past 272,000 input tokens costs twice
# (OpenAI's model page, read 2026-10-03, decided in the old app)
_CONTEXT_TOKENS: dict[str, int] = {"gpt-6-luna": 272_000}
# What a cached input token and an output token cost beside an uncached one: gpt-6-luna at
# 0.10 $, 0.01 $ and 0.50 $ for a million (the official price page, plan M1 Nachtrag 11.2)
_COST_WEIGHTS: dict[str, tuple[str, str]] = {"gpt-6-luna": ("0.1", "5")}


class LLMNotConfigured(Exception):
    """No key for the language model is set."""


def build_model(
    settings: LLMSettings, *, transport: httpx2.AsyncBaseTransport | None = None
) -> OpenAIResponsesModel | OpenAIChatModel:
    """The configured model; ``transport`` stands in for the network in a test.

    Build one per process and keep it: it holds an HTTP client with its connection pool, which
    ``await model.client.close()`` releases when the process ends.
    """
    if settings.openai_api_key is None:
        raise LLMNotConfigured("OPENAI_API_KEY is not set: the language model cannot be asked")
    http_client = httpx2.AsyncClient(
        # ten minutes for an answer, five seconds to connect, as pydantic-ai's own client has
        timeout=httpx2.Timeout(600, connect=5),
        event_hooks={"request": [count_attempt, _carry_trace]},
        transport=transport,
    )
    # The SDK asks again after a timeout, a 429 or a 5xx, twice by default, and every request may
    # be paid for: the app waits and asks itself, each time with a reservation (app/llm/calls.py)
    sdk = AsyncOpenAI(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key.get_secret_value(),
        http_client=cast(Any, http_client),
        max_retries=0,
    )
    provider = OpenAIProvider(openai_client=sdk)
    # max_output_tokens (Responses) or max_completion_tokens (Chat): what an answer may cost at
    # most, reasoning included - the reservation counts on it
    cap = settings.llm_max_output_tokens
    if settings.llm_provider == "openai":
        responses = OpenAIResponsesModelSettings(
            max_tokens=cap,
            openai_reasoning_effort=settings.openai_reasoning_effort,
            openai_text_verbosity=settings.openai_text_verbosity,
        )
        return OpenAIResponsesModel(settings.openai_model, provider=provider, settings=responses)
    chat = OpenAIChatModelSettings(max_tokens=cap, openai_reasoning_effort=settings.openai_reasoning_effort)
    return OpenAIChatModel(settings.openai_model, provider=provider, settings=chat)


class LazyModel:
    """The process's model, built when a job first asks for it - a worker starts, and runs the jobs
    that need none, without a key; asked for while none is set, LLMNotConfigured - and closed with
    the process (``close``), its HTTP client's connections let go."""

    def __init__(self, settings: LLMSettings, *, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport
        self._model: OpenAIResponsesModel | OpenAIChatModel | None = None

    def __call__(self) -> OpenAIResponsesModel | OpenAIChatModel:
        if self._model is None:
            self._model = build_model(self.settings, transport=self._transport)
        return self._model

    async def close(self) -> None:
        if self._model is not None:
            model, self._model = self._model, None
            await model.client.close()


async def _carry_trace(request: httpx2.Request) -> None:
    """The client's request hook: the trace of the request or job the call is made for."""
    request.headers.update(outgoing_headers())


def check_reasoning_effort(settings: LLMSettings) -> None:
    """ValueError where the model's profile says it does not take the configured effort.

    pydantic-ai sends whatever effort it is given, and gpt-6-luna answers ``minimal`` with a
    400 in the middle of a paid job (old app, audit E-84). The profile is the one the model
    gets - the library's - and only what it says against an effort refuses it: a model the library
    does not describe, a gateway's, is not refused what nobody knows. No key is needed, so the start
    checks it before the key is set.
    """
    profile = _profile(settings.openai_model)
    effort = settings.openai_reasoning_effort
    refused = (effort == "minimal" and profile.get("openai_supports_minimal_reasoning_effort") is False) or (
        effort == "none"
        and profile.get("openai_supports_reasoning") is True
        and profile.get("openai_supports_reasoning_effort_none") is False
    )
    if refused:
        raise ValueError(f"OPENAI_REASONING_EFFORT={effort}: {settings.openai_model} does not take it")


def context_tokens(settings: LLMSettings) -> int:
    """LLM_CONTEXT_TOKENS where set; else the model's where known; else the default."""
    if settings.llm_context_tokens is not None:
        return settings.llm_context_tokens
    known = _known(_CONTEXT_TOKENS, settings.openai_model)
    return DEFAULT_CONTEXT_TOKENS if known is None else known


def cost_weights(settings: LLMSettings) -> Weights:
    """LLM_CACHED_INPUT_WEIGHT and LLM_OUTPUT_WEIGHT where set, each in place of the model's
    where known; else 1: every token alike."""
    cached, output = _known(_COST_WEIGHTS, settings.openai_model) or ("1", "1")
    if settings.llm_cached_input_weight is not None:
        cached = str(settings.llm_cached_input_weight)  # 0.1 as written, not as the float stores it
    if settings.llm_output_weight is not None:
        output = str(settings.llm_output_weight)
    return Weights(Decimal(cached), Decimal(output))


def _known[T](table: dict[str, T], model_name: str) -> T | None:
    """The entry for the model or a dated snapshot of it (``-YYYY-MM-DD``), never a variant."""
    return next(
        (
            entry
            for name, entry in table.items()
            if re.fullmatch(rf"{re.escape(name)}(-\d{{4}}-\d{{2}}-\d{{2}})?", model_name)
        ),
        None,
    )


def _profile(model_name: str) -> OpenAIModelProfile:
    """As pydantic-ai resolves it for the model."""
    return cast(OpenAIModelProfile, OpenAIProvider.model_profile(model_name) or {})
