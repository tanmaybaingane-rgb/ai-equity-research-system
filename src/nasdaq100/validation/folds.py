"""Stage S6: walk-forward fold construction (leakage test L6).

A *fold* is one (train core, calibration, test) arrangement over decision dates ``t_idx``.
Because a label looks ``h + 1`` days ahead (time convention, Part II Section II.2), the last
training rows must stop **before** the test period by the purge gap::

    gap       = h + 1 + embargo_days                (26 for h = 20, embargo = 5)
    train_end = t0 - gap - 1                        every train / calibration row: t + gap < t0
    calib     = [train_end - calibration_days + 1, train_end]
    core_end  = calib_start - gap - 1               the core is purged from the calibration block
    core      = [first_train_idx, core_end]         (rolling: last ``train_window_days`` only)

``train_stride`` thins both blocks (``(t_idx - first_train_idx) % stride == 0``); the test period
is never thinned. Only rows with ``eligible`` and ``has_label`` are fitted on (row selection is
the trainer's job; the fold gives dates). ``sklearn.model_selection.TimeSeriesSplit`` is never
used: it splits by row index and assumes equal spacing, which a multi-ticker panel violates.

Dev folds test years 2008..2019 (last dev date 2019-12-31); tuning folds validate 2005..2007 with
no calibration block and ``t <= tuning_max_idx``; locked folds (2020..2026) need the guard token.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from nasdaq100.paths import fold_plan_path
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.validation.guards import (
    LockedAccessToken,
    last_dev_label_idx,
    locked_start_idx,
    require_token,
    tuning_max_idx,
)

if TYPE_CHECKING:
    from nasdaq100.config import Config

DEV = "dev"
TUNING = "tuning"
LOCKED = "locked"


class FoldError(ValueError):
    """Invalid fold parameters, or not enough history for a fold."""


def purge_gap(horizon: int, embargo_days: int) -> int:
    """Gap between the last usable training row and the first test date: ``h + 1 + embargo``."""
    return int(horizon) + 1 + int(embargo_days)


@dataclass
class Fold:
    """One (train core, calibration, test) arrangement (all indices are decision ``t_idx``).

    ``base_rate`` is filled by the trainer at fit time (``None`` until then).
    """

    fold_id: str
    kind: str
    test_year: int
    test_start_idx: int
    test_end_idx: int
    train_core_idx: list[int]
    calib_idx: list[int]
    gap: int
    train_end_idx: int
    base_rate: float | None = None

    @property
    def test_idx(self) -> range:
        """Every decision date of the test period (never thinned by the stride)."""
        return range(self.test_start_idx, self.test_end_idx + 1)

    @property
    def train_idx(self) -> list[int]:
        """Core and calibration dates together (the rows no test label may overlap)."""
        return [*self.train_core_idx, *self.calib_idx]


def make_fold(
    *,
    fold_id: str,
    kind: str,
    test_year: int,
    test_start_idx: int,
    test_end_idx: int,
    horizon: int,
    embargo_days: int,
    calibration_days: int,
    train_stride: int,
    first_train_idx: int,
    train_window_days: int | None = None,
) -> Fold:
    """Build one fold for the test period ``[test_start_idx, test_end_idx]`` (see module doc)."""
    if horizon < 1 or embargo_days < 0 or calibration_days < 0 or train_stride < 1:
        raise FoldError(
            f"invalid fold parameters: horizon={horizon}, embargo_days={embargo_days}, "
            f"calibration_days={calibration_days}, train_stride={train_stride}"
        )
    if train_window_days is not None and train_window_days < 1:
        raise FoldError(f"train_window_days must be positive, got {train_window_days}")
    if test_end_idx < test_start_idx:
        raise FoldError(f"empty test period [{test_start_idx}, {test_end_idx}]")
    if first_train_idx < 0 or test_start_idx <= first_train_idx:
        raise FoldError(f"test start {test_start_idx} is not after first_train_idx {first_train_idx}")

    t0 = int(test_start_idx)
    gap = purge_gap(horizon, embargo_days)
    train_end = t0 - gap - 1
    if calibration_days > 0:
        calib_start = train_end - calibration_days + 1
        core_end = calib_start - gap - 1
    else:
        calib_start = None
        core_end = train_end
    core_start = first_train_idx
    if train_window_days is not None:
        core_start = max(first_train_idx, core_end - train_window_days + 1)
    if core_end < core_start:
        raise FoldError(
            f"{fold_id}: not enough history before test start {t0} "
            f"(core would end at {core_end}, first training index {first_train_idx})"
        )

    def strided(lo: int, hi: int) -> list[int]:
        first = lo + (-(lo - first_train_idx)) % train_stride
        return list(range(first, hi + 1, train_stride))

    core = strided(core_start, core_end)
    calib = strided(calib_start, train_end) if calib_start is not None else []
    if not core or (calibration_days > 0 and not calib):
        raise FoldError(f"{fold_id}: train_stride={train_stride} leaves an empty block")
    return Fold(
        fold_id=fold_id,
        kind=kind,
        test_year=int(test_year),
        test_start_idx=t0,
        test_end_idx=int(test_end_idx),
        train_core_idx=core,
        calib_idx=calib,
        gap=gap,
        train_end_idx=train_end,
    )


def year_bounds(calendar: TradingCalendar, year: int) -> tuple[int, int]:
    """``(first, last)`` ``t_idx`` of the trading dates in calendar ``year``."""
    years = calendar.dates.year.to_numpy()
    pos = (years == year).nonzero()[0]
    if len(pos) == 0:
        raise FoldError(f"calendar has no trading date in {year}")
    return int(pos[0]), int(pos[-1])


def first_train_idx(cfg: Config, calendar: TradingCalendar) -> int:
    """``t_idx`` of the first trading date on or after ``validation.first_train_decision_date``."""
    pos = int(
        calendar.dates.searchsorted(pd.Timestamp(cfg.validation.first_train_decision_date))
    )
    if pos > calendar.last_idx:
        raise FoldError("first_train_decision_date is after the calendar's end")
    return pos


def _params(cfg: Config) -> dict[str, Any]:
    v = cfg.validation
    return {
        "horizon": int(cfg.labels.primary_horizon),
        "embargo_days": int(v.embargo_days),
        "train_stride": int(v.train_stride),
        "train_window_days": v.train_window_days,
    }


def _calendar(calendar: TradingCalendar | None) -> TradingCalendar:
    if calendar is not None:
        return calendar
    try:
        return TradingCalendar.load()
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"{e}. Run `python -m nasdaq100.cli ingest` to create the trading calendar."
        ) from e


def make_dev_folds(cfg: Config, calendar: TradingCalendar | None = None) -> list[Fold]:
    """The development folds: one per ``validation.dev_test_years`` (default 2008..2019).

    Each test period is the whole calendar year (dev: last date 2019-12-31); predictions are made
    on all eligible rows, *evaluation* uses only dates with labels (<= ``last_dev_label_idx``).
    """
    cal = _calendar(calendar)
    lock = locked_start_idx(cfg, cal)
    first = first_train_idx(cfg, cal)
    folds = []
    for year in sorted(set(cfg.validation.dev_test_years)):
        start, end = year_bounds(cal, year)
        if end >= lock:
            raise FoldError(f"dev test year {year} reaches the locked period (t_idx >= {lock})")
        folds.append(
            make_fold(
                fold_id=f"dev_{year}", kind=DEV, test_year=year, test_start_idx=start,
                test_end_idx=end, calibration_days=int(cfg.validation.calibration_days),
                first_train_idx=first, **_params(cfg),
            )
        )
    return folds


def make_tuning_folds(cfg: Config, calendar: TradingCalendar | None = None) -> list[Fold]:
    """Inner folds for hyper-parameter tuning: validation years 2005..2007 (decision C9).

    No calibration block (``calibration_days = 0``); validation dates are restricted to
    ``t_idx <= tuning_max_idx`` (labels resolved before 2008), so 2007 stops at 1988.
    """
    cal = _calendar(calendar)
    first = first_train_idx(cfg, cal)
    cap = tuning_max_idx(cfg, cal)
    folds = []
    for year in sorted(set(cfg.validation.tuning_valid_years)):
        start, end = year_bounds(cal, year)
        end = min(end, cap)
        if end < start:
            raise FoldError(f"tuning validation year {year} starts after tuning_max_idx {cap}")
        folds.append(
            make_fold(
                fold_id=f"tune_{year}", kind=TUNING, test_year=year, test_start_idx=start,
                test_end_idx=end, calibration_days=0, first_train_idx=first, **_params(cfg),
            )
        )
    return folds


def make_locked_folds(
    cfg: Config, token: LockedAccessToken, calendar: TradingCalendar | None = None
) -> list[Fold]:
    """The locked-test folds (test years 2020..last calendar year); needs the guard token.

    Annual refit, expanding window (S16). Training for a later fold may include earlier locked
    years, which were past data at that time. Raises ``LockedTestError`` without a valid token.
    """
    require_token(token, "the locked-test folds")
    cal = _calendar(calendar)
    lock = locked_start_idx(cfg, cal)
    first = first_train_idx(cfg, cal)
    folds = []
    for year in range(cal.date_at(lock).year, cal.last_date.year + 1):
        start, end = year_bounds(cal, year)
        folds.append(
            make_fold(
                fold_id=f"locked_{year}", kind=LOCKED, test_year=year,
                test_start_idx=max(start, lock), test_end_idx=end,
                calibration_days=int(cfg.validation.calibration_days),
                first_train_idx=first, **_params(cfg),
            )
        )
    return folds


def _block(idx: list[int], cal: TradingCalendar) -> dict[str, Any]:
    if not idx:
        return {"n_dates": 0, "start_idx": None, "end_idx": None, "start_date": None,
                "end_date": None, "span_days": 0}
    return {
        "n_dates": len(idx),
        "start_idx": idx[0],
        "end_idx": idx[-1],
        "start_date": cal.date_at(idx[0]).date().isoformat(),
        "end_date": cal.date_at(idx[-1]).date().isoformat(),
        "span_days": idx[-1] - idx[0] + 1,
    }


def fold_summary(fold: Fold, cal: TradingCalendar) -> dict[str, Any]:
    """JSON-serialisable description of one fold (index ranges, dates, block sizes)."""
    return {
        "fold_id": fold.fold_id,
        "kind": fold.kind,
        "test_year": fold.test_year,
        "test_start_idx": fold.test_start_idx,
        "test_end_idx": fold.test_end_idx,
        "test_start_date": cal.date_at(fold.test_start_idx).date().isoformat(),
        "test_end_date": cal.date_at(fold.test_end_idx).date().isoformat(),
        "n_test_dates": fold.test_end_idx - fold.test_start_idx + 1,
        "gap": fold.gap,
        "train_end_idx": fold.train_end_idx,
        "train_end_date": cal.date_at(fold.train_end_idx).date().isoformat(),
        "core": _block(fold.train_core_idx, cal),
        "calibration": _block(fold.calib_idx, cal),
    }


def build_fold_plan(cfg: Config, calendar: TradingCalendar | None = None) -> dict[str, Any]:
    """The documentation plan: all dev folds and the tuning folds, plus the boundary indices.

    Locked folds are deliberately absent (they need the guard token); only the locked start is
    recorded. The plan is deterministic (no timestamps).
    """
    from nasdaq100.config import config_hash

    cal = _calendar(calendar)
    v = cfg.validation
    p = _params(cfg)
    lock = locked_start_idx(cfg, cal)
    return {
        "config_hash": config_hash(cfg),
        "variant": cfg.project.variant,
        "horizon": p["horizon"],
        "embargo_days": p["embargo_days"],
        "gap": purge_gap(p["horizon"], p["embargo_days"]),
        "calibration_days": int(v.calibration_days),
        "train_window_days": p["train_window_days"],
        "train_stride": p["train_stride"],
        "first_train_idx": first_train_idx(cfg, cal),
        "locked_test_start": v.locked_test_start.isoformat(),
        "locked_test_start_idx": lock,
        "last_dev_idx": lock - 1,
        "last_dev_label_idx": last_dev_label_idx(cfg, cal),
        "tuning_max_idx": tuning_max_idx(cfg, cal),
        "calendar_n_days": cal.n_days,
        "dev_folds": [fold_summary(f, cal) for f in make_dev_folds(cfg, cal)],
        "tuning_folds": [fold_summary(f, cal) for f in make_tuning_folds(cfg, cal)],
    }


def write_fold_plan(
    cfg: Config, calendar: TradingCalendar | None = None, path: Path | str | None = None
) -> dict[str, Any]:
    """Write ``fold_plan.json`` (default ``artifacts/{variant}/fold_plan.json``) and return it."""
    plan = build_fold_plan(cfg, calendar)
    out = Path(path) if path is not None else fold_plan_path(cfg.project.variant)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan
