"""S4 acceptance tests on the real frozen dataset (``needs_data``; auto-skipped if absent).

S1 runs once per session into a temp dir (``real_s1``); S2, S3 and S4 build into temp dirs too,
so nothing under ``data/`` is written. Expected numbers: Master Guide Part III S4.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.adjust import run_build_adjusted
from nasdaq100.data.security_master import read_silver, run_build_master
from nasdaq100.data.universe import run_build_universe
from nasdaq100.labels.forward_returns import (
    build_labels,
    label_columns,
    load_labels,
    run_build_labels,
)
from nasdaq100.paths import security_master_curated_path
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.utils.hashing import sha256_file

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def s4(real_s1: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("s4_real")
    cfg = load_config()
    silver_file, cal_file = real_s1["silver_file"], real_s1["tmp"] / "calendar.parquet"
    silver_before = sha256_file(silver_file)
    run_build_master(
        cfg,
        silver_file=silver_file,
        curated_file=security_master_curated_path(),
        master_file=tmp / "security_master.csv",
    )
    universe = run_build_universe(
        cfg,
        silver_file=silver_file,
        master_file=tmp / "security_master.csv",
        universe_file=tmp / "universe.parquet",
    )
    adjusted = run_build_adjusted(
        cfg, silver_file=silver_file, calendar_file=cal_file,
        adjusted_file=tmp / "adjusted_prices.parquet",
    )
    files = {
        "adjusted_file": tmp / "adjusted_prices.parquet",
        "universe_file": tmp / "universe.parquet",
        "calendar_file": cal_file,
        "labels_file": tmp / "labels.parquet",
    }
    labels = run_build_labels(cfg, **files)
    return {
        "cfg": cfg, "labels": labels, "universe": universe, "adjusted": adjusted,
        "silver": read_silver(silver_file), "files": files,
        "calendar": TradingCalendar.load(cal_file),
        "silver_unchanged": sha256_file(silver_file) == silver_before,
    }


def test_shape_schema_and_roundtrip(s4: dict[str, Any]) -> None:
    labels, universe = s4["labels"], s4["universe"]
    assert list(labels.columns) == label_columns([20])
    assert len(labels) == len(universe) == 514_075
    assert labels[["ticker", "date"]].equals(universe[["ticker", "date"]])
    pd.testing.assert_frame_equal(load_labels(s4["cfg"], s4["files"]["labels_file"]), labels)
    assert s4["silver_unchanged"]


def test_last_labelled_date_and_horizon_tail(s4: dict[str, Any]) -> None:
    labels, cal = s4["labels"], s4["calendar"]
    assert labels.loc[labels["has_label_h20"], "date"].max() == pd.Timestamp("2026-01-16")
    assert labels.loc[labels["excess_h20"].notna(), "date"].max() == pd.Timestamp("2026-01-16")
    assert cal.date_at(cal.last_idx - 21) == pd.Timestamp("2026-01-16")
    # exactly the last h+1 = 21 rows of every ticker lack a label
    assert int((~labels["has_label_h20"]).sum()) == 100 * 21
    tail = labels.groupby("ticker").tail(21)
    assert not tail["has_label_h20"].any()
    assert labels.drop(tail.index)["has_label_h20"].all()
    assert labels["label_exit_idx_h20"].notna().all()


def test_class_balance_and_excess_scale(s4: dict[str, Any]) -> None:
    cs = s4["labels"].dropna(subset=["excess_h20"])
    assert cs["y_cls_h20"].mean() == pytest.approx(0.501, abs=0.01)
    assert cs["excess_h20"].std() == pytest.approx(0.085, abs=0.005)
    assert set(cs["y_cls_h20"].unique()) == {0.0, 1.0}
    # training target: clipped, same units, slightly smaller spread; evaluation target: unclipped
    assert cs["y_reg_h20"].std() < cs["excess_h20"].std()
    assert (cs["y_reg_h20"].abs() <= cs["excess_h20"].abs() + 1e-15).all()


def test_cross_sectional_structure(s4: dict[str, Any]) -> None:
    labels, universe = s4["labels"], s4["universe"]
    elig = universe["eligible"].to_numpy()
    labelled = labels["has_label_h20"].to_numpy()
    has_cs = labels["excess_h20"].notna().to_numpy()
    assert (has_cs == (elig & labelled)).all()  # every eligible labelled row, nothing else
    for col in ("y_reg_h20", "y_cls_h20", "rank_pct_h20"):
        assert labels[col].notna().to_numpy().tolist() == has_cs.tolist()
    assert labels.loc[~elig, "excess_h20"].isna().all()
    cs = labels[has_cs]
    g = cs.groupby("date")
    np.testing.assert_allclose(g["excess_h20"].mean().to_numpy(), 0.0, atol=1e-12)
    assert g.size().min() >= 20
    assert (g["rank_pct_h20"].max() == 1.0).all()
    assert cs["date"].min() == pd.Timestamp("2001-01-02")  # t_idx 252: after the seasoning rule
    assert labels.loc[labels["date"] < pd.Timestamp("2001-01-02"), "excess_h20"].isna().all()
    # ret_fwd is available exactly where has_label is
    assert (labels["ret_fwd_h20"].notna().to_numpy() == labelled).all()
    assert np.isfinite(labels["ret_fwd_h20"].dropna().to_numpy()).all()


def test_labels_are_open_to_open_on_adjusted_prices(s4: dict[str, Any]) -> None:
    labels, adjusted = s4["labels"], s4["adjusted"]
    for ticker, date in (("AAPL", "2015-03-02"), ("MSFT", "2008-09-15"), ("KDP", "2018-07-02")):
        a = adjusted[adjusted["ticker"] == ticker].reset_index(drop=True)
        i = int(a.index[a["date"] == pd.Timestamp(date)][0])
        expected = np.log(a.loc[i + 21, "adj_open"] / a.loc[i + 1, "adj_open"])
        got = labels[(labels["ticker"] == ticker) & (labels["date"] == pd.Timestamp(date))]
        assert got["ret_fwd_h20"].iloc[0] == pytest.approx(expected, abs=1e-12)
        assert int(got["label_exit_idx_h20"].iloc[0]) == int(a.loc[i, "t_idx"]) + 21


def test_special_dividend_window_is_not_a_false_crash(s4: dict[str, Any]) -> None:
    """KDP's 2018-07-10 special dividend: raw opens fall > 80%, the label stays moderate."""
    labels, silver = s4["labels"], s4["silver"]
    k = silver[silver["ticker"] == "KDP"].reset_index(drop=True)
    j = int(k.index[k["date"] == pd.Timestamp("2018-07-10")][0])
    t = j - 5  # entry t+1 and exit t+21 straddle the ex-date
    raw = np.log(k.loc[t + 21, "open"] / k.loc[t + 1, "open"])
    row = labels[(labels["ticker"] == "KDP") & (labels["date"] == k.loc[t, "date"])].iloc[0]
    assert raw < -1.0
    assert row["ret_fwd_h20"] > -0.5


def test_real_data_poisoned_future(s4: dict[str, Any]) -> None:
    """Labels at dates whose exit day is <= 2015-06-30 do not need any later data."""
    cfg, files, cal = s4["cfg"], s4["files"], s4["calendar"]
    adjusted, universe, labels = s4["adjusted"], s4["universe"], s4["labels"]
    cut_idx = int(cal.idx_of("2015-06-30"))
    keep = (adjusted["t_idx"] <= cut_idx).to_numpy()
    cal_cut = TradingCalendar.from_dates(cal.dates[: cut_idx + 1])
    cut = build_labels(
        adjusted[keep].reset_index(drop=True),
        universe[keep].reset_index(drop=True),
        cfg.labels,
        cal_cut,
    )
    last_t = cut_idx - 21
    boundary = cal.date_at(last_t)
    pd.testing.assert_frame_equal(
        cut[cut["date"] <= boundary].reset_index(drop=True),
        labels[(labels["date"] <= boundary)].reset_index(drop=True),
    )
    assert not cut.loc[cut["date"] > boundary, "has_label_h20"].any()
    assert files["labels_file"].is_file()


def test_rebuild_is_deterministic(s4: dict[str, Any], tmp_path) -> None:
    again = run_build_labels(
        s4["cfg"], **{**s4["files"], "labels_file": tmp_path / "labels.parquet"}
    )
    pd.testing.assert_frame_equal(again, s4["labels"])
