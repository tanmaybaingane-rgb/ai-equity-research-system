"""Stage S1 validation: hard/soft checks, validation report and data-quality report.

*Hard* checks guard assumptions later stages rely on and raise ``ValidationError`` on failure.
*Soft* checks compare the data with ``configs/data_expectations.yaml`` or describe it; failures
are logged as warnings and never raise. Problems are measured and flagged, never removed.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import yaml

from nasdaq100 import paths
from nasdaq100.config import config_hash
from nasdaq100.data.flags import FLAG_COLUMNS, add_flags, corp_action_events
from nasdaq100.data.ingest import BRONZE_COLUMNS, PRICE_COLUMNS, read_manifest
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.utils.io import read_parquet, write_parquet
from nasdaq100.utils.logging import get_logger

if TYPE_CHECKING:
    from nasdaq100.config import Config

logger = get_logger("data.validate")

SURVIVOR_LABEL = "SURVIVOR-BIASED"
GOOG_GOOGL_MIN_CORR = 0.99  # guide I.3 measured 0.997
_MAX_EXAMPLES = 5


class ValidationError(Exception):
    """One or more hard validation checks failed."""

    def __init__(self, message: str, failures: list[CheckResult] | None = None) -> None:
        super().__init__(message)
        self.failures = failures or []


@dataclass
class CheckResult:
    """Outcome of one check: name, severity ('hard'/'soft'), pass/fail, counts, examples."""

    name: str
    severity: str
    passed: bool
    count: int
    message: str
    examples: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity,
            "passed": bool(self.passed),
            "count": int(self.count),
            "message": self.message,
            "examples": _jsonable(self.examples),
        }


def _jsonable(obj: Any) -> Any:
    """Convert numpy/pandas scalars (and containers of them) to plain JSON types."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if pd.isna(obj) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj


def _hard(name: str, bad: int, message: str, examples: Iterable[Any] = ()) -> CheckResult:
    return CheckResult(name, "hard", bad == 0, int(bad), message, list(examples)[:_MAX_EXAMPLES])


def _soft(
    name: str, passed: bool, count: int, message: str, examples: Iterable[Any] = ()
) -> CheckResult:
    return CheckResult(name, "soft", bool(passed), int(count), message, list(examples)[:10])


def _key_examples(df: pd.DataFrame, mask: pd.Series | np.ndarray) -> list[dict[str, Any]]:
    sub = df.loc[mask, ["ticker", "date"]].head(_MAX_EXAMPLES)
    return [{"ticker": t, "date": d} for t, d in zip(sub["ticker"], sub["date"], strict=True)]


# --------------------------------------------------------------------------- hard checks


def check_schema(df: pd.DataFrame) -> CheckResult:
    """Exact bronze column list (in order) and dtypes."""
    problems: list[str] = []
    cols = tuple(df.columns)
    if cols != BRONZE_COLUMNS:
        problems.append(f"columns {list(cols)} != {list(BRONZE_COLUMNS)}")
    else:
        if not pd.api.types.is_string_dtype(df["ticker"]):
            problems.append(f"ticker dtype {df['ticker'].dtype} is not string")
        if str(df["date"].dtype) != "datetime64[ns]":
            problems.append(f"date dtype {df['date'].dtype} != datetime64[ns]")
        for c in PRICE_COLUMNS:
            if str(df[c].dtype) != "float64":
                problems.append(f"{c} dtype {df[c].dtype} != float64")
        if str(df["volume"].dtype) != "int64":
            problems.append(f"volume dtype {df['volume'].dtype} != int64")
    return _hard("schema", len(problems), "exact columns and dtypes" if not problems else
                 "; ".join(problems), problems)


def check_no_nan(df: pd.DataFrame) -> CheckResult:
    per_col = df.isna().sum()
    per_col = per_col[per_col > 0]
    return _hard(
        "no_nan", int(per_col.sum()), "no missing values" if per_col.empty else
        f"missing values in {dict(per_col)}", [f"{c}: {int(n)}" for c, n in per_col.items()]
    )


def check_no_duplicates(df: pd.DataFrame) -> CheckResult:
    dup = df.duplicated(["ticker", "date"], keep=False)
    n = int(df.duplicated(["ticker", "date"]).sum())
    return _hard("no_duplicate_keys", n, f"{n} duplicate (ticker, date) rows",
                 _key_examples(df, dup))


def check_sorted(df: pd.DataFrame) -> CheckResult:
    ordered = df[["ticker", "date"]].sort_values(["ticker", "date"], kind="stable")
    moved = ordered.index.to_numpy() != df.index.to_numpy()
    n = int(moved.sum())
    return _hard("sorted_by_ticker_date", n, f"{n} rows out of (ticker, date) order",
                 _key_examples(df, moved))


def check_prices_positive(df: pd.DataFrame) -> CheckResult:
    bad = ~(df[list(PRICE_COLUMNS)] > 0).all(axis=1)
    n = int(bad.sum())
    return _hard("prices_positive", n, f"{n} rows with a non-positive or NaN price",
                 _key_examples(df, bad))


def check_ohlc_consistency(df: pd.DataFrame) -> list[CheckResult]:
    """high >= low, high >= max(open, close), low <= min(open, close)."""
    conds = {
        "ohlc_high_ge_low": df["high"] < df["low"],
        "ohlc_high_ge_open_close": df["high"] < df[["open", "close"]].max(axis=1),
        "ohlc_low_le_open_close": df["low"] > df[["open", "close"]].min(axis=1),
    }
    return [
        _hard(name, int(bad.sum()), f"{int(bad.sum())} rows violate {name}", _key_examples(df, bad))
        for name, bad in conds.items()
    ]


def check_calendar_gaps(df: pd.DataFrame, calendar: TradingCalendar) -> CheckResult:
    """Each ticker's rows must occupy consecutive ``t_idx`` between its first and last date.

    Stages S4/S5 rely on this so that row shifts equal trading-day shifts.
    """
    pos = pd.Series(np.arange(calendar.n_days), index=calendar.dates)
    t = pos.reindex(pd.DatetimeIndex(df["date"])).to_numpy()
    unknown = int(np.isnan(t).sum())
    frame = pd.DataFrame({"ticker": df["ticker"].to_numpy(), "t": t}).dropna()
    agg = frame.groupby("ticker")["t"].agg(["min", "max", "nunique"])
    bad = agg[(agg["max"] - agg["min"] + 1) != agg["nunique"]]
    examples: list[dict[str, Any]] = [
        {"issue": "date not on calendar", "n_rows": unknown}
    ] if unknown else []
    for ticker, row in bad.head(_MAX_EXAMPLES).iterrows():
        have = set(frame.loc[frame["ticker"] == ticker, "t"].astype(int))
        missing = sorted(set(range(int(row["min"]), int(row["max"]) + 1)) - have)
        examples.append({
            "ticker": ticker,
            "missing_dates": int(len(missing)),
            "first_missing": calendar.date_at(missing[0]) if missing else None,
        })
    n = int(len(bad)) + (1 if unknown else 0)
    return _hard("no_internal_calendar_gaps", n,
                 f"{len(bad)} tickers with internal gaps; {unknown} rows off the calendar",
                 examples)


def run_hard_checks(df: pd.DataFrame, calendar: TradingCalendar) -> list[CheckResult]:
    """Run all hard checks. If the schema check fails, the rest cannot run and are skipped."""
    schema = check_schema(df)
    if not schema.passed:
        return [schema]
    return [
        schema,
        check_no_nan(df),
        check_no_duplicates(df),
        check_sorted(df),
        check_prices_positive(df),
        *check_ohlc_consistency(df),
        check_calendar_gaps(df, calendar),
    ]


def raise_for_hard_failures(results: Iterable[CheckResult]) -> None:
    """Raise ``ValidationError`` listing every failed hard check."""
    failed = [r for r in results if r.severity == "hard" and not r.passed]
    if failed:
        detail = "; ".join(f"{r.name}: {r.message}" for r in failed)
        raise ValidationError(f"{len(failed)} hard validation check(s) failed: {detail}", failed)


# --------------------------------------------------------------------------- soft checks


def load_expectations(path: Path | str | None = None) -> dict[str, Any]:
    """Load ``configs/data_expectations.yaml``."""
    p = Path(path) if path is not None else paths.data_expectations_path()
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _compare(name: str, actual: Any, expected: Any, label: str) -> CheckResult:
    ok = actual == expected
    return _soft(name, ok, 0 if ok else 1, f"{label}: actual {actual}, expected {expected}",
                 [{"actual": actual, "expected": expected}])


def run_soft_checks(
    df: pd.DataFrame, calendar: TradingCalendar, cfg: Config, expectations: dict[str, Any]
) -> list[CheckResult]:
    """Informational checks. ``passed=False`` is a warning, never an exception."""
    out: list[CheckResult] = []
    dims = expectations.get("dimensions", {})
    qual = expectations.get("quality", {})
    date_min = df["date"].min().strftime("%Y-%m-%d")
    date_max = df["date"].max().strftime("%Y-%m-%d")

    if "expected_rows" in dims:
        out.append(_compare("expected_rows", len(df), dims["expected_rows"], "row count"))
    if "expected_tickers" in dims:
        out.append(_compare("expected_tickers", int(df["ticker"].nunique()),
                            dims["expected_tickers"], "ticker count"))
    if "expected_trading_days" in dims:
        out.append(_compare("expected_trading_days", calendar.n_days,
                            dims["expected_trading_days"], "calendar dates"))
    if "expected_date_min" in dims and "expected_date_max" in dims:
        out.append(_compare("expected_date_range", [date_min, date_max],
                            [dims["expected_date_min"], dims["expected_date_max"]], "date range"))

    # Survivorship indicator: tickers that stop before the global last date.
    last = df.groupby("ticker")["date"].max()
    early = last[last < last.max()]
    out.append(_soft(
        "tickers_ending_before_global_last_date", len(early) == 0, len(early),
        f"{len(early)} tickers end before {date_max}. "
        + ("Zero delistings/acquisitions INDICATES survivorship bias." if len(early) == 0
           else "Dataset contains some exits."),
        [{"ticker": t, "last_date": d} for t, d in early.head(10).items()],
    ))

    # Zero volume
    zero = df["volume"] == 0
    share = zero.groupby(df["ticker"]).mean()
    rows = zero.groupby(df["ticker"]).sum()
    limit = cfg.flags.max_zero_volume_share_ticker
    over = share[share > limit].sort_values(ascending=False)
    out.append(_soft(
        "zero_volume_share_by_ticker", len(over) == 0, len(over),
        f"{len(over)} tickers exceed the zero-volume share limit {limit:.0%}",
        [{"ticker": t, "share": float(s), "zero_rows": int(rows[t])} for t, s in over.items()],
    ))
    if "expected_zero_volume_total" in qual:
        out.append(_compare("expected_zero_volume_total", int(zero.sum()),
                            qual["expected_zero_volume_total"], "zero-volume rows"))
    if "expected_azn_zero_volume" in qual and (df["ticker"] == "AZN").any():
        out.append(_compare("expected_azn_zero_volume", int(rows.get("AZN", 0)),
                            qual["expected_azn_zero_volume"], "AZN zero-volume rows"))

    # Tick noise by year
    low = df["close"] < cfg.flags.tick_noise_min_close
    by_year = low.groupby(df["date"].dt.year).sum()
    out.append(_soft(
        "close_below_tick_noise_by_year", True, int(low.sum()),
        f"{int(low.sum())} rows with close < {cfg.flags.tick_noise_min_close}",
        [{"year": int(y), "rows": int(n)} for y, n in by_year.items()],
    ))
    if "expected_close_under_5_rows" in qual and cfg.flags.tick_noise_min_close == 5.0:
        out.append(_compare("expected_close_under_5_rows", int(low.sum()),
                            qual["expected_close_under_5_rows"], "rows with close < 5"))

    # Largest absolute close returns
    ret = df.groupby("ticker", sort=False)["close"].pct_change()
    big = ret.abs().sort_values(ascending=False).head(10)
    out.append(_soft(
        "largest_abs_close_returns", True, int((ret.abs() > 0.40).sum()),
        f"{int((ret.abs() > 0.40).sum())} rows with |close return| > 40% (see examples: top 10)",
        [{"ticker": df.at[i, "ticker"], "date": df.at[i, "date"], "close_return": float(ret[i])}
         for i in big.index],
    ))

    # Share-class duplicate
    if {"GOOG", "GOOGL"} <= set(df["ticker"].unique()):
        wide = np.log(df.pivot(index="date", columns="ticker", values="adj_close")[["GOOG", "GOOGL"]])
        corr = float(wide.diff().corr().iloc[0, 1])
        out.append(_soft(
            "goog_googl_return_correlation", corr >= GOOG_GOOGL_MIN_CORR, 0,
            f"GOOG/GOOGL daily log-return correlation {corr:.4f} (two share classes of one issuer)",
            [{"correlation": corr}],
        ))
    return out


# --------------------------------------------------------------------------- reporting


def _flag_tables(silver: pd.DataFrame) -> dict[str, Any]:
    flags = list(FLAG_COLUMNS)
    by_year = silver.groupby(silver["date"].dt.year)[flags].sum().astype(int)
    by_ticker = silver.groupby("ticker")[flags].sum().astype(int)
    return {
        "total": {f: int(silver[f].sum()) for f in flags},
        "by_year": {str(y): {f: int(r[f]) for f in flags} for y, r in by_year.iterrows()},
        "by_ticker": {str(t): {f: int(r[f]) for f in flags} for t, r in by_ticker.iterrows()},
    }


def build_report(
    results: list[CheckResult],
    *,
    silver: pd.DataFrame | None,
    calendar: TradingCalendar | None,
    cfg: Config,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the JSON-serialisable validation report (also the input of the markdown)."""
    hard_failed = [r.name for r in results if r.severity == "hard" and not r.passed]
    soft_failed = [r.name for r in results if r.severity == "soft" and not r.passed]
    report: dict[str, Any] = {
        "dataset_status": SURVIVOR_LABEL,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "data_hash": manifest["sha256"] if manifest else None,
        "config_hash": config_hash(cfg),
        "status": {
            "hard_checks_passed": not hard_failed,
            "hard_failures": hard_failed,
            "soft_warnings": soft_failed,
        },
        "flag_thresholds": cfg.flags.model_dump(mode="json"),
        "checks": [r.to_dict() for r in results],
    }
    if silver is None or calendar is None:
        return report

    last = silver.groupby("ticker")["date"].max()
    first = silver.groupby("ticker")["date"].min()
    early = last[last < last.max()]
    events = corp_action_events(silver)
    report["dataset"] = {
        "rows": int(len(silver)),
        "tickers": int(silver["ticker"].nunique()),
        "trading_days": int(calendar.n_days),
        "date_min": silver["date"].min(),
        "date_max": silver["date"].max(),
        "manifest": manifest,
    }
    report["flags"] = _flag_tables(silver)
    report["corp_action_suspect_events"] = [
        {
            "ticker": r.ticker, "date": r.date, "prev_close": r.prev_close, "close": r.close,
            "close_logret": r.logret_close, "adj_close_logret": r.logret_adj, "gap": r.gap,
        }
        for r in events.itertuples()
    ]
    report["survivorship"] = {
        "tickers_total": int(len(last)),
        "tickers_present_on_first_date": int((first == silver["date"].min()).sum()),
        "tickers_ending_before_global_last_date": [str(t) for t in early.index],
        "indicator": (
            "No ticker exits before the final date (no delistings or acquisitions): the data "
            "contains only survivors." if len(early) == 0
            else f"{len(early)} tickers exit before the final date."
        ),
        "label": SURVIVOR_LABEL,
    }
    return _jsonable(report)


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(v: Any) -> str:
        if isinstance(v, float):
            return f"{v:.4f}"
        return "" if v is None else str(v).replace("|", "\\|")

    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join([":---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    """Render ``docs/data_quality_report.md`` from the validation report dictionary."""
    st = report["status"]
    out = [
        "# Data Quality Report",
        "",
        f"> **Dataset status: {report['dataset_status']}.** All results derived from this dataset "
        "carry this label (Decision D1). Generated by `python -m nasdaq100.cli validate`; "
        "do not edit by hand.",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Data hash (SHA-256 of the frozen archive): `{report['data_hash']}`",
        f"- Hard checks: **{'PASSED' if st['hard_checks_passed'] else 'FAILED'}**"
        + ("" if st["hard_checks_passed"] else f" ({', '.join(st['hard_failures'])})"),
        f"- Soft warnings: {', '.join(st['soft_warnings']) if st['soft_warnings'] else 'none'}",
        "",
    ]
    ds = report.get("dataset")
    if ds:
        out += ["## Dataset facts", "", _md_table(["Fact", "Value"], [
            ["Rows", f"{ds['rows']:,}"], ["Tickers", ds["tickers"]],
            ["Trading days (calendar)", f"{ds['trading_days']:,}"],
            ["Date range", f"{ds['date_min']} to {ds['date_max']}"],
        ]), ""]
    out += ["## Checks", "", _md_table(
        ["Check", "Severity", "Result", "Count", "Detail"],
        [[c["name"], c["severity"], "PASS" if c["passed"] else "FAIL", c["count"], c["message"]]
         for c in report["checks"]]), ""]
    fl = report.get("flags")
    if fl:
        names = list(FLAG_COLUMNS)
        short = [n.removeprefix("flag_") for n in names]
        out += ["## Flag counts", "", "Flags mark rows; no rows are removed.", "",
                "### Total", "", _md_table(short, [[fl["total"][n] for n in names]]), "",
                "### By year", "", _md_table(["year", *short], [
                    [y, *[v[n] for n in names]] for y, v in fl["by_year"].items()]), "",
                "### By ticker", "", _md_table(["ticker", *short], [
                    [t, *[v[n] for n in names]] for t, v in fl["by_ticker"].items()]), ""]
        ev = report.get("corp_action_suspect_events", [])
        out += [f"## Suspected corporate-action events ({len(ev)})", "",
                "`Close` is not adjusted for special dividends/spin-offs; `Adj Close` is. A large "
                "gap between the two log returns marks a suspect event.", "",
                _md_table(["ticker", "date", "prev close", "close", "close logret",
                           "adj logret", "gap"],
                          [[e["ticker"], e["date"], e["prev_close"], e["close"],
                            e["close_logret"], e["adj_close_logret"], e["gap"]] for e in ev]), ""]
    sv = report.get("survivorship")
    if sv:
        out += ["## Survivorship indicator", "", f"- Tickers: {sv['tickers_total']}",
                f"- Present on first date: {sv['tickers_present_on_first_date']}",
                f"- Tickers ending before the final date: "
                f"{len(sv['tickers_ending_before_global_last_date'])}",
                f"- {sv['indicator']}", "",
                f"**This dataset is `{sv['label']}`**: absolute returns, base rates and SELL-signal "
                "validation are optimistic; relative comparisons on identical data are more robust.",
                ""]
    return "\n".join(out)


# --------------------------------------------------------------------------- orchestration


def _load_typed(path: Path) -> pd.DataFrame:
    df = read_parquet(path)
    if pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["date"] = df["date"].astype("datetime64[ns]")
    return df


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def run_validate(
    cfg: Config,
    *,
    bronze_file: Path | str | None = None,
    calendar_file: Path | str | None = None,
    manifest_file: Path | str | None = None,
    expectations_file: Path | str | None = None,
    silver_file: Path | str | None = None,
    report_file: Path | str | None = None,
    markdown_file: Path | str | None = None,
) -> dict[str, Any]:
    """Validate bronze, write silver (flagged) + JSON report + markdown report.

    On a hard-check failure the (failed) reports are still written for diagnosis, silver is
    NOT written, and ``ValidationError`` is raised. Returns the report dictionary.
    """
    bronze_p = Path(bronze_file) if bronze_file is not None else paths.prices_bronze_path()
    cal_p = Path(calendar_file) if calendar_file is not None else paths.calendar_path()
    silver_p = Path(silver_file) if silver_file is not None else paths.prices_silver_path()
    report_p = Path(report_file) if report_file is not None else paths.validation_report_path()
    md_p = Path(markdown_file) if markdown_file is not None else paths.data_quality_report_path()
    manifest_p = Path(manifest_file) if manifest_file is not None else paths.manifest_path()

    for p in (bronze_p, cal_p):
        if not p.is_file():
            raise FileNotFoundError(f"{p} not found. Run `python -m nasdaq100.cli ingest` first.")
    bronze = _load_typed(bronze_p)
    calendar = TradingCalendar.load(cal_p)
    manifest = read_manifest(manifest_p) if manifest_p.is_file() else None

    results = run_hard_checks(bronze, calendar)
    failed = [r for r in results if not r.passed]
    if failed:
        for r in failed:
            logger.error("HARD check failed: %s - %s", r.name, r.message)
        report = build_report(results, silver=None, calendar=None, cfg=cfg, manifest=manifest)
        _write_text(report_p, json.dumps(report, indent=2))
        _write_text(md_p, render_markdown(report))
        raise_for_hard_failures(results)

    silver = add_flags(bronze, cfg.flags)
    expectations = load_expectations(expectations_file)
    soft = run_soft_checks(bronze, calendar, cfg, expectations)
    for r in soft:
        if not r.passed:
            logger.warning("Soft check: %s - %s", r.name, r.message)
    results = results + soft

    report = build_report(results, silver=silver, calendar=calendar, cfg=cfg, manifest=manifest)
    write_parquet(silver, silver_p)
    _write_text(report_p, json.dumps(report, indent=2))
    _write_text(md_p, render_markdown(report))
    logger.info(
        "Validation complete: %d hard checks passed, %d soft warnings; silver rows %d",
        sum(r.severity == "hard" for r in results),
        len(report["status"]["soft_warnings"]),
        len(silver),
    )
    return report
