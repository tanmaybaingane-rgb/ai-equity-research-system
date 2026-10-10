"""L7: dev label masking.

In ``dev`` mode labels for decision dates beyond ``last_dev_label_idx`` (5009 on the real
calendar) are NaN, and dev data contain no dates on or after 2020-01-02. The dev panel does not
depend on anything in the locked period.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100.data.loaders import build_panel, panel_label_columns
from nasdaq100.validation.guards import (
    LockedTestError,
    assert_not_locked,
    last_dev_label_idx,
    locked_start_idx,
)
from tests.fixtures.s6_validation import bday_calendar, make_cfg, panel_tables

pytestmark = pytest.mark.leakage

CAL = bday_calendar("2016-01-04", periods=1700)  # to 2022
LOCK_DATE = pd.Timestamp("2020-01-02")


@pytest.mark.parametrize("h", [5, 20, 60])
def test_labels_beyond_the_last_dev_label_idx_are_nan(h: int) -> None:
    cfg = make_cfg(CAL, horizon=h)
    fm, lab, uni = panel_tables(CAL, h=h)
    p = build_panel(fm, lab, uni, CAL, cfg, None, "dev")
    cap = last_dev_label_idx(cfg, CAL)
    lock = locked_start_idx(cfg, CAL)
    assert cap == lock - (h + 2)
    cols = panel_label_columns(h)
    late, early = p["t_idx"] > cap, p["t_idx"] <= cap
    assert late.any() and early.any() and p["t_idx"].max() == lock - 1
    for c in cols:
        if c.startswith(("label_exit_idx", "has_label")):
            continue
        assert p.loc[late, c].isna().all(), c
        assert p.loc[early & p["eligible"], c].notna().all(), c
    assert not p.loc[late, f"has_label_h{h}"].any() and p.loc[early, f"has_label_h{h}"].all()
    # the label of the last kept row resolves strictly before the first locked date:
    # exit index t + 1 + h < lock
    last_kept = int(p.loc[early, "t_idx"].max())
    assert last_kept == cap and last_kept + 1 + h == lock - 1  # exit one day before the lock
    assert p.loc[early, f"label_exit_idx_h{h}"].max() < lock


def test_dev_data_contain_no_dates_on_or_after_the_locked_start() -> None:
    cfg = make_cfg(CAL)
    fm, lab, uni = panel_tables(CAL)
    for labels in (True, False):
        p = build_panel(fm, lab, uni, CAL, cfg, None, "dev", labels)
        assert p["date"].max() == pd.Timestamp("2019-12-31") < LOCK_DATE
        assert_not_locked(p["date"], cfg)
        assert_not_locked(p["t_idx"], cfg, calendar=CAL)
    with pytest.raises(LockedTestError):
        assert_not_locked(fm["date"], cfg)  # the unfiltered tables do contain locked dates


def test_dev_panel_is_independent_of_everything_in_the_locked_period() -> None:
    """Corrupt every locked-period value of every table: the dev panel is bit-identical."""
    cfg = make_cfg(CAL)
    fm, lab, uni = panel_tables(CAL)
    base = build_panel(fm, lab, uni, CAL, cfg, None, "dev")
    locked = (fm["date"] >= LOCK_DATE).to_numpy()
    rng = np.random.default_rng(1)
    fm2, lab2, uni2 = fm.copy(), lab.copy(), uni.copy()
    for col in ("f1", "f2"):
        fm2.loc[locked, col] = rng.normal(size=locked.sum())
    for col in lab2.columns:
        if col in ("ticker", "date") or col.startswith(("label_exit", "has_label")):
            continue
        lab2.loc[locked, col] = rng.normal(size=locked.sum())
    flip = rng.random(locked.sum()) < 0.5
    fm2.loc[locked, "eligible"] = flip
    uni2.loc[locked, "eligible"] = flip
    pd.testing.assert_frame_equal(build_panel(fm2, lab2, uni2, CAL, cfg, None, "dev"), base,
                                  check_exact=True)


def test_dev_label_values_beyond_the_cap_cannot_leak_through_the_panel() -> None:
    """Dec-2019 labels hold open prices of January 2020: changing them changes nothing."""
    cfg = make_cfg(CAL)
    fm, lab, uni = panel_tables(CAL)
    base = build_panel(fm, lab, uni, CAL, cfg, None, "dev")
    cap = last_dev_label_idx(cfg, CAL)
    t = pd.Series(CAL.dates.get_indexer(lab["date"]))
    late = (t > cap).to_numpy()
    lab2 = lab.copy()
    for col in ("ret_fwd_h20", "excess_h20", "y_reg_h20", "y_cls_h20", "rank_pct_h20"):
        lab2.loc[late, col] = 12345.0
    lab2.loc[late, "has_label_h20"] = True
    out = build_panel(fm, lab2, uni, CAL, cfg, None, "dev")
    pd.testing.assert_frame_equal(out, base, check_exact=True)
