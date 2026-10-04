"""S2 acceptance tests on the real frozen dataset (``needs_data``; auto-skipped if absent).

S1 runs once per session into a temp dir (``real_s1``); S2 builds into a temp dir too, so nothing
under ``data/`` is written. Expected numbers: Master Guide Part I section I.3 and Part III S2.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.security_master import (
    build_security_master,
    load_curated,
    load_security_master,
    read_silver,
    run_build_master,
)
from nasdaq100.data.universe import (
    FAIL_COLUMNS,
    UNIVERSE_COLUMNS,
    build_universe,
    load_universe,
    run_build_universe,
)
from nasdaq100.paths import raw_zip_path, security_master_curated_path
from nasdaq100.utils.hashing import sha256_file

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def s2(real_s1: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("s2_real")
    cfg = load_config()
    silver_before = sha256_file(real_s1["silver_file"])
    master = run_build_master(
        cfg,
        silver_file=real_s1["silver_file"],
        curated_file=security_master_curated_path(),
        master_file=tmp / "security_master.csv",
    )
    universe = run_build_universe(
        cfg,
        silver_file=real_s1["silver_file"],
        master_file=tmp / "security_master.csv",
        universe_file=tmp / "universe.parquet",
    )
    return {
        "cfg": cfg, "tmp": tmp, "master": master, "universe": universe,
        "silver": read_silver(real_s1["silver_file"]), "silver_before": silver_before,
        "silver_file": real_s1["silver_file"],
    }


def test_security_master_contents(s2: dict[str, Any]) -> None:
    m = s2["master"]
    assert len(m) == 100 and m["ticker"].is_unique
    assert (m["cohort"] == "orig2000").sum() == 55 and (m["cohort"] == "later").sum() == 45
    assert m.loc[m["ticker"] == "AAPL", "cohort"].item() == "orig2000"
    assert m.loc[m["ticker"] == "TSLA", "cohort"].item() == "later"
    assert sorted(m.loc[~m["include_in_universe"], "ticker"]) == ["AZN", "GOOG"]
    assert sorted(m.loc[m["stitching_suspect"], "ticker"]) == sorted(
        ["CCEP", "KDP", "WBD", "LIN", "BKR", "MDLZ"])
    assert m["issuer_id"].where(m["ticker"] != "GOOG").dropna().eq(
        m["ticker"].where(m["ticker"] != "GOOG").dropna()).all()  # issuer == ticker except GOOG
    assert m.loc[m["ticker"] == "GOOG", "issuer_id"].item() == "GOOGL"
    assert m["n_obs"].min() == 609 and m["n_obs"].max() == 6_571
    assert (m["last_date"] == pd.Timestamp("2026-02-18")).all()  # survivors only


def test_azn_facts_and_quality_rule_alone_excludes_it(s2: dict[str, Any]) -> None:
    m = s2["master"].set_index("ticker")
    assert m.loc["AZN", "zero_volume_share"] == pytest.approx(1_459 / 4_279)
    assert 0.34 < m.loc["AZN", "zero_volume_share"] < 0.35
    assert m.loc["AZN", "median_dollar_volume_last_year"] < 1_000_000  # about $0.2M
    others = m.drop(index="AZN")["median_dollar_volume_last_year"]
    assert others.min() > 20_000_000  # next-lowest name is orders of magnitude more liquid
    assert (others.index[others.eq(others.min())] == ["GFS"]).all()
    assert m.drop(index="AZN")["zero_volume_share"].max() < 0.05

    empty = build_security_master(
        s2["silver"], load_curated(security_master_curated_path()).iloc[0:0],
        s2["cfg"].flags.max_zero_volume_share_ticker,
    )
    assert empty.loc[~empty["include_in_universe"], "ticker"].tolist() == ["AZN"]


def test_universe_shape_and_schema(s2: dict[str, Any]) -> None:
    u, silver = s2["universe"], s2["silver"]
    assert tuple(u.columns) == UNIVERSE_COLUMNS
    assert len(u) == len(silver) == 514_075  # nothing dropped
    keys = u[["ticker", "date"]]
    assert keys.equals(silver[["ticker", "date"]].reset_index(drop=True))
    assert (u["eligible"] == ~u[list(FAIL_COLUMNS)].any(axis=1)).all()
    loaded = load_universe(s2["cfg"], s2["tmp"] / "universe.parquet")
    assert loaded.reset_index(drop=True).equals(u.reset_index(drop=True))


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2001, 42), (2005, 48), (2008, 53), (2010, 59), (2015, 75), (2019, 83), (2022, 94),
     (2025, 98)],
)
def test_eligible_names_per_date_match_the_guide(
    s2: dict[str, Any], year: int, expected: int
) -> None:
    """Median over the year's dates of the number of eligible names, within +/-2."""
    per_date = s2["universe"].groupby("date")["eligible"].sum()
    median = float(per_date[per_date.index.year == year].median())
    assert abs(median - expected) <= 2, f"{year}: {median} vs {expected}"


def test_goog_never_eligible_and_googl_eligible_from_2005_08(s2: dict[str, Any]) -> None:
    u = s2["universe"]
    assert not u.loc[u["ticker"] == "GOOG", "eligible"].any()
    assert u.loc[u["ticker"] == "GOOG", "fail_master"].all()
    first = u.loc[(u["ticker"] == "GOOGL") & u["eligible"], "date"].min()
    assert (first.year, first.month) == (2005, 8)
    gl = u[u["ticker"] == "GOOGL"].reset_index(drop=True)
    assert not gl.loc[:251, "eligible"].any()  # the first 252 observations are never eligible
    assert gl.loc[252, "eligible"]  # the 253rd is the first one


def test_azn_never_eligible(s2: dict[str, Any]) -> None:
    u = s2["universe"]
    assert not u.loc[u["ticker"] == "AZN", "eligible"].any()
    assert u.loc[u["ticker"] == "AZN", "fail_master"].all()


def test_rules_hold_for_every_eligible_row(s2: dict[str, Any]) -> None:
    u = s2["universe"]
    silver = s2["silver"].reset_index(drop=True)
    e = u["eligible"].to_numpy()
    assert (silver.loc[e, "n_obs"] > 252).all()
    assert (silver.loc[e, "close"] >= 5.0).all()
    assert (silver.loc[e, "volume"] > 0).all()
    assert (u.loc[e, "median_dollar_volume_63"] >= 1_000_000).all()
    assert u.loc[e, "median_dollar_volume_63"].notna().all()
    first_elig = u[u["eligible"]].groupby("ticker")["date"].min()
    n_at_first = silver.merge(first_elig.rename("d").reset_index(), on="ticker")
    n_at_first = n_at_first[n_at_first["date"] == n_at_first["d"]]
    assert (n_at_first["n_obs"] >= 253).all()


def test_s1_flags_and_raw_data_are_untouched(s2: dict[str, Any]) -> None:
    assert sha256_file(s2["silver_file"]) == s2["silver_before"]  # silver unchanged by S2
    flagged = s2["silver"][s2["silver"]["flag_corp_action_suspect"]]
    assert len(flagged) == 19
    u = s2["universe"]
    # flagged rows remain in the universe table (flags never remove rows)
    assert len(u.merge(flagged[["ticker", "date"]], on=["ticker", "date"])) == 19
    if raw_zip_path().is_file():
        assert sha256_file(raw_zip_path()) == (
            "e70ce876b218b8af9d891a3c47c471f2a039698614697c60b6be5ad32537e8d2")


def test_variants_cohort_and_stitched_filters(s2: dict[str, Any]) -> None:
    master = load_security_master(s2["tmp"] / "security_master.csv")
    cohort = dict(zip(master["ticker"], master["cohort"], strict=True))
    cfg_orig = load_config(overrides=["universe.cohort_filter=original55"])
    u_orig = build_universe(s2["silver"], master, cfg_orig.universe)
    assert {cohort[t] for t in u_orig.loc[u_orig["eligible"], "ticker"].unique()} == {"orig2000"}
    cfg_later = load_config(overrides=["universe.cohort_filter=later"])
    u_later = build_universe(s2["silver"], master, cfg_later.universe)
    assert {cohort[t] for t in u_later.loc[u_later["eligible"], "ticker"].unique()} == {"later"}

    cfg_ns = load_config(overrides=["universe.drop_stitched=true"])
    u_ns = build_universe(s2["silver"], master, cfg_ns.universe)
    stitched = set(master.loc[master["stitching_suspect"], "ticker"])
    assert not set(u_ns.loc[u_ns["eligible"], "ticker"]) & stitched
    assert u_ns["eligible"].sum() < s2["universe"]["eligible"].sum()


def test_builds_are_deterministic(s2: dict[str, Any], tmp_path: Any) -> None:
    cfg = s2["cfg"]
    run_build_master(
        cfg, silver_file=s2["silver_file"], curated_file=security_master_curated_path(),
        master_file=tmp_path / "sm2.csv",
    )
    assert (tmp_path / "sm2.csv").read_bytes() == (s2["tmp"] / "security_master.csv").read_bytes()
    again = build_universe(s2["silver"], s2["master"], cfg.universe)
    assert again.equals(s2["universe"])
