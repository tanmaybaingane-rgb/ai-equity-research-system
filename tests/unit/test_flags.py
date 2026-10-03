"""Unit tests for silver-layer data-quality flags (Stage S1)."""

from __future__ import annotations

import pandas as pd
import pytest

from nasdaq100.config import FlagsConfig
from nasdaq100.data.flags import (
    FLAG_COLUMNS,
    SILVER_COLUMNS,
    add_flags,
    corp_action_events,
)
from tests.fixtures.s1_prices import make_clean_raw_prices, to_bronze

CFG = FlagsConfig()


def _clean() -> pd.DataFrame:
    return to_bronze(make_clean_raw_prices(("AAA", "BBB"), n_days=20, start_offsets={"BBB": 5}))


def _row(df: pd.DataFrame, ticker: str, k: int) -> int:
    """Index of the k-th (0-based) row of a ticker."""
    return int(df.index[df["ticker"] == ticker][k])


@pytest.mark.unit
def test_clean_rows_trigger_no_flag_and_nothing_is_dropped() -> None:
    bronze = _clean()
    silver = add_flags(bronze, CFG)
    assert len(silver) == len(bronze)  # flags never remove rows
    assert tuple(silver.columns) == SILVER_COLUMNS
    assert not silver[list(FLAG_COLUMNS)].to_numpy().any()
    assert all(silver[c].dtype == bool for c in FLAG_COLUMNS)
    assert str(silver["n_obs"].dtype) == "int32"


@pytest.mark.unit
def test_n_obs_counts_own_observations_from_one() -> None:
    silver = add_flags(_clean(), CFG)
    aaa = silver[silver["ticker"] == "AAA"]["n_obs"].tolist()
    bbb = silver[silver["ticker"] == "BBB"]["n_obs"].tolist()
    assert aaa == list(range(1, 21))
    assert bbb == list(range(1, 16))  # listed 5 days later: starts again at 1


@pytest.mark.unit
def test_flag_tick_noise_threshold_is_strict_less_than() -> None:
    df = _clean()
    df.loc[_row(df, "AAA", 3), "close"] = 4.99
    df.loc[_row(df, "AAA", 4), "close"] = 5.0
    out = add_flags(df, CFG)
    assert out.loc[_row(df, "AAA", 3), "flag_tick_noise"]
    assert not out.loc[_row(df, "AAA", 4), "flag_tick_noise"]
    assert out["flag_tick_noise"].sum() == 1


@pytest.mark.unit
def test_flag_zero_volume() -> None:
    df = _clean()
    df.loc[_row(df, "BBB", 2), "volume"] = 0
    out = add_flags(df, CFG)
    assert out["flag_zero_volume"].sum() == 1
    assert out.loc[_row(df, "BBB", 2), "flag_zero_volume"]


@pytest.mark.unit
def test_flag_flat_bar_needs_all_four_prices_equal() -> None:
    df = _clean()
    i = _row(df, "AAA", 6)
    df.loc[i, ["open", "high", "low", "close"]] = 20.0
    j = _row(df, "AAA", 7)
    df.loc[j, ["open", "high", "low", "close"]] = [20.0, 20.0, 20.0, 20.01]  # not flat
    out = add_flags(df, CFG)
    assert out.loc[i, "flag_flat_bar"] and not out.loc[j, "flag_flat_bar"]
    assert out["flag_flat_bar"].sum() == 1


@pytest.mark.unit
def test_flag_extreme_move_uses_adj_close_and_skips_first_observation() -> None:
    df = _clean()
    i = _row(df, "AAA", 10)
    df.loc[i, "adj_close"] = df.loc[i - 1, "adj_close"] * 1.6  # ln(1.6) = 0.47 > 0.40
    out = add_flags(df, CFG)
    assert out.loc[i, "flag_extreme_move"]
    assert out.loc[i + 1, "flag_extreme_move"]  # the reversal the next day is also > 40%
    assert out["flag_extreme_move"].sum() == 2

    # An absurd first price cannot flag the first observation (no previous row) ...
    df2 = _clean()
    first = _row(df2, "AAA", 0)
    df2.loc[first, "adj_close"] = 1000.0
    out2 = add_flags(df2, CFG)
    assert not out2.loc[first, "flag_extreme_move"]
    # ... but it does flag the move away from it on the second observation.
    assert out2.loc[first + 1, "flag_extreme_move"]


@pytest.mark.unit
def test_flag_corp_action_fires_on_close_drop_without_adj_drop() -> None:
    df = _clean()
    i = _row(df, "AAA", 8)
    # special dividend: close falls 30% but adj_close is smooth -> large gap between returns
    df.loc[i:, "close"] = df.loc[i:, "close"] * 0.70
    out = add_flags(df, CFG)
    assert out.loc[i, "flag_corp_action_suspect"]
    assert out["flag_corp_action_suspect"].sum() == 1  # only the event day, not the days after
    ev = corp_action_events(out)
    assert len(ev) == 1 and ev.loc[0, "ticker"] == "AAA" and ev.loc[0, "gap"] > 0.3


@pytest.mark.unit
def test_corp_action_guard_ignores_low_previous_close_rounding() -> None:
    df = _clean()
    i = _row(df, "AAA", 8)
    df.loc[i - 1, "close"] = 4.0  # previous close below the 5.0 guard
    df.loc[i, "close"] = 2.8  # same 30% drop, but guarded (price-rounding territory)
    out = add_flags(df, CFG)
    assert not out.loc[i, "flag_corp_action_suspect"]


@pytest.mark.unit
def test_first_observation_and_ticker_boundaries_do_not_leak_across_tickers() -> None:
    df = _clean()
    out = add_flags(df, CFG)
    for tk in ("AAA", "BBB"):
        first = _row(df, tk, 0)
        assert not out.loc[first, ["flag_extreme_move", "flag_corp_action_suspect"]].any()
    # BBB's first close (~60) differs from AAA's last close (~50): must not be compared
    assert out["flag_corp_action_suspect"].sum() == 0


@pytest.mark.unit
def test_thresholds_come_from_config() -> None:
    df = _clean()
    i = _row(df, "AAA", 10)
    df.loc[i, "adj_close"] = df.loc[i - 1, "adj_close"] * 1.2  # ln=0.18
    assert not add_flags(df, CFG).loc[i, "flag_extreme_move"]
    strict = FlagsConfig(extreme_move_abs_ret=0.10)
    assert add_flags(df, strict).loc[i, "flag_extreme_move"]


@pytest.mark.unit
def test_add_flags_requires_bronze_columns() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        add_flags(_clean().drop(columns=["volume"]), CFG)
