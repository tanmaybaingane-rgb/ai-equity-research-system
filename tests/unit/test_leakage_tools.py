"""Unit tests for the leakage tooling (``validation/leakage.py``)."""

from __future__ import annotations

import subprocess
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from nasdaq100.data.loaders import build_panel
from nasdaq100.validation import leakage
from nasdaq100.validation.folds import Fold, make_dev_folds, make_tuning_folds
from nasdaq100.validation.leakage import (
    LeakageError,
    SpyEstimator,
    assert_folds_valid,
    null_panel_test,
    poison_future,
    run_leakage_suite,
)
from tests.fixtures.s6_validation import bday_calendar, make_cfg, panel_tables
from tests.fixtures.toy_data import make_null_panel

CAL = bday_calendar()
CFG = make_cfg(CAL, first_train_idx=252)
LOCK = int(CAL.dates.searchsorted(np.datetime64("2020-01-02")))
KW = {"horizon": 20, "embargo_days": 5}


def _fold(**over) -> Fold:
    base = Fold("f", "dev", 2008, 2010, 2262, list(range(252, 1454)), list(range(1480, 1984)),
                26, 1983)
    return replace(base, **over)


@pytest.mark.unit
def test_valid_dev_and_tuning_folds_pass() -> None:
    dev, tun = make_dev_folds(CFG, CAL), make_tuning_folds(CFG, CAL)
    assert_folds_valid(dev, **KW, first_train_idx=252, locked_start_idx=LOCK, train_stride=5)
    assert_folds_valid(tun, **KW, first_train_idx=252, locked_start_idx=LOCK, train_stride=5)
    assert_folds_valid([_fold()], **KW, first_train_idx=252, first_test_idx=2010)


@pytest.mark.unit
def test_off_by_one_row_at_t0_minus_gap_minus_1_allowed_t0_minus_gap_blocked() -> None:
    t0, gap = 2010, 26
    ok = _fold(train_core_idx=[252, t0 - gap - 1], calib_idx=[], train_end_idx=t0 - gap - 1)
    assert_folds_valid([ok], **KW)  # t + gap = t0 - 1 < t0: allowed
    bad = _fold(train_core_idx=[252, t0 - gap], calib_idx=[], train_end_idx=t0 - gap - 1)
    with pytest.raises(LeakageError, match="violates the gap"):
        assert_folds_valid([bad], **KW)  # t + gap = t0: forbidden
    bad_calib = _fold(train_core_idx=[252], calib_idx=[t0 - gap])
    with pytest.raises(LeakageError, match="violates the gap"):
        assert_folds_valid([bad_calib], **KW)  # the calibration block is purged too


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"gap": 25}, "gap 25"),
        ({"train_end_idx": 1984}, "train_end"),
        ({"train_core_idx": []}, "empty training core"),
        ({"calib_idx": list(range(1450, 1984))}, "overlap"),
        ({"train_core_idx": list(range(252, 1480)), "calib_idx": list(range(1480, 1984))},
         "core is not purged"),
        ({"calib_idx": [1990, 1991], "train_end_idx": 1983}, "violates the gap|follow the test"),
        ({"train_core_idx": [300, 299]}, "strictly increasing"),
        ({"test_end_idx": 2000}, "empty or reversed"),
        ({"test_start_idx": 1990, "test_end_idx": 2262}, "train_end"),
    ],
)
def test_assert_folds_valid_rejects_each_violation(changes, match) -> None:
    with pytest.raises(LeakageError, match=match):
        assert_folds_valid([_fold(**changes)], **KW)


@pytest.mark.unit
def test_optional_checks_first_indices_stride_locked_and_order() -> None:
    f = _fold()
    with pytest.raises(LeakageError, match="first_train_idx"):
        assert_folds_valid([f], **KW, first_train_idx=300)
    with pytest.raises(LeakageError, match="first test date"):
        assert_folds_valid([f], **KW, first_test_idx=2011)
    strided = _fold(train_core_idx=[252, 257, 263], calib_idx=[])
    with pytest.raises(LeakageError, match="train_stride"):
        assert_folds_valid([strided], **KW, first_train_idx=252, train_stride=5)
    with pytest.raises(LeakageError, match="locked start"):
        assert_folds_valid([f], **KW, locked_start_idx=2100)  # test period reaches the lock
    locked = replace(f, kind="locked")
    assert_folds_valid([locked], **KW, locked_start_idx=2100)  # locked folds may
    second = replace(f, fold_id="g", test_start_idx=2100, test_end_idx=2300, train_end_idx=2100 - 27)
    with pytest.raises(LeakageError, match="chronological"):
        assert_folds_valid([f, replace(second, test_start_idx=2200, test_end_idx=2300,
                                       train_end_idx=2200 - 27, train_core_idx=[300],
                                       calib_idx=[]), replace(f, fold_id="h")], **KW)
    with pytest.raises(LeakageError, match="chronological"):
        assert_folds_valid([f, f], **KW)  # overlapping test periods


@pytest.mark.unit
def test_poison_future_destroys_everything_after_t_and_keeps_the_rest() -> None:
    fm, lab, uni = panel_tables(CAL)
    panel = build_panel(fm, lab, uni, CAL, CFG, None, "dev")
    before = panel.copy()
    t = 3000
    out = poison_future(panel, t)
    pd.testing.assert_frame_equal(panel, before)  # input untouched
    early, late = out[out["t_idx"] <= t], out[out["t_idx"] > t]
    pd.testing.assert_frame_equal(
        early, panel[panel["t_idx"] <= t], check_dtype=False  # integer columns become float64
    )
    assert len(late) > 0 and (out["t_idx"] == panel["t_idx"]).all()
    assert late[["ticker", "date"]].equals(panel.loc[late.index, ["ticker", "date"]])
    for col in ("f1", "f2", "ret_fwd_h20", "excess_h20", "y_reg_h20", "y_cls_h20",
                "rank_pct_h20", "label_exit_idx_h20"):
        assert late[col].isna().all(), col
    assert not late["eligible"].any() and not late["has_label_h20"].any()
    assert poison_future(panel, int(panel["t_idx"].max())).equals(panel)  # nothing to poison
    with pytest.raises(ValueError, match="t_idx"):
        poison_future(panel.drop(columns=["t_idx"]), 5)


class _MeanEstimator:
    def fit(self, X, y=None, sample_weight=None):
        self.cols_ = list(getattr(X, "columns", []))
        self.mean_ = float(np.mean(y)) if y is not None else 0.0
        return self

    def predict(self, X):
        return np.full(len(X), self.mean_)

    answer = 42


@pytest.mark.unit
def test_spy_estimator_records_the_largest_t_idx_seen_in_fit() -> None:
    spy = SpyEstimator(_MeanEstimator())
    assert spy.max_t_idx_seen is None
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0], "t_idx": [10, 12, 11]})
    assert spy.fit(X, [1.0, 2.0, 3.0]) is spy
    assert spy.max_t_idx_seen == 12 and spy.fit_calls[0] == {
        "n_rows": 3, "min_t_idx": 10, "max_t_idx": 12}
    assert spy.estimator.cols_ == ["a"]  # the t_idx column is not forwarded to the model
    spy.fit(pd.DataFrame({"a": [1.0, 2.0]}), [1.0, 2.0], t_idx=[40, 41])
    assert spy.max_t_idx_seen == 41 and len(spy.fit_calls) == 2
    Xi = pd.DataFrame({"a": [1.0, 2.0]}, index=pd.Index([7, 99], name="t_idx"))
    spy.fit(Xi, [1.0, 2.0])
    assert spy.max_t_idx_seen == 99
    spy.assert_max_t_idx(99)
    with pytest.raises(LeakageError, match="99 > allowed maximum 50"):
        spy.assert_max_t_idx(50)
    assert spy.answer == 42 and list(spy.predict(Xi)) == [1.5, 1.5]  # forwarded
    with pytest.raises(ValueError, match="needs t_idx"):
        spy.fit(pd.DataFrame({"a": [1.0]}), [1.0])
    with pytest.raises(ValueError, match="no rows"):
        spy.fit(Xi.iloc[0:0], [], t_idx=[])
    SpyEstimator(_MeanEstimator()).assert_max_t_idx(0)  # never fitted: nothing to complain about


def _honest_pipeline(panel: pd.DataFrame, seed: int) -> dict:
    """Fit-predict-evaluate on the null panel using only features (a trivial model)."""
    ics = []
    for t in range(0, 130, 21):  # non-overlapping labels
        day = panel[panel["t_idx"] == t]
        ics.append(day["feature_1"].corr(day["excess_h20"], method="spearman"))
    return {"ic_by_date": ics, "auc": 0.5 + 0.0 * seed}


def _leaky_pipeline(panel: pd.DataFrame, seed: int) -> dict:
    """The 'model' sees the label (a deliberately injected leak)."""
    ics = []
    for t in range(0, 130, 21):
        day = panel[panel["t_idx"] == t]
        ics.append(day["excess_h20"].corr(day["excess_h20"] + 0.1 * day["feature_2"],
                                          method="spearman"))
    return {"ic_by_date": ics, "auc": 0.9}


@pytest.mark.unit
def test_null_panel_test_passes_an_honest_pipeline_and_flags_a_leaky_one() -> None:
    def factory(seed):
        return make_null_panel(seed=seed, n_tickers=20, n_days=150)

    summary = null_panel_test(_honest_pipeline, tuple(range(10)), factory)
    assert abs(summary["mean_ic"]) <= 2.5 * summary["se"] and summary["n_extreme_runs"] <= 2
    assert summary["mean_auc"] == 0.5 and summary["n_seeds"] == 10
    default = null_panel_test(_honest_pipeline)  # default factory: the S0 make_null_panel
    assert abs(default["mean_ic"]) <= 2.5 * default["se"]
    with pytest.raises(LeakageError, match="leakage"):
        null_panel_test(_leaky_pipeline, tuple(range(10)), factory)


@pytest.mark.unit
def test_null_panel_test_individual_criteria_and_input_validation() -> None:
    def factory(seed):
        return make_null_panel(seed=seed, n_tickers=20, n_days=150)

    rng = np.random.default_rng(0)

    def biased(panel, seed):  # mean IC clearly above zero
        return {"ic_by_date": 0.3 + rng.normal(0, 0.05, 8)}

    with pytest.raises(LeakageError, match="beyond 2.5 SE"):
        null_panel_test(biased, tuple(range(10)), factory)

    def extreme_runs(panel, seed):  # mean zero overall, but 5 of 10 runs significantly +/-
        sign = 1.0 if seed % 2 else -1.0
        return {"ic_by_date": sign * 0.4 + rng.normal(0, 0.05, 8)}

    with pytest.raises(LeakageError, match="runs have"):
        null_panel_test(extreme_runs, tuple(range(10)), factory, se_multiple=1000.0)

    def good_ic_bad_auc(panel, seed):
        return {"ic_by_date": rng.normal(0, 0.1, 30), "auc": 0.56}

    with pytest.raises(LeakageError, match="AUC"):
        null_panel_test(good_ic_bad_auc, tuple(range(10)), factory)
    with pytest.raises(ValueError, match="at least 10 seeds"):
        null_panel_test(_honest_pipeline, (1, 2, 3), factory)
    with pytest.raises(ValueError, match="non-constant"):
        null_panel_test(lambda p, s: {"ic_by_date": [0.1]}, tuple(range(10)), factory)


@pytest.mark.unit
def test_run_leakage_suite_runs_pytest_leakage_from_the_repo_root(monkeypatch) -> None:
    seen = {}

    def fake_run(cmd, cwd, check):
        seen.update(cmd=cmd, cwd=cwd, check=check)
        return subprocess.CompletedProcess(cmd, 3)

    monkeypatch.setattr(leakage.subprocess, "run", fake_run)
    assert run_leakage_suite() == 3
    assert seen["cmd"][1:6] == ["-m", "pytest", "-m", "leakage", "-q"]
    assert seen["cwd"] == leakage.repo_root() and seen["check"] is False
