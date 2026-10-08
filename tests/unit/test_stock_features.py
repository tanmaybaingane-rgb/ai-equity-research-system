"""Unit tests for the S5 stock-level features (``features/stock_features.py``)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from nasdaq100.features.registry import STOCK_FEATURES, FeatureError, get_spec
from nasdaq100.features.stock_features import SQRT_252, compute_stock_features, safe_log
from tests.fixtures.s5_features import stock_frame

R = math.log(1.01)


def _geometric(n: int = 300, growth: float = 1.01, band: float = 1.02, dvol: float = 1.0e7):
    close = 100.0 * growth ** np.arange(n)
    return stock_frame(close, adj_high=close * band, adj_low=close / band, dollar_volume=dvol)


@pytest.mark.unit
def test_closed_form_values_on_a_geometric_series() -> None:
    n, t = 300, 299
    f = compute_stock_features(_geometric(n), STOCK_FEATURES).iloc[t]
    for k in (5, 21, 63, 126, 252):
        assert f[f"ret_{k}"] == pytest.approx(k * R, abs=1e-12)
    assert f["mom_12_1"] == pytest.approx(231 * R, abs=1e-12)  # ln(c[t-21] / c[t-252])
    assert f["parkinson_21"] == pytest.approx(
        math.log(1.02) / math.sqrt(math.log(2.0)) * SQRT_252, rel=1e-12
    )

    def sma_log(w: int) -> float:  # ln(c_t / mean of the last w closes), closes grow by 1.01
        mean_rel = sum(1.01 ** (-j) for j in range(w)) / w
        return -math.log(mean_rel)

    assert f["px_sma_50"] == pytest.approx(sma_log(50), abs=1e-12)
    assert f["px_sma_200"] == pytest.approx(sma_log(200), abs=1e-12)
    assert f["dist_52w_high"] == pytest.approx(0.0, abs=1e-15)  # today is the 252-day high
    assert f["log_dvol_63"] == pytest.approx(math.log(1.0e7), abs=1e-12)
    assert f["rel_dvol_21_63"] == pytest.approx(0.0, abs=1e-12)
    assert f["amihud_63"] == pytest.approx(math.log1p(1e6 * R / 1.0e7), rel=1e-9)


@pytest.mark.unit
def test_volatility_features_on_alternating_returns() -> None:
    n = 300
    r = np.where(np.arange(n) % 2 == 1, 0.01, -0.01)  # odd rows +1%, even rows -1%
    close = 100.0 * np.exp(np.cumsum(np.r_[0.0, r[1:]]))
    t = 299  # odd row: window 21 holds 11 up / 10 down, window 63 holds 32 up / 31 down
    f = compute_stock_features(stock_frame(close), STOCK_FEATURES).iloc[t]

    def sample_std(n_up: int, n_down: int) -> float:
        m = 0.01 * (n_up - n_down) / (n_up + n_down)
        ss = (n_up + n_down) * 1e-4
        return math.sqrt((ss - (n_up + n_down) * m * m) / (n_up + n_down - 1))

    vol21, vol63 = sample_std(11, 10) * SQRT_252, sample_std(32, 31) * SQRT_252
    assert f["vol_21"] == pytest.approx(vol21, rel=1e-9)
    assert f["vol_63"] == pytest.approx(vol63, rel=1e-9)
    assert f["vol_ratio_21_63"] == pytest.approx(math.log(vol21 / vol63), rel=1e-9)
    assert f["downvol_63"] == pytest.approx(math.sqrt(31 * 1e-4 / 63) * SQRT_252, rel=1e-9)


def _reference_row(df: pd.DataFrame, t: int) -> dict[str, float]:
    """Plain-Python definitions (loops, no pandas rolling) of all 18 features at row ``t``."""
    c, h, lo = df["adj_close"].to_numpy(), df["adj_high"].to_numpy(), df["adj_low"].to_numpy()
    x, m = df["logret_cc"].to_numpy(), df["mkt_logret"].to_numpy()
    dv = df["dollar_volume"].to_numpy()
    nan = float("nan")

    def win(a: np.ndarray, w: int):
        return a[t - w + 1 : t + 1] if t - w + 1 >= 0 else None

    def std(a: np.ndarray) -> float:
        mu = sum(a) / len(a)
        return math.sqrt(sum((v - mu) ** 2 for v in a) / (len(a) - 1))

    out: dict[str, float] = {}
    for k in (5, 21, 63, 126, 252):
        out[f"ret_{k}"] = math.log(c[t] / c[t - k]) if t >= k else nan
    out["mom_12_1"] = math.log(c[t - 21] / c[t - 252]) if t >= 252 else nan
    for w in (21, 63):
        a = win(x, w)
        out[f"vol_{w}"] = std(a) * SQRT_252 if a is not None and not np.isnan(a).any() else nan
    x63 = win(x, 63)
    ok = x63 is not None and not np.isnan(x63).any()
    out["downvol_63"] = (
        math.sqrt(sum(min(v, 0.0) ** 2 for v in x63) / 63) * SQRT_252 if ok else nan
    )
    out["vol_ratio_21_63"] = (
        math.log(out["vol_21"] / out["vol_63"]) if ok else nan
    )
    a_h, a_l = win(h, 21), win(lo, 21)
    out["parkinson_21"] = (
        math.sqrt(sum(math.log(p / q) ** 2 for p, q in zip(a_h, a_l, strict=True)) / 21
                  / (4 * math.log(2))) * SQRT_252
        if a_h is not None else nan
    )
    xs, ms = win(x, 126), win(m, 126)
    if xs is not None and not np.isnan(xs).any() and not np.isnan(ms).any():
        out["beta_126"] = float(np.cov(xs, ms)[0, 1] / np.var(ms, ddof=1))
    else:
        out["beta_126"] = nan
    for w in (50, 200):
        a = win(c, w)
        out[f"px_sma_{w}"] = math.log(c[t] / (sum(a) / w)) if a is not None else nan
    a = win(c, 252)
    out["dist_52w_high"] = math.log(c[t] / max(a)) if a is not None else nan
    a63, a21 = win(dv, 63), win(dv, 21)
    out["log_dvol_63"] = math.log(sum(a63) / 63) if a63 is not None else nan
    out["rel_dvol_21_63"] = (
        math.log((sum(a21) / 21) / (sum(a63) / 63)) if a63 is not None else nan
    )
    if ok:
        terms = [abs(r) / d for r, d in zip(x63, a63, strict=True) if d > 0]
        out["amihud_63"] = math.log1p(1e6 * sum(terms) / len(terms)) if terms else nan
    else:
        out["amihud_63"] = nan
    return out


@pytest.mark.unit
def test_all_features_match_plain_python_reference_at_every_row() -> None:
    rng = np.random.default_rng(7)
    n = 330
    close = 50.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n)))
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close / (1 + rng.uniform(0.001, 0.02, n))
    dvol = rng.uniform(1e5, 5e6, n)
    dvol[[100, 101, 250]] = 0.0  # zero-dollar-volume days exist in the real data
    mkt = np.r_[np.nan, rng.normal(0.0004, 0.01, n - 1)]
    df = stock_frame(close, high, low, dvol, mkt)
    got = compute_stock_features(df, STOCK_FEATURES)
    assert list(got.columns) == list(STOCK_FEATURES)
    for t in range(0, n, 3):
        ref = _reference_row(df, t)
        for name in STOCK_FEATURES:
            if math.isnan(ref[name]):
                assert np.isnan(got.loc[t, name]), (name, t)
            else:
                assert got.loc[t, name] == pytest.approx(ref[name], rel=1e-8, abs=1e-10), (name, t)


@pytest.mark.unit
def test_warm_up_nan_pattern_equals_lookback() -> None:
    rng = np.random.default_rng(3)
    n = 300
    close = 40.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    mkt = np.r_[np.nan, rng.normal(0.0, 0.01, n - 1)]  # defined from the second row
    got = compute_stock_features(stock_frame(close, mkt_logret=mkt), STOCK_FEATURES)
    for name in STOCK_FEATURES:
        spec = get_spec(name)
        valid = got[name].notna().to_numpy()
        assert not valid[: spec.warmup].any(), name
        assert valid[spec.warmup :].all(), name  # first valid row == registry warm-up
    assert got["mom_12_1"].first_valid_index() == 252
    assert got["ret_252"].first_valid_index() == 252


@pytest.mark.unit
def test_features_are_computed_per_ticker_without_bleeding() -> None:
    a, b = _geometric(80), _geometric(80, growth=1.03)
    b["ticker"] = "BBB"
    both = pd.concat([a, b], ignore_index=True)
    got = compute_stock_features(both, ["ret_21", "px_sma_50", "vol_21"])
    solo_a = compute_stock_features(a, ["ret_21", "px_sma_50", "vol_21"])
    solo_b = compute_stock_features(b, ["ret_21", "px_sma_50", "vol_21"])
    pd.testing.assert_frame_equal(got.iloc[:80].reset_index(drop=True), solo_a)
    pd.testing.assert_frame_equal(got.iloc[80:].reset_index(drop=True), solo_b)
    assert got.iloc[80:101]["ret_21"].isna().sum() == 21  # B's warm-up restarts at its own row 0


@pytest.mark.unit
def test_zero_dollar_volume_never_creates_infinities() -> None:
    n = 200
    rng = np.random.default_rng(1)
    close = 30.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    dvol = rng.uniform(1e5, 1e6, n)
    dvol[60:70] = 0.0  # zero-volume days inside the amihud window
    f = compute_stock_features(stock_frame(close, dollar_volume=dvol), STOCK_FEATURES)
    assert np.isfinite(f["amihud_63"].dropna().to_numpy()).all()
    assert f["amihud_63"].iloc[100] == pytest.approx(
        _reference_row(stock_frame(close, dollar_volume=dvol), 100)["amihud_63"], rel=1e-9
    )  # mean over the positive-dollar-volume days only

    zero = compute_stock_features(stock_frame(close, dollar_volume=0.0), STOCK_FEATURES)
    assert zero["amihud_63"].isna().all()  # no positive day -> undefined, not inf
    assert zero["log_dvol_63"].isna().all() and zero["rel_dvol_21_63"].isna().all()  # not -inf
    assert not np.isinf(zero.to_numpy(dtype="float64")).any()


@pytest.mark.unit
def test_flat_prices_give_undefined_not_infinite_ratios() -> None:
    flat = stock_frame(np.full(150, 25.0), adj_high=np.full(150, 25.0), adj_low=np.full(150, 25.0))
    f = compute_stock_features(flat, STOCK_FEATURES)
    assert (f["vol_21"].dropna() == 0.0).all() and (f["vol_63"].dropna() == 0.0).all()
    assert f["vol_ratio_21_63"].isna().all()  # ln(0 / 0) -> NaN
    assert (f["parkinson_21"].dropna() == 0.0).all()
    assert f["dist_52w_high"].isna().all()  # 150 rows < the 252-day window
    assert not np.isinf(f.to_numpy(dtype="float64")).any()


@pytest.mark.unit
def test_beta_known_value_and_degenerate_market() -> None:
    rng = np.random.default_rng(11)
    n = 200
    mkt = np.r_[np.nan, rng.normal(0.0, 0.01, n - 1)]
    noise = rng.normal(0.0, 0.002, n)
    stock_ret = 1.5 * np.nan_to_num(mkt) + noise
    close = 100.0 * np.exp(np.cumsum(np.r_[0.0, stock_ret[1:]]))
    f = compute_stock_features(stock_frame(close, mkt_logret=mkt), ["beta_126"])
    assert f["beta_126"].iloc[199] == pytest.approx(1.5, abs=0.15)
    # a constant market return has no variance: beta undefined (NaN, never huge or infinite)
    const = np.r_[np.nan, np.full(n - 1, 0.001)]
    g = compute_stock_features(stock_frame(close, mkt_logret=const), ["beta_126"])
    assert g["beta_126"].isna().all()
    # a window with a missing market return is NaN
    holes = mkt.copy()
    holes[150] = np.nan
    h = compute_stock_features(stock_frame(close, mkt_logret=holes), ["beta_126"])
    assert h["beta_126"].iloc[150:].isna().all()
    assert h["beta_126"].iloc[149] == pytest.approx(f["beta_126"].iloc[149], rel=1e-12)


@pytest.mark.unit
def test_selection_dependencies_and_validation() -> None:
    df = _geometric(120)
    two = compute_stock_features(df, ["vol_ratio_21_63", "ret_5"])
    assert list(two.columns) == ["ret_5", "vol_ratio_21_63"]  # registry order, only requested
    with pytest.raises(FeatureError, match="not a stock-level"):
        compute_stock_features(df, ["mkt_ret_21"])
    with pytest.raises(FeatureError, match="Unknown feature"):
        compute_stock_features(df, ["rsi_14"])
    with pytest.raises(FeatureError, match="missing columns"):
        compute_stock_features(df.drop(columns=["adj_high"]), ["ret_5"])


@pytest.mark.unit
def test_safe_log() -> None:
    out = safe_log(np.array([1.0, math.e, 0.0, -1.0, np.inf, np.nan]))
    assert out[0] == 0.0 and out[1] == pytest.approx(1.0)
    assert np.isnan(out[2:]).all()
