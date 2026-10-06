"""Synthetic adjusted-price and universe tables for S4 tests (labels).

Labels read only ``ticker, date, t_idx, adj_open`` (adjusted prices) and ``ticker, date,
eligible`` (universe). The generators below still return the *full* S3 / S2 schemas so the same
tables can be written to parquet and read through ``load_adjusted`` / ``load_universe``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nasdaq100.data.adjust import ADJUSTED_COLUMNS
from nasdaq100.data.universe import FAIL_COLUMNS, UNIVERSE_COLUMNS
from nasdaq100.utils.calendar import TradingCalendar

START = "2020-01-06"


def make_adjusted(
    tickers: tuple[str, ...] | list[str],
    n_days: int = 60,
    start_offsets: dict[str, int] | None = None,
    end_offsets: dict[str, int] | None = None,
    seed: int = 3,
) -> tuple[pd.DataFrame, TradingCalendar]:
    """Adjusted table (S3 schema, random-walk opens) plus the calendar of ``n_days`` dates.

    ``start_offsets[tk]`` delays a ticker's first row by that many days; ``end_offsets[tk]``
    drops that many trailing rows (an early exit from the data). ``t_idx`` is the calendar index.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(START, periods=n_days).astype("datetime64[ns]")
    cal = TradingCalendar.from_dates(dates)
    start_offsets, end_offsets = start_offsets or {}, end_offsets or {}
    frames = []
    for k, tk in enumerate(tickers):
        lo, hi = start_offsets.get(tk, 0), n_days - end_offsets.get(tk, 0)
        n = hi - lo
        adj_open = (40.0 + 5.0 * k) * np.exp(np.cumsum(rng.normal(0.0, 0.02, size=n)))
        adj_close = adj_open * np.exp(rng.normal(0.0, 0.01, size=n))
        factor = rng.uniform(0.8, 1.0, size=n)
        volume = rng.integers(1_000, 9_000, size=n).astype("int64")
        frames.append(
            pd.DataFrame(
                {
                    "ticker": tk,
                    "date": dates[lo:hi],
                    "t_idx": np.arange(lo, hi, dtype="int32"),
                    "adj_factor": factor,
                    "adj_open": adj_open,
                    "adj_high": np.maximum(adj_open, adj_close) * 1.01,
                    "adj_low": np.minimum(adj_open, adj_close) * 0.99,
                    "adj_close": adj_close,
                    "volume": volume,
                    "dollar_volume": adj_close * volume,
                    "logret_cc": np.r_[np.nan, np.diff(np.log(adj_close))],
                }
            )
        )
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    return out.loc[:, list(ADJUSTED_COLUMNS)], cal


def make_universe(
    adjusted: pd.DataFrame,
    eligible: np.ndarray | pd.Series | bool | None = True,
    seed: int | None = None,
) -> pd.DataFrame:
    """Universe table (S2 schema) with the same keys as ``adjusted``.

    ``eligible`` is a boolean (all rows), a per-row array, or None together with ``seed`` for a
    random ~85% eligible mask.
    """
    n = len(adjusted)
    if eligible is None:
        eligible = np.random.default_rng(seed).random(n) < 0.85
    flags = np.broadcast_to(np.asarray(eligible, dtype=bool), (n,)).copy()
    uni = pd.DataFrame(
        {
            "ticker": adjusted["ticker"].to_numpy(),
            "date": adjusted["date"].to_numpy(),
            "eligible": flags,
        }
    )
    for col in FAIL_COLUMNS:
        uni[col] = ~flags if col == "fail_master" else False
    uni["median_dollar_volume_63"] = 1.0e7
    return uni.loc[:, list(UNIVERSE_COLUMNS)]


def eligible_where(adjusted: pd.DataFrame, rule) -> np.ndarray:
    """Boolean per-row mask from ``rule(ticker, t_idx) -> bool``."""
    pairs = zip(adjusted["ticker"], adjusted["t_idx"], strict=True)
    return np.array([bool(rule(tk, int(i))) for tk, i in pairs])
