"""Unit tests for the S7 baselines and the ``run-baselines`` pipeline (``models/baselines.py``)."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import config_hash, load_config
from nasdaq100.evaluation.predictive import EvalSettings
from nasdaq100.models.baselines import (
    BASELINE_IDS,
    PREDICTION_COLUMNS,
    BaselineError,
    baseline_meta,
    baseline_score,
    build_predictions,
    evaluate_baselines,
    predict_baseline,
    random_scores,
    required_features,
    run_baselines,
)
from nasdaq100.paths import baseline_metrics_path, dev_reports_dir, features_raw_path
from nasdaq100.utils.io import REGISTRY_COLUMNS, append_registry
from nasdaq100.validation.guards import LockedTestError
from tests.fixtures.s6_validation import bday_calendar
from tests.fixtures.s7_eval import baseline_panel, dev_folds_for

CAL = bday_calendar()
CFG = load_config(
    overrides=[
        f"validation.first_train_decision_date={CAL.date_at(252).date()}",
        "validation.dev_test_years=[2008, 2009]",
        "evaluation.bootstrap_n=100",
    ]
)
LAST_2009 = CAL.idx_of("2009-12-31")
SETTINGS = EvalSettings.from_cfg(CFG)


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return baseline_panel(CAL, seed=1)


@pytest.fixture(scope="module")
def folds(panel: pd.DataFrame):
    return dev_folds_for(panel)


# ------------------------------------------------------------------------------- scores


@pytest.mark.unit
def test_random_scores_depend_only_on_seed_date_and_ticker() -> None:
    day = ["2010-01-04"] * 3
    a = random_scores(["A", "B", "C"], day, 42)
    b = random_scores(["C", "A", "B"], day, 42)  # same keys in another order
    assert (a[0], a[1], a[2]) == (b[1], b[2], b[0])
    assert ((a >= 0.0) & (a < 1.0)).all() and len(set(a)) == 3
    assert random_scores(["A"], ["2010-01-04"], 43)[0] != a[0]  # the seed matters
    assert random_scores(["A"], ["2010-01-05"], 42)[0] != a[0]  # so does the date
    big = random_scores([f"T{k}" for k in range(4000)], ["2010-01-04"] * 4000, 1)
    assert abs(big.mean() - 0.5) < 0.03 and abs(big.std() - math.sqrt(1 / 12)) < 0.02


@pytest.mark.unit
def test_scores_use_the_documented_features_and_signs(panel: pd.DataFrame) -> None:
    assert np.array_equal(baseline_score(panel, "baseline_mom12_1"), panel["mom_12_1"])
    assert np.array_equal(baseline_score(panel, "baseline_rev21"), -panel["ret_21"])
    assert np.array_equal(baseline_score(panel, "baseline_lowvol"), -panel["vol_63"])
    rnd = baseline_score(panel, "baseline_random", seed=7)
    assert rnd.between(0.0, 1.0).all() and rnd.nunique() == len(panel)
    with pytest.raises(BaselineError, match="unknown baseline"):
        baseline_score(panel, "baseline_nope")
    with pytest.raises(BaselineError, match="lacks feature"):
        baseline_score(panel.drop(columns="vol_63"), "baseline_lowvol")
    assert required_features(BASELINE_IDS) == ["mom_12_1", "ret_21", "vol_63"]
    assert required_features(["baseline_random"]) == []


@pytest.mark.unit
def test_baseline_metadata_marks_scores_as_not_return_forecasts() -> None:
    for model_id in BASELINE_IDS:
        meta = baseline_meta(model_id)
        assert meta["units_are_returns"] is False and meta["model_id"] == model_id
    assert baseline_meta("baseline_rev21")["sign"] == -1
    assert baseline_meta("baseline_random")["feature"] is None


# ------------------------------------------------------------------- prediction contract


@pytest.mark.unit
def test_predictions_follow_the_prediction_table_contract(panel, folds) -> None:
    preds = build_predictions(panel, folds, None, seed=42)
    assert list(preds.columns) == list(PREDICTION_COLUMNS)
    assert set(preds["model_id"]) == set(BASELINE_IDS)
    assert preds.groupby(["ticker", "date", "model_id"]).size().max() == 1
    assert preds["prob_raw"].isna().all() and preds["prob_cal"].isna().all()
    assert preds["pred_excess"].notna().all()
    assert set(preds["fold_id"]) == {2008, 2009}
    assert (preds["date"].dt.year == preds["fold_id"]).all()  # fold_id = test year
    # per (model, date): rank_pct is a percentile with 1 = best
    top = preds.groupby(["model_id", "date"])["rank_pct"].max()
    assert (top == 1.0).all()
    one = preds[(preds["model_id"] == "baseline_mom12_1") & (preds["date"] == preds["date"].iloc[0])]
    assert one.loc[one["pred_excess"].idxmax(), "rank_pct"] == 1.0
    assert one.loc[one["pred_excess"].idxmin(), "rank_pct"] == pytest.approx(1.0 / len(one))
    # sorted by ticker, date, model_id
    keys = preds[["ticker", "date", "model_id"]].reset_index(drop=True)
    assert keys.equals(keys.sort_values(["ticker", "date", "model_id"]).reset_index(drop=True))


@pytest.mark.unit
def test_predictions_cover_eligible_rows_of_the_test_years_including_unlabelled_days() -> None:
    cut = LAST_2009 - 30
    masked = baseline_panel(CAL, seed=1, mask_after_idx=cut)
    masked.loc[masked["ticker"] == "T01", "eligible"] = False
    f = dev_folds_for(masked)
    preds = predict_baseline(masked, "baseline_mom12_1", f, seed=42)
    test_rows = masked[(masked["date"].dt.year.isin([2008, 2009])) & masked["eligible"]]
    assert len(preds) == len(test_rows)
    assert "T01" not in set(preds["ticker"])  # ineligible rows get no prediction
    assert preds["date"].min() >= pd.Timestamp("2008-01-01")  # nothing from the pre-test period
    last = masked.loc[masked["t_idx"] == LAST_2009, "date"].iloc[0]
    assert preds["date"].max() == last  # predictions reach the end although labels are masked
    assert not masked.loc[masked["t_idx"] > cut, "has_label_h20"].any()


@pytest.mark.unit
def test_rows_without_a_computed_score_get_no_prediction(panel, folds) -> None:
    p = panel.copy()
    warm = (p["ticker"] == "T00") & (p["date"].dt.year == 2008)
    p.loc[warm, "mom_12_1"] = np.nan
    preds = build_predictions(p, folds, None, seed=42)
    gone = (preds["ticker"] == "T00") & (preds["fold_id"] == 2008)
    assert not (gone & (preds["model_id"] == "baseline_mom12_1")).any()
    assert (gone & (preds["model_id"] == "baseline_rev21")).any()  # other baselines unaffected
    assert (gone & (preds["model_id"] == "baseline_random")).any()  # random needs no feature


@pytest.mark.unit
def test_predictions_do_not_depend_on_the_row_order(panel, folds) -> None:
    a = build_predictions(panel, folds, None, seed=42)
    b = build_predictions(panel.sample(frac=1.0, random_state=1), folds, None, seed=42)
    pd.testing.assert_frame_equal(a, b)


@pytest.mark.unit
def test_baselines_only_run_on_development_folds(panel) -> None:
    with pytest.raises(BaselineError, match="development folds only"):
        build_predictions(panel, dev_folds_for(panel, kind="locked"), None, seed=1)
    with pytest.raises(BaselineError, match="no folds"):
        build_predictions(panel, [], None, seed=1)
    with pytest.raises(BaselineError, match="unknown baseline"):
        build_predictions(panel, dev_folds_for(panel), ["baseline_nope"], seed=1)
    with pytest.raises(BaselineError, match="no baselines"):
        build_predictions(panel, dev_folds_for(panel), [], seed=1)
    with pytest.raises(BaselineError, match="lacks column"):
        predict_baseline(panel.drop(columns="eligible"), "baseline_rev21", dev_folds_for(panel))


# ------------------------------------------------------------------------------ evaluation


@pytest.mark.unit
def test_evaluation_finds_the_planted_signals_and_nothing_in_random_scores(panel, folds) -> None:
    out = evaluate_baselines(panel, folds, None, settings=SETTINGS, horizon=20, seed=42)
    pooled = {m: t[t["scope"] == "pooled"].iloc[0] for m, t in out.tables.items()}
    for model_id in ("baseline_mom12_1", "baseline_rev21", "baseline_lowvol"):
        assert pooled[model_id]["mean_ic"] > 0.1 and pooled[model_id]["ic_tstat"] > 3.0, model_id
        assert pooled[model_id]["mean_quintile_spread"] > 0.0
    assert abs(pooled["baseline_random"]["ic_tstat"]) < 2.5
    for model_id, row in pooled.items():
        assert not row["units_are_returns"]
        assert math.isnan(row["mae"]) and math.isnan(row["r2_oos"])  # raw scores, not returns
        assert row["effective_n"] == 26
        assert (out.tables[model_id]["dataset_status"] == "SURVIVOR-BIASED").all()
        assert set(out.tables[model_id]["scope"]) == {"pooled", "year", "fold"}


@pytest.mark.unit
def test_unlabelled_days_are_predicted_but_not_evaluated() -> None:
    cut = LAST_2009 - 30
    masked = baseline_panel(CAL, seed=1, mask_after_idx=cut)
    out = evaluate_baselines(masked, dev_folds_for(masked), ["baseline_rev21"],
                             settings=SETTINGS, horizon=20, seed=42)
    evaluated = out.evaluated["baseline_rev21"]
    assert out.predictions["date"].max() > evaluated["date"].max()
    assert evaluated["t_idx"].max() <= cut and evaluated["excess"].notna().all()
    assert len(evaluated) < len(out.predictions)
    with pytest.raises(BaselineError, match="duplicate"):
        evaluate_baselines(masked, dev_folds_for(masked), ["baseline_rev21"] * 2)


# ----------------------------------------------------------------------------- run pipeline


def _run(tmp_path, panel, **kwargs):
    return run_baselines(
        CFG,
        panel=panel,
        calendar=CAL,
        runs_root=tmp_path / "runs",
        report_file=tmp_path / "reports" / "baseline_metrics.csv",
        registry_file=tmp_path / "registry.csv",
        data_hash_value="abc123",
        git_commit_value="deadbeef",
        **kwargs,
    )


@pytest.mark.unit
def test_run_baselines_writes_runs_registry_rows_and_the_dev_report(tmp_path) -> None:
    masked = baseline_panel(CAL, seed=1, mask_after_idx=LAST_2009 - 30)
    registry = tmp_path / "registry.csv"
    old = dict.fromkeys(REGISTRY_COLUMNS, "")
    old.update(run_id="older_run", stage="S0", counts_as_trial=False)
    append_registry(old, registry)

    result = _run(tmp_path, masked)

    cfg_hash = config_hash(CFG)[:8]
    assert set(result.run_ids) == set(BASELINE_IDS)
    assert len(set(result.run_ids.values())) == 4
    for model_id, run_id in result.run_ids.items():
        assert run_id.endswith(f"_S7_{model_id}_{cfg_hash}")
        rdir = result.run_dirs[model_id]
        assert rdir == tmp_path / "runs" / run_id
        for name in ("config_resolved.json", "oof_predictions.parquet", "metrics_model.json",
                     "metrics_model.csv"):
            assert (rdir / name).is_file(), name
        oof = pd.read_parquet(rdir / "oof_predictions.parquet")
        assert list(oof.columns) == list(PREDICTION_COLUMNS)
        assert set(oof["model_id"]) == {model_id}
        assert oof["date"].max() == masked.loc[masked["t_idx"] == LAST_2009, "date"].iloc[0]
        meta = json.loads((rdir / "config_resolved.json").read_text(encoding="utf-8"))
        assert meta["seed"] == 42 and meta["git_commit"] == "deadbeef"
        assert meta["data_hash"] == "abc123" and meta["units_are_returns"] is False
        assert meta["config"]["project"]["variant"] == "base" and len(meta["folds"]) == 2
        assert meta["baseline"]["units_are_returns"] is False
        doc = json.loads((rdir / "metrics_model.json").read_text(encoding="utf-8"))
        assert doc["units_are_returns"] is False and doc["pooled"]["mae"] is None
        pooled = result.metrics[(result.metrics["model_id"] == model_id)
                                & (result.metrics["scope"] == "pooled")].iloc[0]
        assert doc["pooled"]["mean_ic"] == pytest.approx(pooled["mean_ic"])
        assert doc["n_evaluated_rows"] < doc["n_prediction_rows"]  # unlabelled tail not scored
        table = pd.read_csv(rdir / "metrics_model.csv")
        assert set(table["scope"]) == {"pooled", "year", "fold"}

    reg = pd.read_csv(registry)
    assert list(reg.columns) == list(REGISTRY_COLUMNS) and len(reg) == 5
    assert reg.loc[0, "run_id"] == "older_run"  # append-only: the earlier row is untouched
    new = reg.iloc[1:]
    assert set(new["stage"]) == {"S7"} and set(new["split"]) == {"dev"}
    assert set(new["counts_as_trial"].astype(str)) == {"True"}
    assert set(new["key_metric_name"]) == {"rank_ic_mean_nonoverlap"}
    assert set(new["run_id"]) == set(result.run_ids.values())
    assert new["notes"].str.contains("units_are_returns=False").all()
    assert new["notes"].str.contains("SURVIVOR-BIASED").all()
    assert (new["git_commit"] == "deadbeef").all() and (new["data_hash"] == "abc123").all()

    report = pd.read_csv(result.report_path)
    assert result.report_path == tmp_path / "reports" / "baseline_metrics.csv"
    assert set(report["model_id"]) == set(BASELINE_IDS)
    assert set(report["scope"]) == {"pooled", "year"}
    assert (report["dataset_status"] == "SURVIVOR-BIASED").all()
    mom = report[(report["model_id"] == "baseline_mom12_1") & (report["scope"] == "pooled")]
    assert mom["mean_ic"].iloc[0] > 0.05


@pytest.mark.unit
def test_run_baselines_reads_raw_features_through_the_guarded_dev_loader(
    monkeypatch, tmp_path, panel
) -> None:
    import nasdaq100.data.loaders as loaders

    calls: list[dict] = []

    def fake_load_panel(cfg, features, split, labels=True, **kwargs):
        calls.append({"features": list(features), "split": split, "labels": labels, **kwargs})
        return panel

    monkeypatch.setattr(loaders, "load_panel", fake_load_panel)
    _run(tmp_path, None, model_ids=["baseline_rev21"])
    assert calls[0]["split"] == "dev" and calls[0]["labels"] is True
    assert calls[0]["features"] == ["ret_21"]
    assert calls[0]["features_file"] == features_raw_path("base")  # features_raw, not _model
    calls.clear()
    _run(tmp_path / "again", None, model_ids=["baseline_random"])
    assert calls[0]["features"] == [] and calls[0]["split"] == "dev"


@pytest.mark.unit
def test_run_baselines_refuses_a_panel_that_reaches_the_locked_period(tmp_path) -> None:
    leaky = baseline_panel(CAL, first="2009-11-02", last="2020-02-28", seed=1)
    with pytest.raises(LockedTestError):
        _run(tmp_path, leaky)
    assert not (tmp_path / "runs").exists()  # nothing was written
    assert not (tmp_path / "registry.csv").exists()


@pytest.mark.unit
def test_run_baselines_rejects_unknown_models_and_non_dev_folds(tmp_path, panel) -> None:
    with pytest.raises(BaselineError, match="unknown baseline"):
        _run(tmp_path, panel, model_ids=["baseline_nope"])
    with pytest.raises(BaselineError, match="development folds only"):
        _run(tmp_path, panel, folds=dev_folds_for(panel, kind="locked"))
    assert not (tmp_path / "registry.csv").exists()


@pytest.mark.unit
def test_baseline_report_path_is_variant_namespaced() -> None:
    assert baseline_metrics_path("base") == dev_reports_dir() / "baseline_metrics.csv"
    assert baseline_metrics_path("alt") == dev_reports_dir() / "baseline_metrics_alt.csv"
