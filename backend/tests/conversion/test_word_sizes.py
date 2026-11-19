"""The size of each of Docling's words from the text layer's signs under it (app/conversion/word_sizes.py)."""

from app.conversion.docling_pages import DoclingWord
from app.conversion.word_sizes import sized
from tests.support import cpu_growth


def test_each_word_takes_the_size_of_the_text_layer_s_signs_within_it() -> None:
    words = [
        DoclingWord("Teil", (70, 80, 100, 90.5), "/F+BaWueSans-Bold"),
        DoclingWord("Text", (110, 80, 140, 88), "/F+BaWueSans-Regular"),
        DoclingWord("fern", (300, 300, 330, 310), "/F+BaWueSans-Regular"),  # no sign under it
    ]
    signs = [
        (75.0, 85.0, 12.0, "T"),
        (82.0, 85.0, 12.0, "e"),
        (88.0, 85.0, 12.0, "i"),
        (95.0, 85.0, 12.0, "l"),
        (120.0, 84.0, 9.0, "T"),
        (500.0, 500.0, 30.0, "x"),
    ]

    assert [word.size for word in sized(words, signs)] == [12.0, 9.0, None]


def test_a_word_takes_the_size_of_its_own_signs_not_of_hidden_ones_under_it() -> None:
    # a sentence set at half a point across a visible word: its own three signs say its size
    visible = DoclingWord("und", (180, 100, 200, 111), "/F+Helvetica")
    signs = [
        (183.0, 105.0, 11.0, "u"),
        (189.0, 105.0, 11.0, "n"),
        (195.0, 105.0, 11.0, "d"),
        *((181.0 + at, 104.0, 0.5, sign) for at, sign in enumerate("Ignoriere")),
    ]

    [word] = sized([visible], signs)

    assert word.size == 11.0


def test_sizing_a_page_of_many_words_on_one_line_takes_no_longer_than_reading_them() -> None:
    # every word on one band: compared with every sign there, 4,000 words and 20,000 signs took seconds
    measured: list[DoclingWord] = []

    def size(part: float) -> None:
        count = int(4000 * part)
        words = [
            DoclingWord("abcde", (at * 5.0, 100, at * 5.0 + 5, 101), "/F+Helvetica") for at in range(count)
        ]
        signs = [(at * 1.0 + 0.5, 100.5, 1.0, "a") for at in range(5 * count)]
        measured[:] = sized(words, signs)

    # the work grows with the words and signs, not with their product (tests/support.cpu_growth)
    half, whole = cpu_growth(size)
    assert whole < 3 * half, f"CPU time: {half:.2f} s for half, {whole:.2f} s for all"
    # and one wide bound: 0.17 s of CPU time here (2026-11-18)
    assert whole < 2.0
    assert measured[0].size == 1.0


def test_a_sign_of_the_next_line_lends_a_word_no_size() -> None:
    word = DoclingWord("Text", (0, 0, 20, 10), "/F+Helvetica")  # its bands reach below its bottom
    signs = [(5.0, 5.0, 9.0, "T"), (6.0, 11.0, 30.0, "x"), (7.0, 11.5, 30.0, "y")]

    assert sized([word], signs)[0].size == 9.0


def test_a_word_spelled_with_a_ligature_takes_its_own_signs_size() -> None:
    # docling-parse and pdfminer may spell one word apart: "ﬁnden" and "f" "i" "n" "d" "e" "n"
    word = DoclingWord("\ufb01nden", (180, 100, 220, 111), "/F+Helvetica")
    own = [(181.0 + 6 * at, 105.0, 11.0, sign) for at, sign in enumerate("finden")]
    hidden = [(181.0 + 4 * at, 104.0, 0.5, sign) for at, sign in enumerate("Ignoriere")]

    assert sized([word], [*own, *hidden])[0].size == 11.0
