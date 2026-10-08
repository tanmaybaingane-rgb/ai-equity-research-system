"""Stage S5: stock-level raw features (18), computed per ticker from adjusted prices.

All features at date ``t`` use only rows of the same ticker with ``t_idx <= t`` (trailing
windows, never centred). Windows count trading *observations*; ``min_periods`` always equals the
window, so a feature is NaN unless its full window is available. Row shifts and rolling windows
are calendar shifts because the caller has asserted that ``t_idx`` is consecutive within every
ticker (S1 gap check).

Only adjusted series are read (decision D3): ``adj_close``, ``adj_high``, ``adj_low``,
``logret_cc`` and ``dollar_volume`` (``close * volume``, actual dollars). Prices enter only
through ratios, so multiplying a ticker's ``adj_*`` series by a constant changes no feature.

Non-finite values never leave this module: ``ln`` of a non-positive argument (an all-zero
dollar-volume window, a flat-price window with zero volatility) is NaN, not ``-inf``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

from nasdaq100.features.registry import STOCK_FEATURES, FeatureError, get_spec

TRADING_DAYS = 252
SQRT_252 = float(np.sqrt(TRADING_DAYS))
#: ``amihud_63`` scale (spec: ``ln(1 + 1e6 * mean(|logret| / dollar_volume))``).
AMIHUD_SCALE = 1.0e6
#: Relative floor of the market variance in ``beta_126``: below it the beta is undefined (NaN).
BETA_MIN_REL_VAR = 1.0e-9

REQUIRED_COLUMNS: tuple[str, ...] = (
    "ticker",
    "adj_high",
    "adj_low",
    "adj_close",
    "dollar_volume",
    "logret_cc",
    "mkt_logret",
)


def safe_log(x: pd.Series | np.ndarray) -> np.ndarray:
    """Natural log with NaN (never ``-inf``/``inf``) where ``x`` is not strictly positive."""
    arr = np.asarray(x, dtype="float64")
    out = np.full(arr.shape, np.nan)
    ok = np.isfinite(arr) & (arr > 0)
    out[ok] = np.log(arr[ok])
    return out


def _roll(df: pd.DataFrame, s: pd.Series, window: int, how: str) -> pd.Series:
    """Trailing per-ticker rolling statistic with ``min_periods == window`` (NaN-aware)."""
    res = getattr(
        s.groupby(df["ticker"], sort=False).rolling(window, min_periods=window), how
    )()
    return res.reset_index(level=0, drop=True).reindex(s.index)


def _shift(df: pd.DataFrame, col: str, k: int) -> pd.Series:
    return df.groupby("ticker", sort=False)[col].shift(k)


def _ret(df: pd.DataFrame, k: int) -> pd.Series:
    return pd.Series(safe_log(df["adj_close"] / _shift(df, "adj_close", k)), index=df.index)


def _mom_12_1(df: pd.DataFrame) -> pd.Series:
    ratio = _shift(df, "adj_close", 21) / _shift(df, "adj_close", 252)
    return pd.Series(safe_log(ratio), index=df.index)


def _vol(df: pd.DataFrame, w: int) -> pd.Series:
    return _roll(df, df["logret_cc"], w, "std") * SQRT_252


def _downvol_63(df: pd.DataFrame) -> pd.Series:
    neg_sq = np.minimum(df["logret_cc"], 0.0) ** 2  # NaN stays NaN
    return np.sqrt(_roll(df, neg_sq, 63, "mean")) * SQRT_252


def _parkinson_21(df: pd.DataFrame) -> pd.Series:
    hl = pd.Series(safe_log(df["adj_high"] / df["adj_low"]), index=df.index) ** 2
    return np.sqrt(_roll(df, hl, 21, "mean") / (4.0 * np.log(2.0))) * SQRT_252


def _beta_126(df: pd.DataFrame) -> pd.Series:
    """``cov(logret, mkt_logret) / var(mkt_logret)`` over 126 days (two-pass, exact).

    A window with any missing stock or market return is NaN. The market series includes the
    stock itself (accepted by the specification; see ``docs/data_dictionary.md``).
    """
    window = 126
    out = np.full(len(df), np.nan)
    x_all = df["logret_cc"].to_numpy(dtype="float64")
    m_all = df["mkt_logret"].to_numpy(dtype="float64")
    for idx in df.groupby("ticker", sort=False).indices.values():
        if len(idx) < window:
            continue
        x = np.lib.stride_tricks.sliding_window_view(x_all[idx], window)
        m = np.lib.stride_tricks.sliding_window_view(m_all[idx], window)
        full = np.isfinite(x).all(axis=1) & np.isfinite(m).all(axis=1)
        xc = x - x.mean(axis=1, keepdims=True)
        mc = m - m.mean(axis=1, keepdims=True)
        cov = (xc * mc).sum(axis=1) / (window - 1)
        var = (mc * mc).sum(axis=1) / (window - 1)
        scale = (m * m).mean(axis=1)
        ok = full & (var > BETA_MIN_REL_VAR * scale)
        beta = np.full(len(x), np.nan)
        beta[ok] = cov[ok] / var[ok]
        out[idx[window - 1 :]] = beta
    return pd.Series(out, index=df.index)


def _px_sma(df: pd.DataFrame, w: int) -> pd.Series:
    return pd.Series(
        safe_log(df["adj_close"] / _roll(df, df["adj_close"], w, "mean")), index=df.index
    )


def _dist_52w_high(df: pd.DataFrame) -> pd.Series:
    return pd.Series(
        safe_log(df["adj_close"] / _roll(df, df["adj_close"], TRADING_DAYS, "max")),
        index=df.index,
    )


def _log_dvol_63(df: pd.DataFrame) -> pd.Series:
    return pd.Series(safe_log(_roll(df, df["dollar_volume"], 63, "mean")), index=df.index)


def _rel_dvol_21_63(df: pd.DataFrame) -> pd.Series:
    m21 = _roll(df, df["dollar_volume"], 21, "mean")
    m63 = _roll(df, df["dollar_volume"], 63, "mean")
    ok = (m21 > 0) & (m63 > 0)
    return pd.Series(safe_log((m21 / m63).where(ok)), index=df.index)


def _amihud_63(df: pd.DataFrame) -> pd.Series:
    """``ln(1 + 1e6 * mean(|logret| / dollar_volume))`` over 63 days with ``dollar_volume > 0``.

    The window must be complete (63 observed returns); only its days with positive dollar volume
    enter the mean. A window without any such day is NaN. Never infinite.
    """
    ret = df["logret_cc"]
    dvol = df["dollar_volume"]
    valid = (dvol > 0) & ret.notna()
    ratio = (ret.abs() / dvol.where(dvol > 0)).where(valid, 0.0)
    n_ret = _roll(df, ret.notna().astype("float64"), 63, "sum")
    n_valid = _roll(df, valid.astype("float64"), 63, "sum")
    total = _roll(df, ratio, 63, "sum")
    mean = (total / n_valid.where(n_valid > 0)).where(n_ret == 63)
    return pd.Series(np.log1p(AMIHUD_SCALE * mean.to_numpy(dtype="float64")), index=df.index)


def compute_stock_features(df: pd.DataFrame, names: Iterable[str]) -> pd.DataFrame:
    """Raw stock-level features ``names`` for every row of ``df`` (columns in registry order).

    ``df`` must be sorted by (ticker, date) with a default RangeIndex, have consecutive
    ``t_idx`` within each ticker (not checked here; ``build_features`` asserts it) and the
    columns in ``REQUIRED_COLUMNS`` (``mkt_logret`` is the date-level market return mapped to
    the rows, NaN where undefined). Features that depend on other features reuse them.
    """
    wanted = list(dict.fromkeys(names))
    for n in wanted:
        if get_spec(n).level != "stock":
            raise FeatureError(f"{n!r} is not a stock-level feature")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise FeatureError(f"Feature input is missing columns: {missing}")

    cache: dict[str, pd.Series] = {}
    builders: dict[str, Callable[[], pd.Series]] = {
        "ret_5": lambda: _ret(df, 5),
        "ret_21": lambda: _ret(df, 21),
        "ret_63": lambda: _ret(df, 63),
        "ret_126": lambda: _ret(df, 126),
        "ret_252": lambda: _ret(df, 252),
        "mom_12_1": lambda: _mom_12_1(df),
        "vol_21": lambda: _vol(df, 21),
        "vol_63": lambda: _vol(df, 63),
        "downvol_63": lambda: _downvol_63(df),
        "vol_ratio_21_63": lambda: _vol_ratio(get("vol_21"), get("vol_63")),
        "parkinson_21": lambda: _parkinson_21(df),
        "beta_126": lambda: _beta_126(df),
        "px_sma_50": lambda: _px_sma(df, 50),
        "px_sma_200": lambda: _px_sma(df, 200),
        "dist_52w_high": lambda: _dist_52w_high(df),
        "log_dvol_63": lambda: _log_dvol_63(df),
        "rel_dvol_21_63": lambda: _rel_dvol_21_63(df),
        "amihud_63": lambda: _amihud_63(df),
    }
    assert tuple(builders) == STOCK_FEATURES  # registry and implementation stay in lockstep

    def get(name: str) -> pd.Series:
        if name not in cache:
            cache[name] = builders[name]().astype("float64")
        return cache[name]

    out = pd.DataFrame({n: get(n) for n in STOCK_FEATURES if n in set(wanted)}, index=df.index)
    return out.replace([np.inf, -np.inf], np.nan)


def _vol_ratio(vol_21: pd.Series, vol_63: pd.Series) -> pd.Series:
    ok = (vol_21 > 0) & (vol_63 > 0)
    return pd.Series(safe_log((vol_21 / vol_63).where(ok)), index=vol_21.index)
