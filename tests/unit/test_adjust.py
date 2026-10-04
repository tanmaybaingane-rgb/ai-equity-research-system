"""Unit tests for S3: adjusted prices and close-to-close log returns (``data/adjust.py``)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data import adjust as adjust_mod
from nasdaq100.data.adjust import (
    ADJUSTED_COLUMNS,
    AdjustError,
    build_adjusted,
    load_adjusted,
    run_build_adjusted,
)
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.utils.io import write_parquet
from tests.fixtures.s2_silver import make_silver

DATES = pd.bdate_range("2020-01-06", periods=6)


def _rows(
    ticker: str,
    dates: pd.DatetimeIndex,
    close: list[float],
    adj_close: list[float],
    *,
    open_: list[float] | None = None,
    high: list[float] | None = None,
    low: list[float] | None = None,
    volume: list[int] | None = None,
) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": dates,
            "open": open_ if open_ is not None else close,
            "high": high if high is not None else [c + 1.0 for c in close],
            "low": low if low is not None else [c - 1.0 for c in close],
            "close": close,
            "adj_close": adj_close,
            "volume": np.asarray(volume if volume is not None else [1_000] * n, dtype="int64"),
        }
    )


def _cal(silver: pd.DataFrame) -> TradingCalendar:
    return TradingCalendar.from_dates(silver["date"])


def _cell(df: pd.DataFrame, ticker: str, date: str, col: str) -> float:
    row = df[(df["ticker"] == ticker) & (df["date"] == pd.Timestamp(date))]
    assert len(row) == 1
    return float(row[col].iloc[0])


@pytest.mark.unit
def test_factor_arithmetic_and_dollar_volume() -> None:
    silver = _rows(
        "AAA", DATES[:2], close=[100.0, 50.0], adj_close=[90.0, 50.0],
        open_=[99.0, 49.0], high=[102.0, 51.0], low=[98.0, 48.0], volume=[1_000, 2_000],
    )
    out = build_adjusted(silver, _cal(silver))
    first, last = out.iloc[0], out.iloc[1]
    assert first["adj_factor"] == pytest.approx(0.9)
    assert first["adj_open"] == pytest.approx(99.0 * 0.9)
    assert first["adj_high"] == pytest.approx(102.0 * 0.9)
    assert first["adj_low"] == pytest.approx(98.0 * 0.9)
    assert first["adj_close"] == 90.0  # carried unchanged, not recomputed
    assert first["dollar_volume"] == 100.0 * 1_000  # actual dollars: close * volume
    assert last["adj_factor"] == 1.0  # last date: adj_close == close
    assert (last["adj_open"], last["adj_high"], last["adj_low"]) == (49.0, 51.0, 48.0)
    assert last["dollar_volume"] == 50.0 * 2_000
    assert list(out["volume"]) == [1_000, 2_000]


@pytest.mark.unit
def test_output_schema_and_row_set() -> None:
    silver = make_silver(("AAA", "BBB", "CCC"), n_days=40, start_offsets={"CCC": 7})
    assert "flag_tick_noise" in silver.columns and "n_obs" in silver.columns
    out = build_adjusted(silver, _cal(silver))
    assert tuple(out.columns) == ADJUSTED_COLUMNS  # no flags, no n_obs, no raw close/open
    assert len(out) == len(silver)  # rows are never dropped
    assert out[["ticker", "date"]].equals(silver[["ticker", "date"]].reset_index(drop=True))
    assert out["date"].dtype == "datetime64[ns]"
    assert out["t_idx"].dtype == "int32"
    assert out["volume"].dtype == "int64"
    for col in ("adj_factor", "adj_open", "adj_high", "adj_low", "adj_close", "dollar_volume",
                "logret_cc"):
        assert out[col].dtype == "float64"


@pytest.mark.unit
def test_ohlc_ordering_preserved() -> None:
    silver = make_silver(("AAA", "BBB"), n_days=120)
    out = build_adjusted(silver, _cal(silver))
    assert (out["adj_low"] <= out["adj_open"]).all()
    assert (out["adj_low"] <= out["adj_close"]).all()
    assert (out["adj_open"] <= out["adj_high"]).all()
    assert (out["adj_close"] <= out["adj_high"]).all()


@pytest.mark.unit
def test_ordering_is_exact_when_float_rounding_would_break_it() -> None:
    # close * (adj_close / close) differs from adj_close by one ulp for these pairs: with
    # low == close (first) or high == close (second) the naive product breaks the ordering.
    silver = _rows(
        "AAA", DATES[:2], close=[10.11, 10.03], adj_close=[7.18, 7.12],
        open_=[10.2, 10.0], high=[10.3, 10.03], low=[10.11, 9.9],
    )
    assert 10.11 * (7.18 / 10.11) > 7.18 and 10.03 * (7.12 / 10.03) < 7.12  # premise
    out = build_adjusted(silver, _cal(silver))
    assert (out["adj_low"] <= out["adj_close"]).all()
    assert (out["adj_close"] <= out["adj_high"]).all()
    assert out["adj_close"].tolist() == [7.18, 7.12]  # vendor value carried bit for bit
    # the widening is at most one ulp: values still equal field * adj_factor to 1e-12
    np.testing.assert_allclose(out["adj_low"], silver["low"] * out["adj_factor"], rtol=1e-12)
    np.testing.assert_allclose(out["adj_high"], silver["high"] * out["adj_factor"], rtol=1e-12)


@pytest.mark.unit
def test_logret_cc_hand_computed_and_first_rows_nan() -> None:
    a = _rows("AAA", DATES[:3], close=[10.0, 10.0, 10.0], adj_close=[8.0, 8.4, 8.4])
    b = _rows("BBB", DATES[2:5], close=[20.0, 20.0, 20.0], adj_close=[18.0, 17.0, 17.0])
    silver = pd.concat([a, b], ignore_index=True)
    out = build_adjusted(silver, _cal(silver))
    assert _cell(out, "AAA", "2020-01-07", "logret_cc") == pytest.approx(np.log(8.4 / 8.0))
    assert _cell(out, "AAA", "2020-01-08", "logret_cc") == pytest.approx(0.0)
    assert _cell(out, "BBB", "2020-01-09", "logret_cc") == pytest.approx(np.log(17.0 / 18.0))
    first_rows = out.groupby("ticker").head(1).index
    assert out.loc[first_rows, "logret_cc"].isna().all()
    # BBB's first row must be NaN although AAA has a row on the previous position
    assert np.isnan(_cell(out, "BBB", "2020-01-08", "logret_cc"))
    assert out.drop(index=first_rows)["logret_cc"].notna().all()


@pytest.mark.unit
def test_t_idx_comes_from_the_calendar() -> None:
    a = _rows("AAA", DATES, close=[10.0] * 6, adj_close=[10.0] * 6)
    b = _rows("BBB", DATES[3:], close=[20.0] * 3, adj_close=[20.0] * 3)
    silver = pd.concat([a, b], ignore_index=True)
    out = build_adjusted(silver, _cal(silver))
    assert out.loc[out["ticker"] == "AAA", "t_idx"].tolist() == [0, 1, 2, 3, 4, 5]
    assert out.loc[out["ticker"] == "BBB", "t_idx"].tolist() == [3, 4, 5]
    # also accepts the calendar as a plain table
    assert build_adjusted(silver, _cal(silver).frame).equals(out)


@pytest.mark.unit
def test_special_dividend_has_small_adjusted_return_but_large_raw_return() -> None:
    # Ex-date: Close falls 40% (special dividend), Adj Close is smooth (cumulative factor).
    silver = _rows(
        "KDP", DATES[:3], close=[100.0, 100.0, 60.0], adj_close=[61.0, 61.0, 60.0],
    )
    out = build_adjusted(silver, _cal(silver))
    raw_ret = np.log(60.0 / 100.0)
    ex_ret = _cell(out, "KDP", "2020-01-08", "logret_cc")
    assert raw_ret < -0.5
    assert abs(ex_ret) < 0.02
    assert ex_ret == pytest.approx(np.log(60.0 / 61.0))
    assert _cell(out, "KDP", "2020-01-08", "adj_factor") == 1.0
    assert _cell(out, "KDP", "2020-01-07", "adj_factor") == pytest.approx(0.61)


@pytest.mark.unit
def test_input_is_not_modified_and_unsorted_input_is_sorted() -> None:
    silver = make_silver(("AAA", "BBB"), n_days=20)
    shuffled = silver.sample(frac=1.0, random_state=3).reset_index(drop=True)
    before = shuffled.copy()
    out = build_adjusted(shuffled, _cal(silver))
    pd.testing.assert_frame_equal(shuffled, before)
    pd.testing.assert_frame_equal(out, build_adjusted(silver, _cal(silver)))
    assert out.equals(out.sort_values(["ticker", "date"]).reset_index(drop=True))


@pytest.mark.unit
def test_internal_gap_raises() -> None:
    a = _rows("AAA", DATES, close=[10.0] * 6, adj_close=[10.0] * 6)
    b = _rows("BBB", DATES, close=[20.0] * 6, adj_close=[20.0] * 6)
    b = b.drop(index=b.index[3]).reset_index(drop=True)  # BBB misses one calendar date
    silver = pd.concat([a, b], ignore_index=True)
    with pytest.raises(AdjustError, match="consecutive"):
        build_adjusted(silver, _cal(silver))


@pytest.mark.unit
def test_date_missing_from_calendar_raises() -> None:
    silver = _rows("AAA", DATES[:4], close=[10.0] * 4, adj_close=[10.0] * 4)
    short_cal = TradingCalendar.from_dates(DATES[:3])
    with pytest.raises(AdjustError, match="not on the trading calendar"):
        build_adjusted(silver, short_cal)


@pytest.mark.unit
def test_invalid_inputs_raise() -> None:
    good = _rows("AAA", DATES[:3], close=[10.0] * 3, adj_close=[9.0] * 3)
    cal = _cal(good)

    with pytest.raises(AdjustError, match="missing columns"):
        build_adjusted(good.drop(columns=["adj_close"]), cal)
    with pytest.raises(AdjustError, match="empty"):
        build_adjusted(good.iloc[0:0], cal)

    nan = good.copy()
    nan.loc[1, "close"] = np.nan
    with pytest.raises(AdjustError, match="NaN"):
        build_adjusted(nan, cal)

    for col in ("close", "adj_close", "open"):
        bad = good.copy()
        bad.loc[1, col] = 0.0
        with pytest.raises(AdjustError, match="non-positive"):
            build_adjusted(bad, cal)

    dup = pd.concat([good, good.iloc[[0]]], ignore_index=True)
    with pytest.raises(AdjustError, match="duplicate"):
        build_adjusted(dup, cal)


@pytest.mark.unit
def test_run_build_adjusted_roundtrip_and_determinism(tmp_path) -> None:
    silver = make_silver(("AAA", "BBB", "CCC"), n_days=60, start_offsets={"CCC": 10})
    silver_file, cal_file = tmp_path / "silver.parquet", tmp_path / "calendar.parquet"
    write_parquet(silver, silver_file)
    write_parquet(_cal(silver).frame, cal_file, sort_keys=("date",))
    cfg = load_config()

    out_file = tmp_path / "out" / "adjusted_prices.parquet"
    built = run_build_adjusted(
        cfg, silver_file=silver_file, calendar_file=cal_file, adjusted_file=out_file
    )
    assert out_file.is_file()
    loaded = load_adjusted(cfg, out_file)
    pd.testing.assert_frame_equal(loaded, built)
    assert tuple(loaded.columns) == ADJUSTED_COLUMNS

    again = run_build_adjusted(
        cfg, silver_file=silver_file, calendar_file=cal_file, adjusted_file=out_file
    )
    pd.testing.assert_frame_equal(again, built)


@pytest.mark.unit
def test_run_build_adjusted_default_path_follows_variant(tmp_path, monkeypatch) -> None:
    silver = make_silver(("AAA",), n_days=30)
    silver_file, cal_file = tmp_path / "silver.parquet", tmp_path / "calendar.parquet"
    write_parquet(silver, silver_file)
    write_parquet(_cal(silver).frame, cal_file, sort_keys=("date",))
    seen: list[str] = []

    def fake_path(variant: str = "base"):
        seen.append(variant)
        return tmp_path / variant / "adjusted_prices.parquet"

    monkeypatch.setattr(adjust_mod, "adjusted_prices_path", fake_path)
    cfg = load_config(overrides=["project.variant=exp1"])
    run_build_adjusted(cfg, silver_file=silver_file, calendar_file=cal_file)
    assert seen == ["exp1"]
    assert (tmp_path / "exp1" / "adjusted_prices.parquet").is_file()
    assert len(load_adjusted(cfg)) == len(silver)


@pytest.mark.unit
def test_run_build_adjusted_missing_inputs(tmp_path) -> None:
    cfg = load_config()
    silver = make_silver(("AAA",), n_days=10)
    silver_file = tmp_path / "silver.parquet"
    write_parquet(silver, silver_file)
    with pytest.raises(FileNotFoundError, match="Silver"):
        run_build_adjusted(cfg, silver_file=tmp_path / "none.parquet",
                           calendar_file=tmp_path / "c.parquet")
    with pytest.raises(FileNotFoundError, match="Calendar"):
        run_build_adjusted(cfg, silver_file=silver_file, calendar_file=tmp_path / "c.parquet")


@pytest.mark.unit
def test_load_adjusted_errors(tmp_path) -> None:
    cfg = load_config()
    with pytest.raises(FileNotFoundError, match="build-adjusted"):
        load_adjusted(cfg, tmp_path / "missing.parquet")
    wrong = tmp_path / "wrong.parquet"
    write_parquet(pd.DataFrame({"ticker": ["A"], "date": [pd.Timestamp("2020-01-06")]}), wrong)
    with pytest.raises(AdjustError, match="columns"):
        load_adjusted(cfg, wrong)
