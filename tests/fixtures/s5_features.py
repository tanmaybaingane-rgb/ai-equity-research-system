"""Synthetic adjusted-price and universe tables for S5 tests (features).

Built on the S4 generator (random-walk adjusted opens, ``adj_close`` with its own noise, so
``logret_cc`` is consistent with ``adj_close``). Toy panels use a short seasoning rule
(``min_obs``) instead of the real 252 observations so that every feature warms up inside a few
hundred days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nasdaq100.utils.calendar import TradingCalendar
from tests.fixtures.s4_labels import make_adjusted, make_universe


def make_seasoned_universe(
    adjusted: pd.DataFrame, min_obs: int = 40, drop_frac: float = 0.1, seed: int = 0
) -> pd.DataFrame:
    """Universe where a row is eligible after ``min_obs`` observations, minus a random share."""
    obs = adjusted.groupby("ticker").cumcount().to_numpy()
    keep = np.random.default_rng(seed).random(len(adjusted)) >= drop_frac
    return make_universe(adjusted, (obs >= min_obs) & keep)


def make_feature_panel(
    n_tickers: int = 30,
    n_days: int = 330,
    seed: int = 5,
    min_obs: int = 40,
    drop_frac: float = 0.1,
    start_offsets: dict[str, int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, TradingCalendar]:
    """``(adjusted, universe, calendar)`` for ``n_tickers`` tickers over ``n_days`` dates."""
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    offsets = {"T03": 20, "T07": 90} if start_offsets is None else start_offsets
    adjusted, cal = make_adjusted(tickers, n_days, start_offsets=offsets, seed=seed)
    return adjusted, make_seasoned_universe(adjusted, min_obs, drop_frac, seed + 1), cal


def stock_frame(
    adj_close: np.ndarray,
    adj_high: np.ndarray | None = None,
    adj_low: np.ndarray | None = None,
    dollar_volume: np.ndarray | float = 1.0e7,
    mkt_logret: np.ndarray | None = None,
    ticker: str = "AAA",
) -> pd.DataFrame:
    """One-ticker frame in the layout ``compute_stock_features`` expects (RangeIndex)."""
    close = np.asarray(adj_close, dtype="float64")
    n = len(close)
    return pd.DataFrame(
        {
            "ticker": ticker,
            "adj_high": close * 1.01 if adj_high is None else adj_high,
            "adj_low": close / 1.01 if adj_low is None else adj_low,
            "adj_close": close,
            "dollar_volume": np.broadcast_to(np.asarray(dollar_volume, dtype="float64"), (n,)),
            "logret_cc": np.r_[np.nan, np.diff(np.log(close))],
            "mkt_logret": np.nan if mkt_logret is None else mkt_logret,
        }
    )
