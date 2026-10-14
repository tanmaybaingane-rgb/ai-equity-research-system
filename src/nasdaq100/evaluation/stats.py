"""Stage S7: statistics helpers for the predictive evaluation (decision C7).

* ``newey_west_tstat`` - t-statistic of a mean with a Bartlett-kernel (Newey-West) long-run
  variance; the right tool for a daily series whose 20-day labels overlap across days.
* ``iid_bootstrap_ci`` / ``block_bootstrap_ci`` - percentile bootstrap confidence intervals of an
  arbitrary statistic (independent resampling, or circular moving blocks for serial dependence).
* ``paired_difference_test`` - mean difference of two aligned series with a t-statistic and a
  bootstrap interval.

All helpers drop non-finite observations, never mutate their inputs and are deterministic for a
given ``seed`` (``numpy.random.default_rng``). (The Deflated / Probabilistic Sharpe Ratio is added
in stage S13, not here.)
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

StatFn = Callable[[np.ndarray], float]


class StatsError(ValueError):
    """Invalid arguments to a statistics helper."""


def _clean(values: Any) -> np.ndarray:
    """Finite values as a float64 vector (order preserved)."""
    arr = np.asarray(values, dtype="float64").reshape(-1)
    return arr[np.isfinite(arr)]


def _percentile_ci(draws: np.ndarray, alpha: float) -> tuple[float, float]:
    finite = draws[np.isfinite(draws)]
    if finite.size == 0:
        return (float("nan"), float("nan"))
    lo, hi = np.quantile(finite, [alpha / 2.0, 1.0 - alpha / 2.0])
    return (float(lo), float(hi))


def _check_boot_args(n: int, alpha: float) -> None:
    if int(n) < 1:
        raise StatsError(f"number of bootstrap draws must be >= 1, got {n}")
    if not 0.0 < alpha < 1.0:
        raise StatsError(f"alpha must be in (0, 1), got {alpha}")


def mean_tstat(values: Any) -> float:
    """Ordinary t-statistic of the mean, ``mean / (std(ddof=1) / sqrt(n))`` (NaN if undefined)."""
    x = _clean(values)
    if x.size < 2:
        return float("nan")
    sd = float(np.std(x, ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(np.mean(x) / (sd / math.sqrt(x.size)))


def newey_west_tstat(series: Any, lag: int = 20) -> float:
    """t-statistic of the mean of ``series`` with a Newey-West (Bartlett) standard error.

    ``long_run_var = g0 + 2 * sum_{l=1..L} (1 - l / (L + 1)) * g_l`` with ``g_l`` the lag-``l``
    autocovariance (divisor ``n``) of the demeaned series and ``L = min(lag, n - 1)``;
    ``t = mean / sqrt(long_run_var / n)``. Non-finite values are dropped (the remaining order is
    kept). Returns NaN for fewer than two observations or a constant series.
    """
    if int(lag) < 0:
        raise StatsError(f"lag must be >= 0, got {lag}")
    x = _clean(series)
    n = x.size
    if n < 2 or float(np.ptp(x)) == 0.0:
        return float("nan")
    e = x - x.mean()
    max_lag = min(int(lag), n - 1)
    lrv = float(e @ e) / n
    for k in range(1, max_lag + 1):
        weight = 1.0 - k / (max_lag + 1.0)
        lrv += 2.0 * weight * float(e[k:] @ e[:-k]) / n
    if not lrv > 0.0:
        return float("nan")
    return float(x.mean() / math.sqrt(lrv / n))


def iid_bootstrap_ci(
    values: Any,
    stat_fn: StatFn = np.mean,
    n: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile ``(1 - alpha)`` interval of ``stat_fn`` under independent resampling.

    ``n`` resamples (with replacement, same size as ``values``) are drawn from
    ``numpy.random.default_rng(seed)``. Fewer than two finite values give ``(nan, nan)``.
    """
    _check_boot_args(n, alpha)
    x = _clean(values)
    m = x.size
    if m < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, m, size=(int(n), m))
    draws = np.array([stat_fn(x[row]) for row in idx], dtype="float64")
    return _percentile_ci(draws, alpha)


def block_bootstrap_ci(
    values: Any,
    stat_fn: StatFn = np.mean,
    block: int = 20,
    n: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile interval of ``stat_fn`` under a circular moving-block bootstrap.

    Blocks of ``block`` consecutive observations (wrapping around the end) are concatenated until
    the original length is reached, which preserves serial dependence up to ``block`` lags.
    ``values`` must be in time order; non-finite values are dropped first.
    """
    _check_boot_args(n, alpha)
    if int(block) < 1:
        raise StatsError(f"block must be >= 1, got {block}")
    x = _clean(values)
    m = x.size
    if m < 2:
        return (float("nan"), float("nan"))
    b = min(int(block), m)
    n_blocks = math.ceil(m / b)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, m, size=(int(n), n_blocks))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]) % m
    idx = idx.reshape(int(n), n_blocks * b)[:, :m]
    draws = np.array([stat_fn(x[row]) for row in idx], dtype="float64")
    return _percentile_ci(draws, alpha)


@dataclass(frozen=True)
class PairedDifference:
    """Result of ``paired_difference_test`` (``a - b``)."""

    n: int
    mean_diff: float
    std_diff: float
    t_stat: float
    ci_low: float
    ci_high: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def paired_difference_test(
    a: Any,
    b: Any,
    *,
    n: int = 2000,
    seed: int = 0,
    block: int | None = None,
    alpha: float = 0.05,
) -> PairedDifference:
    """Test ``mean(a - b) = 0`` for two paired samples.

    Two ``pandas.Series`` are aligned on their index (inner join); otherwise both must have the
    same length. Pairs with a non-finite member are dropped. ``t_stat`` is the ordinary paired
    t-statistic (``ddof=1``); the interval is a percentile bootstrap of the mean difference
    (independent resampling, or circular blocks of length ``block`` for a serially dependent
    series).
    """
    if isinstance(a, pd.Series) and isinstance(b, pd.Series):
        a, b = a.align(b, join="inner")
    av = np.asarray(a, dtype="float64").reshape(-1)
    bv = np.asarray(b, dtype="float64").reshape(-1)
    if av.size != bv.size:
        raise StatsError(f"paired samples differ in length: {av.size} vs {bv.size}")
    keep = np.isfinite(av) & np.isfinite(bv)
    d = av[keep] - bv[keep]
    if d.size < 2:
        nan = float("nan")
        return PairedDifference(int(d.size), float(d.mean()) if d.size else nan, nan, nan, nan, nan)
    sd = float(np.std(d, ddof=1))
    mean = float(d.mean())
    t_stat = mean / (sd / math.sqrt(d.size)) if sd > 0.0 else float("nan")
    if block is None:
        lo, hi = iid_bootstrap_ci(d, np.mean, n=n, seed=seed, alpha=alpha)
    else:
        lo, hi = block_bootstrap_ci(d, np.mean, block=block, n=n, seed=seed, alpha=alpha)
    return PairedDifference(int(d.size), mean, sd, float(t_stat), lo, hi)


__all__ = [
    "PairedDifference",
    "StatsError",
    "block_bootstrap_ci",
    "iid_bootstrap_ci",
    "mean_tstat",
    "newey_west_tstat",
    "paired_difference_test",
]
