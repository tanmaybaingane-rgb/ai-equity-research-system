"""Unit tests for the S5 feature pipeline (``features/build.py``)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.features import build as fb
from nasdaq100.features.build import (
    build_features,
    feature_columns,
    load_features_model,
    load_features_raw,
    load_market_series,
    run_build_features,
)
from nasdaq100.features.market_features import MARKET_SERIES_COLUMNS
from nasdaq100.features.normalize import rank_gauss_per_date
from nasdaq100.features.registry import (
    ALL_FEATURES,
    MARKET_FEATURES,
    STOCK_FEATURES,
    FeatureError,
    get_spec,
)
from nasdaq100.labels.forward_returns import build_labels
from nasdaq100.utils.io import write_parquet
from tests.fixtures.s5_features import make_feature_panel

ID = ["ticker", "date", "eligible"]


def fcfg(families: list[str] | None = None, winsor: list[float] | None = None):
    ov = []
    if families is not None:
        ov.append("features.families=" + json.dumps(families, separators=(",", ":")))
    if winsor is not None:
        ov.append("features.winsor_pct=" + json.dumps(winsor, separators=(",", ":")))
    return load_config(overrides=ov).features


@pytest.fixture(scope="module")
def panel():
    adjusted, universe, cal = make_feature_panel()
    return adjusted, universe, cal, build_features(adjusted, universe, fcfg())


@pytest.mark.unit
def test_schema_order_dtypes_and_row_set(panel) -> None:
    adjusted, universe, cal, t = panel
    assert list(t.market_series.columns) == list(MARKET_SERIES_COLUMNS)
    assert list(t.features_raw.columns) == ID + list(ALL_FEATURES)
    assert list(t.features_model.columns) == ID + list(ALL_FEATURES)
    assert len(ALL_FEATURES) == 24 and feature_columns(list(fcfg().families)) == list(ALL_FEATURES)
    keys = adjusted.sort_values(["ticker", "date"]).reset_index(drop=True)[["ticker", "date"]]
    for tab in (t.features_raw, t.features_model):
        assert tab[["ticker", "date"]].equals(keys)  # rows never dropped, sorted
        assert tab["date"].dtype == "datetime64[ns]" and tab["eligible"].dtype == "bool"
        for c in ALL_FEATURES:
            assert tab[c].dtype == "float64"
    assert len(t.market_series) == cal.n_days and t.market_series["date"].is_unique
    assert t.market_series["n_eligible"].dtype == "int32"
    u = universe.sort_values(["ticker", "date"]).reset_index(drop=True)
    assert (t.features_raw["eligible"].to_numpy() == u["eligible"].to_numpy()).all()


@pytest.mark.unit
def test_no_infinities_and_milestone_m1_key_join(panel) -> None:
    adjusted, universe, cal, t = panel
    for tab in (t.features_raw, t.features_model):
        assert not np.isinf(tab[list(ALL_FEATURES)].to_numpy()).any()
    cfg = load_config(overrides=["labels.horizons=[3]", "labels.primary_horizon=3"])
    labels = build_labels(adjusted, universe, cfg.labels, cal, min_names=2)
    u = universe.sort_values(["ticker", "date"]).reset_index(drop=True)
    for tab in (labels, t.features_raw, t.features_model, u):
        assert tab[["ticker", "date"]].equals(u[["ticker", "date"]])  # no key mismatches
    joined = u.merge(labels, on=["ticker", "date"], validate="1:1").merge(
        t.features_model, on=["ticker", "date", "eligible"], validate="1:1"
    )
    assert len(joined) == len(u)


@pytest.mark.unit
def test_market_features_identical_across_tickers_and_copied_raw_into_model(panel) -> None:
    _, _, _, t = panel
    for name in MARKET_FEATURES:
        per_date = t.features_raw.groupby("date")[name].nunique(dropna=False)
        assert (per_date == 1).all(), name
        pd.testing.assert_series_equal(t.features_model[name], t.features_raw[name])
    ms = t.market_series.set_index("date")
    got = t.features_raw.drop_duplicates("date").set_index("date")["mkt_ret_21"]
    exp = ms["mkt_logret"].rolling(21, min_periods=21).sum()
    pd.testing.assert_series_equal(got, exp.rename("mkt_ret_21"), check_freq=False)


@pytest.mark.unit
def test_model_features_are_per_date_rank_gauss_of_eligible_raw_features(panel) -> None:
    _, _, _, t = panel
    raw, model = t.features_raw, t.features_model
    stock = list(STOCK_FEATURES)
    assert model.loc[~model["eligible"], stock].isna().all().all()  # ineligible -> NaN
    again = rank_gauss_per_date(raw[stock], raw["date"], raw["eligible"], [0.01, 0.99])
    pd.testing.assert_frame_equal(model[stock], again)
    # NaN pattern: a model value exists exactly where the raw value exists and the row is eligible
    exp_mask = raw[stock].notna().to_numpy() & raw["eligible"].to_numpy()[:, None]
    assert (model[stock].notna().to_numpy() == exp_mask).all()
    # per-date mean ~ 0 and std ~ 1 (+-0.1) on dates with enough names
    e = model[model["eligible"]]
    g = e.groupby("date")[stock]
    counts = g.count()
    mean, std = g.mean().where(counts >= 15), g.std().where(counts >= 15)
    assert mean.abs().max().max() < 0.1
    assert ((std - 1.0).abs().max().max()) < 0.1
    # monotone with raw within a date (eligible rows)
    d = raw.loc[raw["eligible"], "date"].iloc[len(raw[raw["eligible"]]) // 2]
    day = raw[(raw["date"] == d) & raw["eligible"]]
    zday = model.loc[day.index]
    for name in stock:
        ok = day[name].notna()
        order = np.argsort(day.loc[ok, name].to_numpy())
        assert (np.diff(zday.loc[ok, name].to_numpy()[order]) >= -1e-12).all()


@pytest.mark.unit
def test_warm_up_pattern_of_the_built_features(panel) -> None:
    adjusted, _, _, t = panel
    raw = t.features_raw
    for tk in ("T00", "T03", "T07"):  # starts at row 0, 20 and 90 of the calendar
        rows = raw[raw["ticker"] == tk].reset_index(drop=True)
        for name in STOCK_FEATURES:
            if name == "beta_126":
                continue  # also needs the market series (checked below)
            w = get_spec(name).warmup
            assert rows[name].iloc[:w].isna().all(), (tk, name)
            if len(rows) > w:
                assert rows[name].iloc[w:].notna().all(), (tk, name)
        if len(rows) > 252:  # T07 has only 240 rows: its 12-1 momentum never warms up
            assert rows["mom_12_1"].first_valid_index() == 252
        else:
            assert rows["mom_12_1"].isna().all()
    ms = t.market_series.reset_index(drop=True)
    first_elig = int(np.flatnonzero(ms["n_eligible"].to_numpy() > 0)[0])
    assert ms["mkt_logret"].first_valid_index() == first_elig + 1  # composition: previous day
    assert ms["mkt_index"].first_valid_index() == first_elig + 1
    assert raw["mkt_breadth_50"].notna().any() and raw["xs_disp_21"].notna().any()
    # beta_126 needs 126 market returns (window of 126 rows with all returns defined)
    t00 = raw[raw["ticker"] == "T00"].reset_index(drop=True)
    assert t00["beta_126"].first_valid_index() == max(126, first_elig + 126)


@pytest.mark.unit
def test_family_switch_drops_the_right_columns_and_keeps_the_values(panel) -> None:
    adjusted, universe, _, full = panel
    cases = {
        ("momentum", "market"): STOCK_FEATURES[:6] + MARKET_FEATURES,
        ("volatility",): STOCK_FEATURES[6:12],  # beta_126 still works: the series is built anyway
        ("trend", "liquidity"): STOCK_FEATURES[12:],
        ("market",): MARKET_FEATURES,
    }
    for fam, expected in cases.items():
        t = build_features(adjusted, universe, fcfg(list(fam)))
        cols = list(expected)
        assert list(t.features_raw.columns) == ID + cols, fam
        assert list(t.features_model.columns) == ID + cols, fam
        pd.testing.assert_frame_equal(t.features_raw, full.features_raw[ID + cols])
        pd.testing.assert_frame_equal(t.features_model, full.features_model[ID + cols])
        pd.testing.assert_frame_equal(t.market_series, full.market_series)  # always written
    # without any stock family the model table carries only the raw market features
    only_market = build_features(adjusted, universe, fcfg(["market"]))
    assert list(only_market.features_model.columns) == ID + list(MARKET_FEATURES)


@pytest.mark.unit
def test_winsor_pct_is_honoured(panel) -> None:
    adjusted, universe, _, full = panel
    tight = build_features(adjusted, universe, fcfg(winsor=[0.2, 0.8]))
    assert not tight.features_model.equals(full.features_model)  # clipped tails now tie
    pd.testing.assert_frame_equal(tight.features_raw, full.features_raw)  # raw is never clipped
    # with fewer than ~100 names per date the default 1% / 99% clip moves at most one value per
    # tail and creates no tie, so the ranks (hence the rank-gauss scores) equal the unclipped ones
    wide = build_features(adjusted, universe, fcfg(winsor=[0.0, 1.0]))
    pd.testing.assert_frame_equal(wide.features_model, full.features_model)


@pytest.mark.unit
def test_determinism_and_input_immutability() -> None:
    adjusted, universe, _ = make_feature_panel(n_tickers=12, n_days=300, seed=2)
    sa = adjusted.sample(frac=1.0, random_state=1).reset_index(drop=True)
    su = universe.sample(frac=1.0, random_state=2).reset_index(drop=True)
    before = (sa.copy(), su.copy())
    a = build_features(sa, su, fcfg())
    pd.testing.assert_frame_equal(sa, before[0])
    pd.testing.assert_frame_equal(su, before[1])
    b = build_features(adjusted, universe, fcfg())
    for x, y in zip(a, b, strict=True):
        pd.testing.assert_frame_equal(x, y)  # input row order does not matter; reruns identical


@pytest.mark.unit
def test_invalid_inputs_raise() -> None:
    adjusted, universe, _ = make_feature_panel(n_tickers=6, n_days=60, seed=1, min_obs=10)
    cfg = fcfg()
    with pytest.raises(FeatureError, match="missing columns"):
        build_features(adjusted.drop(columns=["adj_high"]), universe, cfg)
    with pytest.raises(FeatureError, match="missing columns"):
        build_features(adjusted, universe.drop(columns=["eligible"]), cfg)
    with pytest.raises(FeatureError, match="empty"):
        build_features(adjusted.iloc[0:0], universe, cfg)
    dup = pd.concat([adjusted, adjusted.iloc[[0]]], ignore_index=True)
    with pytest.raises(FeatureError, match="duplicate"):
        build_features(dup, universe, cfg)
    for col, val, match in (
        ("adj_close", np.nan, "NaN"),
        ("dollar_volume", np.nan, "NaN"),
        ("adj_low", 0.0, "non-positive"),
        ("adj_high", -1.0, "non-positive"),
        ("dollar_volume", -5.0, "negative"),
        ("logret_cc", np.inf, "infinite"),
        ("logret_cc", np.nan, "not the first row"),
    ):
        bad = adjusted.copy()
        bad.loc[10, col] = val
        with pytest.raises(FeatureError, match=match):
            build_features(bad, universe, cfg)
    with pytest.raises(FeatureError, match="identical"):
        build_features(adjusted, universe.iloc[:-1], cfg)
    gap_a = adjusted[~((adjusted["ticker"] == "T01") & (adjusted["t_idx"] == 30))]
    gap_u = universe.loc[gap_a.index]
    with pytest.raises(FeatureError, match="consecutive"):
        build_features(gap_a, gap_u, cfg)
    nan_u = universe.copy().astype({"eligible": "object"})
    nan_u.loc[3, "eligible"] = None
    with pytest.raises(FeatureError, match="eligible"):
        build_features(adjusted, nan_u, cfg)
    with pytest.raises(FeatureError, match="Unknown feature families"):
        build_features(adjusted, universe, fcfg(["momentum", "sentiment"]))
    with pytest.raises(FeatureError, match="winsor_pct"):
        build_features(adjusted, universe, fcfg(winsor=[0.9, 0.1]))


@pytest.mark.unit
def test_run_build_features_roundtrip_variant_and_errors(tmp_path, monkeypatch) -> None:
    adjusted, universe, _ = make_feature_panel(n_tickers=10, n_days=280, seed=3)
    a_file, u_file = tmp_path / "a.parquet", tmp_path / "u.parquet"
    write_parquet(adjusted, a_file)
    write_parquet(universe, u_file)
    cfg = load_config()
    files = {"adjusted_file": a_file, "universe_file": u_file, "market_file": tmp_path / "m.pq",
             "raw_file": tmp_path / "r.pq", "model_file": tmp_path / "f.pq"}
    built = run_build_features(cfg, **files)
    pd.testing.assert_frame_equal(load_market_series(cfg, files["market_file"]), built.market_series)
    pd.testing.assert_frame_equal(load_features_raw(cfg, files["raw_file"]), built.features_raw)
    pd.testing.assert_frame_equal(load_features_model(cfg, files["model_file"]), built.features_model)
    again = run_build_features(cfg, **files)
    for x, y in zip(again, built, strict=True):
        pd.testing.assert_frame_equal(x, y)

    # default paths follow the variant
    seen: list[str] = []

    def fake(name):
        def path(variant: str = "base"):
            seen.append(f"{name}:{variant}")
            return tmp_path / variant / f"{name}.parquet"
        return path

    for attr, name in (("market_series_path", "m"), ("features_raw_path", "r"),
                       ("features_model_path", "f")):
        monkeypatch.setattr(fb, attr, fake(name))
    cfg2 = load_config(overrides=["project.variant=exp1"])
    run_build_features(cfg2, adjusted_file=a_file, universe_file=u_file)
    assert sorted(seen) == ["f:exp1", "m:exp1", "r:exp1"]
    assert len(load_features_model(cfg2)) == len(adjusted)

    # loaders: missing file, and a file built with other families than the current config
    with pytest.raises(FileNotFoundError, match="build-features"):
        load_features_raw(cfg, tmp_path / "missing.parquet")
    with pytest.raises(FeatureError, match="columns"):
        load_features_raw(load_config(overrides=['features.families=["momentum"]']),
                          files["raw_file"])
    # missing upstream inputs
    with pytest.raises(FileNotFoundError, match="build-adjusted"):
        run_build_features(cfg, adjusted_file=tmp_path / "none.parquet", universe_file=u_file)
    with pytest.raises(FileNotFoundError, match="build-universe"):
        run_build_features(cfg, adjusted_file=a_file, universe_file=tmp_path / "none.parquet")
