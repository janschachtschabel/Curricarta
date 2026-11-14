"""The anchors of an import's rows (app/sources/mem/anchoring.py, Teilplan M2-5b): each wording looked for in
the document's order, after the place of the one before; found, its blocks and pages, its match kind left
to X5; not found, or past the search's time, notFound on the page of the row before; the stages counted
apart for nodes and statements."""

from collections.abc import Iterator

import pytest

from app.conversion.base import Block
from app.pipeline.anchor_search import search_text
from app.sources.mem.anchoring import anchor_rows
from app.sources.mem.drafts import Row

pytestmark = pytest.mark.anyio

CV = "https://w3id.org/wlo/curriculum/vocab#"


def block(page: int, number: int, text: str) -> Block:
    return Block(
        id=f"p{page}-b{number}",
        page=page,
        kind="text",
        text=text,
        bbox=None,
        font_size=None,
        bold=False,
        italic=False,
    )


SEARCHED = search_text(
    [
        block(1, 1, "1 Optik"),
        block(1, 2, "Die Lernenden beschreiben Licht."),
        block(2, 1, "2 Mechanik"),
        block(2, 2, "Die Lernenden beschreiben Licht."),
        block(3, 1, "Sie messen Kräfte und"),
        block(4, 1, "Geschwindigkeiten."),
    ],
    frozenset(),
)


def clock(*times: float) -> Iterator[float]:
    yield from times


async def test_each_row_is_anchored_where_its_wording_stands_after_the_row_before() -> None:
    rows = [
        Row("a", "1 Optik", True),
        Row("b", "2 Mechanik", True),
        Row("c", "Die Lernenden beschreiben Licht.", False),
        Row("d", "Sie messen Kräfte und Geschwindigkeiten.", False),
    ]

    made = await anchor_rows(rows, SEARCHED, 300.0)

    assert {key: (anchor.block_ids, anchor.page_start, anchor.page_end, anchor.match_kind)
            for key, anchor in made.anchors.items()} == {
        "a": (("p1-b1",), 1, None, None),
        "b": (("p2-b1",), 2, None, None),
        "c": (("p2-b2",), 2, None, None),  # the second copy: it stands after Mechanik
        "d": (("p3-b1", "p4-b1"), 3, 4, None),
    }  # fmt: skip
    assert made.stages == {"node": {"exact": 2}, "statement": {"exact": 1, "whitespace": 1}}
    assert made.stage_of == {"a": "exact", "b": "exact", "c": "exact", "d": "whitespace"}
    assert made.unsearched == 0


async def test_a_wording_found_nowhere_takes_the_page_of_the_row_before() -> None:
    rows = [Row("a", "2 Mechanik", True), Row("b", "Thermodynamik der Sterne", False)]

    made = await anchor_rows(rows, SEARCHED, 300.0)

    assert (made.anchors["b"].block_ids, made.anchors["b"].page_start, made.anchors["b"].match_kind) == (
        (),
        2,
        CV + "match_notFound",
    )
    assert made.stages["statement"] == {"notFound": 1}
    assert made.stage_of["b"] == "notFound"


async def test_past_its_time_the_search_stops_and_the_rest_is_not_found_on_the_page_before() -> None:
    rows = [
        Row("a", "1 Optik", True),
        Row("b", "2 Mechanik", True),
        Row("c", "Die Lernenden beschreiben Licht.", False),
    ]
    # the clock reads 0 at the start, 10 before the first row, 400 before the second
    ticks = clock(0.0, 10.0, 400.0, 400.0, 400.0)

    made = await anchor_rows(rows, SEARCHED, 300.0, clock=lambda: next(ticks))

    assert made.anchors["a"].block_ids == ("p1-b1",)
    assert [(made.anchors[key].match_kind, made.anchors[key].page_start) for key in ("b", "c")] == [
        (CV + "match_notFound", 1),
        (CV + "match_notFound", 1),
    ]
    assert made.unsearched == 2
    assert made.stages == {"node": {"exact": 1, "unsearched": 1}, "statement": {"unsearched": 1}}
    assert made.stage_of == {"a": "exact", "b": "unsearched", "c": "unsearched"}


async def test_no_row_no_anchor() -> None:
    made = await anchor_rows([], SEARCHED, 300.0)

    assert (made.anchors, made.unsearched) == ({}, 0)
