"""The pieces of the MEM import's report that read no database (app/quality/mem_hits.py, app/quality/
mem_report.py ``rarest_too_often``): a run that searched nothing has no rate, and a not-found wording is
hidden from the fuzzy stage once its rarest word stands more often than the places it tries."""

from app.pipeline.anchor_fuzzy import FUZZY_PLACES
from app.quality.mem_hits import hits
from app.quality.mem_report import rarest_too_often


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
