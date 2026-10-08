"""S5 acceptance tests on the real frozen dataset (``needs_data``; auto-skipped if absent).

S1 runs once per session into a temp dir (``real_s1``); S2, S3, S4 and S5 build into temp dirs
too, so nothing under ``data/`` is written. Includes Milestone M1: universe, labels and features
join on (ticker, date) without key mismatches.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.adjust import run_build_adjusted
from nasdaq100.data.security_master import run_build_master
from nasdaq100.data.universe import run_build_universe
from nasdaq100.features.build import (
    build_features,
    load_features_model,
    load_features_raw,
    load_market_series,
    run_build_features,
)
from nasdaq100.features.registry import ALL_FEATURES, MARKET_FEATURES, STOCK_FEATURES, get_spec
from nasdaq100.labels.forward_returns import run_build_labels
from nasdaq100.paths import security_master_curated_path
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.utils.hashing import sha256_file

pytestmark = pytest.mark.needs_data
ID = ["ticker", "date", "eligible"]


@pytest.fixture(scope="module")
def s5(real_s1: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("s5_real")
    cfg = load_config()
    silver_file, cal_file = real_s1["silver_file"], real_s1["tmp"] / "calendar.parquet"
    silver_before = sha256_file(silver_file)
    run_build_master(cfg, silver_file=silver_file, curated_file=security_master_curated_path(),
                     master_file=tmp / "security_master.csv")
    universe = run_build_universe(cfg, silver_file=silver_file,
                                  master_file=tmp / "security_master.csv",
                                  universe_file=tmp / "universe.parquet")
    adjusted = run_build_adjusted(cfg, silver_file=silver_file, calendar_file=cal_file,
                                  adjusted_file=tmp / "adjusted_prices.parquet")
    labels = run_build_labels(cfg, adjusted_file=tmp / "adjusted_prices.parquet",
                              universe_file=tmp / "universe.parquet", calendar_file=cal_file,
                              labels_file=tmp / "labels.parquet")
    files = {"adjusted_file": tmp / "adjusted_prices.parquet",
             "universe_file": tmp / "universe.parquet", "market_file": tmp / "market.parquet",
             "raw_file": tmp / "features_raw.parquet", "model_file": tmp / "features_model.parquet"}
    tables = run_build_features(cfg, **files)
    return {"cfg": cfg, "t": tables, "files": files, "adjusted": adjusted, "universe": universe,
            "labels": labels, "calendar": TradingCalendar.load(cal_file),
            "silver_unchanged": sha256_file(silver_file) == silver_before}


def test_shape_schema_roundtrip_and_no_infinities(s5: dict[str, Any]) -> None:
    t, cfg, f = s5["t"], s5["cfg"], s5["files"]
    assert len(ALL_FEATURES) == 24  # the feature matrix has 24 columns
    for tab in (t.features_raw, t.features_model):
        assert list(tab.columns) == ID + list(ALL_FEATURES)
        assert len(tab) == len(s5["universe"]) == 514_075
        assert not np.isinf(tab[list(ALL_FEATURES)].to_numpy()).any()
    assert len(t.market_series) == 6_571
    pd.testing.assert_frame_equal(load_features_raw(cfg, f["raw_file"]), t.features_raw)
    pd.testing.assert_frame_equal(load_features_model(cfg, f["model_file"]), t.features_model)
    pd.testing.assert_frame_equal(load_market_series(cfg, f["market_file"]), t.market_series)
    assert s5["silver_unchanged"]


def test_milestone_m1_universe_labels_features_join_without_key_mismatch(s5) -> None:
    u, lab, t = s5["universe"], s5["labels"], s5["t"]
    for tab in (lab, t.features_raw, t.features_model):
        assert tab[["ticker", "date"]].equals(u[["ticker", "date"]])
    joined = u[["ticker", "date", "eligible"]].merge(
        lab[["ticker", "date", "excess_h20"]], on=["ticker", "date"], validate="1:1"
    ).merge(t.features_model, on=["ticker", "date", "eligible"], validate="1:1")
    assert len(joined) == len(u)
    labelled = joined[joined["eligible"] & joined["excess_h20"].notna()]
    assert len(labelled) == 434_695  # the S4 panel of eligible, labelled rows
    assert labelled[[c for c in STOCK_FEATURES if c != "beta_126"]].notna().all().all()


def test_first_valid_date_and_warm_up_on_real_data(s5) -> None:
    raw, cal = s5["t"].features_raw, s5["calendar"]
    t_idx = raw["date"].map(pd.Series(np.arange(cal.n_days), index=cal.dates))
    no_beta = [c for c in STOCK_FEATURES if c != "beta_126"]
    elig = raw[raw["eligible"]]
    assert elig["date"].min() == pd.Timestamp("2001-01-02")  # t_idx 252
    assert elig[no_beta].notna().all().all()  # every eligible row is fully featured
    # all-24 first valid date among the stock-level features is the first eligible date
    full = raw[raw[no_beta].notna().all(axis=1) & raw["eligible"]]
    assert full["date"].min() == pd.Timestamp("2001-01-02")
    assert int(t_idx[raw["mom_12_1"].notna()].min()) == 252
    assert int(t_idx[raw["ret_252"].notna()].min()) == 252
    for name in STOCK_FEATURES:
        if name != "beta_126":  # beta also waits for the market series
            assert int(t_idx[raw[name].notna()].min()) == get_spec(name).warmup, name
    # beta_126 and the windowed market features wait for the market series (first defined
    # on the date after the first eligible date)
    first = {n: raw.loc[raw[n].notna(), "date"].min().date().isoformat() for n in
             ("beta_126", "mkt_ret_21", "mkt_ret_63", "mkt_vol_21", "mkt_trend_200",
              "mkt_breadth_50", "xs_disp_21")}
    assert first == {"beta_126": "2001-07-03", "mkt_ret_21": "2001-02-01",
                     "mkt_ret_63": "2001-04-03", "mkt_vol_21": "2001-02-01",
                     "mkt_trend_200": "2001-10-23", "mkt_breadth_50": "2001-01-02",
                     "xs_disp_21": "2001-01-02"}


def test_market_series_on_real_data(s5) -> None:
    ms = s5["t"].market_series.reset_index(drop=True)
    assert ms["mkt_logret"].iloc[:253].isna().all() and ms["mkt_logret"].iloc[253:].notna().all()
    assert ms["n_eligible"].iloc[:252].eq(0).all() and ms["n_eligible"].iloc[252] == 42
    assert int(ms["n_eligible"].max()) == 98
    assert ms["mkt_index"].iloc[253] == pytest.approx(math.exp(ms["mkt_logret"].iloc[253]))
    assert ms["mkt_index"].iloc[-1] == pytest.approx(
        math.exp(ms["mkt_logret"].sum()), rel=1e-9
    )
    # composition check on one date: mean of logret over the names eligible the day before
    adj, uni, d = s5["adjusted"], s5["universe"], ms["date"].iloc[1000]
    prev = adj.loc[adj["date"] == ms["date"].iloc[999], "ticker"][
        uni.loc[uni["date"] == ms["date"].iloc[999], "eligible"].to_numpy()
    ]
    today = adj[(adj["date"] == d) & adj["ticker"].isin(prev)]
    assert ms["mkt_logret"].iloc[1000] == pytest.approx(today["logret_cc"].mean(), rel=1e-12)


def test_market_features_identical_across_tickers(s5) -> None:
    for tab in (s5["t"].features_raw, s5["t"].features_model):
        sample = tab[tab["date"].isin(tab["date"].drop_duplicates().iloc[::97])]
        for name in MARKET_FEATURES:
            assert (sample.groupby("date")[name].nunique(dropna=False) == 1).all(), name


def test_model_features_are_per_date_rank_gauss_among_eligible(s5) -> None:
    model = s5["t"].features_model
    stock = list(STOCK_FEATURES)
    assert model.loc[~model["eligible"], stock].isna().all().all()
    e = model[model["eligible"]]
    g = e.groupby("date")[stock]
    mean, std = g.mean(), g.std()
    ties = ["dist_52w_high"]  # exact ties at 0 (names at their 52-week high) shrink the spread
    ok = [c for c in stock if c not in ties and c != "beta_126"]
    assert mean[ok].abs().max().max() < 0.01 and (std[ok] - 1.0).abs().max().max() < 0.01
    assert mean["dist_52w_high"].abs().max() < 0.1 and std["dist_52w_high"].min() > 0.8
    assert (std["dist_52w_high"] < 1.1).all()
    # beta_126 only exists from 2001-07-03; afterwards it is normalised like the others
    beta = e.loc[e["date"] >= pd.Timestamp("2001-07-03")].groupby("date")["beta_126"]
    assert beta.mean().abs().max() < 0.01 and (beta.std() - 1.0).abs().max() < 0.01
    # monotone with raw on a sample date
    raw = s5["t"].features_raw
    d = pd.Timestamp("2015-06-30")
    day = raw[(raw["date"] == d) & raw["eligible"]]
    for name in stock:
        order = np.argsort(day[name].to_numpy())
        assert (np.diff(model.loc[day.index, name].to_numpy()[order]) >= -1e-12).all()


def test_spot_check_against_independent_computation(s5) -> None:
    adj, raw = s5["adjusted"], s5["t"].features_raw
    a = adj[adj["ticker"] == "AAPL"].reset_index(drop=True)
    r = raw[raw["ticker"] == "AAPL"].reset_index(drop=True)
    for i in (300, 2500, 6000):
        c, lr, dv = a["adj_close"].to_numpy(), a["logret_cc"].to_numpy(), a["dollar_volume"].to_numpy()
        assert r.loc[i, "ret_21"] == pytest.approx(math.log(c[i] / c[i - 21]), abs=1e-12)
        assert r.loc[i, "mom_12_1"] == pytest.approx(math.log(c[i - 21] / c[i - 252]), abs=1e-12)
        assert r.loc[i, "px_sma_200"] == pytest.approx(
            math.log(c[i] / c[i - 199 : i + 1].mean()), abs=1e-10
        )
        assert r.loc[i, "vol_63"] == pytest.approx(
            lr[i - 62 : i + 1].std(ddof=1) * math.sqrt(252), rel=1e-10
        )
        assert r.loc[i, "log_dvol_63"] == pytest.approx(math.log(dv[i - 62 : i + 1].mean()), abs=1e-10)
        assert r.loc[i, "dist_52w_high"] == pytest.approx(
            math.log(c[i] / c[i - 251 : i + 1].max()), abs=1e-12
        )


def test_real_data_poisoned_future(s5) -> None:
    """Features at dates <= 2015-06-30 do not change when all later data is removed."""
    adjusted, universe, t = s5["adjusted"], s5["universe"], s5["t"]
    cut = pd.Timestamp("2015-06-30")
    keep = (adjusted["date"] <= cut).to_numpy()
    cut_t = build_features(adjusted[keep].reset_index(drop=True),
                           universe[keep].reset_index(drop=True), s5["cfg"].features)
    for kind in ("features_raw", "features_model"):
        full = getattr(t, kind)
        pd.testing.assert_frame_equal(
            getattr(cut_t, kind), full[full["date"] <= cut].reset_index(drop=True),
            check_exact=True,
        )
    pd.testing.assert_frame_equal(
        cut_t.market_series, t.market_series[t.market_series["date"] <= cut].reset_index(drop=True),
        check_exact=True,
    )


def test_rebuild_is_deterministic(s5, tmp_path) -> None:
    again = run_build_features(
        s5["cfg"],
        **{**s5["files"], "market_file": tmp_path / "m.parquet", "raw_file": tmp_path / "r.parquet",
           "model_file": tmp_path / "f.parquet"},
    )
    for x, y in zip(again, s5["t"], strict=True):
        pd.testing.assert_frame_equal(x, y)
