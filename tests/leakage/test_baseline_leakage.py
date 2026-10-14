"""Leakage tests for S7: baselines and the predictive evaluation never look ahead.

* a baseline prediction at date ``t`` uses only features at ``t`` (poisoned-future test);
* predictions never depend on labels;
* unlabelled rows are never evaluated, even when they carry numeric garbage;
* a null panel gives no significant skill for any baseline, a planted panel does (the pipeline
  can find a signal and does not invent one);
* structurally, S7 code reads panels only through ``load_panel(..., "dev")`` and never opens the
  locked test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nasdaq100
from nasdaq100.evaluation.predictive import EvalSettings, attach_labels
from nasdaq100.models.baselines import BASELINE_IDS, build_predictions, evaluate_baselines
from tests.fixtures.s6_validation import bday_calendar
from tests.fixtures.s7_eval import baseline_panel, dev_folds_for

CAL = bday_calendar()
SETTINGS = EvalSettings(n_boot=100, seed=42)
S7_MODULES = ("models/baselines.py", "evaluation/predictive.py", "evaluation/stats.py")
FORBIDDEN_NAMES = (
    "open_locked_test",
    "load_features_model",
    "load_features_raw",
    "load_labels",
    "load_universe",
)


@pytest.mark.leakage
def test_poisoned_future_does_not_change_earlier_predictions() -> None:
    panel = baseline_panel(CAL, seed=1)
    folds = dev_folds_for(panel)
    cutoff = CAL.idx_of("2008-09-30")
    base = build_predictions(panel, folds, None, seed=42)

    poisoned = panel.copy()
    future = poisoned["t_idx"] > cutoff
    rng = np.random.default_rng(0)
    for col in ("mom_12_1", "ret_21", "vol_63", "excess_h20", "y_reg_h20", "ret_fwd_h20"):
        poisoned.loc[future, col] = rng.normal(100.0, 50.0, int(future.sum()))
    poisoned.loc[future, "has_label_h20"] = False
    after = build_predictions(poisoned, folds, None, seed=42)

    cut_date = CAL.date_at(cutoff)
    pd.testing.assert_frame_equal(
        base[base["date"] <= cut_date].reset_index(drop=True),
        after[after["date"] <= cut_date].reset_index(drop=True),
    )
    assert not after[after["date"] > cut_date].equals(base[base["date"] > cut_date])  # sanity


@pytest.mark.leakage
def test_predictions_do_not_depend_on_labels() -> None:
    panel = baseline_panel(CAL, seed=1)
    folds = dev_folds_for(panel)
    shuffled = panel.copy()
    for col in ("ret_fwd_h20", "excess_h20", "y_reg_h20", "y_cls_h20", "rank_pct_h20"):
        shuffled[col] = np.random.default_rng(9).permutation(shuffled[col].to_numpy())
    shuffled["has_label_h20"] = False
    pd.testing.assert_frame_equal(
        build_predictions(panel, folds, None, seed=42),
        build_predictions(shuffled, folds, None, seed=42),
    )


@pytest.mark.leakage
def test_unlabelled_rows_are_never_evaluated_even_with_numeric_garbage() -> None:
    cut = CAL.idx_of("2009-12-31") - 30
    panel = baseline_panel(CAL, seed=1, mask_after_idx=cut)
    folds = dev_folds_for(panel)
    garbage = panel.copy()
    late = garbage["t_idx"] > cut
    garbage.loc[late, "excess_h20"] = 1e6  # numbers, but has_label_h20 is still False
    garbage.loc[late, "y_cls_h20"] = 1.0
    clean = evaluate_baselines(panel, folds, None, settings=SETTINGS, horizon=20, seed=42)
    dirty = evaluate_baselines(garbage, folds, None, settings=SETTINGS, horizon=20, seed=42)
    for model_id in BASELINE_IDS:
        pd.testing.assert_frame_equal(clean.tables[model_id], dirty.tables[model_id])
        assert (clean.evaluated[model_id]["t_idx"] <= cut).all()
    preds = clean.predictions
    pred_m = preds[preds["model_id"] == "baseline_rev21"]
    assert attach_labels(pred_m, garbage, 20)["t_idx"].max() <= cut


@pytest.mark.leakage
def test_null_panel_gives_no_skill_and_a_planted_panel_does() -> None:
    for seed in (1, 2):
        null = baseline_panel(CAL, seed=seed, strength=0.0)
        out = evaluate_baselines(null, dev_folds_for(null), None, settings=SETTINGS, seed=42)
        for model_id, table in out.tables.items():
            tstat = table.loc[table["scope"] == "pooled", "ic_tstat"].iloc[0]
            assert abs(tstat) < 3.0, (seed, model_id, tstat)  # leakage would show up here
        planted = baseline_panel(CAL, seed=seed, strength=0.4)
        out = evaluate_baselines(planted, dev_folds_for(planted), None, settings=SETTINGS, seed=42)
        pooled = {m: t[t["scope"] == "pooled"].iloc[0] for m, t in out.tables.items()}
        for model_id in ("baseline_mom12_1", "baseline_rev21", "baseline_lowvol"):
            assert pooled[model_id]["ic_tstat"] > 3.0 and pooled[model_id]["mean_ic"] > 0.1
        assert abs(pooled["baseline_random"]["ic_tstat"]) < 2.5  # random stays random


def _names_used(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            used.update(a.name for a in node.names)
        elif isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    return used


@pytest.mark.leakage
def test_s7_modules_use_neither_the_locked_test_nor_the_unguarded_readers() -> None:
    root = Path(nasdaq100.__file__).parent
    for rel in S7_MODULES:
        names = _names_used(root / rel)
        for forbidden in FORBIDDEN_NAMES:
            assert forbidden not in names, f"{rel} uses {forbidden}"


@pytest.mark.leakage
def test_run_baselines_builds_only_the_development_panel() -> None:
    root = Path(nasdaq100.__file__).parent
    tree = ast.parse((root / "models" / "baselines.py").read_text(encoding="utf-8"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "load_panel"
    ]
    assert len(calls) == 1
    split = calls[0].args[2]
    assert isinstance(split, ast.Constant) and split.value == "dev"
    assert not any(kw.arg == "token" for kw in calls[0].keywords)
