"""Unit tests for the S2 universe builder (Part III S2, decision D6)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.flags import add_flags
from nasdaq100.data.ingest import BRONZE_COLUMNS
from nasdaq100.data.security_master import write_security_master
from nasdaq100.data.universe import (
    FAIL_COLUMNS,
    LIQUIDITY_WINDOW,
    UNIVERSE_COLUMNS,
    UniverseError,
    build_universe,
    load_universe,
    master_fail_by_ticker,
    run_build_universe,
)
from nasdaq100.utils.io import write_parquet
from tests.fixtures.s2_silver import (
    cfg_with,
    make_curated,
    make_master,
    make_silver,
    universe_cfg,
)

UCFG = universe_cfg()


def _build(silver: pd.DataFrame, ucfg=UCFG, curated=None) -> pd.DataFrame:
    return build_universe(silver, make_master(silver, curated), ucfg)


def _t(u: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """One ticker's rows with a 1-based observation number ``n``."""
    sub = u[u["ticker"] == ticker].reset_index(drop=True)
    return sub.assign(n=range(1, len(sub) + 1))


@pytest.mark.unit
def test_schema_sorting_and_no_rows_dropped() -> None:
    silver = make_silver(("BBB", "AAA"), start_offsets={"AAA": 10})
    u = _build(silver)
    assert tuple(u.columns) == UNIVERSE_COLUMNS
    assert len(u) == len(silver)  # nothing dropped, ineligible rows are kept
    assert str(u["date"].dtype) == "datetime64[ns]"
    assert all(u[c].dtype == bool for c in ("eligible", *FAIL_COLUMNS))
    assert u["median_dollar_volume_63"].dtype == "float64"
    keys = list(zip(u["ticker"], u["date"], strict=True))
    assert keys == sorted(keys)
    assert (u["eligible"] == ~u[list(FAIL_COLUMNS)].any(axis=1)).all()


@pytest.mark.unit
def test_eligibility_flips_exactly_at_the_253rd_observation() -> None:
    u = _t(_build(make_silver(("AAA",), n_days=300)), "AAA")
    assert u.loc[u["n"] <= 252, "fail_seasoning"].all()
    assert not u.loc[u["n"] >= 253, "fail_seasoning"].any()
    assert not u.loc[u["n"] <= 252, "eligible"].any()
    assert u.loc[u["n"] >= 253, "eligible"].all()
    assert u.loc[u["n"] == 252, "eligible"].item() is False
    assert u.loc[u["n"] == 253, "eligible"].item() is True


@pytest.mark.unit
def test_seasoning_counts_own_observations_not_calendar_position() -> None:
    silver = make_silver(("AAA", "BBB"), n_days=320, start_offsets={"BBB": 40})
    u = _build(silver)
    a, b = _t(u, "AAA"), _t(u, "BBB")
    assert a.loc[a["eligible"], "n"].min() == 253
    assert b.loc[b["eligible"], "n"].min() == 253  # also its own 253rd row (280th date)
    assert b.loc[b["eligible"], "date"].min() > a.loc[a["eligible"], "date"].min()


@pytest.mark.unit
def test_seasoning_days_comes_from_config() -> None:
    u = _t(_build(make_silver(("AAA",), n_days=120), universe_cfg("universe.seasoning_days=70")),
           "AAA")
    assert u.loc[u["eligible"], "n"].min() == 71


@pytest.mark.unit
def test_min_close_rule_is_strict_and_uses_split_adjusted_close() -> None:
    silver = make_silver(("AAA",), n_days=300)
    i4, i5, i6 = silver.index[270], silver.index[271], silver.index[272]
    silver.loc[i4, "close"] = 4.99
    silver.loc[i5, "close"] = 5.0
    silver.loc[i6, "adj_close"] = 0.01  # adj_close is irrelevant: the mask is on `close` (C10)
    u = _build(silver)
    assert u.loc[i4, "fail_min_close"] and not u.loc[i4, "eligible"]
    assert not u.loc[i5, "fail_min_close"] and u.loc[i5, "eligible"]
    assert not u.loc[i6, "fail_min_close"]
    assert int(u["fail_min_close"].sum()) == 1


@pytest.mark.unit
def test_min_close_threshold_comes_from_config() -> None:
    silver = make_silver(("AAA",), n_days=300)  # prices ~50
    assert not _build(silver, universe_cfg("universe.min_close=40"))["fail_min_close"].any()
    assert _build(silver, universe_cfg("universe.min_close=1000"))["fail_min_close"].all()


@pytest.mark.unit
def test_zero_volume_rule_and_its_switch() -> None:
    silver = make_silver(("AAA",), n_days=300)
    i = silver.index[280]
    silver.loc[i, "volume"] = 0
    u = _build(silver)
    assert u.loc[i, "fail_zero_volume"] and not u.loc[i, "eligible"]
    assert int(u["fail_zero_volume"].sum()) == 1
    off = _build(silver, universe_cfg("universe.require_positive_volume=false"))
    assert not off["fail_zero_volume"].any()
    # a single zero day lowers the median little, so this row is only blocked by the zero rule
    assert off.loc[i, "eligible"]


@pytest.mark.unit
def test_liquidity_is_nan_until_63_observations_and_nan_means_ineligible() -> None:
    silver = make_silver(("AAA",), n_days=120)
    u = _t(_build(silver, universe_cfg("universe.seasoning_days=10")), "AAA")
    assert LIQUIDITY_WINDOW == 63
    assert u.loc[u["n"] < 63, "median_dollar_volume_63"].isna().all()  # min_periods = 63
    assert u.loc[u["n"] >= 63, "median_dollar_volume_63"].notna().all()
    assert u.loc[u["n"] < 63, "fail_liquidity"].all()  # NaN counts as failure
    assert not u.loc[u["n"] >= 63, "fail_liquidity"].any()
    # seasoning (10) is satisfied from n=11, but liquidity keeps the name out until n=63
    assert u.loc[u["eligible"], "n"].min() == 63
    assert not u.loc[(u["n"] > 10) & (u["n"] < 63), "eligible"].any()


@pytest.mark.unit
def test_liquidity_uses_trailing_median_of_close_times_volume() -> None:
    silver = make_silver(("AAA",), n_days=200)
    u = _build(silver)
    dv = silver["close"] * silver["volume"]
    expected = dv.rolling(63, min_periods=63).median()
    pd.testing.assert_series_equal(
        u["median_dollar_volume_63"], expected, check_names=False, check_exact=False
    )


@pytest.mark.unit
def test_liquidity_threshold_is_inclusive_and_median_resists_one_spike() -> None:
    silver = make_silver(("AAA",), n_days=300)
    silver["close"] = 50.0
    silver["open"], silver["high"], silver["low"] = 50.0, 50.1, 49.9
    silver["volume"] = 20_000  # exactly $1,000,000 per day
    u = _build(silver)
    assert not u["fail_liquidity"].iloc[62:].any()  # == threshold passes
    silver.loc[silver.index[100], "volume"] = 10_000_000_000  # one huge day cannot lift the median
    silver["volume"] = silver["volume"].where(silver.index < 150, 19_999)  # just under later on
    u2 = _build(silver)
    assert u2["fail_liquidity"].iloc[62:100].eq(False).all()
    assert u2["fail_liquidity"].iloc[250:].all()  # median now below $1M despite the spike
    assert not _build(silver, universe_cfg("universe.min_median_dollar_volume_63=500000.0")
                      )["fail_liquidity"].iloc[62:].any()


@pytest.mark.unit
def test_master_exclusion_marks_every_row_of_the_ticker() -> None:
    silver = make_silver(("AAA", "BBB"), n_days=300)
    cur = make_curated([{"ticker": "BBB", "exclusion_reason": "excluded for test"}])
    u = _build(silver, curated=cur)
    assert u.loc[u["ticker"] == "BBB", "fail_master"].all()
    assert not u.loc[u["ticker"] == "BBB", "eligible"].any()
    assert not u.loc[u["ticker"] == "AAA", "fail_master"].any()
    assert u.loc[u["ticker"] == "AAA", "eligible"].any()


@pytest.mark.unit
def test_cohort_filter_and_stitched_drop_remove_the_right_tickers() -> None:
    silver = make_silver(("AAA", "BBB", "CCC"), n_days=300, start_offsets={"CCC": 5})
    shift = pd.Timestamp("2000-01-03") - silver["date"].min()
    silver = silver.assign(date=silver["date"] + shift)  # AAA, BBB start 2000-01-03; CCC later
    cur = make_curated([{"ticker": "BBB", "stitching_suspect": True}])
    master = make_master(silver, cur)
    assert dict(zip(master["ticker"], master["cohort"], strict=True)) == {
        "AAA": "orig2000", "BBB": "orig2000", "CCC": "later"}

    def failed(*overrides: str) -> set[str]:
        u = build_universe(silver, master, universe_cfg(*overrides))
        by = u.groupby("ticker")["fail_master"].all()
        assert (by == u.groupby("ticker")["fail_master"].any()).all()  # per ticker, all or none
        return set(by.index[by])

    assert failed() == set()
    assert failed("universe.cohort_filter=original55") == {"CCC"}  # keeps the original names
    assert failed("universe.cohort_filter=later") == {"AAA", "BBB"}
    assert failed("universe.drop_stitched=true") == {"BBB"}
    assert failed("universe.cohort_filter=original55", "universe.drop_stitched=true") == {
        "BBB", "CCC"}
    with pytest.raises(UniverseError, match="cohort_filter"):
        master_fail_by_ticker(master, universe_cfg("universe.cohort_filter=orig2000"))
    with pytest.raises(UniverseError, match="cohort_filter"):
        build_universe(silver, master, universe_cfg("universe.cohort_filter=bogus"))


@pytest.mark.unit
def test_azn_is_excluded_by_the_quality_rule_alone() -> None:
    silver = make_silver(("AZN", "BBB"), n_days=300)
    mask = (silver["ticker"] == "AZN") & (silver.groupby("ticker").cumcount() % 100 < 34)
    silver.loc[mask, "volume"] = 0
    master = make_master(silver, make_curated())  # curated file is EMPTY
    assert master.loc[master["ticker"] == "AZN", "exclusion_reason"].item() == ""
    u = build_universe(silver, master, UCFG)
    assert u.loc[u["ticker"] == "AZN", "fail_master"].all()
    assert not u.loc[u["ticker"] == "AZN", "eligible"].any()
    assert u.loc[u["ticker"] == "BBB", "eligible"].any()


@pytest.mark.unit
def test_s1_flags_are_untouched_and_silver_is_not_mutated() -> None:
    bronze = make_silver(("AAA", "BBB"), n_days=300)[list(BRONZE_COLUMNS)].copy()
    bronze.loc[bronze.index[5], "close"] = 2.0  # tick-noise row
    silver = add_flags(bronze, load_config().flags)
    assert int(silver["flag_tick_noise"].sum()) == 1
    before = silver.copy(deep=True)
    u = _build(silver)
    pd.testing.assert_frame_equal(silver, before)  # flags and every other column unchanged
    assert int(silver["flag_tick_noise"].sum()) == 1
    assert len(u) == len(silver)  # the flagged row is kept in the universe table
    assert set(u.columns).isdisjoint({"flag_tick_noise", "n_obs", "close", "volume"})


@pytest.mark.unit
def test_universe_ignores_whole_history_master_columns() -> None:
    """first_date / last_date / n_obs in the master are descriptors; eligibility must not use them."""
    silver = make_silver(("AAA", "BBB"), n_days=300, start_offsets={"BBB": 20})
    master = make_master(silver)
    tampered = master.copy()
    tampered["last_date"] = pd.Timestamp("1999-01-01")
    tampered["first_date"] = pd.Timestamp("2099-01-01")
    tampered["n_obs"] = 1
    tampered["median_dollar_volume_last_year"] = 0.0
    pd.testing.assert_frame_equal(
        build_universe(silver, master, UCFG), build_universe(silver, tampered, UCFG)
    )


@pytest.mark.unit
def test_input_validation_errors() -> None:
    silver = make_silver(("AAA",), n_days=300)
    master = make_master(silver)
    with pytest.raises(UniverseError, match="missing columns"):
        build_universe(silver.drop(columns=["n_obs"]), master, UCFG)
    nan = silver.copy()
    nan.loc[3, "volume"] = float("nan")
    with pytest.raises(UniverseError, match="NaN"):
        build_universe(nan, master, UCFG)
    stale = silver.copy()
    stale["n_obs"] = stale["n_obs"] + 1
    with pytest.raises(UniverseError, match="n_obs"):
        build_universe(stale, master, UCFG)
    dup = pd.concat([silver, silver.iloc[[7]]]).reset_index(drop=True)
    with pytest.raises(UniverseError, match="duplicate"):
        build_universe(dup, master, UCFG)
    with pytest.raises(UniverseError, match="missing from the security master"):
        build_universe(make_silver(("AAA", "ZZZ"), n_days=300), master, UCFG)


@pytest.mark.unit
def test_run_build_universe_and_load_universe_end_to_end(tmp_path: Path) -> None:
    silver = make_silver(("AAA", "BBB"), n_days=300)
    write_parquet(silver, tmp_path / "silver.parquet")
    write_security_master(make_master(silver), tmp_path / "sm.csv")
    cfg = cfg_with()
    out = tmp_path / "proc" / "universe.parquet"
    built = run_build_universe(
        cfg, silver_file=tmp_path / "silver.parquet", master_file=tmp_path / "sm.csv",
        universe_file=out,
    )
    loaded = load_universe(cfg, out)
    pd.testing.assert_frame_equal(loaded.reset_index(drop=True), built.reset_index(drop=True))
    with pytest.raises(FileNotFoundError, match="build-master"):
        run_build_universe(cfg, silver_file=tmp_path / "silver.parquet",
                           master_file=tmp_path / "missing.csv")
    with pytest.raises(FileNotFoundError, match="build-universe"):
        load_universe(cfg, tmp_path / "missing.parquet")


@pytest.mark.unit
def test_load_universe_honours_project_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    silver = make_silver(("AAA", "BBB"), n_days=300)
    master = make_master(silver)
    base_u = build_universe(silver, master, UCFG)
    alt_cfg = universe_cfg("universe.min_close=1000")
    alt_u = build_universe(silver, master, alt_cfg)
    assert alt_u["eligible"].sum() == 0 < base_u["eligible"].sum()

    def fake_path(variant: str = "base") -> Path:
        return tmp_path / "processed" / variant / "universe.parquet"

    monkeypatch.setattr("nasdaq100.data.universe.universe_path", fake_path)
    write_parquet(base_u, fake_path("base"))
    write_parquet(alt_u, fake_path("hi_close"))
    base_cfg = cfg_with()
    var_cfg = cfg_with("project.variant=hi_close")
    assert load_universe(base_cfg)["eligible"].sum() == base_u["eligible"].sum()
    assert load_universe(var_cfg)["eligible"].sum() == 0  # variants never overwrite each other
    with pytest.raises(FileNotFoundError, match="other_variant"):
        load_universe(cfg_with("project.variant=other_variant"))


@pytest.mark.unit
def test_load_universe_rejects_wrong_schema(tmp_path: Path) -> None:
    p = tmp_path / "u.parquet"
    write_parquet(pd.DataFrame({"ticker": ["A"], "date": [pd.Timestamp("2020-01-01")]}), p)
    with pytest.raises(UniverseError, match="columns"):
        load_universe(cfg_with(), p)
