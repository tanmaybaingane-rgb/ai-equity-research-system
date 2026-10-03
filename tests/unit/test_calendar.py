"""Unit tests for the trading calendar helpers (Part II Sections II.1 and II.2)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.utils.calendar import TradingCalendar, build_calendar, rebalance_dates
from nasdaq100.utils.io import write_parquet


@pytest.fixture
def cal() -> TradingCalendar:
    return TradingCalendar.from_dates(pd.bdate_range("2020-01-01", periods=600))


@pytest.mark.unit
def test_build_calendar_schema_and_sorting() -> None:
    shuffled = ["2020-01-03", "2020-01-02", "2020-01-03", "2020-02-03", "2020-02-04"]
    out = build_calendar(shuffled)
    assert list(out.columns) == ["date", "t_idx", "year", "is_month_first_day"]
    assert str(out["date"].dtype) == "datetime64[ns]"
    assert str(out["t_idx"].dtype) == "int32"
    assert out["t_idx"].tolist() == [0, 1, 2, 3]
    assert out["date"].is_monotonic_increasing and out["date"].is_unique
    assert out["is_month_first_day"].tolist() == [True, False, True, False]
    assert out["is_month_first_day"].dtype == bool
    assert set(out["year"]) == {2020}


@pytest.mark.unit
def test_build_calendar_rejects_empty() -> None:
    with pytest.raises(ValueError, match="zero dates"):
        build_calendar([])


@pytest.mark.unit
def test_idx_of_and_date_at_roundtrip(cal: TradingCalendar) -> None:
    assert cal.idx_of("2020-01-01") == 0
    assert cal.date_at(0) == pd.Timestamp("2020-01-01")
    for i in (0, 1, 250, 599):
        assert cal.idx_of(cal.date_at(i)) == i
    assert cal.idx_of(pd.Timestamp("2020-01-02 15:30")) == 1  # normalised to midnight
    assert cal.last_idx == 599 and cal.n_days == 600 and len(cal) == 600


@pytest.mark.unit
def test_idx_of_rejects_non_trading_day_and_bad_index(cal: TradingCalendar) -> None:
    with pytest.raises(KeyError, match="not a trading date"):
        cal.idx_of("2020-01-04")  # Saturday
    with pytest.raises(IndexError):
        cal.date_at(-1)
    with pytest.raises(IndexError):
        cal.date_at(600)


@pytest.mark.unit
def test_offset_counts_trading_days_not_calendar_days(cal: TradingCalendar) -> None:
    # Friday 2020-01-03 + 1 trading day is Monday 2020-01-06 (3 calendar days)
    assert cal.offset("2020-01-03", 1) == pd.Timestamp("2020-01-06")
    assert cal.offset("2020-01-06", -1) == pd.Timestamp("2020-01-03")
    assert cal.offset("2020-01-03", 0) == pd.Timestamp("2020-01-03")
    with pytest.raises(IndexError):
        cal.offset(cal.date_at(cal.last_idx), 1)
    with pytest.raises(IndexError):
        cal.offset(cal.date_at(0), -1)  # never wraps to the end


@pytest.mark.unit
def test_rebalance_dates_follow_anchor_and_stride(cal: TradingCalendar) -> None:
    cfg = load_config()
    reb = rebalance_dates(cfg, cal)
    assert list(reb.columns) == ["date", "t_idx"]
    assert reb["t_idx"].iloc[0] == 252
    assert (reb["t_idx"] >= 252).all()
    assert ((reb["t_idx"] - 252) % 20 == 0).all()
    assert reb["t_idx"].diff().dropna().eq(20).all()
    assert reb["t_idx"].iloc[-1] <= cal.last_idx < reb["t_idx"].iloc[-1] + 20
    assert reb["date"].tolist() == [cal.date_at(i) for i in reb["t_idx"]]
    assert cal.rebalance_dates(cfg).equals(reb)  # method == function


@pytest.mark.unit
def test_rebalance_dates_use_config_overrides(cal: TradingCalendar) -> None:
    cfg = load_config(
        overrides=["backtest.rebalance_anchor_idx=100", "backtest.rebalance_every_days=50"]
    )
    reb = rebalance_dates(cfg, cal)
    assert reb["t_idx"].iloc[:3].tolist() == [100, 150, 200]


@pytest.mark.unit
def test_calendar_load_roundtrip_and_validation(tmp_path: Path, cal: TradingCalendar) -> None:
    path = tmp_path / "calendar.parquet"
    write_parquet(cal.frame, path, sort_keys=("date",))
    loaded = TradingCalendar.load(path)
    assert loaded.n_days == 600 and loaded.idx_of("2020-01-02") == 1

    broken = cal.frame
    broken.loc[5, "t_idx"] = 99
    with pytest.raises(ValueError, match="t_idx"):
        TradingCalendar(broken)
    with pytest.raises(ValueError, match="missing columns"):
        TradingCalendar(cal.frame.drop(columns=["year"]))
