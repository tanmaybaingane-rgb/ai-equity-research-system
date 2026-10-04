"""L3 (S3 part): adjusted-series scale invariance and causality of ``logret_cc``.

Multiplying a ticker's adjusted series by a constant must leave its returns unchanged (the
adjusted *level* carries no information), and a return at ``t`` may only use data at ``t`` and
``t-1`` (Part IV Section IV.5).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100.data.adjust import build_adjusted
from nasdaq100.utils.calendar import TradingCalendar
from tests.fixtures.s2_silver import make_silver

pytestmark = pytest.mark.leakage

N_DAYS = 80
CUT = 50  # last decision position t on the synthetic calendar


def _silver() -> pd.DataFrame:
    return make_silver(("AAA", "BBB"), n_days=N_DAYS, seed=21)


def _adjusted(silver: pd.DataFrame) -> pd.DataFrame:
    return build_adjusted(silver, TradingCalendar.from_dates(silver["date"]))


@pytest.mark.parametrize("scale", [0.01, 0.37, 1234.5])
def test_scaling_adjusted_series_leaves_returns_unchanged(scale: float) -> None:
    silver = _silver()
    base = _adjusted(silver)

    scaled_silver = silver.copy()
    mask = scaled_silver["ticker"] == "AAA"
    scaled_silver.loc[mask, "adj_close"] = scaled_silver.loc[mask, "adj_close"] * scale
    scaled = _adjusted(scaled_silver)

    np.testing.assert_allclose(
        scaled["logret_cc"].to_numpy(), base["logret_cc"].to_numpy(), rtol=0, atol=1e-12
    )
    # the whole adjusted OHLC block of the scaled ticker moves by the constant ...
    for col in ("adj_factor", "adj_open", "adj_high", "adj_low", "adj_close"):
        np.testing.assert_allclose(
            scaled.loc[mask.to_numpy(), col].to_numpy(),
            base.loc[mask.to_numpy(), col].to_numpy() * scale,
            rtol=1e-12,
        )
    # ... within-bar price ratios (level-free quantities) are unchanged ...
    ratio = scaled["adj_close"] / scaled["adj_open"]
    np.testing.assert_allclose(ratio, base["adj_close"] / base["adj_open"], rtol=1e-12)
    # ... and the other ticker is untouched, bit for bit
    other = ~mask.to_numpy()
    pd.testing.assert_frame_equal(
        scaled[other].reset_index(drop=True), base[other].reset_index(drop=True)
    )


def test_changing_future_rows_leaves_past_rows_unchanged() -> None:
    silver = _silver()
    base = _adjusted(silver)

    poisoned = silver.copy()
    future = poisoned["date"] > poisoned["date"].drop_duplicates().sort_values().iloc[CUT]
    for col in ("open", "high", "low", "close", "adj_close"):
        poisoned.loc[future, col] = poisoned.loc[future, col] * 3.7
    poisoned.loc[future, "volume"] = poisoned.loc[future, "volume"] + 12_345
    changed = _adjusted(poisoned)

    past = (base["t_idx"] <= CUT).to_numpy()
    pd.testing.assert_frame_equal(
        changed[past].reset_index(drop=True), base[past].reset_index(drop=True)
    )
    assert not changed[~past].reset_index(drop=True).equals(base[~past].reset_index(drop=True))
