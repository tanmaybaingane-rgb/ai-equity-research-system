"""Unit tests for the S5 market series and market-level features."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from nasdaq100.features.market_features import (
    MARKET_SERIES_COLUMNS,
    build_market_series,
    compute_market_features,
)
from nasdaq100.features.registry import MARKET_FEATURES, FeatureError
from nasdaq100.features.stock_features import SQRT_252

DATES = pd.bdate_range("2020-01-06", periods=8).astype("datetime64[ns]")


def _frame(rows: dict[str, tuple[list[float], list[bool]]]) -> pd.DataFrame:
    parts = []
    for tk, (ret, elig) in rows.items():
        n = len(ret)
        parts.append(
            pd.DataFrame(
                {"ticker": tk, "date": DATES[:n], "t_idx": np.arange(n, dtype="int32"),
                 "logret_cc": ret, "eligible": elig}
            )
        )
    return pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(
        drop=True
    )


@pytest.mark.unit
def test_market_return_uses_composition_eligible_the_day_before() -> None:
    nan = float("nan")
    df = _frame(
        {
            # A: eligible from day 2; B: eligible from day 3 (becomes eligible AT day 3);
            # C: never eligible
            "A": ([nan, 0.01, 0.02, 0.03, 0.04, 0.05], [False, False, True, True, True, True]),
            "B": ([nan, 0.10, 0.20, 0.30, 0.40, 0.50], [False, False, False, True, True, True]),
            "C": ([nan, 0.90, 0.90, 0.90, 0.90, 0.90], [False] * 6),
        }
    )
    m = build_market_series(df)
    assert list(m.columns) == list(MARKET_SERIES_COLUMNS)
    assert len(m) == 6 and m["date"].dtype == "datetime64[ns]"
    # day t uses names eligible at t-1: nobody before day 3; A alone on day 3; A and B from day 4
    assert m["mkt_logret"].iloc[:3].isna().all()
    assert m["mkt_logret"].iloc[3] == pytest.approx(0.03)  # A only (B only eligible AT day 3)
    assert m["mkt_logret"].iloc[4] == pytest.approx((0.04 + 0.40) / 2)
    assert m["mkt_logret"].iloc[5] == pytest.approx((0.05 + 0.50) / 2)
    # n_eligible counts the names eligible ON the day itself
    assert m["n_eligible"].tolist() == [0, 0, 1, 2, 2, 2]
    # index: cumulative exp of the returns, NaN while undefined (nothing invented before)
    assert m["mkt_index"].iloc[:3].isna().all()
    assert m["mkt_index"].iloc[3] == pytest.approx(math.exp(0.03))
    assert m["mkt_index"].iloc[5] == pytest.approx(math.exp(0.03 + 0.22 + 0.275))


@pytest.mark.unit
def test_market_series_ignores_missing_returns_and_validates_dates() -> None:
    nan = float("nan")
    df = _frame({"A": ([nan, 0.02, 0.02], [True] * 3), "B": ([nan, nan, 0.04], [True] * 3)})
    m = build_market_series(df)
    assert m["mkt_logret"].iloc[1] == pytest.approx(0.02)  # B's NaN return is not averaged in
    assert m["mkt_logret"].iloc[2] == pytest.approx(0.03)
    gap = df[df["date"] != DATES[1]]  # a calendar date on which nobody has a row
    with pytest.raises(FeatureError, match="consecutive"):
        build_market_series(gap)
    with pytest.raises(FeatureError, match="missing columns"):
        build_market_series(df.drop(columns=["eligible"]))


def _market(n: int, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0005, 0.01, n)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2019-01-02", periods=n).astype("datetime64[ns]"),
            "mkt_logret": r,
            "mkt_index": np.exp(np.cumsum(r)),
            "n_eligible": 5,
        }
    )


@pytest.mark.unit
def test_return_vol_and_trend_features_match_definitions() -> None:
    n = 260
    mkt = _market(n)
    ctx = pd.DataFrame({"date": mkt["date"], "eligible": True, "px_sma_50": 0.0, "ret_21": 0.0})
    f = compute_market_features(mkt, ctx, MARKET_FEATURES)
    assert list(f.columns) == list(MARKET_FEATURES) and f.index.equals(pd.Index(mkt["date"]))
    r, idx = mkt["mkt_logret"].to_numpy(), mkt["mkt_index"].to_numpy()
    t = 255
    assert f["mkt_ret_21"].iloc[t] == pytest.approx(r[t - 20 : t + 1].sum(), rel=1e-12)
    assert f["mkt_ret_63"].iloc[t] == pytest.approx(r[t - 62 : t + 1].sum(), rel=1e-12)
    assert f["mkt_vol_21"].iloc[t] == pytest.approx(
        np.std(r[t - 20 : t + 1], ddof=1) * SQRT_252, rel=1e-12
    )
    assert f["mkt_trend_200"].iloc[t] == pytest.approx(
        math.log(idx[t] / idx[t - 199 : t + 1].mean()), rel=1e-12
    )
    # full windows only
    assert f["mkt_ret_21"].iloc[:20].isna().all() and f["mkt_ret_21"].iloc[20:].notna().all()
    assert f["mkt_ret_63"].iloc[:62].isna().all() and f["mkt_ret_63"].iloc[62:].notna().all()
    assert f["mkt_trend_200"].iloc[:199].isna().all() and f["mkt_trend_200"].iloc[199:].notna().all()


@pytest.mark.unit
def test_breadth_and_dispersion_use_eligible_names_of_the_date_only() -> None:
    d = DATES[:2]
    stock = pd.DataFrame(
        {
            "date": [d[0]] * 5 + [d[1]] * 3,
            "eligible": [True, True, True, True, False, True, True, True],
            # day 0: eligible px_sma_50 = +,+,-,0 (0 is not > 0); the ineligible name is ignored
            "px_sma_50": [0.1, 0.2, -0.1, 0.0, 9.0, np.nan, 0.3, 0.4],
            "ret_21": [0.1, 0.2, 0.3, 0.4, 99.0, 0.5, np.nan, 0.5],
        }
    )
    mkt = pd.DataFrame({"date": d, "mkt_logret": np.nan, "mkt_index": np.nan, "n_eligible": 4})
    f = compute_market_features(mkt, stock, ["mkt_breadth_50", "xs_disp_21"])
    assert f["mkt_breadth_50"].iloc[0] == pytest.approx(2 / 4)
    assert f["mkt_breadth_50"].iloc[1] == pytest.approx(2 / 2)  # the NaN px_sma_50 is not counted
    # cross-sectional sample std (ddof = 1) of the eligible names with a defined ret_21
    assert f["xs_disp_21"].iloc[0] == pytest.approx(np.std([0.1, 0.2, 0.3, 0.4], ddof=1))
    assert f["xs_disp_21"].iloc[1] == pytest.approx(0.0)  # two eligible values, both 0.5
    none = stock.assign(eligible=False)
    g = compute_market_features(mkt, none, ["mkt_breadth_50", "xs_disp_21"])
    assert g.isna().all().all()  # no eligible name -> undefined, not a number


@pytest.mark.unit
def test_market_feature_selection_and_validation() -> None:
    mkt = _market(30)
    ctx = pd.DataFrame({"date": mkt["date"], "eligible": True})
    f = compute_market_features(mkt, ctx, ["mkt_ret_21", "mkt_vol_21"])
    assert list(f.columns) == ["mkt_ret_21", "mkt_vol_21"]
    with pytest.raises(FeatureError, match="not a market-level"):
        compute_market_features(mkt, ctx, ["ret_21"])
