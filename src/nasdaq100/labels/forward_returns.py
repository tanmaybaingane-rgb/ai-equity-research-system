"""Stage S4: forward-return labels (decisions D4 and D5).

Time convention (Part II Section II.2): the decision is taken at the close of day ``t``; the order
fills at the **adjusted open of ``t+1``** and the position is closed at the adjusted open of
``t+1+h``. For each horizon ``h`` in ``labels.horizons``::

    ret_fwd_h        = ln(adj_open[t+1+h]) - ln(adj_open[t+1])     (same ticker)
    label_exit_idx_h = t_idx + 1 + h
    has_label_h      = exit index on the calendar and both prices exist

Cross-sectional labels are computed per date over rows with ``eligible and has_label_h`` only::

    excess_h   = ret_fwd_h - mean(ret_fwd_h)             (unclipped; used for evaluation)
    y_reg_h    = excess_h clipped at the per-date labels.winsor_pct quantiles (used for training)
    y_cls_h    = 1[excess_h > 0]
    rank_pct_h = per-date percentile rank of ret_fwd_h    (1.0 = best)

Labels are the only place where future data legitimately appears, so this module is small and
every future dependency is explicit: the label of a ticker at ``t`` reads the adjusted open at
``t+1`` and ``t+1+h`` only, and the cross-sectional columns at ``t`` read other tickers' forward
returns *of the same date* (which resolve no later than ``t+1+h`` either). Nothing after
``t+1+h`` is ever read. The eligibility flag is read at ``t`` (S2 guarantees it is time-safe).

Only ``adj_open`` enters a label: never ``adj_close`` or raw prices (close-to-close labels would
violate D4; raw prices would violate D3).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from nasdaq100.data.adjust import load_adjusted
from nasdaq100.data.ingest import read_manifest
from nasdaq100.data.universe import load_universe
from nasdaq100.paths import calendar_path, labels_path, manifest_path
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.utils.io import read_parquet, write_parquet
from nasdaq100.utils.logging import get_logger

if TYPE_CHECKING:
    from nasdaq100.config import Config

logger = get_logger("labels.forward_returns")

#: Per-horizon label columns, in output order (Part II Section II.5). Suffix: ``h{h}``.
LABEL_STEMS: tuple[str, ...] = (
    "ret_fwd_h",
    "excess_h",
    "y_reg_h",
    "y_cls_h",
    "rank_pct_h",
    "label_exit_idx_h",
    "has_label_h",
)
#: Cross-sectional label stems: NaN on rows that are ineligible, unlabelled or on thin dates.
CROSS_SECTIONAL_STEMS: tuple[str, ...] = ("excess_h", "y_reg_h", "y_cls_h", "rank_pct_h")
KEY_COLUMNS: tuple[str, ...] = ("ticker", "date")
ADJUSTED_INPUT_COLUMNS: tuple[str, ...] = ("ticker", "date", "t_idx", "adj_open")
UNIVERSE_INPUT_COLUMNS: tuple[str, ...] = ("ticker", "date", "eligible")
#: Dates with fewer eligible labelled names than this get NaN cross-sectional labels (S4 spec 4).
MIN_CROSS_SECTION = 20


class LabelError(Exception):
    """Invalid inputs or configuration for the label builder."""


def label_columns(horizons: list[int] | tuple[int, ...]) -> list[str]:
    """Output columns for ``horizons``: keys, then the seven label columns per horizon."""
    return [*KEY_COLUMNS, *(f"{stem}{h}" for h in horizons for stem in LABEL_STEMS)]


def _check_config(labels_cfg: Any) -> tuple[list[int], float, float]:
    """Validate ``cfg.labels`` and return ``(horizons, winsor_lo, winsor_hi)``."""
    horizons = [int(h) for h in labels_cfg.horizons]
    if not horizons:
        raise LabelError("labels.horizons is empty")
    if any(h < 1 for h in horizons):
        raise LabelError(f"labels.horizons must be positive integers, got {horizons}")
    if len(set(horizons)) != len(horizons):
        raise LabelError(f"labels.horizons contains duplicates: {horizons}")
    if int(labels_cfg.primary_horizon) not in horizons:
        raise LabelError(
            f"labels.primary_horizon={labels_cfg.primary_horizon} is not in "
            f"labels.horizons={horizons}"
        )
    winsor = [float(q) for q in labels_cfg.winsor_pct]
    if len(winsor) != 2 or not (0.0 <= winsor[0] < winsor[1] <= 1.0):
        raise LabelError(
            f"labels.winsor_pct must be [lo, hi] with 0 <= lo < hi <= 1, got {winsor}"
        )
    return horizons, winsor[0], winsor[1]


def _check_inputs(adjusted: pd.DataFrame, universe: pd.DataFrame) -> None:
    for name, frame, cols in (
        ("adjusted prices", adjusted, ADJUSTED_INPUT_COLUMNS),
        ("universe", universe, UNIVERSE_INPUT_COLUMNS),
    ):
        missing = [c for c in cols if c not in frame.columns]
        if missing:
            raise LabelError(f"{name} table is missing columns: {missing}")
        if len(frame) == 0:
            raise LabelError(f"{name} table is empty")
        if frame.duplicated(list(KEY_COLUMNS)).any():
            raise LabelError(f"{name} table has duplicate (ticker, date) rows")
    if adjusted["adj_open"].isna().any():
        raise LabelError("adjusted prices contain NaN adj_open")
    if not (adjusted["adj_open"].to_numpy(dtype="float64") > 0).all():
        raise LabelError("adjusted prices contain non-positive adj_open")
    if universe["eligible"].isna().any():
        raise LabelError("universe contains NaN in 'eligible'")


def build_labels(
    adjusted: pd.DataFrame,
    universe: pd.DataFrame,
    labels_cfg: Any,
    calendar: TradingCalendar | pd.DataFrame,
    *,
    min_names: int = MIN_CROSS_SECTION,
) -> pd.DataFrame:
    """Build the labels table from adjusted prices, the universe and the trading calendar.

    ``labels_cfg`` is ``cfg.labels`` (``horizons``, ``primary_horizon``, ``winsor_pct``). The row
    set equals the adjusted table's (and must equal the universe's). Rows are never dropped; the
    output is sorted by (ticker, date). Raises ``LabelError`` on invalid input, on a key mismatch
    between the two tables, or when ``t_idx`` is not consecutive within a ticker (the row shifts
    below are only valid under that contiguity).
    """
    horizons, q_lo, q_hi = _check_config(labels_cfg)
    _check_inputs(adjusted, universe)
    cal = calendar if isinstance(calendar, TradingCalendar) else TradingCalendar(calendar)

    px = adjusted.loc[:, list(ADJUSTED_INPUT_COLUMNS)].copy()
    px["date"] = pd.to_datetime(px["date"]).astype("datetime64[ns]")
    px = px.sort_values(list(KEY_COLUMNS), kind="mergesort").reset_index(drop=True)

    uni = universe.loc[:, list(UNIVERSE_INPUT_COLUMNS)].copy()
    uni["date"] = pd.to_datetime(uni["date"]).astype("datetime64[ns]")
    uni = uni.sort_values(list(KEY_COLUMNS), kind="mergesort").reset_index(drop=True)
    if len(px) != len(uni) or not px[list(KEY_COLUMNS)].equals(uni[list(KEY_COLUMNS)]):
        raise LabelError(
            "adjusted prices and universe do not have identical (ticker, date) keys "
            f"({len(px)} vs {len(uni)} rows); rebuild with build-adjusted and build-universe"
        )
    eligible = uni["eligible"].to_numpy(dtype=bool)

    # t_idx must agree with the calendar and be consecutive within each ticker.
    pos = cal.dates.get_indexer(pd.DatetimeIndex(px["date"]))
    if (pos < 0).any():
        raise LabelError(f"Date {px.loc[pos < 0, 'date'].iloc[0].date()} is not on the calendar")
    t_idx = px["t_idx"].to_numpy(dtype="int64")
    if not np.array_equal(t_idx, pos.astype("int64")):
        raise LabelError("adjusted t_idx does not match the trading calendar")
    ticker_key = px["ticker"].to_numpy()
    step = pd.Series(t_idx).groupby(ticker_key).diff()
    bad = step.notna() & (step != 1)
    if bad.any():
        row = px.loc[bad.to_numpy()].iloc[0]
        raise LabelError(
            f"t_idx is not consecutive within ticker {row['ticker']} at {row['date'].date()}; "
            "forward shifts would not be calendar shifts"
        )

    last_idx = cal.last_idx
    log_open = pd.Series(np.log(px["adj_open"].to_numpy(dtype="float64")))
    grouped = log_open.groupby(ticker_key, sort=False)
    entry = grouped.shift(-1)  # ln(adj_open[t+1]) (NaN when the ticker has no row at t+1)

    date_key = px["date"].to_numpy()
    out: dict[str, Any] = {"ticker": px["ticker"], "date": px["date"]}
    thin_dates: dict[int, int] = {}
    empty_dates: dict[int, int] = {}
    for h in horizons:
        exit_idx = t_idx + 1 + h
        exit_ = grouped.shift(-(1 + h))  # ln(adj_open[t+1+h])
        ret = (exit_ - entry).to_numpy(dtype="float64")
        has_label = (exit_idx <= last_idx) & np.isfinite(ret)
        ret = np.where(has_label, ret, np.nan)

        valid = eligible & has_label
        counts = pd.Series(valid).groupby(date_key).transform("sum").to_numpy()
        usable = valid & (counts >= min_names)
        n_by_date = pd.Series(valid).groupby(date_key).sum()
        thin_dates[h] = int(((n_by_date > 0) & (n_by_date < min_names)).sum())
        empty_dates[h] = int((n_by_date == 0).sum())

        r = pd.Series(np.where(usable, ret, np.nan))
        by_date = r.groupby(date_key)
        excess = r - by_date.transform("mean")
        e_by_date = excess.groupby(date_key)
        lo_q = e_by_date.quantile(q_lo)
        hi_q = e_by_date.quantile(q_hi)
        lo_row = pd.Series(date_key).map(lo_q).to_numpy(dtype="float64")
        hi_row = pd.Series(date_key).map(hi_q).to_numpy(dtype="float64")
        y_reg = np.minimum(np.maximum(excess.to_numpy(), lo_row), hi_row)
        y_cls = np.where(usable, (excess.to_numpy() > 0).astype("float64"), np.nan)
        rank_pct = by_date.rank(method="average", pct=True, ascending=True).to_numpy()

        out[f"ret_fwd_h{h}"] = ret
        out[f"excess_h{h}"] = excess.to_numpy()
        out[f"y_reg_h{h}"] = np.where(usable, y_reg, np.nan)
        out[f"y_cls_h{h}"] = y_cls
        out[f"rank_pct_h{h}"] = np.where(usable, rank_pct, np.nan)
        out[f"label_exit_idx_h{h}"] = exit_idx.astype("int32")
        out[f"has_label_h{h}"] = has_label.astype(bool)

    for h, n_thin in thin_dates.items():
        if n_thin:
            logger.warning(
                "h=%d: %d date(s) have fewer than %d eligible labelled names; cross-sectional "
                "labels are NaN on those dates",
                h,
                n_thin,
                min_names,
            )
    for h, n_empty in empty_dates.items():
        logger.info(
            "h=%d: %d date(s) have no eligible labelled name (seasoning period, trailing "
            "horizon); their cross-sectional labels are NaN",
            h,
            n_empty,
        )
    return pd.DataFrame(out).loc[:, label_columns(horizons)].reset_index(drop=True)


def run_build_labels(
    cfg: Config,
    *,
    adjusted_file: Path | str | None = None,
    universe_file: Path | str | None = None,
    calendar_file: Path | str | None = None,
    labels_file: Path | str | None = None,
) -> pd.DataFrame:
    """Build and write ``data/processed/{variant}/labels.parquet``.

    Requires ``adjusted_prices.parquet`` (S3) and ``universe.parquet`` (S2) for the same variant
    and ``calendar.parquet`` (S1). Missing inputs raise ``FileNotFoundError`` with the command
    that produces them (no substitute data is fabricated).
    """
    adjusted = load_adjusted(cfg, adjusted_file)
    universe = load_universe(cfg, universe_file)
    cal_path = Path(calendar_file) if calendar_file is not None else calendar_path()
    if not cal_path.is_file():
        raise FileNotFoundError(
            f"Calendar not found: {cal_path}. Run `python -m nasdaq100.cli ingest`."
        )
    calendar = TradingCalendar.load(cal_path)
    labels = build_labels(adjusted, universe, cfg.labels, calendar)
    out_path = (
        Path(labels_file) if labels_file is not None else labels_path(cfg.project.variant)
    )
    write_parquet(labels, out_path)

    try:
        data_hash = read_manifest(manifest_path())["sha256"]
    except (FileNotFoundError, ValueError):
        data_hash = "unknown"
    logger.info(
        "Labels [variant=%s, data hash %s]: %d rows, horizons %s -> %s",
        cfg.project.variant,
        str(data_hash)[:12],
        len(labels),
        list(cfg.labels.horizons),
        out_path.name,
    )
    for h in cfg.labels.horizons:
        n_label = int(labels[f"has_label_h{h}"].sum())
        n_cs = int(labels[f"excess_h{h}"].notna().sum())
        logger.info(
            "  h=%d: %d rows with a forward return, %d with cross-sectional labels",
            h,
            n_label,
            n_cs,
        )
    return labels


def load_labels(cfg: Config, path: Path | str | None = None) -> pd.DataFrame:
    """Return the stored labels table for ``cfg.project.variant``.

    The only supported way for later stages to obtain labels. It applies no filtering of its own
    (the locked-test guard of decision D19 belongs to S6/S16, which must wrap this loader).
    """
    p = Path(path) if path is not None else labels_path(cfg.project.variant)
    if not p.is_file():
        raise FileNotFoundError(
            f"Labels not found for variant {cfg.project.variant!r}: {p}. "
            "Run `python -m nasdaq100.cli build-labels`."
        )
    df = read_parquet(p)
    expected = label_columns([int(h) for h in cfg.labels.horizons])
    if list(df.columns) != expected:
        raise LabelError(f"{p.name}: columns {list(df.columns)} != expected {expected}")
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df
