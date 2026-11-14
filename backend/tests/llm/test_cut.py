"""An answer cut at the output cap (audit 2026-11-14): booked once, as it reports, and said to be cut
rather than asked again under the same cap - told from a whole answer at the cap, and from one out
of form, by the provider's reason, the arguments of its tool call and, without a reason, the output
reported at the cap. A model stands in (FunctionModel)."""

from collections.abc import Callable
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from app.llm.calls import StageAgent, ask, build_agent
from app.llm.metering import Spent
from tests.llm.test_calls import SCHEMA, Kept, Ledger, stage

pytestmark = pytest.mark.anyio


async def test_an_answer_cut_at_the_cap_is_booked_once_and_said_to_be_cut() -> None:
    # pydantic-ai would ask twice more before it gives up on a cut tool call, each paid and cut alike
    seen: list[list[ModelMessage]] = []

    def cut(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        usage = RequestUsage(input_tokens=100, output_tokens=2_000)
        part = ToolCallPart(info.output_tools[0].name, '{"title": "Zah')
        return ModelResponse(parts=[part], usage=usage, finish_reason="length")

    built = build_agent(
        FunctionModel(cut, settings={"max_tokens": 2_000}), schema=SCHEMA, name="titel", instructions="x"
    )
    ledger, kept = Ledger(), Kept()

    answer = await ask(built, "Text", meter=ledger, raw=kept)

    assert (answer.output, answer.cut) == (None, True)
    assert answer.failure is not None and "2000" in answer.failure
    assert (len(seen), len(kept.answers)) == (1, 1)
    assert ledger.booked == [(1, Spent(input_tokens=100, output_tokens=2_000, requests=1))]
    assert answer.spent == Spent(input_tokens=100, output_tokens=2_000, requests=1)


def answering(
    parts: Callable[[AgentInfo], list[Any]], *, finish_reason: Any = "length", output_tokens: int = 2_000
) -> tuple[StageAgent, list[list[ModelMessage]]]:
    """A stage over a model that answers each request with ``parts`` and ``finish_reason``, reporting
    ``output_tokens`` (the cap is 2 000)."""
    seen: list[list[ModelMessage]] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        usage = RequestUsage(input_tokens=100, output_tokens=output_tokens)
        return ModelResponse(parts=parts(info), usage=usage, finish_reason=finish_reason)

    model = FunctionModel(answer, settings={"max_tokens": 2_000})
    return build_agent(model, schema=SCHEMA, name="titel", instructions="x"), seen


async def test_an_answer_whole_at_the_cap_is_read() -> None:
    # the cap met as the arguments closed: the answer is whole and paid for, not cut
    built, seen = answering(lambda info: [ToolCallPart(info.output_tools[0].name, '{"title": "Zahlen"}')])
    ledger = Ledger()

    answer = await ask(built, "Text", meter=ledger)

    assert (answer.output, answer.cut, len(seen)) == ({"title": "Zahlen"}, False, 1)
    assert ledger.booked == [(1, Spent(input_tokens=100, output_tokens=2_000, requests=1))]


@pytest.mark.parametrize("parts", ["text", "none"])
async def test_an_answer_cut_at_the_cap_before_any_tool_call_is_cut(parts: str) -> None:
    built, seen = answering(lambda _: [TextPart("Die Antwort lautet")] if parts == "text" else [])
    ledger = Ledger()

    answer = await ask(built, "Text", meter=ledger)

    assert (answer.output, answer.cut, len(seen)) == (None, True, 1)
    assert ledger.booked == [(1, Spent(input_tokens=100, output_tokens=2_000, requests=1))]


async def test_a_tool_call_cut_at_the_cap_before_its_first_argument_is_cut() -> None:
    # empty arguments read as {}: only the cap tells them from an answer of no title
    built, seen = answering(lambda info: [ToolCallPart(info.output_tools[0].name, "")])

    answer = await ask(built, "Text", meter=Ledger())

    assert (answer.output, answer.cut, len(seen)) == (None, True, 1)


async def test_an_answer_at_the_cap_whose_reason_is_unknown_and_arguments_cut_is_cut() -> None:
    # a provider whose reason pydantic-ai does not know (finish_reason None): the cap reached and the
    # arguments no JSON yet tell the cut together
    built, seen = answering(
        lambda info: [ToolCallPart(info.output_tools[0].name, '{"title": "Zah')], finish_reason=None
    )

    answer = await ask(built, "Text", meter=Ledger())

    assert (answer.output, answer.cut, len(seen)) == (None, True, 1)


@pytest.mark.parametrize(
    ("args", "output_tokens"), [('{"title": "Zah', 1_999), ('{"title": "Zahlen"}', 2_000)]
)
async def test_an_answer_with_one_sign_of_a_cut_alone_is_not_taken_for_cut(
    args: str, output_tokens: int
) -> None:
    # arguments cut below the cap are an answer out of form, asked again; the cap reached with whole
    # arguments is an answer read
    built, seen = answering(
        lambda info: [ToolCallPart(info.output_tools[0].name, args)],
        finish_reason=None,
        output_tokens=output_tokens,
    )

    answer = await ask(built, "Text", meter=Ledger())

    assert answer.cut is False
    assert len(seen) == (3 if answer.output is None else 1)


async def test_an_answer_out_of_form_is_not_taken_for_cut() -> None:
    built, _ = stage(['{"title": 3}'])

    answer = await ask(built, "Das Dokument.", meter=Ledger())

    assert (answer.output, answer.cut) == (None, False)
