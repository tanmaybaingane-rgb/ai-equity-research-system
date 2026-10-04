"""Stage S3: adjusted price series and returns.

The one price representation used by all modelling and backtesting (Decision D3).

``Close`` / ``Open`` / ``High`` / ``Low`` are split-adjusted only; ``Adj Close`` is split *and*
dividend adjusted. ``adj_factor = adj_close / close`` is the cumulative dividend adjustment (1.0
on a ticker's last date, below 1.0 earlier for dividend payers). Multiplying open/high/low by it
puts all four prices on the same total-return basis, so ``adj_open`` and ``adj_close`` can be
compared. Ratios of adjusted prices are total returns; the *level* of an adjusted price is
meaningless (it changes whenever a new dividend is paid), so levels must never become features.

Flags are not carried: join them from silver when needed. Rows are never dropped: eligibility
is decided only in the universe (``load_universe``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from nasdaq100.data.ingest import read_manifest
from nasdaq100.data.security_master import read_silver
from nasdaq100.paths import adjusted_prices_path, calendar_path, manifest_path
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.utils.io import read_parquet, write_parquet
from nasdaq100.utils.logging import get_logger

if TYPE_CHECKING:
    from nasdaq100.config import Config

logger = get_logger("data.adjust")

ADJUSTED_COLUMNS: tuple[str, ...] = (
    "ticker",
    "date",
    "t_idx",
    "adj_factor",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "volume",
    "dollar_volume",
    "logret_cc",
)
SILVER_INPUT_COLUMNS: tuple[str, ...] = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
)
PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "adj_close")
#: Tolerance when reporting tickers whose ``adj_factor`` is not 1.0 on their last date.
LAST_FACTOR_TOL = 1e-9


class AdjustError(Exception):
    """Invalid inputs for the adjusted-series builder."""


def _check_inputs(silver: pd.DataFrame) -> None:
    """Fail loudly on inputs S1's hard checks should already have excluded."""
    missing = [c for c in SILVER_INPUT_COLUMNS if c not in silver.columns]
    if missing:
        raise AdjustError(f"Silver table is missing columns: {missing}")
    if len(silver) == 0:
        raise AdjustError("Silver table is empty")
    if silver[list(SILVER_INPUT_COLUMNS)].isna().any().any():
        raise AdjustError("Silver table contains NaN in price, volume, ticker or date columns")
    for col in PRICE_COLUMNS:
        if not (silver[col].to_numpy(dtype="float64") > 0).all():
            raise AdjustError(f"Silver column {col!r} contains non-positive values")
    if silver.duplicated(["ticker", "date"]).any():
        raise AdjustError("Silver table has duplicate (ticker, date) rows")


def _calendar_of(calendar: TradingCalendar | pd.DataFrame) -> TradingCalendar:
    return calendar if isinstance(calendar, TradingCalendar) else TradingCalendar(calendar)


def build_adjusted(silver: pd.DataFrame, calendar: TradingCalendar | pd.DataFrame) -> pd.DataFrame:
    """Build the adjusted-price table from silver and the trading calendar.

    Specification (Part III, S3):

    1. ``adj_factor = adj_close / close``; ``adj_open/high/low = field * adj_factor``;
       ``adj_close`` is carried unchanged. ``adj_low <= adj_open, adj_close <= adj_high`` holds
       exactly (high/low are widened by at most one ulp where float rounding would break it).
    2. ``dollar_volume = close * volume`` (split-adjusted close times split-adjusted volume is
       actual dollars traded; splits cancel).
    3. ``logret_cc = ln(adj_close_t / adj_close_{t-1})`` per ticker, NaN on a ticker's first row.
    4. ``t_idx`` comes from the calendar; ``t_idx`` must be consecutive within each ticker.
    5. Only the Section II.5 columns are kept; the row set equals silver's.

    The result is sorted by (ticker, date). Raises ``AdjustError`` on invalid input.
    """
    cal = _calendar_of(calendar)
    _check_inputs(silver)

    df = silver.loc[:, list(SILVER_INPUT_COLUMNS)].copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df = df.sort_values(["ticker", "date"], kind="mergesort").reset_index(drop=True)

    pos = cal.dates.get_indexer(pd.DatetimeIndex(df["date"]))
    if (pos < 0).any():
        bad = df.loc[pos < 0, "date"].iloc[0]
        raise AdjustError(f"Silver date {bad.date()} is not on the trading calendar")
    t_idx = pos.astype("int32")

    step = pd.Series(t_idx, dtype="int64").groupby(df["ticker"].to_numpy()).diff()
    bad_step = step.notna() & (step != 1)
    if bad_step.any():
        row = df.loc[bad_step.to_numpy()].iloc[0]
        raise AdjustError(
            f"t_idx is not consecutive within ticker {row['ticker']} at {row['date'].date()} "
            "(internal calendar gap; S1 validation should have caught this)"
        )

    close = df["close"].to_numpy(dtype="float64")
    adj_close = df["adj_close"].to_numpy(dtype="float64")
    factor = adj_close / close

    adj_open = df["open"].to_numpy(dtype="float64") * factor
    # ``adj_close`` is the vendor value, not ``close * factor``; the two can differ by one ulp.
    # Where the bar's high (low) equals the close that would break ``adj_close <= adj_high``
    # (``adj_low <= adj_close``) at the 1e-16 level, so the extremes are widened by that ulp to
    # keep the ordering exact. S1's OHLC hard checks guarantee the raw ordering.
    adj_high = np.maximum.reduce(
        [df["high"].to_numpy(dtype="float64") * factor, adj_open, adj_close]
    )
    adj_low = np.minimum.reduce(
        [df["low"].to_numpy(dtype="float64") * factor, adj_open, adj_close]
    )

    out = pd.DataFrame(
        {
            "ticker": df["ticker"],
            "date": df["date"],
            "t_idx": t_idx,
            "adj_factor": factor,
            "adj_open": adj_open,
            "adj_high": adj_high,
            "adj_low": adj_low,
            "adj_close": adj_close,
            "volume": df["volume"].astype("int64"),
            "dollar_volume": close * df["volume"].to_numpy(dtype="float64"),
        }
    )
    prev_adj = out.groupby("ticker", sort=False)["adj_close"].shift(1)
    out["logret_cc"] = np.log(out["adj_close"] / prev_adj)
    return out.loc[:, list(ADJUSTED_COLUMNS)].reset_index(drop=True)


def run_build_adjusted(
    cfg: Config,
    *,
    silver_file: Path | str | None = None,
    calendar_file: Path | str | None = None,
    adjusted_file: Path | str | None = None,
) -> pd.DataFrame:
    """Build and write ``data/processed/{variant}/adjusted_prices.parquet``.

    Requires ``prices_silver.parquet`` and ``calendar.parquet`` (S1: ``ingest`` and ``validate``).
    The table does not depend on any configuration key; it is written per variant so that
    variant pipelines find all their inputs in one directory.
    """
    silver = read_silver(silver_file)
    cal_path = Path(calendar_file) if calendar_file is not None else calendar_path()
    if not cal_path.is_file():
        raise FileNotFoundError(
            f"Calendar not found: {cal_path}. Run `python -m nasdaq100.cli ingest`."
        )
    calendar = TradingCalendar.load(cal_path)
    adjusted = build_adjusted(silver, calendar)
    out_path = (
        Path(adjusted_file)
        if adjusted_file is not None
        else adjusted_prices_path(cfg.project.variant)
    )
    write_parquet(adjusted, out_path)

    try:
        data_hash = read_manifest(manifest_path())["sha256"]
    except (FileNotFoundError, ValueError):
        data_hash = "unknown"
    last_factor = adjusted.groupby("ticker", sort=False)["adj_factor"].last()
    off = last_factor[(last_factor - 1.0).abs() > LAST_FACTOR_TOL]
    logger.info(
        "Adjusted prices [variant=%s, data hash %s]: %d rows, %d tickers, %d NaN logret_cc "
        "(first rows) -> %s",
        cfg.project.variant,
        str(data_hash)[:12],
        len(adjusted),
        adjusted["ticker"].nunique(),
        int(adjusted["logret_cc"].isna().sum()),
        out_path.name,
    )
    if len(off):
        logger.warning(
            "adj_factor is not 1.0 on the last date for %d ticker(s): %s",
            len(off),
            ", ".join(off.index.astype(str)[:10]),
        )
    return adjusted


def load_adjusted(cfg: Config, path: Path | str | None = None) -> pd.DataFrame:
    """Return the stored adjusted-price table for ``cfg.project.variant``.

    The only supported way for later stages to obtain adjusted prices and ``logret_cc``.
    """
    p = Path(path) if path is not None else adjusted_prices_path(cfg.project.variant)
    if not p.is_file():
        raise FileNotFoundError(
            f"Adjusted prices not found for variant {cfg.project.variant!r}: {p}. "
            "Run `python -m nasdaq100.cli build-adjusted`."
        )
    df = read_parquet(p)
    if tuple(df.columns) != ADJUSTED_COLUMNS:
        raise AdjustError(
            f"{p.name}: columns {list(df.columns)} != expected {list(ADJUSTED_COLUMNS)}"
        )
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df
