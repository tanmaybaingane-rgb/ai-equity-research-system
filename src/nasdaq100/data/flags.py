"""Data-quality flags (silver layer).

Problems are *flagged, never deleted* (Stage S1): later stages decide what to do with them.
All flags that use the previous row look at the same ticker's previous observation; the first
observation of each ticker therefore has those flags set to False. This relies on the hard
"no internal calendar gaps" validation check, so previous row == previous trading day.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from nasdaq100.data.ingest import BRONZE_COLUMNS

FLAG_COLUMNS: tuple[str, ...] = (
    "flag_tick_noise",
    "flag_zero_volume",
    "flag_flat_bar",
    "flag_corp_action_suspect",
    "flag_extreme_move",
)
SILVER_COLUMNS: tuple[str, ...] = (*BRONZE_COLUMNS, "n_obs", *FLAG_COLUMNS)


def previous_row_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker previous close and log returns of ``close`` and ``adj_close``.

    Input must be sorted by (ticker, date). The first row of each ticker is NaN.
    """
    grouped = df.groupby("ticker", sort=False)
    prev_close = grouped["close"].shift(1)
    prev_adj = grouped["adj_close"].shift(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        logret_close = np.log(df["close"] / prev_close)
        logret_adj = np.log(df["adj_close"] / prev_adj)
    return pd.DataFrame(
        {"prev_close": prev_close, "logret_close": logret_close, "logret_adj": logret_adj},
        index=df.index,
    )


def add_flags(bronze: pd.DataFrame, flags_cfg: Any) -> pd.DataFrame:
    """Return the silver table: bronze + ``n_obs`` + the five ``flag_*`` columns.

    Rows are never removed. ``flags_cfg`` is ``cfg.flags`` (``tick_noise_min_close``,
    ``corp_action_ret_gap``, ``corp_action_min_prev_close``, ``extreme_move_abs_ret``).

    * ``flag_tick_noise``: ``close < tick_noise_min_close``
    * ``flag_zero_volume``: ``volume == 0``
    * ``flag_flat_bar``: ``open == high == low == close``
    * ``flag_extreme_move``: ``|ln(adj_close_t / adj_close_{t-1})| > extreme_move_abs_ret``
    * ``flag_corp_action_suspect``: ``|ln(close_t/close_{t-1}) - ln(adj_t/adj_{t-1})| >
      corp_action_ret_gap`` AND ``close_{t-1} >= corp_action_min_prev_close`` (the second
      condition stops 2-decimal rounding on low prices from triggering the flag)
    * ``n_obs``: the ticker's own observation count up to and including the row (starts at 1)
    """
    missing = [c for c in BRONZE_COLUMNS if c not in bronze.columns]
    if missing:
        raise ValueError(f"Cannot add flags: missing columns {missing}")

    df = bronze.loc[:, list(BRONZE_COLUMNS)].sort_values(
        ["ticker", "date"], kind="stable"
    ).reset_index(drop=True)
    rets = previous_row_returns(df)

    gap = (rets["logret_close"] - rets["logret_adj"]).abs()
    out = df.copy()
    out["n_obs"] = (df.groupby("ticker", sort=False).cumcount() + 1).astype("int32")
    out["flag_tick_noise"] = (df["close"] < flags_cfg.tick_noise_min_close).astype(bool)
    out["flag_zero_volume"] = (df["volume"] == 0).astype(bool)
    out["flag_flat_bar"] = (
        (df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])
    ).astype(bool)
    out["flag_corp_action_suspect"] = (
        (gap > flags_cfg.corp_action_ret_gap)
        & (rets["prev_close"] >= flags_cfg.corp_action_min_prev_close)
    ).astype(bool)
    out["flag_extreme_move"] = (rets["logret_adj"].abs() > flags_cfg.extreme_move_abs_ret).astype(
        bool
    )
    return out.loc[:, list(SILVER_COLUMNS)]


def corp_action_events(silver: pd.DataFrame) -> pd.DataFrame:
    """Rows flagged ``flag_corp_action_suspect`` with the returns that triggered them."""
    rets = previous_row_returns(silver)
    mask = silver["flag_corp_action_suspect"].to_numpy(dtype=bool)
    events = pd.DataFrame(
        {
            "ticker": silver["ticker"],
            "date": silver["date"],
            "prev_close": rets["prev_close"],
            "close": silver["close"],
            "adj_close": silver["adj_close"],
            "logret_close": rets["logret_close"],
            "logret_adj": rets["logret_adj"],
        }
    )[mask]
    events = events.assign(gap=(events["logret_close"] - events["logret_adj"]).abs())
    return events.sort_values(["date", "ticker"]).reset_index(drop=True)
