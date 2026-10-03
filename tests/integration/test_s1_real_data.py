"""S1 acceptance tests on the real frozen dataset (``needs_data``; auto-skipped if absent).

The pipeline runs once per module into a temporary directory; nothing under ``data/`` is written.
Expected numbers come from Part I Section I.3 and ``configs/data_expectations.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.ingest import run_ingest
from nasdaq100.data.validate import run_validate
from nasdaq100.paths import raw_csv_path, raw_zip_path
from nasdaq100.utils.calendar import TradingCalendar, rebalance_dates

EXPECTED_ZIP_SHA256 = "e70ce876b218b8af9d891a3c47c471f2a039698614697c60b6be5ad32537e8d2"

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def s1(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("s1_real")
    csv_p = raw_csv_path() if raw_csv_path().is_file() else tmp / raw_csv_path().name
    ingest_kw = {
        "zip_path": raw_zip_path(),
        "csv_path": csv_p,
        "manifest_file": tmp / "MANIFEST.json",
        "bronze_file": tmp / "prices_bronze.parquet",
        "calendar_file": tmp / "calendar.parquet",
    }
    manifest = run_ingest(**ingest_kw)
    cfg = load_config()
    report = run_validate(
        cfg,
        bronze_file=ingest_kw["bronze_file"],
        calendar_file=ingest_kw["calendar_file"],
        manifest_file=ingest_kw["manifest_file"],
        silver_file=tmp / "prices_silver.parquet",
        report_file=tmp / "validation_report.json",
        markdown_file=tmp / "data_quality_report.md",
    )
    return {
        "tmp": tmp,
        "kw": ingest_kw,
        "manifest": manifest,
        "report": report,
        "bronze": pd.read_parquet(ingest_kw["bronze_file"]),
        "silver": pd.read_parquet(tmp / "prices_silver.parquet"),
        "calendar": TradingCalendar.load(ingest_kw["calendar_file"]),
        "cfg": cfg,
    }


def _check(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in report["checks"] if c["name"] == name)


def test_dataset_dimensions_and_manifest(s1: dict[str, Any]) -> None:
    m = s1["manifest"]
    assert m["rows"] == 514_075 and len(s1["bronze"]) == 514_075
    assert m["n_tickers"] == 100 and s1["bronze"]["ticker"].nunique() == 100
    assert (m["date_min"], m["date_max"]) == ("2000-01-03", "2026-02-18")
    assert s1["calendar"].n_days == 6_571
    if raw_zip_path().is_file():
        assert m["sha256"] == EXPECTED_ZIP_SHA256


def test_zero_hard_check_failures(s1: dict[str, Any]) -> None:
    st = s1["report"]["status"]
    assert st["hard_checks_passed"] is True and st["hard_failures"] == []
    hard = [c for c in s1["report"]["checks"] if c["severity"] == "hard"]
    assert len(hard) == 9 and all(c["passed"] for c in hard)


def test_soft_checks_reproduce_expectations(s1: dict[str, Any]) -> None:
    report = s1["report"]
    expected = [c for c in report["checks"] if c["name"].startswith("expected_")]
    assert len(expected) == 7 and all(c["passed"] for c in expected)
    assert _check(report, "tickers_ending_before_global_last_date")["count"] == 0
    assert "zero_volume_share_by_ticker" in report["status"]["soft_warnings"]  # AZN
    assert _check(report, "largest_abs_close_returns")["count"] == 27
    corr = _check(report, "goog_googl_return_correlation")["examples"][0]["correlation"]
    assert 0.99 < corr < 1.0
    assert report["dataset_status"] == "SURVIVOR-BIASED"


def test_flag_counts_match_guide(s1: dict[str, Any]) -> None:
    silver = s1["silver"]
    assert len(silver) == len(s1["bronze"])  # flags never remove rows
    azn = silver[silver["ticker"] == "AZN"]
    assert int(azn["flag_zero_volume"].sum()) == 1_459
    assert int(silver["flag_zero_volume"].sum()) == 1_594
    assert int((silver["close"] < 5).sum()) == 48_646
    assert int(silver["flag_tick_noise"].sum()) == 48_646


@pytest.mark.parametrize(
    ("ticker", "date"),
    [
        ("KDP", "2018-07-10"),
        ("BKR", "2017-07-05"),
        ("MDLZ", "2012-10-02"),
        ("TMUS", "2013-05-01"),
    ],
)
def test_corp_action_suspect_fires_on_reference_events(
    s1: dict[str, Any], ticker: str, date: str
) -> None:
    silver = s1["silver"]
    row = silver[(silver["ticker"] == ticker) & (silver["date"] == pd.Timestamp(date))]
    assert len(row) == 1 and bool(row["flag_corp_action_suspect"].iloc[0])
    events = s1["report"]["corp_action_suspect_events"]
    assert any(e["ticker"] == ticker and e["date"] == date for e in events)


def test_tick_noise_example_is_flagged(s1: dict[str, Any]) -> None:
    silver = s1["silver"]
    row = silver[(silver["ticker"] == "NFLX") & (silver["date"] == pd.Timestamp("2002-10-18"))]
    assert bool(row["flag_tick_noise"].iloc[0])


def test_n_obs_and_ordering(s1: dict[str, Any]) -> None:
    silver = s1["silver"]
    counts = silver.groupby("ticker")["n_obs"].agg(["min", "max", "size"])
    assert (counts["min"] == 1).all() and (counts["max"] == counts["size"]).all()
    assert counts["size"].min() == 609 and counts["size"].max() == 6_571  # ARM ... full history
    keys = silver[["ticker", "date"]]
    assert keys.equals(keys.sort_values(["ticker", "date"]).reset_index(drop=True))


def test_calendar_key_indices_and_rebalance_schedule(s1: dict[str, Any]) -> None:
    cal = s1["calendar"]
    assert cal.idx_of("2001-01-02") == 252
    assert cal.idx_of("2008-01-02") == 2_010
    assert cal.idx_of("2019-11-29") == 5_009
    assert cal.idx_of("2020-01-02") == 5_031
    assert cal.last_idx == 6_570 and cal.date_at(6_549) == pd.Timestamp("2026-01-16")
    reb = rebalance_dates(s1["cfg"], cal)
    assert reb["date"].iloc[0] == pd.Timestamp("2001-01-02")
    assert reb["t_idx"].iloc[1] == 272


def test_reports_written_and_labelled(s1: dict[str, Any]) -> None:
    md = (Path(s1["tmp"]) / "data_quality_report.md").read_text(encoding="utf-8")
    assert "SURVIVOR-BIASED" in md and "KDP" in md and "514,075" in md
    assert (Path(s1["tmp"]) / "validation_report.json").is_file()


def test_reingest_is_idempotent_and_frozen_guard_holds(s1: dict[str, Any]) -> None:
    again = run_ingest(**s1["kw"])
    assert again == s1["manifest"]
