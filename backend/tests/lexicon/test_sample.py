"""The sample of the research cues the editors check (plan M1 10.3, 10c C4): by stratum - sector and
regions - a tenth of each, rounded up, in the order a fixed seed gives each cue's IRI; the same cues give
the same sample, whatever their order and whatever the other strata hold."""

import hashlib
from collections import Counter
from dataclasses import dataclass

from app.lexicon.sample import SEED, Stratum, sample


@dataclass(frozen=True)
class Item:
    iri: str
    stratum: Stratum


def items(count: int, sector: str = "school", regions: tuple[str, ...] = ("DE-NW",)) -> list[Item]:
    name = f"{sector}-{'-'.join(regions)}"
    return [Item(f"https://example.org/{name}/cue-{n}", (sector, regions)) for n in range(count)]


def test_each_stratum_gives_a_tenth_rounded_up_so_at_least_one() -> None:
    cues = items(25) + items(3, regions=("DE-BY",)) + items(10, sector="beruf") + items(11, regions=("DE",))

    picked = sample(cues)

    assert Counter(cue.stratum for cue in picked) == {
        ("school", ("DE-NW",)): 3,
        ("school", ("DE-BY",)): 1,
        ("beruf", ("DE-NW",)): 1,
        ("school", ("DE",)): 2,
    }


def test_within_a_stratum_the_seed_orders_the_cues_by_their_iri() -> None:
    cues = items(25)

    def order(cue: Item) -> str:
        return hashlib.sha256(f"{SEED}\n{cue.iri}".encode()).hexdigest()

    assert sample(cues) == sorted(cues, key=order)[:3]
    assert (
        SEED == "curricarta-m1-10c"
    )  # another seed is another sample: the editors' decisions refer to this one


def test_the_order_of_the_cues_changes_nothing() -> None:
    cues = items(25) + items(30, sector="beruf")

    assert sample(cues) == sample(list(reversed(cues)))


def test_a_stratum_is_sampled_by_itself_alone() -> None:
    school = items(25)

    picked = sample(school + items(40, sector="beruf") + items(7, regions=("DE-BY",)))

    assert [cue for cue in picked if cue.stratum == ("school", ("DE-NW",))] == sample(school)


def test_the_strata_come_in_their_order() -> None:
    picked = sample(items(5, sector="b") + items(5, sector="a", regions=("DE-SN",)) + items(5, sector="a"))

    assert [cue.stratum for cue in picked] == [("a", ("DE-NW",)), ("a", ("DE-SN",)), ("b", ("DE-NW",))]


def test_no_cues_give_no_sample() -> None:
    assert sample([]) == []
