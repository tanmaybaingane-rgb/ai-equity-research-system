"""L6: fold validity (property-based over random parameters).

Chronological, disjoint, the purge gap exact for every training and calibration row (off-by-one
cases), no test date before the first test date. Calendars and parameters are random
(h in {5, 20, 60}, embargo, calibration length, stride, rolling window).
"""

from __future__ import annotations

import random
from dataclasses import replace

import numpy as np
import pytest

from nasdaq100.validation.folds import (
    FoldError,
    make_dev_folds,
    make_fold,
    make_locked_folds,
    make_tuning_folds,
    year_bounds,
)
from nasdaq100.validation.guards import last_dev_label_idx, locked_start_idx, tuning_max_idx
from nasdaq100.validation.leakage import assert_folds_valid
from tests.fixtures.s6_validation import bday_calendar, issue_token, make_cfg

pytestmark = pytest.mark.leakage


def _draw(seed: int):
    rng = random.Random(seed)
    cal = bday_calendar(f"{rng.randint(1998, 2002)}-01-03", periods=rng.randint(6300, 7000))
    h = rng.choice([5, 20, 60])
    p = {
        "horizon": h,
        "first_train_idx": rng.randint(252, 320),
        "embargo_days": rng.randint(0, 10),
        "calibration_days": rng.choice([0, 21, 126, 252, 504]),
        "train_stride": rng.randint(1, 7),
        "train_window_days": rng.choice([None, 250, 756, 1500]),
    }
    cfg = make_cfg(cal, **p)
    return cal, cfg, p


def _expected_blocks(t0: int, p: dict, calib_days: int):
    """Independent re-derivation of one fold's blocks by plain set comprehension."""
    gap = p["horizon"] + 1 + p["embargo_days"]
    train_end = t0 - gap - 1
    first, stride, window = p["first_train_idx"], p["train_stride"], p["train_window_days"]
    if calib_days:
        calib_lo = train_end - calib_days + 1
        calib = {t for t in range(calib_lo, train_end + 1) if (t - first) % stride == 0}
        core_hi = calib_lo - gap - 1
    else:
        calib, core_hi = set(), train_end
    core_lo = first if window is None else max(first, core_hi - window + 1)
    core = {t for t in range(core_lo, core_hi + 1) if (t - first) % stride == 0}
    return gap, train_end, sorted(core), sorted(calib)


@pytest.mark.parametrize("seed", range(60))
def test_random_parameters_give_valid_folds_that_match_the_formulas(seed: int, tmp_path) -> None:
    cal, cfg, p = _draw(seed)
    lock = locked_start_idx(cfg, cal)
    folds = make_dev_folds(cfg, cal) + make_tuning_folds(cfg, cal)
    folds.sort(key=lambda f: (f.kind, f.test_year))
    for kind in ("dev", "tuning"):
        group = [f for f in folds if f.kind == kind]
        assert_folds_valid(
            group, p["horizon"], p["embargo_days"], first_train_idx=p["first_train_idx"],
            locked_start_idx=lock, train_stride=p["train_stride"],
        )
    for f in folds:
        calib_days = p["calibration_days"] if f.kind == "dev" else 0
        gap, train_end, core, calib = _expected_blocks(f.test_start_idx, p, calib_days)
        assert (f.gap, f.train_end_idx) == (gap, train_end)  # gap = h + 1 + embargo exactly
        assert f.train_core_idx == core and f.calib_idx == calib
        assert all(t + gap < f.test_start_idx for t in f.train_idx)
        assert all(t + 1 + p["horizon"] < f.test_start_idx for t in f.train_idx)  # label exit
        assert list(f.test_idx) == list(range(f.test_start_idx, f.test_end_idx + 1))  # unthinned
        assert f.test_start_idx > p["first_train_idx"]
    dev = [f for f in folds if f.kind == "dev"]
    assert [f.test_year for f in dev] == list(range(2008, 2020))
    assert all(a.test_end_idx + 1 == b.test_start_idx for a, b in zip(dev, dev[1:], strict=False))
    assert dev[-1].test_end_idx < lock and max(max(f.train_idx) for f in dev) < lock
    tune = [f for f in folds if f.kind == "tuning"]
    assert max(f.test_end_idx for f in tune) == tuning_max_idx(cfg, cal)  # 2007 is cut there
    # locked folds (with a token) are valid too and start at the lock
    locked = make_locked_folds(cfg, issue_token(cfg, tmp_path), cal)
    assert_folds_valid(locked, p["horizon"], p["embargo_days"],
                       first_train_idx=p["first_train_idx"], train_stride=p["train_stride"])
    assert locked[0].test_start_idx == lock and locked[-1].test_end_idx == cal.last_idx


@pytest.mark.parametrize("h", [5, 20, 60])
@pytest.mark.parametrize("embargo", [0, 5])
def test_gap_off_by_one_for_every_horizon(h: int, embargo: int) -> None:
    gap = h + 1 + embargo
    t0 = 3000
    f = make_fold(fold_id="x", kind="dev", test_year=2011, test_start_idx=t0, test_end_idx=3100,
                  horizon=h, embargo_days=embargo, calibration_days=100, train_stride=1,
                  first_train_idx=252)
    assert t0 - gap - 1 in f.train_idx and t0 - gap not in f.train_idx
    assert max(f.train_idx) == t0 - gap - 1
    assert_folds_valid([f], h, embargo)
    # a fold that admits t0 - gap fails, one that stops at t0 - gap - 1 passes
    sneaky = replace(f, calib_idx=[*f.calib_idx, t0 - gap])
    with pytest.raises(AssertionError, match="violates the gap"):
        assert_folds_valid([sneaky], h, embargo)
    # the label of the last allowed row resolves strictly before the first test decision date
    assert (t0 - gap - 1) + 1 + h < t0


def test_core_is_always_purged_from_the_calibration_block() -> None:
    for seed in range(30):
        cal, cfg, p = _draw(seed)
        if p["calibration_days"] == 0:
            continue
        for f in make_dev_folds(cfg, cal):
            assert max(f.train_core_idx) + f.gap < min(f.calib_idx)
            assert not set(f.train_core_idx) & set(f.calib_idx)


def test_dev_folds_never_include_locked_dates_even_as_training_features() -> None:
    cal = bday_calendar()
    cfg = make_cfg(cal, first_train_idx=252)
    lock = locked_start_idx(cfg, cal)
    for f in make_dev_folds(cfg, cal) + make_tuning_folds(cfg, cal):
        assert f.test_end_idx < lock and max(f.train_idx) < lock
        assert f.test_end_idx <= lock - 1 and cal.date_at(f.test_end_idx) < np.datetime64("2020-01-02")
    assert last_dev_label_idx(cfg, cal) == lock - 22
    with pytest.raises(FoldError, match="locked period"):
        make_dev_folds(make_cfg(cal, first_train_idx=252, dev_test_years=[2020]), cal)


def test_no_test_date_before_the_first_test_date_and_years_are_complete() -> None:
    cal = bday_calendar()
    cfg = make_cfg(cal, first_train_idx=252)
    folds = make_dev_folds(cfg, cal)
    first_test = year_bounds(cal, 2008)[0]
    assert_folds_valid(folds, 20, 5, first_test_idx=first_test)
    assert min(f.test_start_idx for f in folds) == first_test
    for f in folds:
        a, b = year_bounds(cal, f.test_year)
        assert (f.test_start_idx, f.test_end_idx) == (a, b)  # the whole year, never thinned
