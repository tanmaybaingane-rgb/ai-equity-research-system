"""Unit tests for the S2 security master."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.security_master import (
    CURATED_COLUMNS,
    LAST_YEAR_OBS,
    MASTER_COLUMNS,
    SecurityMasterError,
    build_security_master,
    load_curated,
    load_security_master,
    normalise_curated,
    run_build_master,
    write_security_master,
)
from nasdaq100.paths import security_master_curated_path
from nasdaq100.utils.io import write_parquet
from tests.fixtures.s2_silver import make_curated, make_master, make_silver

MAX_SHARE = 0.05


def _row(master: pd.DataFrame, ticker: str) -> pd.Series:
    return master.loc[master["ticker"] == ticker].iloc[0]


@pytest.mark.unit
def test_shipped_curated_file_matches_the_guide() -> None:
    cur = load_curated(security_master_curated_path()).set_index("ticker")
    assert list(cur.index) == ["AZN", "GOOG", "GOOGL", "CCEP", "KDP", "WBD", "LIN", "BKR", "MDLZ"]
    assert cur.loc["AZN", "exclusion_reason"] == (
        "illiquid non-representative series; 34% zero-volume days"
    )
    assert cur.loc["GOOG", "exclusion_reason"] == "duplicate share class of GOOGL"
    assert cur.loc["GOOG", "issuer_id"] == "GOOGL" and cur.loc["GOOGL", "issuer_id"] == "GOOGL"
    assert cur.loc["GOOGL", "share_class"] == "A" and cur.loc["GOOGL", "exclusion_reason"] == ""
    stitched = cur.index[cur["stitching_suspect"]].tolist()
    assert stitched == ["CCEP", "KDP", "WBD", "LIN", "BKR", "MDLZ"]
    assert (cur.loc[stitched, "notes"] == "history appears to include predecessor company; "
            "unverified").all()
    excluded = cur.index[cur["exclusion_reason"] != ""].tolist()
    assert excluded == ["AZN", "GOOG"]  # only exceptions are listed


@pytest.mark.unit
def test_load_curated_validation(tmp_path: Path) -> None:
    def write(text: str) -> Path:
        p = tmp_path / "c.csv"
        p.write_text(text, encoding="utf-8")
        return p

    head = ",".join(CURATED_COLUMNS) + "\n"
    ok = load_curated(write(head + "XYZ,,,,TRUE,note\n"))
    assert ok.loc[0, "issuer_id"] == "XYZ"  # blank issuer defaults to ticker
    assert bool(ok.loc[0, "stitching_suspect"]) is True

    with pytest.raises(SecurityMasterError, match="columns"):
        load_curated(write("ticker,issuer_id\nA,A\n"))
    with pytest.raises(SecurityMasterError, match="duplicate"):
        load_curated(write(head + "A,A,,,false,\nA,A,,,false,\n"))
    with pytest.raises(SecurityMasterError, match="stitching_suspect"):
        load_curated(write(head + "A,A,,,maybe,\n"))
    with pytest.raises(SecurityMasterError, match="blank ticker"):
        load_curated(write(head + ",A,,,false,\n"))
    with pytest.raises(FileNotFoundError):
        load_curated(tmp_path / "missing.csv")


@pytest.mark.unit
def test_defaults_for_tickers_not_in_curated_file() -> None:
    silver = make_silver(("AAA", "BBB"))
    master = make_master(silver)
    assert list(master.columns) == list(MASTER_COLUMNS)
    for t in ("AAA", "BBB"):
        r = _row(master, t)
        assert r["issuer_id"] == t and r["share_class"] == "" and r["exclusion_reason"] == ""
        assert bool(r["stitching_suspect"]) is False and bool(r["include_in_universe"]) is True
        assert r["status_reason"] == ""


@pytest.mark.unit
def test_curated_values_are_applied_and_unknown_curated_ticker_raises() -> None:
    silver = make_silver(("AAA", "BBB", "CCC"))
    cur = make_curated([
        {"ticker": "BBB", "issuer_id": "AAA", "share_class": "C",
         "exclusion_reason": "duplicate share class of AAA"},
        {"ticker": "CCC", "stitching_suspect": True, "notes": "stitched"},
    ])
    master = make_master(silver, cur)
    b, c = _row(master, "BBB"), _row(master, "CCC")
    assert b["issuer_id"] == "AAA" and b["share_class"] == "C"
    assert not b["include_in_universe"] and "duplicate share class" in b["status_reason"]
    assert bool(c["stitching_suspect"]) is True and c["include_in_universe"]  # stitched != excluded
    assert c["notes"] == "stitched"

    with pytest.raises(SecurityMasterError, match="not in the data"):
        make_master(silver, make_curated([{"ticker": "ZZZ"}]))


@pytest.mark.unit
def test_derived_columns() -> None:
    silver = make_silver(("AAA", "BBB"), n_days=300, start_offsets={"BBB": 40})
    master = make_master(silver)
    a, b = _row(master, "AAA"), _row(master, "BBB")
    dates = silver[silver["ticker"] == "AAA"]["date"]
    assert a["first_date"] == dates.min() and a["last_date"] == dates.max()
    assert a["n_obs"] == 300 and b["n_obs"] == 260
    assert b["first_date"] > a["first_date"] and b["last_date"] == a["last_date"]
    assert a["zero_volume_share"] == 0.0

    sub = silver[silver["ticker"] == "AAA"].tail(LAST_YEAR_OBS)
    expected = float((sub["close"] * sub["volume"]).median())
    assert a["median_dollar_volume_last_year"] == pytest.approx(expected)


@pytest.mark.unit
def test_cohort_is_orig2000_only_for_first_date_2000_01_03() -> None:
    silver = make_silver(("AAA", "BBB"), n_days=30, start_offsets={"BBB": 3})
    # shift the whole synthetic calendar so that AAA starts on 2000-01-03
    shift = pd.Timestamp("2000-01-03") - silver["date"].min()
    silver = silver.assign(date=silver["date"] + shift)
    master = make_master(silver)
    assert _row(master, "AAA")["first_date"] == pd.Timestamp("2000-01-03")
    assert _row(master, "AAA")["cohort"] == "orig2000"
    assert _row(master, "BBB")["cohort"] == "later"
    # the default silver (start 2020) has no orig2000 name
    assert set(make_master(make_silver())["cohort"]) == {"later"}


@pytest.mark.unit
def test_zero_volume_quality_rule_excludes_azn_even_with_empty_curated_file() -> None:
    silver = make_silver(("AZN", "BBB"), n_days=100)
    mask = (silver["ticker"] == "AZN") & (silver.groupby("ticker").cumcount() % 100 < 34)
    silver.loc[mask, "volume"] = 0  # 34% zero-volume days, like the real AZN
    master = build_security_master(silver, make_curated(), MAX_SHARE)  # empty curated file
    azn = _row(master, "AZN")
    assert azn["zero_volume_share"] == pytest.approx(0.34)
    assert not azn["include_in_universe"]
    assert azn["exclusion_reason"] == ""  # nothing curated ...
    assert "quality rule" in azn["status_reason"] and "34.0%" in azn["status_reason"]
    assert _row(master, "BBB")["include_in_universe"]


@pytest.mark.unit
def test_zero_volume_threshold_is_inclusive() -> None:
    silver = make_silver(("AAA",), n_days=100)
    silver.loc[silver.index[:5], "volume"] = 0  # exactly 5%
    assert _row(build_security_master(silver, make_curated(), 0.05), "AAA")["include_in_universe"]
    silver.loc[silver.index[:6], "volume"] = 0  # 6%
    assert not _row(build_security_master(silver, make_curated(), 0.05), "AAA")[
        "include_in_universe"
    ]


@pytest.mark.unit
def test_curated_and_quality_reasons_combine() -> None:
    silver = make_silver(("AAA",), n_days=100)
    silver.loc[silver.index[:50], "volume"] = 0
    cur = make_curated([{"ticker": "AAA", "exclusion_reason": "manual"}])
    r = _row(build_security_master(silver, cur, MAX_SHARE), "AAA")
    assert r["status_reason"].startswith("curated: manual; quality rule:")


@pytest.mark.unit
def test_build_does_not_modify_silver_or_drop_rows() -> None:
    silver = make_silver(("AAA", "BBB"))
    before = silver.copy(deep=True)
    make_master(silver)
    pd.testing.assert_frame_equal(silver, before)


@pytest.mark.unit
def test_build_rejects_bad_silver() -> None:
    silver = make_silver(("AAA",))
    with pytest.raises(SecurityMasterError, match="missing columns"):
        make_master(silver.drop(columns=["volume"]))
    bad = silver.copy()
    bad.loc[0, "close"] = float("nan")
    with pytest.raises(SecurityMasterError, match="NaN"):
        make_master(bad)


@pytest.mark.unit
def test_write_is_deterministic_and_roundtrips(tmp_path: Path) -> None:
    master = make_master(make_silver(("BBB", "AAA")))
    p1 = write_security_master(master, tmp_path / "a" / "sm.csv")
    p2 = write_security_master(master.sample(frac=1, random_state=3), tmp_path / "b.csv")
    assert p1.read_bytes() == p2.read_bytes()  # row order and OS independent
    assert b"\r\n" not in p1.read_bytes()
    assert p1.read_text(encoding="utf-8").splitlines()[0] == ",".join(MASTER_COLUMNS)
    assert p1.read_text(encoding="utf-8").splitlines()[1].startswith("AAA,")  # sorted by ticker

    loaded = load_security_master(p1)
    assert loaded["ticker"].tolist() == ["AAA", "BBB"]
    assert str(loaded["first_date"].dtype) == "datetime64[ns]"
    assert loaded["include_in_universe"].dtype == bool and loaded["stitching_suspect"].dtype == bool
    pd.testing.assert_series_equal(
        loaded["median_dollar_volume_last_year"].reset_index(drop=True),
        master.sort_values("ticker")["median_dollar_volume_last_year"].reset_index(drop=True),
    )
    with pytest.raises(FileNotFoundError, match="build-master"):
        load_security_master(tmp_path / "missing.csv")


@pytest.mark.unit
def test_load_security_master_rejects_wrong_columns(tmp_path: Path) -> None:
    p = tmp_path / "sm.csv"
    p.write_text("ticker,issuer_id\nA,A\n", encoding="utf-8")
    with pytest.raises(SecurityMasterError, match="columns"):
        load_security_master(p)


@pytest.mark.unit
def test_run_build_master_end_to_end(tmp_path: Path) -> None:
    silver = make_silver(("AAA", "GOOG"))
    write_parquet(silver, tmp_path / "silver.parquet")
    curated = tmp_path / "curated.csv"
    curated.write_text(
        ",".join(CURATED_COLUMNS)
        + "\nGOOG,GOOGL,C,duplicate share class of GOOGL,false,\n",
        encoding="utf-8",
    )
    master = run_build_master(
        load_config(),
        silver_file=tmp_path / "silver.parquet",
        curated_file=curated,
        master_file=tmp_path / "out" / "sm.csv",
    )
    assert master.loc[master["ticker"] == "GOOG", "include_in_universe"].item() is False
    assert (tmp_path / "out" / "sm.csv").is_file()
    with pytest.raises(FileNotFoundError, match="ingest"):
        run_build_master(load_config(), silver_file=tmp_path / "nope.parquet")


@pytest.mark.unit
def test_normalise_curated_accepts_frame_directly() -> None:
    out = normalise_curated(make_curated([{"ticker": "AAA", "stitching_suspect": True}]))
    assert out.loc[0, "issuer_id"] == "AAA" and bool(out.loc[0, "stitching_suspect"]) is True
