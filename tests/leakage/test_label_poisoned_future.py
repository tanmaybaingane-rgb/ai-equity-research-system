"""L1: label poisoned-future tests (Part IV Section IV.5).

The label of ticker ``i`` at decision date ``t`` may read the adjusted open at ``t+1`` and at
``t+1+h`` and nothing later. The cross-sectional columns at ``t`` read the other names' forward
returns of the *same* date, which resolve no later than ``t+1+h`` either. These tests corrupt
the future in every way that matters and require identical labels at and before ``t``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.labels.forward_returns import build_labels
from nasdaq100.utils.calendar import TradingCalendar
from tests.fixtures.s4_labels import make_adjusted, make_universe

pytestmark = pytest.mark.leakage

N_TICKERS = 24  # above the default 20-name minimum, so the production default is exercised
N_DAYS = 90
PRICE_COLS = ("adj_factor", "adj_open", "adj_high", "adj_low", "adj_close", "dollar_volume")


def _cfg(h: int):
    return load_config(overrides=[f"labels.horizons=[{h}]", f"labels.primary_horizon={h}"]).labels


def _panel(seed: int = 12):
    tickers = [f"T{i:02d}" for i in range(N_TICKERS)]
    adjusted, cal = make_adjusted(
        tickers, N_DAYS, start_offsets={"T03": 10, "T04": 25}, end_offsets={"T05": 6}, seed=seed
    )
    universe = make_universe(adjusted, None, seed=seed + 1)
    # keep >= 20 eligible names on every date so cross-sectional labels exist everywhere
    universe.loc[universe["ticker"].isin(tickers[6:]), "eligible"] = True
    return adjusted, universe, cal


def _labels(adjusted, universe, cal, h):
    return build_labels(adjusted, universe, _cfg(h), cal)


def _upto(df: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    return df[df["date"] <= date].reset_index(drop=True)


def _poison_after(adjusted, universe, cal, idx: int, seed: int = 99):
    """Corrupt every adjusted row with t_idx > idx and every universe row with t_idx > t."""
    rng = np.random.default_rng(seed)
    adj = adjusted.copy()
    late = (adj["t_idx"] > idx).to_numpy()
    for col in PRICE_COLS:
        adj.loc[late, col] = adj.loc[late, col].to_numpy() * rng.uniform(0.05, 20.0, late.sum())
    adj.loc[late, "volume"] = 1
    return adj


@pytest.mark.parametrize("h", [1, 5, 20])
@pytest.mark.parametrize("t", [30, 55])
def test_data_after_exit_day_cannot_change_labels(h: int, t: int) -> None:
    adjusted, universe, cal = _panel()
    base = _labels(adjusted, universe, cal, h)
    exit_idx = t + 1 + h
    assert exit_idx < N_DAYS - 1  # there is data after the exit day to poison
    adj_p = _poison_after(adjusted, universe, cal, exit_idx)
    uni_p = universe.copy()
    rng = np.random.default_rng(5)
    late_u = (adjusted["t_idx"] > t).to_numpy()  # universe rows after the decision date
    uni_p.loc[late_u, "eligible"] = rng.random(late_u.sum()) < 0.5
    poisoned = _labels(adj_p, uni_p, cal, h)
    cutoff = cal.date_at(t)
    pd.testing.assert_frame_equal(_upto(poisoned, cutoff), _upto(base, cutoff))
    assert not poisoned.equals(base)  # the corruption was real: later dates do differ


@pytest.mark.parametrize("h", [1, 5, 20])
def test_labels_from_data_truncated_at_exit_day_are_identical(h: int) -> None:
    """Only data through t+1+h exists: labels at dates <= t equal the full-history labels."""
    adjusted, universe, cal = _panel()
    base = _labels(adjusted, universe, cal, h)
    t = 40
    horizon_end = t + 1 + h
    keep = (adjusted["t_idx"] <= horizon_end).to_numpy()
    cal_cut = TradingCalendar.from_dates(cal.dates[: horizon_end + 1])
    cut = _labels(adjusted[keep].reset_index(drop=True), universe[keep].reset_index(drop=True),
                  cal_cut, h)
    cutoff = cal.date_at(t)
    pd.testing.assert_frame_equal(_upto(cut, cutoff), _upto(base, cutoff))
    # on the truncated history the label of date t is still resolvable; t+1 is not
    on_t = cut[cut["date"] == cutoff]
    assert on_t.loc[on_t["ticker"] != "T05", f"has_label_h{h}"].all()
    assert not cut.loc[cut["date"] == cal.date_at(t + 1), f"has_label_h{h}"].any()


@pytest.mark.parametrize("h", [1, 5, 20])
def test_exit_day_open_changes_the_label_and_entry_is_t_plus_1(h: int) -> None:
    adjusted, universe, cal = _panel()
    base = _labels(adjusted, universe, cal, h)
    t, tk = 35, "T10"
    date_t = cal.date_at(t)
    assert universe[(universe["ticker"] == tk) & (universe["date"] == date_t)]["eligible"].all()

    def changed(idx: int, col: str = "adj_open") -> pd.DataFrame:
        adj = adjusted.copy()
        m = (adj["ticker"] == tk) & (adj["t_idx"] == idx)
        adj.loc[m, col] = adj.loc[m, col] * 1.5
        return _labels(adj, universe, cal, h)

    def row(df: pd.DataFrame, ticker: str = tk) -> pd.Series:
        return df[(df["ticker"] == ticker) & (df["date"] == date_t)].iloc[0]

    stem = f"h{h}"
    # data AT t+1+h changes the label (own return, own excess, and the peers' mean -> peers too)
    ex = changed(t + 1 + h)
    assert row(ex)[f"ret_fwd_{stem}"] != row(base)[f"ret_fwd_{stem}"]
    assert row(ex)[f"excess_{stem}"] != row(base)[f"excess_{stem}"]
    assert row(ex, "T11")[f"excess_{stem}"] != row(base, "T11")[f"excess_{stem}"]
    # data AT t+1 (the entry) changes it
    en = changed(t + 1)
    assert row(en)[f"ret_fwd_{stem}"] != row(base)[f"ret_fwd_{stem}"]
    # data at t (the decision-day open) and at t+2.. before the exit does not touch ret_fwd of t
    at_t = changed(t)
    assert row(at_t)[f"ret_fwd_{stem}"] == row(base)[f"ret_fwd_{stem}"]
    # the exit-day close / high / low / factor are irrelevant: labels are open-to-open (D4)
    for col in ("adj_close", "adj_high", "adj_low", "adj_factor", "dollar_volume"):
        pd.testing.assert_frame_equal(changed(t + 1 + h, col), base)
        pd.testing.assert_frame_equal(changed(t + 1, col), base)


@pytest.mark.parametrize("h", [1, 5, 20])
def test_single_price_change_has_an_exact_dependency_footprint(h: int) -> None:
    """Changing adj_open of one (ticker, day j) moves labels only on dates j-1 and j-1-h."""
    adjusted, universe, cal = _panel()
    base = _labels(adjusted, universe, cal, h)
    j, tk = 60, "T12"
    adj = adjusted.copy()
    m = (adj["ticker"] == tk) & (adj["t_idx"] == j)
    adj.loc[m, "adj_open"] = adj.loc[m, "adj_open"] * 1.7
    new = _labels(adj, universe, cal, h)
    diff = (new.drop(columns=["ticker", "date"]).to_numpy(dtype="float64")
            != base.drop(columns=["ticker", "date"]).to_numpy(dtype="float64"))
    nan_both = (new.drop(columns=["ticker", "date"]).isna().to_numpy()
                & base.drop(columns=["ticker", "date"]).isna().to_numpy())
    changed_rows = (diff & ~nan_both).any(axis=1)
    changed_dates = set(base.loc[changed_rows, "date"])
    assert changed_dates == {cal.date_at(j - 1), cal.date_at(j - 1 - h)}


@pytest.mark.parametrize("h", [1, 5, 20])
def test_cross_sectional_statistics_never_use_other_dates(h: int) -> None:
    """Scrambling the prices of every other date leaves a date's cross-section unchanged."""
    adjusted, universe, cal = _panel()
    base = _labels(adjusted, universe, cal, h)
    t = 45
    keep = {t + 1, t + 1 + h}  # the two opens the labels of date t actually read
    adj = adjusted.copy()
    other = ~adj["t_idx"].isin(keep)
    rng = np.random.default_rng(1)
    adj.loc[other, "adj_open"] = adj.loc[other, "adj_open"].to_numpy() * rng.uniform(
        0.2, 5.0, other.sum()
    )
    new = _labels(adj, universe, cal, h)
    d = cal.date_at(t)
    pd.testing.assert_frame_equal(
        new[new["date"] == d].reset_index(drop=True),
        base[base["date"] == d].reset_index(drop=True),
    )
