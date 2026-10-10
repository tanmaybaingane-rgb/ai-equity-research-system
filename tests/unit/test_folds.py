"""Unit tests for fold construction (``validation/folds.py``)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from nasdaq100.validation.folds import (
    Fold,
    FoldError,
    build_fold_plan,
    first_train_idx,
    fold_summary,
    make_dev_folds,
    make_fold,
    make_locked_folds,
    make_tuning_folds,
    purge_gap,
    write_fold_plan,
    year_bounds,
)
from nasdaq100.validation.guards import LockedTestError
from tests.fixtures.s6_validation import bday_calendar, issue_token, make_cfg

KW = {"horizon": 20, "embargo_days": 5, "train_stride": 1, "first_train_idx": 252}


def _fold(t0: int = 2010, end: int = 2262, calib: int = 504, **over):
    kw = {**KW, "calibration_days": calib, **over}
    return make_fold(fold_id="f", kind="dev", test_year=2008, test_start_idx=t0,
                     test_end_idx=end, **kw)


@pytest.mark.unit
def test_worked_example_of_the_guide_dev_fold_2008() -> None:
    f = _fold()  # t0 = 2010 (2008-01-02), unstrided blocks as in section II.2 / S6
    assert purge_gap(20, 5) == 26 == f.gap
    assert f.train_end_idx == 1983  # t0 - gap - 1; label exit 1983 + 21 = 2004 < 2010
    assert (f.calib_idx[0], f.calib_idx[-1]) == (1480, 1983)
    assert (f.train_core_idx[0], f.train_core_idx[-1]) == (252, 1453)  # core_end = 1480 - 27
    assert len(f.calib_idx) == 504 and len(f.train_core_idx) == 1202  # ~4.8 years of dates
    assert f.test_start_idx == 2010 and f.test_end_idx == 2262
    assert max(f.train_idx) + f.gap < f.test_start_idx
    assert f.kind == "dev" and f.base_rate is None
    f.base_rate = 0.5  # filled by the trainer at fit time
    assert f.base_rate == 0.5 and list(f.test_idx) == list(range(2010, 2263))


@pytest.mark.unit
def test_gap_is_exact_row_at_t0_minus_gap_minus_1_allowed_t0_minus_gap_not() -> None:
    for h, emb in ((5, 0), (20, 5), (60, 10)):
        gap = h + 1 + emb
        f = _fold(t0=3000, end=3100, horizon=h, embargo_days=emb)
        assert f.gap == gap and f.train_end_idx == 3000 - gap - 1
        assert max(f.calib_idx) == 3000 - gap - 1  # the last allowed row is used ...
        assert 3000 - gap not in f.train_idx  # ... and the first forbidden one never
        for t in f.train_idx:
            assert t + gap < 3000  # t + gap < t0 for every row


@pytest.mark.unit
def test_core_is_purged_from_the_calibration_block() -> None:
    f = _fold()
    assert max(f.train_core_idx) + f.gap < min(f.calib_idx)
    assert max(f.train_core_idx) == min(f.calib_idx) - f.gap - 1
    assert not set(f.train_core_idx) & set(f.calib_idx)


@pytest.mark.unit
def test_stride_pattern_applies_to_both_blocks_but_never_to_test_dates() -> None:
    f = _fold(train_stride=5)
    assert all((t - 252) % 5 == 0 for t in f.train_idx)
    assert f.train_core_idx[:3] == [252, 257, 262]
    assert f.calib_idx[0] == 1482 and f.calib_idx[-1] == 1982  # strided inside [1480, 1983]
    assert len(f.train_core_idx) == 241 and len(f.calib_idx) == 101
    assert list(f.test_idx) == list(range(2010, 2263))  # every test date, no stride
    unstrided = _fold()
    assert set(f.train_idx) <= set(unstrided.train_idx)


@pytest.mark.unit
def test_rolling_window_limits_the_core() -> None:
    f = _fold(train_window_days=300)
    assert f.train_core_idx[-1] == 1453 and f.train_core_idx[0] == 1453 - 300 + 1
    assert len(f.train_core_idx) == 300
    huge = _fold(train_window_days=10_000)
    assert huge.train_core_idx[0] == 252 and huge.train_core_idx == _fold().train_core_idx
    short = _fold(train_window_days=50)
    assert short.train_core_idx[0] == 1453 - 49


@pytest.mark.unit
def test_no_calibration_block_when_calibration_days_is_zero() -> None:
    f = _fold(calib=0)
    assert f.calib_idx == [] and f.train_core_idx[-1] == f.train_end_idx == 1983
    assert f.train_core_idx[0] == 252


@pytest.mark.unit
def test_invalid_parameters_and_insufficient_history_raise() -> None:
    for bad in ({"horizon": 0}, {"embargo_days": -1}, {"train_stride": 0},
                {"train_window_days": 0}):
        with pytest.raises(FoldError, match="invalid|positive"):
            _fold(**bad)
    with pytest.raises(FoldError, match="empty test period"):
        _fold(t0=2010, end=2009)
    with pytest.raises(FoldError, match="not after first_train_idx"):
        _fold(t0=252)
    with pytest.raises(FoldError, match="not enough history"):
        _fold(t0=700)  # train_end 673, calibration from 170, core would end at 143 < 252
    with pytest.raises(FoldError, match="leaves an empty block"):
        _fold(t0=2010, calib=3, train_stride=1000)


@pytest.mark.unit
def test_year_bounds_and_first_train_idx_on_a_calendar() -> None:
    cal = bday_calendar()
    first, last = year_bounds(cal, 2008)
    assert cal.date_at(first).year == 2008 and cal.date_at(first - 1).year == 2007
    assert cal.date_at(last).year == 2008 and cal.date_at(last + 1).year == 2009
    with pytest.raises(FoldError, match="no trading date"):
        year_bounds(cal, 1990)
    cfg = make_cfg(cal, first_train_idx=260)
    assert first_train_idx(cfg, cal) == 260


def _setup():
    cal = bday_calendar()
    return cal, make_cfg(cal, first_train_idx=252)


@pytest.mark.unit
def test_make_dev_folds_one_per_year_covering_each_full_year() -> None:
    cal, cfg = _setup()
    folds = make_dev_folds(cfg, cal)
    assert [f.test_year for f in folds] == list(range(2008, 2020)) and len(folds) == 12
    assert [f.fold_id for f in folds][:2] == ["dev_2008", "dev_2009"]
    for f in folds:
        first, last = year_bounds(cal, f.test_year)
        assert (f.test_start_idx, f.test_end_idx) == (first, last)
        assert f.kind == "dev" and f.gap == 26
        assert cal.date_at(f.test_end_idx).year == f.test_year < 2020
    lock = int(cal.dates.searchsorted(np.datetime64("2020-01-02")))
    assert cal.date_at(folds[-1].test_end_idx) == np.datetime64("2019-12-31")  # last dev date
    assert folds[-1].test_end_idx < lock
    assert all(max(f.train_idx) < lock for f in folds)
    # years may be listed in any order, duplicates are ignored
    odd = make_cfg(cal, first_train_idx=252, dev_test_years=[2010, 2009, 2009])
    assert [f.test_year for f in make_dev_folds(odd, cal)] == [2009, 2010]
    with pytest.raises(FoldError, match="locked period"):
        make_dev_folds(make_cfg(cal, first_train_idx=252, dev_test_years=[2019, 2020]), cal)


@pytest.mark.unit
def test_make_tuning_folds_have_no_calibration_and_stop_at_tuning_max_idx() -> None:
    cal, cfg = _setup()
    folds = make_tuning_folds(cfg, cal)
    assert [f.test_year for f in folds] == [2005, 2006, 2007]
    cap = int(cal.dates.searchsorted(np.datetime64("2007-12-31"), side="right")) - 22
    for f in folds:
        assert f.kind == "tuning" and f.calib_idx == [] and f.test_end_idx <= cap
        assert max(f.train_idx) + f.gap < f.test_start_idx
    assert folds[-1].test_end_idx == cap  # 2007 is cut where labels stop resolving before 2008
    assert folds[0].test_end_idx == year_bounds(cal, 2005)[1]
    late = make_cfg(cal, first_train_idx=252, tuning_valid_years=[2009])
    with pytest.raises(FoldError, match="after tuning_max_idx"):
        make_tuning_folds(late, cal)


@pytest.mark.unit
def test_make_locked_folds_requires_the_token_and_covers_2020_to_the_end(tmp_path) -> None:
    cal, cfg = _setup()
    with pytest.raises(LockedTestError):
        make_locked_folds(cfg, None, cal)  # type: ignore[arg-type]
    token = issue_token(cfg, tmp_path)
    folds = make_locked_folds(cfg, token, cal)
    lock = int(cal.dates.searchsorted(np.datetime64("2020-01-02")))
    assert [f.test_year for f in folds] == list(range(2020, cal.last_date.year + 1))
    assert folds[0].test_start_idx == lock and folds[-1].test_end_idx == cal.last_idx
    assert all(f.kind == "locked" for f in folds)
    # an expanding window: later folds train on earlier locked years
    assert max(folds[1].train_idx) >= lock


@pytest.mark.unit
def test_locked_folds_start_at_the_configured_lock_not_at_the_start_of_the_year(tmp_path) -> None:
    cal = bday_calendar()
    cfg = make_cfg(cal, first_train_idx=252, locked_test_start="2020-06-15")
    folds = make_locked_folds(cfg, issue_token(cfg, tmp_path), cal)
    lock = int(cal.dates.searchsorted(np.datetime64("2020-06-15")))
    assert folds[0].test_year == 2020 and folds[0].test_start_idx == lock
    assert cal.date_at(folds[0].test_start_idx) >= np.datetime64("2020-06-15")
    assert folds[1].test_start_idx == year_bounds(cal, 2021)[0]


@pytest.mark.unit
def test_fold_plan_documents_dev_and_tuning_folds_but_not_locked_ones(tmp_path) -> None:
    cal, cfg = _setup()
    plan = build_fold_plan(cfg, cal)
    assert len(plan["dev_folds"]) == 12 and len(plan["tuning_folds"]) == 3
    assert plan["gap"] == 26 and plan["horizon"] == 20 and plan["train_stride"] == 5
    assert plan["locked_test_start"] == "2020-01-02"
    assert plan["last_dev_label_idx"] == plan["locked_test_start_idx"] - 22
    assert "locked_folds" not in plan and plan == json.loads(json.dumps(plan))
    f0 = plan["dev_folds"][0]
    assert f0["gap"] == 26 and f0["core"]["n_dates"] > 0 and f0["calibration"]["n_dates"] > 0
    assert f0["calibration"]["span_days"] == 501 and f0["n_test_dates"] > 200
    out = tmp_path / "sub" / "fold_plan.json"
    written = write_fold_plan(cfg, cal, out)
    assert json.loads(out.read_text(encoding="utf-8")) == written == plan
    assert write_fold_plan(cfg, cal, out) == plan  # deterministic
    summary = fold_summary(make_dev_folds(cfg, cal)[0], cal)
    assert summary["test_start_date"] == cal.date_at(summary["test_start_idx"]).date().isoformat()


@pytest.mark.unit
def test_fold_dataclass_helpers() -> None:
    f = Fold("x", "dev", 2008, 100, 110, [1, 2], [5], 26, 99)
    assert f.train_idx == [1, 2, 5] and list(f.test_idx) == list(range(100, 111))
    assert f.base_rate is None
