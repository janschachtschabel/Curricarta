"""The gold standard's arithmetic (plan H-3 §3.4), on small made samples with values computed by hand:
a rate weighted by each stratum's share of the population, the Wilson interval of a pooled rate, recall
over blocks, and what a replay would keep and lose of the judgements."""

import pytest

from app.quality.rates import Recall, recall, replayed, weighted, wilson


def test_precision_weighs_each_stratum_by_its_share_of_the_document() -> None:
    # 30 of 40 in a, 9 of 10 judged correct there; 10 of 40 in b, 1 of 2: 0.75 * 0.9 + 0.25 * 0.5
    frame = {"a": 30, "b": 10}

    rate = weighted(frame, {"a": (9, 10), "b": (1, 2)})

    assert rate == pytest.approx(0.8)
    assert rate != pytest.approx(10 / 12)  # the plain mean over the judged items
    assert weighted(frame, {"a": (10, 10), "b": (2, 2)}) == pytest.approx(1.0)  # all correct
    assert weighted(frame, {"a": (0, 10), "b": (0, 2)}) == 0.0
    empty = weighted({"a": 30, "b": 0}, {"a": (3, 4)})  # an empty stratum weighs nothing
    assert empty == pytest.approx(0.75)


def test_a_stratum_nobody_judged_leaves_the_weighted_rate_unsaid() -> None:
    frame = {"a": 30, "b": 10}

    assert weighted(frame, {"a": (9, 10)}) is None  # b drawn, not judged: null, not 0
    assert weighted(frame, {"a": (9, 10), "b": (0, 0)}) is None
    assert weighted(frame, {}) is None  # nothing judged yet
    assert weighted({}, {}) is None


def test_the_wilson_interval_of_a_pooled_rate() -> None:
    assert wilson(8, 10) == pytest.approx((0.4902, 0.9433), abs=1e-4)
    assert wilson(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert wilson(10, 10) == pytest.approx((0.7225, 1.0), abs=1e-4)
    with pytest.raises(ValueError, match="judged"):
        wilson(0, 0)
    with pytest.raises(ValueError, match="hits"):
        wilson(3, 2)


def test_recall_counts_no_more_found_than_expected() -> None:
    # (expected, found) per block: 3 of 4, 2 of 2 though 5 found, 0 of 1
    counted = recall([(4, 3), (2, 5), (1, 0)])

    assert counted == Recall(expected=7, found=5, recall=5 / 7, missed_blocks=1, surplus_blocks=0, surplus=3)
    assert recall([]) == Recall(0, 0, None, 0, 0, 0)  # nothing judged: unsaid


def test_a_block_expected_empty_with_statements_is_counted_apart() -> None:
    counted = recall([(0, 2), (0, 0), (2, 2)])

    assert counted == Recall(expected=2, found=2, recall=1.0, missed_blocks=0, surplus_blocks=1, surplus=2)
    assert recall([(0, 0)]).recall is None  # no statement expected anywhere: no rate


H, H2, J, K = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def test_a_statement_replaced_with_the_same_wording_at_the_same_block_keeps_its_judgement() -> None:
    # judged as it was drawn; read again by today's reader as a new row: the same wording at the same
    # block keeps its judgement, the same wording at another block is another statement
    judged = [((H, "p1-b2"), "correct"), ((H2, "p1-b3"), "wrong")]

    effect = replayed(judged, stored=[(H, "p1-b2"), (H2, "p1-b3")], read_now=[(H, "p1-b2"), (H2, "p2-b1")])

    assert effect["kept_correct"] == 1
    assert effect["gone_wrong"] == 1
    assert effect["new_unjudged"] == 1  # I at p2-b1


def test_what_a_replay_would_keep_and_lose_is_counted() -> None:
    judged = [
        ((H, "p1-b1"), "correct"),
        ((H2, "p1-b2"), "imprecise"),
        ((J, "p1-b3"), "wrong"),
        ((K, None), "wrong"),  # no block: matched by its wording and the lack of one
        ((H, "p9-b9"), "correct"),
        ((H2, "p9-b9"), "imprecise"),
    ]
    stored = [key for key, _ in judged] + [("e" * 64, "p2-b1")]
    read_now = [(H, "p1-b1"), (H2, "p1-b2"), (K, None), ("f" * 64, "p3-b1"), ("e" * 64, "p2-b1")]

    effect = replayed(judged, stored=stored, read_now=read_now)

    assert effect == {
        "kept_correct": 1, "kept_imprecise": 1, "kept_wrong": 1,
        "gone_correct": 1, "gone_imprecise": 1, "gone_wrong": 1,
        "new_unjudged": 1,
    }  # fmt: skip
