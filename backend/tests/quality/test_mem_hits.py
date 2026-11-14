"""The pieces of the MEM import's report that read no database (app/quality/mem_hits.py, app/quality/
mem_rare.py): a run that searched nothing has no rate, a not-found wording is hidden from the fuzzy stage
once its rarest word stands more often than the places it tries, and the rows past the search's time are
the last ones in its order - unknown where one of them keeps no MEM IRI."""

from app.pipeline.anchor_fuzzy import FUZZY_PLACES
from app.quality.mem_hits import hits
from app.quality.mem_rare import rarest_too_often, rows_left
from app.sources.mem.drafts import Row


def test_an_import_that_searched_nothing_has_no_rate() -> None:
    made = hits({"stages": {"statement": {"unsearched": 3}}, "front": {}})

    assert made["all"]["statement"]["hit_rate"] is None and made["all"]["rows"]["searched"] == 0
    assert made["all"]["node"]["rows"] == 0


def test_a_wording_is_hidden_once_its_rarest_word_stands_more_often_than_the_places_tried() -> None:
    # the rarest of its words of three letters and more: "am" is none, "Bach" the rarest
    tried = " ".join(["Bach"] * FUZZY_PLACES + ["Kiesel"] * (FUZZY_PLACES + 5))

    assert not rarest_too_often("Kiesel am Bach", tried)
    assert rarest_too_often("Kiesel am Bach", tried + " Bach")
    assert not rarest_too_often("Lehm am Ufer", tried)  # none of its words there: nothing to hide it


def test_the_rows_past_the_search_s_time_are_the_last_in_its_order() -> None:
    rows = [Row(f"https://example.org/p/{n}", "x", False) for n in range(4)]

    assert rows_left(rows, 0) == frozenset() and rows_left(None, 0) == frozenset()
    assert rows_left(rows, 2) == frozenset({"https://example.org/p/2", "https://example.org/p/3"})
    assert rows_left(rows, 4) is None  # every row: the plan's own title among them keeps no MEM IRI
    assert rows_left(None, 1) is None
    assert rows_left([*rows, Row("urn:x y", "x", False)], 1) is None  # an IRI the rows keep not
