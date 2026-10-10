"""Stage S6: the locked-test guard (decision D19; leakage test L8).

The locked test (decision dates on or after ``validation.locked_test_start``) may be looked at
exactly once, through a deliberate and logged act. This module is the only place where that act
exists:

* ``assert_not_locked`` raises ``LockedTestError`` for any decision date (or ``t_idx``) in the
  locked period. Every loader, model runner and backtest calls it.
* ``open_locked_test`` verifies that ``experiments/locked_test_protocol.json`` exists with
  ``frozen == true``, records ``test_opened = true`` with a timestamp in that file, logs the act
  and returns a ``LockedAccessToken``. The token is the only thing that unlocks the guarded
  entry points (``load_panel("locked", ...)``, ``make_locked_folds``).

**Nothing outside S16 may call ``open_locked_test``** (the S16 ``locked-test`` command is its one
caller; a structural test fails if any other module in ``src/`` does).

Time convention: Part II Section II.2 (decision day ``t``; purge gap ``h + 1 + embargo``).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from nasdaq100.paths import locked_test_protocol_path
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.utils.logging import get_logger

if TYPE_CHECKING:
    from nasdaq100.config import Config

logger = get_logger("validation.guards")


class LockedTestError(RuntimeError):
    """An attempt to read, train on or evaluate locked-test data without the guard token."""


@dataclass(frozen=True)
class LockedAccessToken:
    """Proof that ``open_locked_test`` succeeded in this process (not constructible by hand)."""

    nonce: str
    opened_at: str


#: Nonces of the tokens issued by ``open_locked_test`` in this process.
_ISSUED_NONCES: set[str] = set()


def is_valid_token(token: object) -> bool:
    """True iff ``token`` was issued by ``open_locked_test`` in this process."""
    return isinstance(token, LockedAccessToken) and token.nonce in _ISSUED_NONCES


def require_token(token: object, what: str = "locked-test data") -> LockedAccessToken:
    """Return ``token`` if valid, else raise ``LockedTestError`` (never returns data)."""
    if not is_valid_token(token):
        raise LockedTestError(
            f"Access to {what} requires a token from open_locked_test(), which requires a "
            "frozen locked-test protocol (S16). Development code must not touch the locked "
            "period."
        )
    return token  # type: ignore[return-value]


def locked_start_idx(cfg: Config, calendar: TradingCalendar) -> int:
    """``t_idx`` of the first trading date on or after ``validation.locked_test_start``."""
    start = pd.Timestamp(cfg.validation.locked_test_start)
    pos = int(calendar.dates.searchsorted(start, side="left"))
    if pos > calendar.last_idx:
        raise LockedTestError(f"locked_test_start {start.date()} is after the calendar's end")
    return pos


def last_dev_label_idx(cfg: Config, calendar: TradingCalendar) -> int:
    """Last decision ``t_idx`` of the development period whose label is resolved (decision C4).

    ``locked_test_start_idx - (h + 2)``: ``t + 1 + h`` stays before the first locked date
    (5009 on the real calendar, 2019-11-29). Later dev dates keep their features but no label.
    """
    return locked_start_idx(cfg, calendar) - (int(cfg.labels.primary_horizon) + 2)


def tuning_max_idx(cfg: Config, calendar: TradingCalendar) -> int:
    """Last decision ``t_idx`` usable for tuning (decision C9): labels resolved before the first
    date after ``validation.tuning_end_date`` (1988 on the real calendar).
    """
    end = pd.Timestamp(cfg.validation.tuning_end_date)
    first_after = int(calendar.dates.searchsorted(end, side="right"))
    if first_after > calendar.last_idx:
        raise LockedTestError("tuning_end_date is at or after the calendar's end")
    return first_after - (int(cfg.labels.primary_horizon) + 2)


def _as_array(values: Any) -> np.ndarray:
    if isinstance(values, pd.Series | pd.Index):
        values = values.to_numpy()
    arr = np.asarray(values)
    return arr.reshape(-1) if arr.ndim != 1 else arr


def assert_not_locked(
    dates_or_idx: Any,
    cfg: Config | None = None,
    *,
    calendar: TradingCalendar | None = None,
    token: LockedAccessToken | None = None,
) -> None:
    """Raise ``LockedTestError`` if any decision date (or ``t_idx``) is in the locked period.

    ``dates_or_idx`` is a scalar or array-like of dates (``datetime64``, ``Timestamp``, ``date``,
    ISO strings) or of integer ``t_idx`` values (resolved with ``calendar``, default: the stored
    calendar). Missing values (NaT / NaN) are ignored. The boundary is exact: 2019-12-31 is
    allowed, 2020-01-02 is blocked (default configuration). A valid ``token`` disables the check.
    """
    if token is not None and is_valid_token(token):
        return
    if cfg is None:
        from nasdaq100.config import load_config

        cfg = load_config()
    arr = _as_array(dates_or_idx)
    if arr.size == 0:
        return
    if arr.dtype.kind in "Mm":
        stamps = pd.DatetimeIndex(arr)
    elif arr.dtype.kind in "iu":
        stamps = None
    elif arr.dtype.kind == "f":
        finite = arr[np.isfinite(arr)]
        if not np.array_equal(finite, np.floor(finite)):
            raise TypeError("assert_not_locked: float input must hold whole t_idx values")
        arr = finite.astype("int64")
        stamps = None
    elif arr.dtype.kind in "OUS":
        stamps = pd.DatetimeIndex(pd.to_datetime(pd.Series(arr)))
    else:
        raise TypeError(f"assert_not_locked: unsupported dtype {arr.dtype}")

    if stamps is not None:
        stamps = stamps.dropna()
        if len(stamps) == 0:
            return
        limit = pd.Timestamp(cfg.validation.locked_test_start)
        bad = stamps[stamps >= limit]
        if len(bad):
            raise LockedTestError(
                f"{len(bad)} decision date(s) are in the locked test period (first: "
                f"{bad.min().date()}; locked from {limit.date()})"
            )
        return
    if arr.size == 0:
        return
    cal = calendar if calendar is not None else TradingCalendar.load()
    start_idx = locked_start_idx(cfg, cal)
    bad_idx = arr[arr >= start_idx]
    if len(bad_idx):
        raise LockedTestError(
            f"{len(bad_idx)} t_idx value(s) are in the locked test period (first: "
            f"{int(bad_idx.min())}; locked from t_idx {start_idx})"
        )


def _read_protocol(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise LockedTestError(
            f"Locked-test protocol not found: {path}. The locked test cannot be opened before "
            "the protocol is frozen (S16 `freeze-protocol`)."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise LockedTestError(f"Locked-test protocol {path} is unreadable: {e}") from e
    if not isinstance(data, dict):
        raise LockedTestError(f"Locked-test protocol {path} must be a JSON object")
    return data


def open_locked_test(cfg: Config, protocol_file: Path | str | None = None) -> LockedAccessToken:
    """Open the locked test: the one deliberate, logged act (S16 only).

    Requires ``experiments/locked_test_protocol.json`` (or ``protocol_file``) to exist with
    ``frozen == true``. Records ``test_opened = true`` and ``test_opened_at`` (UTC, ISO 8601) in
    the file (an earlier ``test_opened_at`` is never overwritten), logs a warning and returns a
    ``LockedAccessToken``. Raises ``LockedTestError`` otherwise; nothing is written then.
    """
    path = Path(protocol_file) if protocol_file is not None else locked_test_protocol_path()
    proto = _read_protocol(path)
    if proto.get("frozen") is not True:
        raise LockedTestError(
            f"Locked-test protocol {path} is not frozen (frozen={proto.get('frozen')!r}); "
            "refusing to open the locked test."
        )
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    if proto.get("test_opened") is True and proto.get("test_opened_at"):
        logger.warning(
            "Locked test was already opened at %s; opening again (S16 flags reruns).",
            proto["test_opened_at"],
        )
        opened_at = str(proto["test_opened_at"])
    else:
        proto["test_opened"] = True
        proto["test_opened_at"] = now
        opened_at = now
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(proto, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    logger.warning(
        "LOCKED TEST OPENED (decision dates from %s) at %s",
        cfg.validation.locked_test_start,
        opened_at,
    )
    token = LockedAccessToken(nonce=secrets.token_hex(16), opened_at=opened_at)
    _ISSUED_NONCES.add(token.nonce)
    return token
