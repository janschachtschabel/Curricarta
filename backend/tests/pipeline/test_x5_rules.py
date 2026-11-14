"""X5's rules on a statement's wording, as pure predicates (app/pipeline/x5_checks.py): a figure's label
or value taken for a statement of unclear kind, a lead-in taken for one of its own (acceptance M1:
255 statements of unclear kind, many a label's)."""

import time

import pytest

from app.pipeline.x5_checks import is_label, is_lead_in

UNCLASSIFIED = "https://w3id.org/wlo/curriculum/vocab#kind_unclassified"
CONTENT = "https://w3id.org/wlo/curriculum/vocab#kind_content"


@pytest.mark.parametrize(
    "wording",
    [
        *("Abb. 3", "Kraft (N)", "25 %", "1.2.3", "Legende", "2019 2020 2021"),
        # a point after an abbreviation, a number, a sign: no sentence's end
        *("Abb. 3.", "z. B.", "usw.", "1.", "IV.", "Kraft (N).", "Legende.", "25 %.", "2019."),
    ],
)
def test_a_fragment_of_unclear_kind_is_a_label(wording: str) -> None:
    assert is_label(wording, UNCLASSIFIED)


@pytest.mark.parametrize(
    ("wording", "kind"),
    [
        ("Die Lernenden beschreiben die Ausbreitung des Lichts.", UNCLASSIFIED),  # a sentence
        ("Elektrische Ladung", CONTENT),  # a content's short line, classified
    ],
)
def test_a_sentence_or_a_classified_line_is_no_label(wording: str, kind: str) -> None:
    assert not is_label(wording, kind)


@pytest.mark.parametrize("wording", ["Die Kinder spielen.", "Sicher schwimmen können.", "Wer hilft wem?"])
def test_a_short_sentence_of_unclear_kind_is_no_label(wording: str) -> None:
    # the elementary profile has the model keep a short "Kinder lernen ..." sentence unclassified
    assert not is_label(wording, UNCLASSIFIED)


@pytest.mark.parametrize(
    "wording",
    [
        "• Die Schülerinnen und Schüler können:",  # a bullet before it
        "Die Schüler\N{SOFT HYPHEN}innen und Schüler können",  # a soft hyphen in a word
    ],
)
def test_a_lead_in_set_otherwise_is_still_the_lead_in(wording: str) -> None:
    assert is_lead_in(wording, {"Die Schülerinnen und Schüler können"})


@pytest.mark.parametrize(
    "wording",
    [
        "Die Schülerinnen und Schüler können",
        "Die Schülerinnen und Schüler können …",
        "Die Schülerinnen und Schüler können ...",  # an ellipsis of points ends no sentence
        "die schülerinnen und schüler können:",
    ],
)
def test_a_wording_that_is_another_statement_s_lead_in_is_a_lead_in(wording: str) -> None:
    assert is_lead_in(wording, {"Die Schülerinnen und Schüler können"})


def test_a_wording_beginning_with_a_lead_in_is_no_lead_in() -> None:
    assert not is_lead_in(
        "Die Schülerinnen und Schüler können Licht beschreiben.", {"Die Schülerinnen und Schüler können"}
    )


def test_a_sentence_ending_as_a_sentence_is_no_lead_in_though_another_takes_it_for_one() -> None:
    # a learning field's action goal, given as the next sentences' lead-in too (Hochbauberufe BW)
    goal = "Die Schülerinnen und Schüler planen die Herstellung des Mauerwerks."

    assert not is_lead_in(goal, {goal})


@pytest.mark.parametrize(
    "goal",
    [
        "Die Schülerinnen und Schüler wählen die Säge (Antrieb, Blattdurchmesser, Segmentart).",
        "Die Kinder nennen das Wort „Kinderrestaurant“.",
    ],
)
def test_a_sentence_ends_so_after_a_bracket_or_a_quote(goal: str) -> None:
    assert not is_lead_in(goal, {goal})


@pytest.mark.parametrize(
    "goal",
    [
        "„Ich kann das ganz allein.“",  # a child's words, the point inside the quote
        "(Siehe dazu den Anhang.)",
        "Die Kinder spielen.\N{ZERO WIDTH SPACE}",  # a sign that sets the text, saying nothing
        "Die Lernenden mauern nach DIN EN 1996.",  # an action goal ending in a standard's number
    ],
)
def test_a_sentence_ends_so_before_a_closing_sign_or_after_a_number(goal: str) -> None:
    assert not is_lead_in(goal, {goal})
    assert not is_label(goal, UNCLASSIFIED)


@pytest.mark.parametrize("wording", ["40 Std.", "ca. 40 Std.", "45 Min.", "20 UE."])
def test_a_short_value_with_its_unit_is_a_label_though_it_ends_with_a_point(wording: str) -> None:
    assert is_label(wording, UNCLASSIFIED)


@pytest.mark.parametrize(
    "sentence",
    [
        "2. Kinder spielen.",  # numbered: the wording is as written, its numbering with it
        "(3) Licht beschreiben.",
        "Bis 100 zählen.",  # a number within, a word at the end
        "In 3D zeichnen.",
    ],
)
def test_a_short_sentence_with_a_number_stays_a_sentence(sentence: str) -> None:
    assert not is_label(sentence, UNCLASSIFIED)
    assert not is_lead_in(sentence, {sentence})


@pytest.mark.parametrize(
    "wording", ["12 14 16 18.", "1.2.3.4.", "2020 2021 2022 2023.", "Tabelle 3.1: 40 60 80."]
)
def test_a_row_of_numbers_ending_with_a_point_is_a_label(wording: str) -> None:
    # a number ends a sentence of words, not one of numbers
    assert is_label(wording, UNCLASSIFIED)


@pytest.mark.parametrize(
    "wording",
    [
        "(40 Std.)",
        "(ca. 20 Std.)",
        "40 Std.)",
        "1.5 Std.",  # its first part no numbering
        "1. 40 Std.",  # numbered
        "Zeitrichtwert: 40 Std.",
        "Lernfeld 12: 80 Std.",
        "ca. 1,5 Std.",
    ],
)
def test_a_value_in_brackets_numbered_or_after_its_label_is_a_label(wording: str) -> None:
    assert is_label(wording, UNCLASSIFIED)


@pytest.mark.parametrize("wording", ["(siehe Abb.)", "(vgl. Kap.)", "Metall (bzw.)", "siehe Abb."])
def test_a_wording_ending_with_an_abbreviation_ends_no_sentence(wording: str) -> None:
    assert is_label(wording, UNCLASSIFIED)


@pytest.mark.parametrize("sentence", ["Es dauert 40 Std.", "Sie mauern nach DIN 1996."])
def test_a_sentence_around_a_value_or_of_four_words_before_a_number_stays_one(sentence: str) -> None:
    assert not is_lead_in(sentence, {sentence})
    assert not is_label(sentence, UNCLASSIFIED)  # the value is a part of it, not all of it


def test_three_words_before_a_number_end_no_sentence() -> None:
    assert is_lead_in("Mauern nach DIN 1996.", {"Mauern nach DIN 1996"})


@pytest.mark.parametrize(
    "goal",
    [
        "Die Schülerinnen und Schüler nutzen Werkzeuge, Maschinen usw.",
        "Die Schülerinnen und Schüler überarbeiten ihre Texte ggf.",
        "Sie planen Arbeitsabläufe und dokumentieren diese, vgl. Tab.",
    ],
)
def test_a_sentence_ending_with_an_abbreviation_still_ends_as_a_sentence(goal: str) -> None:
    # the point an abbreviation ends with ends the sentence too: an action goal stays no lead-in
    assert not is_lead_in(goal, {goal})


def test_a_sentence_before_a_value_is_no_value() -> None:
    # the label before a value is a few words, not a sentence
    assert not is_label("Die Schülerinnen und Schüler planen den Ablauf: 20 Min.", UNCLASSIFIED)


def test_a_long_run_of_closing_signs_is_read_in_linear_time() -> None:
    started = time.perf_counter()

    is_label("ab" + ")" * 20_000 + "." + ")" * 20_000 + "x", UNCLASSIFIED)

    assert time.perf_counter() - started < 0.5
