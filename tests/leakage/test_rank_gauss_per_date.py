"""L5: rank-gauss per date only (Part IV Section IV.5).

Normalisation statistics (winsor quantiles, ranks, counts) never use other dates and never use
ineligible names.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.features.build import build_features
from nasdaq100.features.normalize import rank_gauss_per_date
from nasdaq100.features.registry import ALL_FEATURES, STOCK_FEATURES
from tests.fixtures.s5_features import make_feature_panel

pytestmark = pytest.mark.leakage

DATES = pd.bdate_range("2020-01-06", periods=6).astype("datetime64[ns]")


def _raw(seed: int = 1, per_date: int = 80):
    rng = np.random.default_rng(seed)
    n = per_date * len(DATES)
    raw = pd.DataFrame({"a": rng.standard_t(4, n), "b": rng.uniform(0, 1, n)})
    raw.loc[rng.random(n) < 0.05, "b"] = np.nan
    dates = np.repeat(DATES.to_numpy(), per_date)
    elig = rng.random(n) < 0.8
    return raw, dates, elig


@pytest.mark.parametrize("target", range(len(DATES)))
def test_other_dates_cannot_change_a_dates_scores(target: int) -> None:
    raw, dates, elig = _raw()
    base = rank_gauss_per_date(raw, dates, elig, [0.01, 0.99])
    other = dates != DATES[target].to_datetime64()
    rng = np.random.default_rng(5)
    scrambled = raw.copy()
    scrambled.loc[other, "a"] = rng.normal(0, 1e6, other.sum())  # destroy every other date
    scrambled.loc[other, "b"] = np.nan
    new = rank_gauss_per_date(scrambled, dates, elig, [0.01, 0.99])
    pd.testing.assert_frame_equal(new[~other], base[~other], check_exact=True)


def test_ineligible_names_cannot_change_anyones_scores() -> None:
    raw, dates, elig = _raw(seed=2)
    base = rank_gauss_per_date(raw, dates, elig, [0.01, 0.99])
    poisoned = raw.copy()
    rng = np.random.default_rng(8)
    poisoned.loc[~elig, "a"] = rng.normal(0, 1e9, (~elig).sum())  # extreme outliers
    poisoned.loc[~elig, "b"] = rng.uniform(-1e9, 1e9, (~elig).sum())
    new = rank_gauss_per_date(poisoned, dates, elig, [0.01, 0.99])
    pd.testing.assert_frame_equal(new[elig], base[elig], check_exact=True)
    assert new[~elig].isna().all().all()  # and they receive no score themselves


def test_a_never_eligible_ticker_cannot_move_any_other_tickers_features() -> None:
    """Pipeline level: market series, ranks, quantiles and betas only ever see eligible names."""
    adjusted, universe, _ = make_feature_panel(n_tickers=24, n_days=330, seed=29, drop_frac=0.0)
    universe.loc[universe["ticker"] == "T09", "eligible"] = False
    cfg = load_config().features
    base = build_features(adjusted, universe, cfg)
    adj = adjusted.copy()
    m = (adj["ticker"] == "T09").to_numpy()
    rng = np.random.default_rng(3)
    for col in ("adj_open", "adj_high", "adj_low", "adj_close", "dollar_volume"):
        adj.loc[m, col] = adj.loc[m, col].to_numpy() * rng.uniform(0.01, 100.0, m.sum())
    adj.loc[m, "logret_cc"] = rng.normal(0.0, 0.5, m.sum())
    new = build_features(adj, universe, cfg)
    keep = (base.features_raw["ticker"] != "T09").to_numpy()
    cols = ["ticker", "date", "eligible", *ALL_FEATURES]
    pd.testing.assert_frame_equal(new.features_raw.loc[keep, cols],
                                  base.features_raw.loc[keep, cols], check_exact=True)
    pd.testing.assert_frame_equal(new.features_model.loc[keep, cols],
                                  base.features_model.loc[keep, cols], check_exact=True)
    pd.testing.assert_frame_equal(new.market_series, base.market_series, check_exact=True)
    t09 = new.features_model[~keep]
    assert t09[list(STOCK_FEATURES)].isna().all().all()
