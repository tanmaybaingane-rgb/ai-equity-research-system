"""Stage S2: universe (eligibility) builder: the single place where eligibility is decided.

Time convention (Part II Section II.2): eligibility of (ticker, t) uses only that row's own data
and the same ticker's earlier rows (own observation count, trailing 63-observation median dollar
volume). It never uses ``last_date``, total history length or any later row. The only static,
ticker-level inputs are the security-master decisions (``include_in_universe``, ``cohort``,
``stitching_suspect``), which are curation choices and not functions of the row's future.

Survivorship: eligibility rules guard against garbage data and very recent listings; they do
NOT cure survivorship bias (see ``docs/survivorship.md``). A point-in-time membership provider
would plug in here as an extra boolean ANDed into ``eligible``; nothing else would change.

Later stages must read the universe through ``load_universe`` and never re-implement a filter.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from nasdaq100.data.ingest import read_manifest
from nasdaq100.data.security_master import load_security_master, read_silver
from nasdaq100.paths import manifest_path, universe_path
from nasdaq100.utils.io import read_parquet, write_parquet
from nasdaq100.utils.logging import get_logger

if TYPE_CHECKING:
    from nasdaq100.config import Config

logger = get_logger("data.universe")

FAIL_COLUMNS: tuple[str, ...] = (
    "fail_master",
    "fail_seasoning",
    "fail_min_close",
    "fail_zero_volume",
    "fail_liquidity",
)
UNIVERSE_COLUMNS: tuple[str, ...] = (
    "ticker",
    "date",
    "eligible",
    *FAIL_COLUMNS,
    "median_dollar_volume_63",
)
#: Trailing window (in observations) of the median dollar volume. Part of the feature name
#: ``universe.min_median_dollar_volume_63`` and of Decision D6.
LIQUIDITY_WINDOW = 63
#: ``universe.cohort_filter`` value -> ``security_master.cohort`` value. The configuration
#: reference (Part II Section II.4) calls the first cohort ``original55``; the security master
#: schema (Section II.5) stores it as ``orig2000``. Same 55 tickers (first date 2000-01-03).
COHORT_FILTER_TO_COHORT: dict[str, str] = {"original55": "orig2000", "later": "later"}
SILVER_INPUT_COLUMNS: tuple[str, ...] = ("ticker", "date", "close", "volume", "n_obs")


class UniverseError(Exception):
    """Invalid inputs or configuration for the universe builder."""


def master_fail_by_ticker(master: pd.DataFrame, universe_cfg: Any) -> pd.Series:
    """Ticker-indexed boolean: True where the security master excludes the ticker.

    ``fail_master`` = not ``include_in_universe``, or excluded by ``universe.cohort_filter``,
    or (``universe.drop_stitched`` and ``stitching_suspect``).
    """
    cohort_filter = universe_cfg.cohort_filter
    if cohort_filter is not None and cohort_filter not in COHORT_FILTER_TO_COHORT:
        raise UniverseError(
            f"universe.cohort_filter={cohort_filter!r} is invalid; "
            f"use null or one of {sorted(COHORT_FILTER_TO_COHORT)}"
        )
    fail = ~master["include_in_universe"].astype(bool)
    if cohort_filter is not None:
        fail = fail | (master["cohort"] != COHORT_FILTER_TO_COHORT[cohort_filter])
    if universe_cfg.drop_stitched:
        fail = fail | master["stitching_suspect"].astype(bool)
    return pd.Series(fail.to_numpy(dtype=bool), index=master["ticker"].astype(str).to_numpy())


def build_universe(silver: pd.DataFrame, master: pd.DataFrame, universe_cfg: Any) -> pd.DataFrame:
    """Compute the eligibility table for every (ticker, date) row of ``silver``.

    Returns exactly the ``UNIVERSE_COLUMNS`` (Part II Section II.5), sorted by (ticker, date),
    one row per silver row (nothing is dropped). Rules (D6, Part III S2):

    * ``dollar_volume = close * volume``; ``median_dollar_volume_63`` = trailing 63-observation
      median including the current row, NaN until 63 observations (``min_periods=63``)
    * ``fail_seasoning = n_obs <= seasoning_days`` (eligible from the 253rd observation)
    * ``fail_min_close = close < min_close`` (split-adjusted close; the C10 compromise)
    * ``fail_zero_volume = require_positive_volume and volume == 0``
    * ``fail_liquidity = not (median_dollar_volume_63 >= min_median_dollar_volume_63)``
      (NaN counts as failure)
    * ``eligible = not any(fail_*)``

    ``silver`` is not modified.
    """
    missing = [c for c in SILVER_INPUT_COLUMNS if c not in silver.columns]
    if missing:
        raise UniverseError(f"silver is missing columns {missing}")
    df = silver.loc[:, list(SILVER_INPUT_COLUMNS)].copy()
    df["ticker"] = df["ticker"].astype(str)
    if df.isna().any().any():
        raise UniverseError("silver contains NaN in ticker/date/close/volume/n_obs; run validate")
    df = df.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)
    if df.duplicated(["ticker", "date"]).any():
        raise UniverseError("silver contains duplicate (ticker, date) rows; run validate")

    expected_n_obs = df.groupby("ticker", sort=False).cumcount() + 1
    if not np.array_equal(df["n_obs"].to_numpy(), expected_n_obs.to_numpy()):
        raise UniverseError("silver n_obs is inconsistent with row order; rebuild silver")

    unknown = sorted(set(df["ticker"]) - set(master["ticker"].astype(str)))
    if unknown:
        raise UniverseError(f"tickers missing from the security master: {unknown}")

    dollar_volume = df["close"].astype("float64") * df["volume"].astype("float64")
    mdv63 = dollar_volume.groupby(df["ticker"], sort=False).transform(
        lambda s: s.rolling(LIQUIDITY_WINDOW, min_periods=LIQUIDITY_WINDOW).median()
    )

    master_fail = master_fail_by_ticker(master, universe_cfg)
    out = pd.DataFrame({"ticker": df["ticker"], "date": df["date"]})
    out["fail_master"] = df["ticker"].map(master_fail).to_numpy(dtype=bool)
    out["fail_seasoning"] = (df["n_obs"] <= universe_cfg.seasoning_days).to_numpy(dtype=bool)
    out["fail_min_close"] = (df["close"] < universe_cfg.min_close).to_numpy(dtype=bool)
    if universe_cfg.require_positive_volume:
        out["fail_zero_volume"] = (df["volume"] == 0).to_numpy(dtype=bool)
    else:
        out["fail_zero_volume"] = np.zeros(len(df), dtype=bool)
    out["fail_liquidity"] = (
        ~(mdv63 >= universe_cfg.min_median_dollar_volume_63)
    ).to_numpy(dtype=bool)
    out["median_dollar_volume_63"] = mdv63.astype("float64")
    out["eligible"] = ~out[list(FAIL_COLUMNS)].any(axis=1)
    out["date"] = out["date"].astype("datetime64[ns]")
    return out.loc[:, list(UNIVERSE_COLUMNS)].reset_index(drop=True)


def run_build_universe(
    cfg: Config,
    *,
    silver_file: Path | str | None = None,
    master_file: Path | str | None = None,
    universe_file: Path | str | None = None,
) -> pd.DataFrame:
    """Build and write ``data/processed/{variant}/universe.parquet``.

    Requires ``prices_silver.parquet`` (S1) and ``security_master.csv`` (``build-master``). The
    security master embeds ``flags.max_zero_volume_share_ticker``; re-run ``build-master`` after
    changing that key.
    """
    silver = read_silver(silver_file)
    master = load_security_master(master_file)
    universe = build_universe(silver, master, cfg.universe)
    out_path = Path(universe_file) if universe_file is not None else universe_path(
        cfg.project.variant
    )
    write_parquet(universe, out_path)

    n_rows, n_elig = len(universe), int(universe["eligible"].sum())
    per_date = universe.groupby("date")["eligible"].sum()
    try:
        data_hash = read_manifest(manifest_path())["sha256"]
    except (FileNotFoundError, ValueError):
        data_hash = "unknown"
    logger.info(
        "Universe [variant=%s, data hash %s]: %d rows, %d eligible (%.1f%%); eligible names per "
        "date min %d / median %d / max %d -> %s",
        cfg.project.variant,
        str(data_hash)[:12],
        n_rows,
        n_elig,
        100.0 * n_elig / max(n_rows, 1),
        int(per_date.min()),
        int(per_date.median()),
        int(per_date.max()),
        out_path.name,
    )
    for col in FAIL_COLUMNS:
        logger.info("  %s: %d rows", col, int(universe[col].sum()))
    return universe


def load_universe(cfg: Config, path: Path | str | None = None) -> pd.DataFrame:
    """Return the stored universe table for ``cfg.project.variant``.

    This is the only supported way for later stages to obtain eligibility. It applies no
    filtering of its own (single source of truth: ``build_universe``).
    """
    p = Path(path) if path is not None else universe_path(cfg.project.variant)
    if not p.is_file():
        raise FileNotFoundError(
            f"Universe not found for variant {cfg.project.variant!r}: {p}. "
            "Run `python -m nasdaq100.cli build-universe`."
        )
    df = read_parquet(p)
    if tuple(df.columns) != UNIVERSE_COLUMNS:
        raise UniverseError(
            f"{p.name}: columns {list(df.columns)} != expected {list(UNIVERSE_COLUMNS)}"
        )
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df
