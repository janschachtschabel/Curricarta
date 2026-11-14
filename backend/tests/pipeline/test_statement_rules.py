"""The rules a statement is read by, as X3, X4 and X6 ask (acceptance M1, Nachtrag 11): headings and a
figure's labels and values were taken for statements - 255 of unclear kind, 128 a heading's -, and a
lead-in and an action goal were read apart from what they lead or are."""

import pytest

from app.pipeline.prompts import x3, x4, x6
from app.pipeline.prompts.statements import STATEMENT_RULES


@pytest.mark.parametrize(
    "named",
    ["Überschriften", "Tabellenköpfe", "Beschriftungen", "Legenden", "Achsen", "Werte", "Seitenzahlen"],
)
def test_the_rules_name_what_no_statement_is_not_even_unclassified(named: str) -> None:
    rule = next(line for line in STATEMENT_RULES.split("\n- ") if "Keine Aussagen" in line)

    assert named in rule
    assert "auch nicht als unclassified" in rule


def test_unclassified_is_for_a_statement_of_its_own_meaning_whose_kind_is_unclear() -> None:
    assert "unclassified nur für eine Aussage mit eigener Bedeutung" in " ".join(STATEMENT_RULES.split())


def test_a_lead_in_stands_with_each_statement_it_leads_never_as_one_of_its_own() -> None:
    rule = next(line for line in STATEMENT_RULES.split("\n- ") if "leadIn" in line)

    assert "wörtlich" in rule
    assert "nie als eigene Aussage" in rule


def test_an_action_goal_is_a_learning_outcome_a_learner_s_wish_the_purpose_of_its_row() -> None:
    rule = next(line for line in STATEMENT_RULES.split("\n- ") if "Handlungsziel" in line)

    assert "learningOutcome" in rule
    assert "purposeText" in rule
    # the noun points two ways: a learning field's goal, an integration course's column of wishes
    assert "Handlungsziel eines Lernfelds" in rule
    assert "„Handlungsziele“" in rule.split("purposeText")[0].split("learningOutcome")[1]


@pytest.mark.parametrize(
    ("stage", "version"),
    [(x3, "x3-frame/2"), (x4, "x4-statements/2"), (x6, "x6-repair/2")],
    ids=["x3", "x4", "x6"],
)
def test_each_stage_asks_by_the_rules_under_a_new_version(stage: object, version: str) -> None:
    assert STATEMENT_RULES in stage.INSTRUCTIONS  # type: ignore[attr-defined]
    assert version == stage.PROMPT_VERSION  # type: ignore[attr-defined]
