"""L4 (feature poisoned-future) and the S5 part of L3 (adjusted-series scale invariance).

Every feature at decision date ``t`` may use data with date <= ``t`` only. The tests corrupt or
remove everything after ``t`` (prices, volume, returns and the universe) and require every one
of the 24 features, raw and model-input, and the market series to be identical at all dates
<= ``t``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.features.build import FeatureTables, build_features
from nasdaq100.features.registry import ALL_FEATURES
from tests.fixtures.s5_features import make_feature_panel

pytestmark = pytest.mark.leakage

CFG = load_config().features
CUTS = (120, 260)  # decision-date positions on the 330-day synthetic calendar
GARBAGE_COLS = ("adj_high", "adj_low", "adj_close", "adj_open", "dollar_volume")

_CACHE: dict[object, object] = {}


def _panel():
    if "panel" not in _CACHE:
        _CACHE["panel"] = make_feature_panel(n_tickers=30, n_days=330, seed=17)
    return _CACHE["panel"]


def _base() -> FeatureTables:
    if "base" not in _CACHE:
        adjusted, universe, _ = _panel()
        _CACHE["base"] = build_features(adjusted, universe, CFG)
    return _CACHE["base"]


def _poisoned(t: int) -> FeatureTables:
    """Build with every row after ``t`` replaced by garbage (also random future eligibility)."""
    key = ("poison", t)
    if key not in _CACHE:
        adjusted, universe, _ = _panel()
        rng = np.random.default_rng(t)
        adj, uni = adjusted.copy(), universe.copy()
        late = (adj["t_idx"] > t).to_numpy()
        for col in GARBAGE_COLS:
            adj.loc[late, col] = adj.loc[late, col].to_numpy() * rng.uniform(0.05, 25.0, late.sum())
        adj.loc[late, "logret_cc"] = rng.normal(0.0, 0.3, late.sum())
        adj.loc[late, "volume"] = 1
        uni.loc[late, "eligible"] = rng.random(late.sum()) < 0.5
        _CACHE[key] = build_features(adj, uni, CFG)
    return _CACHE[key]


def _truncated(t: int) -> FeatureTables:
    """Build from data that ends at ``t`` (the future simply does not exist)."""
    key = ("trunc", t)
    if key not in _CACHE:
        adjusted, universe, _ = _panel()
        keep = (adjusted["t_idx"] <= t).to_numpy()
        _CACHE[key] = build_features(
            adjusted[keep].reset_index(drop=True), universe[keep].reset_index(drop=True), CFG
        )
    return _CACHE[key]


def _upto(tab: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    return tab[tab["date"] <= cutoff].reset_index(drop=True)


def _cutoff(t: int) -> pd.Timestamp:
    return _panel()[2].date_at(t)


@pytest.mark.parametrize("t", CUTS)
@pytest.mark.parametrize("name", ALL_FEATURES)
def test_garbage_after_t_leaves_every_feature_at_or_before_t_unchanged(name: str, t: int) -> None:
    base, poisoned, cutoff = _base(), _poisoned(t), _cutoff(t)
    for kind in ("features_raw", "features_model"):
        a, b = _upto(getattr(base, kind), cutoff), _upto(getattr(poisoned, kind), cutoff)
        pd.testing.assert_series_equal(a[name], b[name], check_exact=True)
    # ... while the future really did change (the corruption was effective)
    later = base.features_raw["date"] > cutoff
    assert not base.features_raw.loc[later, name].equals(poisoned.features_raw.loc[later, name])


@pytest.mark.parametrize("t", CUTS)
def test_garbage_after_t_leaves_identifiers_and_market_series_unchanged(t: int) -> None:
    base, poisoned, cutoff = _base(), _poisoned(t), _cutoff(t)
    pd.testing.assert_frame_equal(_upto(base.market_series, cutoff),
                                  _upto(poisoned.market_series, cutoff), check_exact=True)
    for kind in ("features_raw", "features_model"):
        a, b = _upto(getattr(base, kind), cutoff), _upto(getattr(poisoned, kind), cutoff)
        pd.testing.assert_frame_equal(a, b, check_exact=True)  # all columns, ids included


@pytest.mark.parametrize("t", CUTS)
def test_data_ending_at_t_gives_identical_features_up_to_t(t: int) -> None:
    base, trunc, cutoff = _base(), _truncated(t), _cutoff(t)
    pd.testing.assert_frame_equal(_upto(base.features_raw, cutoff), trunc.features_raw,
                                  check_exact=True)
    pd.testing.assert_frame_equal(_upto(base.features_model, cutoff), trunc.features_model,
                                  check_exact=True)
    pd.testing.assert_frame_equal(_upto(base.market_series, cutoff), trunc.market_series,
                                  check_exact=True)


@pytest.mark.parametrize("j", [100, 200])
def test_a_price_change_never_moves_earlier_dates(j: int) -> None:
    """Changing one ticker's prices from day ``j`` on moves features only at dates >= ``j``."""
    adjusted, universe, _ = _panel()
    adj = adjusted.copy()
    m = ((adj["ticker"] == "T10") & (adj["t_idx"] >= j)).to_numpy()
    for col in ("adj_open", "adj_high", "adj_low", "adj_close"):
        adj.loc[m, col] = adj.loc[m, col] * 1.3
    adj.loc[(adj["ticker"] == "T10") & (adj["t_idx"] == j), "logret_cc"] += np.log(1.3)
    new, base, cutoff = build_features(adj, universe, CFG), _base(), _cutoff(j - 1)
    for kind in ("features_raw", "features_model"):
        pd.testing.assert_frame_equal(_upto(getattr(new, kind), cutoff),
                                      _upto(getattr(base, kind), cutoff), check_exact=True)
    assert not new.features_raw.equals(base.features_raw)


@pytest.mark.parametrize("c", [0.01, 37.5, 1234.5])
def test_scaling_a_tickers_adjusted_series_leaves_price_ratio_features_unchanged(c: float) -> None:
    """L3 (S5 part): the adjusted price level carries no information."""
    adjusted, universe, _ = _panel()
    base = _base()
    adj = adjusted.copy()
    m = (adj["ticker"] == "T04").to_numpy()
    for col in ("adj_open", "adj_high", "adj_low", "adj_close"):
        adj.loc[m, col] = adj.loc[m, col] * c  # logret_cc, dollar_volume, adj_factor untouched
    scaled = build_features(adj, universe, CFG)
    pd.testing.assert_frame_equal(scaled.features_raw, base.features_raw, rtol=1e-9, atol=1e-11)
    pd.testing.assert_frame_equal(scaled.features_model, base.features_model, rtol=0, atol=1e-9)
    pd.testing.assert_frame_equal(scaled.market_series, base.market_series)
