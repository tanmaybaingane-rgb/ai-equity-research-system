"""S3 acceptance tests on the real frozen dataset (``needs_data``; auto-skipped if absent).

S1 runs once per session into a temp dir (``real_s1``); S3 builds into a temp dir too, so nothing
under ``data/`` is written. Expected numbers: Master Guide Part III S3.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.adjust import ADJUSTED_COLUMNS, load_adjusted, run_build_adjusted
from nasdaq100.data.security_master import read_silver
from nasdaq100.utils.hashing import sha256_file

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def s3(real_s1: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("s3_real")
    cfg = load_config()
    silver_before = sha256_file(real_s1["silver_file"])
    adjusted = run_build_adjusted(
        cfg,
        silver_file=real_s1["silver_file"],
        calendar_file=real_s1["tmp"] / "calendar.parquet",
        adjusted_file=tmp / "adjusted_prices.parquet",
    )
    return {
        "cfg": cfg,
        "adjusted": adjusted,
        "file": tmp / "adjusted_prices.parquet",
        "silver": read_silver(real_s1["silver_file"]),
        "silver_unchanged": sha256_file(real_s1["silver_file"]) == silver_before,
    }


def _ret(adjusted: pd.DataFrame, ticker: str, date: str) -> float:
    row = adjusted[(adjusted["ticker"] == ticker) & (adjusted["date"] == pd.Timestamp(date))]
    assert len(row) == 1
    return float(row["logret_cc"].iloc[0])


def test_shape_schema_and_roundtrip(s3: dict[str, Any]) -> None:
    adjusted, silver = s3["adjusted"], s3["silver"]
    assert tuple(adjusted.columns) == ADJUSTED_COLUMNS
    assert len(adjusted) == len(silver) == 514_075
    assert adjusted["ticker"].nunique() == 100
    assert adjusted[["ticker", "date"]].equals(silver[["ticker", "date"]])
    pd.testing.assert_frame_equal(load_adjusted(s3["cfg"], s3["file"]), adjusted)
    assert s3["silver_unchanged"]


def test_adj_factor_is_one_on_every_tickers_last_date(s3: dict[str, Any]) -> None:
    last = s3["adjusted"].groupby("ticker")["adj_factor"].last()
    assert len(last) == 100
    np.testing.assert_allclose(last.to_numpy(), 1.0, rtol=0, atol=1e-12)
    assert (s3["adjusted"]["adj_factor"] <= 1.0 + 1e-9).all()


def test_known_event_returns(s3: dict[str, Any]) -> None:
    adjusted = s3["adjusted"]
    assert _ret(adjusted, "KDP", "2018-07-10") == pytest.approx(0.109, abs=0.02)
    # AAPL 7:1 split-day: low-price rounding makes the adjusted return imprecise (+-0.06)
    assert _ret(adjusted, "AAPL", "2000-09-29") == pytest.approx(-0.73, abs=0.06)


def test_special_dividend_events_are_not_false_crashes(s3: dict[str, Any]) -> None:
    silver = s3["silver"]
    for ticker, date in (("BKR", "2017-07-05"), ("MDLZ", "2012-10-02"), ("KDP", "2018-07-10")):
        row = silver[(silver["ticker"] == ticker) & (silver["date"] == pd.Timestamp(date))]
        prev = silver[(silver["ticker"] == ticker) & (silver["date"] < pd.Timestamp(date))].iloc[-1]
        raw = float(np.log(row["close"].iloc[0] / prev["close"]))
        assert raw < -0.3  # the raw close return is a false crash ...
        assert _ret(s3["adjusted"], ticker, date) > -0.1  # ... the adjusted return is not


def test_nan_only_on_each_tickers_first_row(s3: dict[str, Any]) -> None:
    adjusted = s3["adjusted"]
    assert adjusted.drop(columns="logret_cc").notna().all().all()
    first = adjusted.groupby("ticker").head(1).index
    assert adjusted.loc[first, "logret_cc"].isna().all()
    assert len(first) == 100
    rest = adjusted.drop(index=first)["logret_cc"]
    assert rest.notna().all() and np.isfinite(rest.to_numpy()).all()


def test_t_idx_matches_calendar_and_is_consecutive(s3: dict[str, Any]) -> None:
    adjusted = s3["adjusted"]
    assert int(adjusted["t_idx"].min()) == 0 and int(adjusted["t_idx"].max()) == 6570
    steps = adjusted.groupby("ticker")["t_idx"].diff().dropna()
    assert (steps == 1).all()
    dates = adjusted.drop_duplicates("t_idx").sort_values("t_idx")["date"]
    assert dates.is_monotonic_increasing and len(dates) == 6_571


def test_price_relationships_and_dollar_volume(s3: dict[str, Any]) -> None:
    adjusted, silver = s3["adjusted"], s3["silver"]
    assert (adjusted["adj_low"] <= adjusted["adj_open"]).all()
    assert (adjusted["adj_low"] <= adjusted["adj_close"]).all()
    assert (adjusted["adj_open"] <= adjusted["adj_high"]).all()
    assert (adjusted["adj_close"] <= adjusted["adj_high"]).all()
    for col in ("open", "high", "low"):
        np.testing.assert_allclose(
            adjusted[f"adj_{col}"].to_numpy(),
            (silver[col] * adjusted["adj_factor"]).to_numpy(),
            rtol=1e-12,
        )
    np.testing.assert_array_equal(adjusted["adj_close"].to_numpy(), silver["adj_close"].to_numpy())
    np.testing.assert_allclose(
        adjusted["dollar_volume"].to_numpy(),
        (silver["close"] * silver["volume"]).to_numpy(dtype="float64"),
        rtol=1e-12,
    )


def test_rebuild_is_deterministic(s3: dict[str, Any], real_s1: dict[str, Any], tmp_path) -> None:
    again = run_build_adjusted(
        s3["cfg"],
        silver_file=real_s1["silver_file"],
        calendar_file=real_s1["tmp"] / "calendar.parquet",
        adjusted_file=tmp_path / "adjusted_prices.parquet",
    )
    pd.testing.assert_frame_equal(again, s3["adjusted"])
