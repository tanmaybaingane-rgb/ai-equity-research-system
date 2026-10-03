"""Global trading calendar and trading-day arithmetic.

Implements the calendar contract of Part II Section II.1 and the rebalance schedule of
Section II.2.

* The calendar is the sorted union of all dates in the dataset; ``t_idx`` is the 0-based
  position of a date on it. ``t_idx`` is the only allowed unit for "k trading days later or
  earlier" (never calendar days, never ``pd.Timedelta``).
* Rebalance decision dates are those with ``t_idx >= anchor`` and
  ``(t_idx - anchor) % every == 0`` (defaults 252 and 20, i.e. 2001-01-02 on the real data).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from nasdaq100.paths import calendar_path
from nasdaq100.utils.io import read_parquet

if TYPE_CHECKING:
    from nasdaq100.config import Config

CALENDAR_COLUMNS: tuple[str, ...] = ("date", "t_idx", "year", "is_month_first_day")


def _to_timestamp(value: Any) -> pd.Timestamp:
    """Convert a date-like value to a tz-naive Timestamp normalised to midnight."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        raise ValueError(f"Dates must be timezone-naive, got {value!r}")
    return ts.normalize()


def build_calendar(dates: Iterable[Any]) -> pd.DataFrame:
    """Build the calendar table from any collection of dates (duplicates allowed).

    Returns columns ``date`` (datetime64[ns]), ``t_idx`` (int32, 0..N-1), ``year`` (int32) and
    ``is_month_first_day`` (bool; first trading day of each calendar month in the data).
    """
    index = pd.DatetimeIndex(pd.to_datetime(list(dates))).normalize().unique().sort_values()
    if len(index) == 0:
        raise ValueError("Cannot build a calendar from zero dates")
    index = index.astype("datetime64[ns]")
    month_key = pd.Series(index.year * 12 + index.month)
    return pd.DataFrame(
        {
            "date": index,
            "t_idx": np.arange(len(index), dtype="int32"),
            "year": np.asarray(index.year, dtype="int32"),
            "is_month_first_day": (~month_key.duplicated()).to_numpy(dtype=bool),
        }
    )


class TradingCalendar:
    """Immutable view over the calendar table with trading-day helpers."""

    def __init__(self, frame: pd.DataFrame) -> None:
        missing = [c for c in CALENDAR_COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"Calendar is missing columns: {missing}")
        dates = pd.DatetimeIndex(frame["date"]).astype("datetime64[ns]")
        t_idx = frame["t_idx"].to_numpy()
        if len(dates) == 0:
            raise ValueError("Calendar is empty")
        if not dates.is_unique or not dates.is_monotonic_increasing:
            raise ValueError("Calendar dates must be unique and strictly increasing")
        if not np.array_equal(t_idx, np.arange(len(dates))):
            raise ValueError("Calendar t_idx must be exactly 0..N-1 in date order")
        self._frame = frame.reset_index(drop=True).copy()
        self._dates = dates

    @classmethod
    def from_dates(cls, dates: Iterable[Any]) -> TradingCalendar:
        """Build a calendar directly from dates."""
        return cls(build_calendar(dates))

    @classmethod
    def load(cls, path: Path | str | None = None) -> TradingCalendar:
        """Load ``calendar.parquet`` (default location from ``nasdaq100.paths``)."""
        return cls(read_parquet(path if path is not None else calendar_path()))

    @property
    def frame(self) -> pd.DataFrame:
        """A copy of the underlying calendar table."""
        return self._frame.copy()

    @property
    def dates(self) -> pd.DatetimeIndex:
        """All trading dates in order (position == ``t_idx``)."""
        return self._dates

    @property
    def n_days(self) -> int:
        """Number of trading dates."""
        return len(self._dates)

    @property
    def last_idx(self) -> int:
        """``t_idx`` of the last date."""
        return len(self._dates) - 1

    @property
    def first_date(self) -> pd.Timestamp:
        """First trading date."""
        return self._dates[0]

    @property
    def last_date(self) -> pd.Timestamp:
        """Last trading date."""
        return self._dates[-1]

    def __len__(self) -> int:
        return self.n_days

    def idx_of(self, date: Any) -> int:
        """Return ``t_idx`` of a trading date; ``KeyError`` if it is not on the calendar."""
        ts = _to_timestamp(date)
        pos = int(self._dates.get_indexer([ts])[0])
        if pos < 0:
            raise KeyError(f"{ts.date()} is not a trading date on the calendar")
        return pos

    def date_at(self, idx: int) -> pd.Timestamp:
        """Return the date at ``t_idx``; ``IndexError`` if outside 0..last_idx."""
        i = int(idx)
        if not 0 <= i <= self.last_idx:
            raise IndexError(f"t_idx {i} is outside the calendar range 0..{self.last_idx}")
        return self._dates[i]

    def offset(self, date: Any, k: int) -> pd.Timestamp:
        """Return the date ``k`` trading days after (``k>0``) or before (``k<0``) ``date``."""
        return self.date_at(self.idx_of(date) + int(k))

    def rebalance_dates(self, cfg: Config) -> pd.DataFrame:
        """Rebalance decision dates per Part II Section II.2 (columns ``date``, ``t_idx``)."""
        return rebalance_dates(cfg, self)


def rebalance_dates(cfg: Config, calendar: TradingCalendar | None = None) -> pd.DataFrame:
    """Decision dates with ``t_idx >= anchor`` and ``(t_idx - anchor) % every == 0``.

    ``anchor`` is ``cfg.backtest.rebalance_anchor_idx`` (252) and ``every`` is
    ``cfg.backtest.rebalance_every_days`` (20). Time convention: Part II Section II.2.
    """
    cal = calendar if calendar is not None else TradingCalendar.load()
    anchor = int(cfg.backtest.rebalance_anchor_idx)
    every = int(cfg.backtest.rebalance_every_days)
    if every <= 0:
        raise ValueError("backtest.rebalance_every_days must be positive")
    idx = np.arange(anchor, cal.n_days, every, dtype=np.int64)
    return pd.DataFrame(
        {"date": cal.dates[idx], "t_idx": idx.astype("int32")}
    ).reset_index(drop=True)
