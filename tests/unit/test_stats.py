"""Unit tests for the S7 statistics helpers (``evaluation/stats.py``)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from nasdaq100.evaluation.stats import (
    StatsError,
    block_bootstrap_ci,
    iid_bootstrap_ci,
    mean_tstat,
    newey_west_tstat,
    paired_difference_test,
)


def _ar1(n: int, phi: float, seed: int, mean: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    eps = rng.normal(size=n)
    out = np.zeros(n)
    for t in range(1, n):
        out[t] = phi * out[t - 1] + eps[t]
    return out + mean


@pytest.mark.unit
def test_newey_west_matches_a_hand_computed_example() -> None:
    # x = 1..5, lag 1: e = (-2..2), g0 = 2, g1 = 0.8, weight 1/2 -> lrv = 2.8, t = 3 / sqrt(2.8/5)
    assert newey_west_tstat([1, 2, 3, 4, 5], lag=1) == pytest.approx(3.0 / math.sqrt(0.56))
    # lag 0 is the plain (divisor n) variance: lrv = 2, t = 3 / sqrt(2/5)
    assert newey_west_tstat([1, 2, 3, 4, 5], lag=0) == pytest.approx(3.0 / math.sqrt(0.4))


@pytest.mark.unit
def test_newey_west_is_close_to_the_ordinary_t_on_iid_data() -> None:
    x = np.random.default_rng(1).normal(0.1, 1.0, 5000)
    nw, ordinary = newey_west_tstat(x, lag=20), mean_tstat(x)
    assert ordinary > 3.0
    assert nw == pytest.approx(ordinary, rel=0.15)


@pytest.mark.unit
def test_newey_west_is_smaller_on_positively_autocorrelated_data() -> None:
    x = _ar1(5000, phi=0.5, seed=1, mean=0.1)
    assert newey_west_tstat(x, lag=20) < 0.8 * mean_tstat(x)


@pytest.mark.unit
def test_newey_west_edge_cases() -> None:
    assert math.isnan(newey_west_tstat([1.0, 1.0, 1.0]))  # constant series
    assert math.isnan(newey_west_tstat([1.0]))
    assert math.isnan(newey_west_tstat([]))
    assert newey_west_tstat([np.nan, 1, 2, 3, 4, 5], lag=1) == newey_west_tstat([1, 2, 3, 4, 5], 1)
    assert math.isfinite(newey_west_tstat([1.0, 2.0], lag=50))  # lag is capped at n - 1
    with pytest.raises(StatsError):
        newey_west_tstat([1, 2, 3], lag=-1)


@pytest.mark.unit
def test_mean_tstat_uses_the_sample_standard_deviation() -> None:
    x = [1.0, 2.0, 3.0, 4.0]
    assert mean_tstat(x) == pytest.approx(2.5 / (np.std(x, ddof=1) / 2.0))
    assert math.isnan(mean_tstat([2.0, 2.0])) and math.isnan(mean_tstat([1.0]))


@pytest.mark.unit
def test_iid_bootstrap_ci_covers_the_mean_and_is_deterministic() -> None:
    x = np.random.default_rng(2).normal(0.3, 1.0, 400)
    lo, hi = iid_bootstrap_ci(x, np.mean, n=500, seed=7)
    assert lo < x.mean() < hi and hi - lo < 0.5
    assert (lo, hi) == iid_bootstrap_ci(x, np.mean, n=500, seed=7)
    assert (lo, hi) != iid_bootstrap_ci(x, np.mean, n=500, seed=8)
    med_lo, med_hi = iid_bootstrap_ci(x, np.median, n=300, seed=1)
    assert med_lo < med_hi
    wide = iid_bootstrap_ci(x, np.mean, n=500, seed=7, alpha=0.5)
    assert wide[0] > lo and wide[1] < hi  # a 50 % interval sits inside the 95 % interval


@pytest.mark.unit
def test_iid_bootstrap_ci_covers_the_true_mean_in_repeated_draws() -> None:
    rng = np.random.default_rng(11)
    true_mean, hits, repeats = 0.3, 0, 200
    for i in range(repeats):
        sample = rng.normal(true_mean, 1.0, 150)
        lo, hi = iid_bootstrap_ci(sample, np.mean, n=200, seed=i)
        hits += int(lo <= true_mean <= hi)
    assert hits / repeats >= 0.90


@pytest.mark.unit
def test_bootstrap_edge_cases() -> None:
    for fn in (iid_bootstrap_ci, block_bootstrap_ci):
        lo, hi = fn([1.0], np.mean, n=10, seed=0)
        assert math.isnan(lo) and math.isnan(hi)
        lo, hi = fn([np.nan, np.nan, 1.0], np.mean, n=10, seed=0)
        assert math.isnan(lo)
        with pytest.raises(StatsError):
            fn([1.0, 2.0, 3.0], np.mean, n=0, seed=0)
        with pytest.raises(StatsError):
            fn([1.0, 2.0, 3.0], np.mean, n=10, seed=0, alpha=1.5)
    with pytest.raises(StatsError):
        block_bootstrap_ci([1.0, 2.0, 3.0], np.mean, block=0, n=10, seed=0)
    lo, hi = block_bootstrap_ci(np.arange(10.0), np.mean, block=50, n=50, seed=1)  # block capped
    assert lo <= hi


@pytest.mark.unit
def test_block_bootstrap_is_wider_than_iid_for_serially_dependent_data() -> None:
    x = _ar1(1000, phi=0.7, seed=1)
    iid = iid_bootstrap_ci(x, np.mean, n=500, seed=3)
    blk = block_bootstrap_ci(x, np.mean, block=20, n=500, seed=3)
    assert (blk[1] - blk[0]) > 1.5 * (iid[1] - iid[0])
    assert blk == block_bootstrap_ci(x, np.mean, block=20, n=500, seed=3)


@pytest.mark.unit
def test_paired_difference_detects_a_planted_shift() -> None:
    rng = np.random.default_rng(3)
    b = rng.normal(size=200)
    a = b + 0.3 + rng.normal(0.0, 0.5, size=200)
    res = paired_difference_test(a, b, n=500, seed=1)
    assert res.n == 200 and res.mean_diff == pytest.approx(0.3, abs=0.15)
    assert res.t_stat > 5.0 and res.ci_low > 0.0 and res.ci_low < res.mean_diff < res.ci_high
    rev = paired_difference_test(b, a, n=500, seed=1)
    assert rev.mean_diff == pytest.approx(-res.mean_diff) and rev.t_stat == pytest.approx(
        -res.t_stat
    )
    blk = paired_difference_test(a, b, n=300, seed=1, block=10)
    assert blk.ci_low < blk.mean_diff < blk.ci_high
    assert set(res.as_dict()) == {"n", "mean_diff", "std_diff", "t_stat", "ci_low", "ci_high"}


@pytest.mark.unit
def test_paired_difference_alignment_and_degenerate_inputs() -> None:
    a = pd.Series([1.0, 2.0, 3.0, 4.0], index=[0, 1, 2, 3])
    b = pd.Series([0.5, 1.0, 2.5], index=[1, 2, 3])
    res = paired_difference_test(a, b, n=50, seed=0)  # aligned on the shared index 1..3
    assert res.n == 3 and res.mean_diff == pytest.approx(np.mean([1.5, 2.0, 1.5]))
    with pytest.raises(StatsError):
        paired_difference_test([1.0, 2.0], [1.0, 2.0, 3.0])
    nan_pair = paired_difference_test([1.0, np.nan, 3.0, 4.0], [0.0, 1.0, 2.0, np.nan], n=20)
    assert nan_pair.n == 2  # pairs with a NaN member are dropped
    same = paired_difference_test([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], n=20)
    assert same.mean_diff == 0.0 and math.isnan(same.t_stat)
    one = paired_difference_test([1.0], [0.0])
    assert one.n == 1 and math.isnan(one.t_stat) and math.isnan(one.ci_low)
