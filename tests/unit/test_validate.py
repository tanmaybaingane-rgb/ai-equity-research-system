"""Unit tests for S1 validation: hard/soft checks, reports and orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.flags import add_flags
from nasdaq100.data.ingest import run_ingest
from nasdaq100.data.validate import (
    CheckResult,
    ValidationError,
    check_calendar_gaps,
    raise_for_hard_failures,
    render_markdown,
    run_hard_checks,
    run_soft_checks,
    run_validate,
)
from nasdaq100.utils.calendar import TradingCalendar
from tests.fixtures.s1_prices import make_clean_raw_prices, to_bronze


def _bronze(**kw) -> pd.DataFrame:
    return to_bronze(make_clean_raw_prices(**kw))


def _cal(df: pd.DataFrame) -> TradingCalendar:
    return TradingCalendar.from_dates(df["date"])


def _failed(df: pd.DataFrame, cal: TradingCalendar | None = None) -> dict[str, CheckResult]:
    results = run_hard_checks(df, cal or _cal(df))
    return {r.name: r for r in results if not r.passed}


def _idx(df: pd.DataFrame, ticker: str, k: int) -> int:
    return int(df.index[df["ticker"] == ticker][k])


@pytest.mark.unit
def test_clean_data_passes_every_hard_check() -> None:
    df = _bronze(start_offsets={"BBB": 4})  # staggered listing is not a gap
    results = run_hard_checks(df, _cal(df))
    assert len(results) == 9
    assert all(r.severity == "hard" and r.passed for r in results)
    raise_for_hard_failures(results)  # does not raise


@pytest.mark.unit
def test_schema_failure_raises_and_skips_other_checks() -> None:
    df = _bronze().drop(columns=["volume"])
    results = run_hard_checks(df, _cal(_bronze()))
    assert [r.name for r in results] == ["schema"] and not results[0].passed
    with pytest.raises(ValidationError, match="schema"):
        raise_for_hard_failures(results)

    wrong_dtype = _bronze().assign(volume=lambda d: d["volume"].astype("float64"))
    assert "schema" in _failed(wrong_dtype, _cal(_bronze()))
    wrong_date = _bronze().assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d"))
    assert "schema" in _failed(wrong_date, _cal(_bronze()))


@pytest.mark.unit
def test_nan_raises() -> None:
    df = _bronze()
    df.loc[3, "close"] = float("nan")
    failed = _failed(df)
    assert "no_nan" in failed and failed["no_nan"].count == 1
    with pytest.raises(ValidationError):
        raise_for_hard_failures(run_hard_checks(df, _cal(df)))


@pytest.mark.unit
def test_duplicate_key_raises() -> None:
    df = _bronze()
    df = pd.concat([df, df.iloc[[5]]]).sort_values(["ticker", "date"], kind="stable")
    df = df.reset_index(drop=True)
    failed = _failed(df)
    assert failed["no_duplicate_keys"].count == 1
    assert failed["no_duplicate_keys"].examples[0]["ticker"] == "AAA"


@pytest.mark.unit
def test_unsorted_raises() -> None:
    df = _bronze().sort_values(["date", "ticker"]).reset_index(drop=True)  # date-major
    failed = _failed(df)
    assert "sorted_by_ticker_date" in failed and failed["sorted_by_ticker_date"].count > 0


@pytest.mark.unit
def test_non_positive_price_raises() -> None:
    for col in ("open", "high", "low", "close", "adj_close"):
        df = _bronze()
        df.loc[2, col] = 0.0
        assert "prices_positive" in _failed(df), col
    df = _bronze()
    df.loc[2, "adj_close"] = -1.0
    assert "prices_positive" in _failed(df)


@pytest.mark.unit
def test_ohlc_violations_raise() -> None:
    df = _bronze()
    df.loc[1, "high"] = df.loc[1, "low"] - 0.5
    assert "ohlc_high_ge_low" in _failed(df)

    df = _bronze()
    df.loc[1, "high"] = min(df.loc[1, "open"], df.loc[1, "close"]) + 0.001
    df.loc[1, "close"] = df.loc[1, "high"] + 0.5  # close above high
    assert "ohlc_high_ge_open_close" in _failed(df)

    df = _bronze()
    df.loc[1, "low"] = max(df.loc[1, "open"], df.loc[1, "close"]) + 0.5  # low above open/close
    assert "ohlc_low_le_open_close" in _failed(df)


@pytest.mark.unit
def test_internal_calendar_gap_raises() -> None:
    full = _bronze()
    cal = _cal(full)
    gap = full.drop(index=_idx(full, "AAA", 10)).reset_index(drop=True)  # hole inside AAA
    failed = _failed(gap, cal)
    assert "no_internal_calendar_gaps" in failed
    ex = failed["no_internal_calendar_gaps"].examples[0]
    assert ex["ticker"] == "AAA" and ex["missing_dates"] == 1
    assert ex["first_missing"] == cal.date_at(10)
    with pytest.raises(ValidationError, match="no_internal_calendar_gaps"):
        raise_for_hard_failures(run_hard_checks(gap, cal))


@pytest.mark.unit
def test_gap_check_ignores_late_listing_and_early_end_but_flags_off_calendar_dates() -> None:
    full = _bronze()
    cal = _cal(full)
    trimmed = full[~((full["ticker"] == "CCC") & (full.groupby("ticker").cumcount() >= 20))]
    assert check_calendar_gaps(trimmed.reset_index(drop=True), cal).passed  # ends early: fine
    late = _bronze(start_offsets={"CCC": 7})
    assert check_calendar_gaps(late, _cal(full)).passed  # starts late: fine

    off = _bronze()
    off.loc[0, "date"] = pd.Timestamp("2030-01-01")
    assert not check_calendar_gaps(off, cal).passed


def _expectations(df: pd.DataFrame) -> dict:
    return {
        "dimensions": {
            "expected_rows": len(df),
            "expected_tickers": df["ticker"].nunique(),
            "expected_trading_days": df["date"].nunique(),
            "expected_date_min": df["date"].min().strftime("%Y-%m-%d"),
            "expected_date_max": df["date"].max().strftime("%Y-%m-%d"),
        },
        "quality": {"expected_zero_volume_total": 0, "expected_close_under_5_rows": 0},
    }


@pytest.mark.unit
def test_soft_checks_pass_on_matching_expectations_and_warn_on_mismatch() -> None:
    df = _bronze()
    cfg = load_config()
    soft = {r.name: r for r in run_soft_checks(df, _cal(df), cfg, _expectations(df))}
    assert all(r.severity == "soft" for r in soft.values())
    assert soft["expected_rows"].passed and soft["expected_date_range"].passed
    assert soft["tickers_ending_before_global_last_date"].passed  # none end early (survivors)
    assert "survivorship" in soft["tickers_ending_before_global_last_date"].message.lower()

    wrong = _expectations(df)
    wrong["dimensions"]["expected_rows"] = len(df) + 1
    res = {r.name: r for r in run_soft_checks(df, _cal(df), cfg, wrong)}
    assert not res["expected_rows"].passed  # a warning only: nothing is raised


@pytest.mark.unit
def test_soft_checks_detect_early_exit_zero_volume_and_googl_correlation() -> None:
    df = _bronze(tickers=("GOOG", "GOOGL", "ZZZ"))
    # ZZZ stops 5 days early; GOOG/GOOGL both there
    df = df[~((df["ticker"] == "ZZZ") & (df.groupby("ticker").cumcount() >= 25))].reset_index(drop=True)
    zv = df["ticker"].eq("ZZZ") & df.groupby("ticker").cumcount().lt(10)
    df.loc[zv, "volume"] = 0  # 10 of 25 rows -> 40% zero volume
    cfg = load_config()
    soft = {r.name: r for r in run_soft_checks(df, _cal(df), cfg, {})}

    early = soft["tickers_ending_before_global_last_date"]
    assert not early.passed and early.count == 1 and early.examples[0]["ticker"] == "ZZZ"
    zvs = soft["zero_volume_share_by_ticker"]
    assert not zvs.passed and zvs.examples[0]["ticker"] == "ZZZ"
    assert zvs.examples[0]["zero_rows"] == 10
    assert "goog_googl_return_correlation" in soft  # present when both share classes exist
    assert "goog_googl_return_correlation" not in {
        r.name for r in run_soft_checks(_bronze(), _cal(_bronze()), cfg, {})
    }


def _ingest_and_paths(tmp: Path, raw: pd.DataFrame) -> dict[str, Path]:
    import zipfile

    p = {k: tmp / v for k, v in {
        "zip_path": "archive.zip", "csv_path": "data.csv", "manifest_file": "MANIFEST.json",
        "bronze_file": "bronze.parquet", "calendar_file": "calendar.parquet",
    }.items()}
    text = raw.assign(Date=raw["Date"].dt.strftime("%Y-%m-%d")).to_csv(index=False, lineterminator="\n")
    with zipfile.ZipFile(p["zip_path"], "w") as zf:
        zf.writestr("data.csv", text)
    run_ingest(**p)
    return p


def _validate_kwargs(tmp: Path, p: dict[str, Path], raw: pd.DataFrame) -> dict[str, Path]:
    import yaml

    exp = tmp / "expectations.yaml"
    exp.write_text(yaml.safe_dump(_expectations(to_bronze(raw))), encoding="utf-8")
    return {
        "bronze_file": p["bronze_file"], "calendar_file": p["calendar_file"],
        "manifest_file": p["manifest_file"], "expectations_file": exp,
        "silver_file": tmp / "silver.parquet", "report_file": tmp / "report.json",
        "markdown_file": tmp / "dq.md",
    }


@pytest.mark.unit
def test_run_validate_writes_silver_report_and_markdown(tmp_path: Path) -> None:
    raw = make_clean_raw_prices()
    raw.loc[raw.index[(raw["Ticker"] == "BBB")][5:], "Close"] *= 0.7  # special-dividend-like drop
    # keep the bars valid after editing Close
    raw["High"] = raw[["High", "Open", "Close"]].max(axis=1) + 0.05
    raw["Low"] = raw[["Open", "Close"]].min(axis=1) - 0.05
    p = _ingest_and_paths(tmp_path, raw)
    kw = _validate_kwargs(tmp_path, p, raw)
    report = run_validate(load_config(), **kw)

    silver = pd.read_parquet(kw["silver_file"])
    assert len(silver) == len(raw)  # no rows removed
    assert {"n_obs", "flag_tick_noise", "flag_corp_action_suspect"} <= set(silver.columns)
    assert silver["flag_corp_action_suspect"].sum() == 1

    on_disk = json.loads(kw["report_file"].read_text(encoding="utf-8"))
    assert on_disk["dataset_status"] == "SURVIVOR-BIASED" == report["dataset_status"]
    assert on_disk["status"]["hard_checks_passed"] is True
    assert on_disk["data_hash"] == json.loads(p["manifest_file"].read_text())["sha256"]
    assert len(on_disk["corp_action_suspect_events"]) == 1
    assert on_disk["corp_action_suspect_events"][0]["ticker"] == "BBB"
    assert set(on_disk["flags"]["by_ticker"]) == {"AAA", "BBB", "CCC"}
    assert on_disk["survivorship"]["tickers_ending_before_global_last_date"] == []

    md = kw["markdown_file"].read_text(encoding="utf-8")
    assert "SURVIVOR-BIASED" in md and "Survivorship indicator" in md
    assert "Suspected corporate-action events (1)" in md and "BBB" in md


@pytest.mark.unit
def test_run_validate_hard_failure_raises_writes_reports_but_not_silver(tmp_path: Path) -> None:
    raw = make_clean_raw_prices()
    raw = raw.drop(index=raw.index[(raw["Ticker"] == "AAA")][10])  # internal gap
    p = _ingest_and_paths(tmp_path, raw)
    kw = _validate_kwargs(tmp_path, p, raw)
    with pytest.raises(ValidationError, match="no_internal_calendar_gaps"):
        run_validate(load_config(), **kw)
    assert not kw["silver_file"].exists()  # silver only exists for validated data
    failed_report = json.loads(kw["report_file"].read_text(encoding="utf-8"))
    assert failed_report["status"]["hard_checks_passed"] is False
    assert failed_report["status"]["hard_failures"] == ["no_internal_calendar_gaps"]
    assert "FAILED" in kw["markdown_file"].read_text(encoding="utf-8")


@pytest.mark.unit
def test_run_validate_requires_ingest_first(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ingest"):
        run_validate(
            load_config(), bronze_file=tmp_path / "b.parquet", calendar_file=tmp_path / "c.parquet"
        )


@pytest.mark.unit
def test_render_markdown_handles_minimal_failed_report() -> None:
    report = {
        "dataset_status": "SURVIVOR-BIASED", "generated_at": "now", "data_hash": None,
        "status": {"hard_checks_passed": False, "hard_failures": ["schema"], "soft_warnings": []},
        "checks": [{"name": "schema", "severity": "hard", "passed": False, "count": 1,
                    "message": "bad", "examples": []}],
    }
    md = render_markdown(report)
    assert "FAILED" in md and "schema" in md and "SURVIVOR-BIASED" in md


@pytest.mark.unit
def test_silver_flags_match_add_flags_on_validated_data(tmp_path: Path) -> None:
    raw = make_clean_raw_prices()
    p = _ingest_and_paths(tmp_path, raw)
    kw = _validate_kwargs(tmp_path, p, raw)
    run_validate(load_config(), **kw)
    silver = pd.read_parquet(kw["silver_file"])
    expected = add_flags(pd.read_parquet(p["bronze_file"]), load_config().flags)
    pd.testing.assert_frame_equal(silver.reset_index(drop=True), expected.reset_index(drop=True))
