"""Fixtures for the S7 predictive-evaluation and baseline tests (synthetic, no real data)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.validation.folds import Fold

H = 20


def eval_frame(
    n_days: int = 600,
    n_names: int = 30,
    seed: int = 0,
    strength: float = 0.0,
    start_idx: int = 252,
) -> pd.DataFrame:
    """Evaluation frame ``ticker, date, t_idx, feat, excess``.

    ``excess = strength * feat + N(0, 1)`` per date, so a predictor equal to ``feat`` has a
    positive rank IC when ``strength > 0`` and none when ``strength == 0``.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2008-01-02", periods=n_days)
    tickers = [f"T{k:02d}" for k in range(n_names)]
    parts = []
    for i, d in enumerate(dates):
        feat = rng.normal(size=n_names)
        parts.append(
            pd.DataFrame(
                {
                    "ticker": tickers,
                    "date": d,
                    "t_idx": start_idx + i,
                    "feat": feat,
                    "excess": strength * feat + rng.normal(size=n_names),
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


def baseline_panel(
    cal: TradingCalendar,
    first: str = "2007-10-01",
    last: str = "2009-12-31",
    n_names: int = 25,
    seed: int = 0,
    strength: float = 0.4,
    mask_after_idx: int | None = None,
) -> pd.DataFrame:
    """A ``load_panel``-shaped dev panel with the three raw baseline features.

    Columns: ``ticker, date, t_idx, eligible, mom_12_1, ret_21, vol_63`` and the primary-horizon
    labels. The excess label loads on ``mom_12_1`` (+), ``ret_21`` (-) and ``vol_63`` (-), so
    every non-random baseline has a planted signal. Labels after ``mask_after_idx`` are NaN with
    ``has_label_h20`` False (like the dev mask of ``load_panel``).
    """
    rng = np.random.default_rng(seed)
    dates = cal.dates[(cal.dates >= pd.Timestamp(first)) & (cal.dates <= pd.Timestamp(last))]
    tickers = [f"T{k:02d}" for k in range(n_names)]
    parts = []
    for d in dates:
        mom = rng.normal(size=n_names)
        ret = rng.normal(size=n_names)
        vol = np.abs(rng.normal(size=n_names)) + 0.1
        y = strength * (mom - ret - vol) / 1.7 + rng.normal(size=n_names)
        parts.append(
            pd.DataFrame(
                {
                    "ticker": tickers,
                    "date": d,
                    "t_idx": np.int32(cal.idx_of(d)),
                    "eligible": True,
                    "mom_12_1": mom,
                    "ret_21": ret,
                    "vol_63": vol,
                    "ret_fwd_h20": y,
                    "excess_h20": y,
                    "y_reg_h20": np.clip(y, -2.0, 2.0),
                    "y_cls_h20": (y > 0).astype("float64"),
                    "rank_pct_h20": 0.5,
                    "label_exit_idx_h20": np.int32(cal.idx_of(d) + 1 + H),
                    "has_label_h20": True,
                }
            )
        )
    panel = pd.concat(parts, ignore_index=True)
    if mask_after_idx is not None:
        late = panel["t_idx"] > mask_after_idx
        for col in ("ret_fwd_h20", "excess_h20", "y_reg_h20", "y_cls_h20", "rank_pct_h20"):
            panel.loc[late, col] = np.nan
        panel.loc[late, "has_label_h20"] = False
    return panel


def dev_folds_for(panel: pd.DataFrame, years: tuple[int, ...] = (2008, 2009), kind: str = "dev"):
    """One ``Fold`` per calendar year covering that year's dates in ``panel`` (no training
    blocks: baselines only use the test period).
    """
    folds = []
    for year in years:
        sel = panel[panel["date"].dt.year == year]
        folds.append(
            Fold(
                fold_id=f"{kind}_{year}",
                kind=kind,
                test_year=year,
                test_start_idx=int(sel["t_idx"].min()),
                test_end_idx=int(sel["t_idx"].max()),
                train_core_idx=[],
                calib_idx=[],
                gap=26,
                train_end_idx=0,
            )
        )
    return folds
