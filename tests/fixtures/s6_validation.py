"""Fixtures for the S6 validation-framework tests (calendars, configs, panel tables)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from nasdaq100.config import Config, load_config
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.validation.guards import LockedAccessToken, open_locked_test

H = 20


def bday_calendar(start: str = "2000-01-03", periods: int = 6600) -> TradingCalendar:
    """Business-day calendar without New Year's Day and Christmas (so 2019-12-31 is the last
    date before 2020-01-02, as on the real calendar), long enough for dev and locked years.
    """
    holidays = [pd.Timestamp(y, m, d) for y in range(1990, 2041) for m, d in ((1, 1), (12, 25))]
    return TradingCalendar.from_dates(
        pd.bdate_range(start, periods=periods, freq="C", holidays=holidays)
    )


def make_cfg(
    cal: TradingCalendar | None = None,
    *,
    horizon: int = H,
    first_train_idx: int | None = None,
    **validation: object,
) -> Config:
    """Default config with the given primary horizon and ``validation.*`` overrides.

    ``first_train_idx`` sets ``validation.first_train_decision_date`` from the calendar.
    """
    ov = [f"labels.horizons=[{horizon}]", f"labels.primary_horizon={horizon}"]
    if first_train_idx is not None:
        assert cal is not None
        ov.append(f"validation.first_train_decision_date={cal.date_at(first_train_idx).date()}")
    for key, val in validation.items():
        ov.append(f"validation.{key}=" + (json.dumps(val) if isinstance(val, list) else str(val)))
    return load_config(overrides=ov)


def write_protocol(path: Path, **fields: object) -> Path:
    """Write a locked-test protocol file (frozen by default)."""
    proto = {"frozen": True, "frozen_at": "2026-01-01T00:00:00+00:00", "test_opened": False}
    proto.update(fields)
    path.write_text(json.dumps(proto, indent=2), encoding="utf-8")
    return path


def issue_token(cfg: Config, tmp_dir: Path) -> LockedAccessToken:
    """A valid guard token obtained the legitimate way, with a temporary frozen protocol."""
    return open_locked_test(cfg, write_protocol(tmp_dir / "locked_test_protocol.json"))


def panel_tables(
    cal: TradingCalendar,
    tickers: tuple[str, ...] = ("AAA", "BBB", "CCC"),
    h: int = H,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``(features_model, labels, universe)`` with identical keys over the whole calendar.

    Every value encodes its own ``t_idx`` (feature ``f1 = t_idx``, label ``excess = t_idx +
    0.5``) so masking and truncation are visible exactly. ``has_label`` follows the S4 rule.
    """
    rows = []
    for k, tk in enumerate(tickers):
        t = np.arange(cal.n_days)
        rows.append(pd.DataFrame({"ticker": tk, "date": cal.dates, "t": t, "k": k}))
    base = pd.concat(rows, ignore_index=True)
    t = base["t"].to_numpy()
    eligible = (t >= 10) & ((t + base["k"].to_numpy()) % 7 != 0)
    fm = pd.DataFrame({"ticker": base["ticker"], "date": base["date"], "eligible": eligible,
                       "f1": t.astype("float64"), "f2": -t.astype("float64")})
    has = (t + 1 + h) <= cal.last_idx
    lab = pd.DataFrame(
        {
            "ticker": base["ticker"],
            "date": base["date"],
            f"ret_fwd_h{h}": np.where(has, t + 0.25, np.nan),
            f"excess_h{h}": np.where(has & eligible, t + 0.5, np.nan),
            f"y_reg_h{h}": np.where(has & eligible, t + 0.5, np.nan),
            f"y_cls_h{h}": np.where(has & eligible, 1.0, np.nan),
            f"rank_pct_h{h}": np.where(has & eligible, 0.5, np.nan),
            f"label_exit_idx_h{h}": (t + 1 + h).astype("int32"),
            f"has_label_h{h}": has,
        }
    )
    uni = pd.DataFrame({"ticker": base["ticker"], "date": base["date"], "eligible": eligible})
    return fm, lab, uni
