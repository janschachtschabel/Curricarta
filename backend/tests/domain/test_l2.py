"""The second layer's drafts (app/domain/l2.py): a number of a value is a number - NaN and the endless
are refused as the store refuses them (migration l2_values), by the name of its check."""

from decimal import Decimal

import pytest

from app.domain.l2 import TimeSpanDraft, ValueRefused, WorkloadDraft

CV = "https://w3id.org/wlo/curriculum/vocab#"
NOT_FINITE = [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")]


@pytest.mark.parametrize("number", NOT_FINITE, ids=str)
def test_a_workload_s_amounts_are_numbers(number: Decimal) -> None:
    with pytest.raises(ValueRefused) as amount:
        WorkloadDraft(amount=number, unit=CV + "unit_lesson")
    with pytest.raises(ValueRefused) as amount_to:
        WorkloadDraft(amount=Decimal(1), amount_to=number, unit=CV + "unit_lesson")

    assert (amount.value.check, amount_to.value.check) == (
        "workload_amount_finite",
        "workload_amount_to_finite",
    )


@pytest.mark.parametrize("number", NOT_FINITE, ids=str)
def test_a_time_span_s_ends_are_numbers(number: Decimal) -> None:
    with pytest.raises(ValueRefused) as start:
        TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=number)
    with pytest.raises(ValueRefused) as end:
        TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_to=number)

    assert (start.value.check, end.value.check) == ("time_span_span_from_finite", "time_span_span_to_finite")


def test_numbers_and_open_ends_stand() -> None:
    WorkloadDraft(amount=Decimal("40.5"), amount_to=None, unit=CV + "unit_lesson")
    TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=None, span_to=Decimal(0))
