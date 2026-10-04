"""L2: universe time-safety (Part IV Section IV.5).

Changing rows after ``t`` must leave eligibility at dates <= ``t`` unchanged. The security
master is held fixed: it is the static ticker-level curation input of the builder (its
``include_in_universe`` decision is a documented, whole-history quality rule; see
``docs/survivorship.md``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.flags import add_flags
from nasdaq100.data.universe import UNIVERSE_COLUMNS, build_universe
from tests.fixtures.s1_prices import make_clean_raw_prices, to_bronze
from tests.fixtures.s2_silver import make_master

pytestmark = pytest.mark.leakage

CFG = load_config()
N_DAYS = 330
CUT = 280  # the last decision date t: position on the synthetic calendar


def _bronze() -> pd.DataFrame:
    raw = make_clean_raw_prices(("AAA", "BBB", "CCC"), n_days=N_DAYS,
                                start_offsets={"CCC": 30}, seed=5)
    rng = np.random.default_rng(6)
    raw["Volume"] = rng.integers(200_000, 400_000, size=len(raw)).astype("int64")
    return to_bronze(raw)


def _universe(bronze: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    return build_universe(add_flags(bronze, CFG.flags), master, CFG.universe)


def _upto(u: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    return u[u["date"] <= t].reset_index(drop=True)


def _setup() -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    bronze = _bronze()
    t = bronze["date"].drop_duplicates().sort_values().iloc[CUT]
    master = make_master(add_flags(bronze, CFG.flags))
    return bronze, master, t


def test_poisoned_future_rows_do_not_change_eligibility_up_to_t() -> None:
    bronze, master, t = _setup()
    clean = _upto(_universe(bronze, master), t)
    assert clean["eligible"].any() and (~clean["eligible"]).any()  # both outcomes are exercised

    for seed in range(5):
        rng = np.random.default_rng(seed)
        poisoned = bronze.copy()
        fut = poisoned["date"] > t
        n = int(fut.sum())
        junk = rng.uniform(0.01, 1e4, size=n)
        for col in ("open", "high", "low", "close", "adj_close"):
            poisoned.loc[fut, col] = junk
        poisoned.loc[fut, "volume"] = rng.choice([0, 1, 10**12], size=n)
        got = _upto(_universe(poisoned, master), t)
        pd.testing.assert_frame_equal(got, clean)


def test_truncating_the_future_does_not_change_eligibility_up_to_t() -> None:
    bronze, master, t = _setup()
    full = _upto(_universe(bronze, master), t)
    truncated = _universe(bronze[bronze["date"] <= t].reset_index(drop=True), master)
    pd.testing.assert_frame_equal(truncated, full)
    assert tuple(truncated.columns) == UNIVERSE_COLUMNS


def test_changing_data_at_t_can_change_eligibility_at_t_but_not_before() -> None:
    """Sanity check that the test above can fail: the rule does react to the row's own data."""
    bronze, master, t = _setup()
    base = _universe(bronze, master)
    changed = bronze.copy()
    changed.loc[changed["date"] == t, "volume"] = 0
    after = _universe(changed, master)
    assert not base.loc[base["date"] == t, "fail_zero_volume"].any()
    assert after.loc[after["date"] == t, "fail_zero_volume"].all()
    pd.testing.assert_frame_equal(
        _upto(base, t - pd.Timedelta(days=1)), _upto(after, t - pd.Timedelta(days=1))
    )


def test_each_ticker_is_independent_of_other_tickers_future() -> None:
    bronze, master, t = _setup()
    base = _universe(bronze, master)
    poisoned = bronze.copy()
    poisoned.loc[(poisoned["ticker"] == "BBB") & (poisoned["date"] > t), "volume"] = 0
    other = _universe(poisoned, master)
    for tk in ("AAA", "CCC"):
        pd.testing.assert_frame_equal(
            base[base["ticker"] == tk].reset_index(drop=True),
            other[other["ticker"] == tk].reset_index(drop=True),
        )
