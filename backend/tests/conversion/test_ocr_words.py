"""The words of a scanned page, read by OCR (app/conversion/ocr_words.py): each line's words at a share of
its box, at the size the x-height of its ink says - OCR gives none, and its boxes' heights follow the
letters' ascenders and descenders, not the type's size (plan M1 3b-2, measured on five curricula)."""

import pytest
from PIL import Image, ImageDraw

from app.conversion.layout import style_of
from app.conversion.ocr_words import BOX_HEIGHT, X_HEIGHT, OcrLine, words_of, x_height

SCALE = 2.0  # pixels of the page's image to a point


def line_image(band: int, *, width: int = 400, height: int = 60, paper: int = 255) -> Image.Image:
    """A line of type drawn as letters are: a band ``band`` high that every letter fills, a few ascenders
    and descenders, thin, above and below it."""
    image = Image.new("L", (width, height), paper)
    draw = ImageDraw.Draw(image)
    top = 20
    for x in range(10, width - 20, 14):  # lower case: the band
        draw.rectangle((x, top, x + 9, top + band - 1), fill=0)
    for x in range(12, width - 20, 70):  # an ascender, a descender now and then
        draw.rectangle((x, top - 12, x + 2, top - 1), fill=0)
        draw.rectangle((x + 30, top + band, x + 32, top + band + 9), fill=0)
    return image


def test_the_x_height_is_the_band_lower_case_fills_not_the_ascenders_or_descenders() -> None:
    assert x_height(line_image(20)) == 20


def test_a_grey_paper_is_no_ink() -> None:
    # a scan's paper is seldom white
    assert x_height(line_image(14, paper=200)) == 14


def test_a_line_of_no_ink_has_no_x_height() -> None:
    assert x_height(Image.new("L", (100, 30), 255)) is None


def test_a_line_s_words_share_its_box_by_their_signs_at_the_size_of_its_x_height() -> None:
    page = Image.new("L", (1200, 1700), 255)
    page.paste(line_image(12, width=360, height=40), (200, 400))  # the line at (100, 200) points, 2 px each
    line = OcrLine("Die Schüler planen", (100.0, 200.0, 280.0, 220.0), 0.9)

    words = words_of([line], page, SCALE)

    assert [word.text for word in words] == ["Die", "Schüler", "planen"]
    assert [word.box for word in words] == [
        (100.0, 200.0, 130.0, 220.0),
        (140.0, 200.0, 210.0, 220.0),
        (220.0, 200.0, 280.0, 220.0),
    ]
    # 12 pixels are 6 points, the x-height of a type of some 11
    assert all(word.size == pytest.approx(6 / X_HEIGHT) for word in words)
    assert all(word.upright and style_of(word.font) == (False, False) for word in words)


def test_a_line_reaching_beyond_the_page_s_image_is_measured_on_it() -> None:
    # the image's outside would read as ink
    page = Image.new("L", (400, 100), 255)
    page.paste(line_image(10, width=200, height=40), (200, 60))
    line = OcrLine("Rand", (100.0, 30.0, 260.0, 50.5), 0.8)

    [word] = words_of([line], page, SCALE)

    assert word.size == pytest.approx(5 / X_HEIGHT)


def test_a_line_of_no_ink_takes_its_box_s_measure_and_one_of_no_text_is_no_word() -> None:
    page = Image.new("L", (400, 400), 255)
    lines = [OcrLine("leer", (10.0, 10.0, 60.0, 23.0), 0.6), OcrLine("  ", (10.0, 40.0, 60.0, 50.0), 0.6)]

    assert [(word.text, word.size) for word in words_of(lines, page, SCALE)] == [("leer", 13 / BOX_HEIGHT)]


def test_ink_too_thin_for_the_line_s_box_is_no_x_height_of_its_type() -> None:
    # a rule or a dotted line under the line's box: its words take the box's measure, not a size of 2 points -
    # on the measure of a type's (a box some 1.3 times its size), not larger than the lines measured beside it
    page = Image.new("L", (400, 200), 255)
    ImageDraw.Draw(page).line((20, 50, 380, 50), fill=0, width=3)
    line = OcrLine("Seite zwei", (10.0, 15.0, 190.0, 35.0), 0.5)

    assert [word.size for word in words_of([line], page, SCALE)] == [20 / BOX_HEIGHT, 20 / BOX_HEIGHT]


def test_each_word_is_measured_on_its_own_a_slant_across_the_line_widens_no_band() -> None:
    # a scan set a little askew: its words stand lower and lower along the line - measured as one, the line's
    # band would reach from the first word's top to the last word's bottom
    page = Image.new("L", (800, 120), 255)
    for at, x in enumerate((20, 280, 540)):
        page.paste(line_image(12, width=240, height=60), (x, 8 * at))
    line = OcrLine("Erste zweite dritte", (10.0, 2.0, 400.0, 28.0), 0.9)

    words = words_of([line], page, SCALE)

    assert [word.size for word in words] == [pytest.approx(6 / X_HEIGHT)] * 3


def test_a_line_s_words_of_lower_case_say_its_size_not_its_capitals_and_figures() -> None:
    # "LF 12:" stands as high as the capitals; "Lernfeld" says the x-height of the type
    page = Image.new("L", (800, 100), 255)
    page.paste(line_image(12, width=300, height=60), (0, 0))
    page.paste(line_image(17, width=300, height=60), (320, 0))
    line = OcrLine("Lernfeld 12: LF", (0.0, 0.0, 310.0, 28.0), 0.9)

    words = words_of([line], page, SCALE)

    assert all(word.size == pytest.approx(6 / X_HEIGHT) for word in words)


def test_a_line_in_capitals_reads_as_larger_than_its_type_as_ocr_says_no_weight() -> None:
    # its capitals' height in place of an x-height: a heading set in capitals stands out as one set larger
    page = Image.new("L", (400, 100), 255)
    page.paste(line_image(17, width=360, height=60), (0, 0))
    line = OcrLine("ZIELE DES UNTERRICHTS", (0.0, 0.0, 180.0, 30.0), 0.9)

    assert all(word.size == pytest.approx(8.5 / X_HEIGHT) for word in words_of([line], page, SCALE))


def test_a_line_of_figures_alone_takes_its_box_s_measure() -> None:
    page = Image.new("L", (400, 100), 255)
    page.paste(line_image(17, width=200, height=60), (0, 0))
    line = OcrLine("2024 - 25", (0.0, 0.0, 100.0, 26.0), 0.9)

    assert {word.size for word in words_of([line], page, SCALE)} == {26 / BOX_HEIGHT}


def test_a_line_at_no_place_is_measured_nowhere() -> None:
    # EasyOCR gives pixels; a box not finite is the file's: its words stay unplaced (docling_pages drops them)
    page = Image.new("L", (100, 100), 255)
    line = OcrLine("irgendwo", (float("nan"), 0.0, 50.0, 10.0), 0.9)

    [word] = words_of([line], page, SCALE)

    assert word.size is None
