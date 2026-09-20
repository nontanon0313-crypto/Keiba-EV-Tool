"""Plackett-Luce 順位モデルのテスト。"""
import math

import pytest


def pl_first_probs(scores):
    total = sum(math.exp(s) for s in scores)
    return [math.exp(s) / total for s in scores]


def pl_sequence_prob(scores, order):
    remaining = list(range(len(scores)))
    p = 1.0
    for idx in order:
        weights = [math.exp(scores[i]) for i in remaining]
        tot = sum(weights)
        pos = remaining.index(idx)
        p *= weights[pos] / tot
        remaining.pop(pos)
    return p


def test_first_probs_sum_to_one():
    scores = [1.0, 2.0, 3.0]
    probs = pl_first_probs(scores)
    assert sum(probs) == pytest.approx(1.0)


def test_sequence_prob_matches_manual():
    scores = [0.0, 0.0, 0.0]
    p = pl_sequence_prob(scores, [0, 1, 2])
    # 均等なら 1/3 * 1/2 * 1 = 1/6
    assert p == pytest.approx(1.0 / 6.0)


def test_sequence_not_independent_product():
    scores = [0.5, 0.0, -0.5]
    seq = pl_sequence_prob(scores, [0, 1, 2])
    first = pl_first_probs(scores)
    naive = first[0] * first[1] * first[2]
    # PL の逐次確率は独立積と一致しない
    assert seq != pytest.approx(naive)


def test_sequence_prob_is_probability():
    scores = [1.2, -0.3, 0.4, 0.0]
    for perm in ([0, 1, 2, 3], [3, 2, 1, 0], [1, 0, 3, 2]):
        p = pl_sequence_prob(scores, list(perm))
        assert 0.0 < p < 1.0
