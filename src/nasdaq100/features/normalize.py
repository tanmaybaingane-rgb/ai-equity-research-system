"""Stage S5: per-date winsorisation and rank-gauss normalisation of stock-level features.

For every date, **using only the eligible rows of that date** and every feature separately:

1. clip the raw values to the ``features.winsor_pct`` quantiles of that date;
2. replace each value by ``z = Phi^-1((rank - 0.5) / n)``, ``rank`` the average rank among the
   non-NaN values of the date (ties share their average rank) and ``n`` their number.

Features of ineligible rows are NaN. No statistic is ever pooled across dates or taken over
ineligible names (leakage test L5): the groupings below are by date, on the eligible subset.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.special import ndtri

from nasdaq100.features.registry import FeatureError


def check_winsor(winsor_pct: Sequence[float]) -> tuple[float, float]:
    """Validate ``features.winsor_pct`` as ``[lo, hi]`` with ``0 <= lo < hi <= 1``."""
    q = [float(v) for v in winsor_pct]
    if len(q) != 2 or not (0.0 <= q[0] < q[1] <= 1.0):
        raise FeatureError(f"features.winsor_pct must be [lo, hi] with 0 <= lo < hi <= 1, got {q}")
    return q[0], q[1]


def rank_gauss_per_date(
    raw: pd.DataFrame,
    dates: pd.Series | np.ndarray,
    eligible: pd.Series | np.ndarray,
    winsor_pct: Sequence[float],
) -> pd.DataFrame:
    """Winsorise then rank-gauss the columns of ``raw`` per date among eligible rows.

    ``raw`` holds one row per (ticker, date) with the raw stock-level features; ``dates`` and
    ``eligible`` are aligned with its rows. Returns a frame of the same shape and index; values
    of ineligible rows, and of rows whose raw value is NaN, are NaN.
    """
    q_lo, q_hi = check_winsor(winsor_pct)
    elig = np.asarray(eligible, dtype=bool)
    date_arr = np.asarray(dates)
    out = pd.DataFrame(np.nan, index=raw.index, columns=raw.columns, dtype="float64")
    if not elig.any() or raw.shape[1] == 0:
        return out

    sub = raw.loc[elig].astype("float64")
    key = date_arr[elig]
    by_date = sub.groupby(key)
    lo = by_date.quantile(q_lo).reindex(key).to_numpy()
    hi = by_date.quantile(q_hi).reindex(key).to_numpy()
    clipped = pd.DataFrame(
        np.minimum(np.maximum(sub.to_numpy(), lo), hi), index=sub.index, columns=sub.columns
    )
    grouped = clipped.groupby(key)
    rank = grouped.rank(method="average")
    n = grouped.transform("count")
    z = ndtri(((rank - 0.5) / n).to_numpy(dtype="float64"))
    out.loc[elig, :] = z
    return out
