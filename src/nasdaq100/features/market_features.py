"""Stage S5: market series and the six market-level features.

Market series (specification 1): ``mkt_logret_t`` is the mean of ``logret_t`` over the names
that were **eligible at t-1** (the composition is fixed before the return happens);
``mkt_index`` is the cumulative ``exp`` of ``mkt_logret`` starting at 1; ``n_eligible_t`` is the
number of eligible names on ``t`` itself.

Until the first name becomes eligible (the seasoning period: 252 observations) there is no
composition, so ``mkt_logret`` is NaN and so is ``mkt_index``; nothing is invented for those
dates. The first defined return belongs to the date after the first eligible one.

Market features are date-level: identical for every ticker on a date, derived from the market
series (trailing windows over dates) and from stock-level columns of the same date.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from nasdaq100.features.registry import MARKET_FEATURES, FeatureError, get_spec
from nasdaq100.features.stock_features import SQRT_252, safe_log

MARKET_SERIES_COLUMNS: tuple[str, ...] = ("date", "mkt_logret", "mkt_index", "n_eligible")


def build_market_series(df: pd.DataFrame) -> pd.DataFrame:
    """Market series from a (ticker, date)-sorted frame with ``eligible`` and ``logret_cc``.

    Returns one row per date with exactly ``MARKET_SERIES_COLUMNS``. The dates must be
    consecutive trading days (``t_idx`` step 1); otherwise ``FeatureError``.
    """
    missing = [c for c in ("ticker", "date", "t_idx", "eligible", "logret_cc") if c not in df]
    if missing:
        raise FeatureError(f"Market series input is missing columns: {missing}")
    dates = pd.DatetimeIndex(np.sort(df["date"].unique()))
    day_idx = df.groupby("date")["t_idx"].first().reindex(dates)
    if len(dates) > 1 and not (day_idx.diff().dropna() == 1).all():
        raise FeatureError("Market series needs consecutive trading dates (t_idx step 1)")

    prev_elig = (
        df.groupby("ticker", sort=False)["eligible"].shift(1).fillna(False).astype(bool)
    )
    members = df.loc[prev_elig, ["date", "logret_cc"]]
    mkt_logret = members.groupby("date")["logret_cc"].mean().reindex(dates)
    n_eligible = df.groupby("date")["eligible"].sum().reindex(dates).astype("int32")
    out = pd.DataFrame(
        {
            "date": dates.astype("datetime64[ns]"),
            "mkt_logret": mkt_logret.to_numpy(dtype="float64"),
            "mkt_index": np.exp(mkt_logret.cumsum()).to_numpy(dtype="float64"),
            "n_eligible": n_eligible.to_numpy(),
        }
    )
    return out.loc[:, list(MARKET_SERIES_COLUMNS)]


def _roll(s: pd.Series, window: int, how: str) -> pd.Series:
    return getattr(s.rolling(window, min_periods=window), how)()


def compute_market_features(
    market: pd.DataFrame, stock: pd.DataFrame, names: Iterable[str]
) -> pd.DataFrame:
    """Date-level market features ``names`` (columns in registry order), indexed by date.

    ``stock`` carries per-row ``date``, ``eligible`` and the stock-level columns ``px_sma_50`` and
    ``ret_21`` (needed by ``mkt_breadth_50`` and ``xs_disp_21``; only requested ones are read).
    """
    wanted = list(dict.fromkeys(names))
    for n in wanted:
        if get_spec(n).level != "market":
            raise FeatureError(f"{n!r} is not a market-level feature")
    ms = market.set_index("date")
    ret = ms["mkt_logret"]
    feats: dict[str, pd.Series] = {}
    if "mkt_ret_21" in wanted:
        feats["mkt_ret_21"] = _roll(ret, 21, "sum")
    if "mkt_ret_63" in wanted:
        feats["mkt_ret_63"] = _roll(ret, 63, "sum")
    if "mkt_vol_21" in wanted:
        feats["mkt_vol_21"] = _roll(ret, 21, "std") * SQRT_252
    if "mkt_trend_200" in wanted:
        idx = ms["mkt_index"]
        feats["mkt_trend_200"] = pd.Series(
            safe_log(idx / _roll(idx, 200, "mean")), index=ms.index
        )
    elig = stock["eligible"].to_numpy(dtype=bool)
    if "mkt_breadth_50" in wanted:
        px = stock["px_sma_50"]
        use = elig & px.notna().to_numpy()
        g = pd.DataFrame({"date": stock["date"], "use": use, "pos": use & (px > 0).to_numpy()})
        by = g.groupby("date")[["use", "pos"]].sum()
        feats["mkt_breadth_50"] = (by["pos"] / by["use"].where(by["use"] > 0)).reindex(ms.index)
    if "xs_disp_21" in wanted:
        r21 = stock["ret_21"].where(elig)
        feats["xs_disp_21"] = r21.groupby(stock["date"]).std().reindex(ms.index)
    out = pd.DataFrame(
        {n: feats[n].astype("float64") for n in MARKET_FEATURES if n in feats}, index=ms.index
    )
    return out.replace([np.inf, -np.inf], np.nan)
