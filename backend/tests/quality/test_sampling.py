"""The stratified sample of the gold standard (app/quality/sampling.py, plan H-3 §3.2): each stratum gets its
least and the rest by its share; within a stratum the items stand in the order the seed gives their keys,
so the same items give the same sample, whatever their order and whatever the other strata hold."""

import hashlib
from dataclasses import dataclass

from app.quality.sampling import allotted, drawn, place

SEED = "curricarta-h3"


@dataclass(frozen=True)
class Unit:
    stratum: str
    key: str


def units(stratum: str, count: int, prefix: str = "k") -> list[Unit]:
    return [Unit(stratum, f"{prefix}{stratum}{number}") for number in range(count)]


def sample(items: list[Unit], size: int, seed: str = SEED, least: int = 2) -> list[Unit]:
    return drawn(
        items, seed=seed, size=size, stratum=lambda unit: unit.stratum, key=lambda unit: unit.key, least=least
    )


def test_a_place_is_the_hash_of_the_seed_and_the_key() -> None:
    assert place("s", "k") == hashlib.sha256(b"s\nk").hexdigest()


def test_every_stratum_gets_its_least_and_the_rest_by_share() -> None:
    # 2, 2 and the one c has; the 15 left by share of a and b, the one over to the larger remainder
    assert allotted({"a": 100, "b": 10, "c": 1}, 20) == {"a": 16, "b": 3, "c": 1}
    assert allotted({"a": 100, "b": 10, "c": 1}, 20, least=5) == {"a": 13, "b": 6, "c": 1}
    assert allotted({"a": 30, "b": 30}, 3) == {"a": 2, "b": 2}  # the least over the size: each its least
    assert allotted({"b": 3, "a": 0}, 2) == {"b": 2}  # an empty stratum gets nothing
    # each stratum by itself, in their order
    assert list(allotted({"b": 5, "a": 5}, 4)) == ["a", "b"]


def test_a_stratum_smaller_than_its_least_gives_all_it_has() -> None:
    assert allotted({"a": 1, "b": 50}, 10, least=5) == {"a": 1, "b": 9}

    picked = sample([*units("a", 1), *units("b", 50)], 10, least=5)

    assert [unit.stratum for unit in picked] == ["a"] + ["b"] * 9


def test_the_same_items_give_the_same_sample_whatever_their_order() -> None:
    items = [*units("a", 20), *units("b", 7), *units("c", 3)]

    first = sample(items, 12)

    assert sample(list(reversed(items)), 12) == first
    assert sample(sorted(items, key=lambda unit: place("other", unit.key)), 12) == first
    assert len(first) == 12


def test_another_seed_is_another_sample() -> None:
    items = units("a", 40)

    assert sample(items, 10, seed="another") != sample(items, 10)
    assert sample(items, 10, seed=SEED) == sample(items, 10)


def test_a_stratum_is_sampled_by_itself_alone() -> None:
    a = units("a", 30)
    by_seed = sorted(a, key=lambda unit: place(SEED, unit.key))

    picked = sample([*a, *units("b", 30)], 10)
    beside_others = sample([*a, *units("b", 30, prefix="other")], 10)

    # a's own come first, the first of its seed's order; what b holds changes nothing of them
    assert [unit for unit in picked if unit.stratum == "a"] == by_seed[:5]
    assert [unit for unit in beside_others if unit.stratum == "a"] == by_seed[:5]


def test_no_items_give_no_sample() -> None:
    assert sample([], 40) == []
    assert allotted({}, 40) == {}


def test_a_size_beyond_the_population_takes_everyone() -> None:
    items = [*units("a", 4), *units("b", 3)]

    picked = sample(items, 100)

    assert sorted(picked, key=lambda unit: unit.key) == sorted(items, key=lambda unit: unit.key)
    assert allotted({"a": 4, "b": 3}, 100) == {"a": 4, "b": 3}
