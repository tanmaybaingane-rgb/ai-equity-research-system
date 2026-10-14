"""Unit tests for the S7 predictive evaluation library (``evaluation/predictive.py``)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from nasdaq100.config import load_config
from nasdaq100.evaluation.predictive import (
    CLASSIFICATION_COLUMNS,
    METRIC_COLUMNS,
    EvalSettings,
    PredictiveError,
    attach_labels,
    brier_score,
    calibration_slope_intercept,
    classification_metrics,
    compare_models,
    evaluate_model,
    expected_calibration_error,
    log_loss,
    metrics_by_group,
    metrics_frame,
    nonoverlap_mask,
    quantile_spread_by_date,
    rank_ic_by_date,
    regression_fit,
    reliability_table,
    roc_auc,
    spread_summary,
    summarise,
)
from tests.fixtures.s7_eval import eval_frame

S = EvalSettings(n_boot=200, seed=1)


def _with_pred(df: pd.DataFrame, pred: object) -> pd.DataFrame:
    return df.assign(pred_excess=pred)


# ----------------------------------------------------------------------------- rank IC


@pytest.mark.unit
def test_rank_ic_of_a_perfect_reversed_and_constant_predictor() -> None:
    df = eval_frame(n_days=60, strength=0.5)
    assert np.allclose(rank_ic_by_date(_with_pred(df, df["excess"]))["ic"], 1.0)
    assert np.allclose(rank_ic_by_date(_with_pred(df, -df["excess"]))["ic"], -1.0)
    const = _with_pred(df, 3.0)
    assert rank_ic_by_date(const)["ic"].isna().all()  # a constant predictor has no rank IC
    summary = summarise(const, S)  # ... and the aggregation does not raise
    assert math.isnan(summary["mean_ic"]) and summary["effective_n"] == 0


@pytest.mark.unit
def test_rank_ic_matches_scipy_spearman_including_ties() -> None:
    df = eval_frame(n_days=30, strength=0.5)
    ic = rank_ic_by_date(_with_pred(df, df["feat"]))
    day = ic["date"].iloc[5]
    part = df[df["date"] == day]
    assert ic["ic"].iloc[5] == pytest.approx(spearmanr(part["feat"], part["excess"])[0], abs=1e-12)
    assert ic["n_names"].iloc[5] == len(part)
    tied = part.assign(pred_excess=np.round(part["feat"]))
    expected = spearmanr(tied["pred_excess"], tied["excess"])[0]
    assert rank_ic_by_date(tied)["ic"].iloc[0] == pytest.approx(expected, abs=1e-12)


@pytest.mark.unit
def test_rank_ic_requires_the_minimum_number_of_names_per_date() -> None:
    df = eval_frame(n_days=10, n_names=19)
    ic = rank_ic_by_date(_with_pred(df, df["excess"]))
    assert ic.empty and list(ic.columns) == ["date", "t_idx", "n_names", "ic"]
    assert len(rank_ic_by_date(_with_pred(df, df["excess"]), min_names=19)) == 10
    ok = eval_frame(n_days=10, n_names=20)
    assert len(rank_ic_by_date(_with_pred(ok, ok["excess"]))) == 10
    empty = ok.iloc[0:0].assign(pred_excess=[])
    assert rank_ic_by_date(empty).empty and quantile_spread_by_date(empty).empty
    with pytest.raises(PredictiveError):
        rank_ic_by_date(ok)  # no pred_excess column


@pytest.mark.unit
def test_nonoverlap_mask_selects_every_step_th_date_from_the_anchor() -> None:
    t = np.arange(250, 340)
    assert list(t[nonoverlap_mask(t, 20, 252)]) == [252, 272, 292, 312, 332]
    assert list(nonoverlap_mask([232, 233], 20, 252)) == [True, False]  # before the anchor too
    with pytest.raises(PredictiveError):
        nonoverlap_mask(t, 0)


@pytest.mark.unit
def test_planted_signal_has_a_clearly_positive_ic_and_noise_has_none() -> None:
    planted = eval_frame(strength=0.5)
    res = summarise(_with_pred(planted, planted["feat"]), S)
    assert res["mean_ic"] > 0.1 and res["ic_tstat"] > 5.0 and res["hit_rate"] > 0.8
    assert res["ic_ci_low"] > 0.0 and res["ic_ci_low"] < res["mean_ic"] < res["ic_ci_high"]
    assert res["daily_mean_ic"] > 0.1 and res["daily_ic_nw_t"] > 5.0
    assert res["n_dates"] == 600 and 25 <= res["effective_n"] <= 35  # 600 days / step 20
    for seed in range(4):  # a random predictor on random labels: no significant IC
        noise = eval_frame(n_days=900, seed=seed)
        rnd = np.random.default_rng(100 + seed).normal(size=len(noise))
        out = summarise(_with_pred(noise, rnd), S)
        assert abs(out["ic_tstat"]) < 2.5, (seed, out["ic_tstat"])  # within 2.5 standard errors


@pytest.mark.unit
def test_headline_ic_statistics_use_only_non_overlapping_dates() -> None:
    df = eval_frame(n_days=200, strength=0.5)
    pred = _with_pred(df, df["feat"])
    ic = rank_ic_by_date(pred)
    on_grid = ic[nonoverlap_mask(ic["t_idx"], S.step, S.anchor)]["ic"].to_numpy()
    res = summarise(pred, S)
    assert res["effective_n"] == len(on_grid) == 10
    assert res["mean_ic"] == pytest.approx(on_grid.mean())
    assert res["std_ic"] == pytest.approx(np.std(on_grid, ddof=1))
    assert res["ic_tstat"] == pytest.approx(on_grid.mean() / (np.std(on_grid, ddof=1) / math.sqrt(10)))
    assert res["daily_mean_ic"] == pytest.approx(ic["ic"].mean())  # secondary view: every date


# ------------------------------------------------------------------------ quantile spreads


@pytest.mark.unit
def test_quantile_buckets_have_the_documented_arithmetic() -> None:
    one = pd.DataFrame(
        {
            "ticker": range(100),
            "date": pd.Timestamp("2010-01-04"),
            "t_idx": 252,
            "pred_excess": np.arange(1, 101, dtype="float64"),
            "excess": np.arange(1, 101, dtype="float64"),
        }
    )
    row = quantile_spread_by_date(one).iloc[0]
    assert row["n_names"] == 100
    assert row["top_mean"] == np.mean(np.arange(80, 101))  # rank_pct >= 0.8 -> 21 names
    assert row["bottom_mean"] == np.mean(np.arange(1, 21))  # rank_pct <= 0.2 -> 20 names
    assert row["top_decile_mean"] == np.mean(np.arange(90, 101))
    assert row["spread"] == row["top_mean"] - row["bottom_mean"]


@pytest.mark.unit
def test_quantile_spread_sign_follows_the_predictor() -> None:
    df = eval_frame(n_days=200, strength=0.5)
    assert quantile_spread_by_date(_with_pred(df, df["feat"]))["spread"].mean() > 0.5
    assert quantile_spread_by_date(_with_pred(df, -df["feat"]))["spread"].mean() < -0.5
    assert quantile_spread_by_date(_with_pred(df, 1.0))["spread"].isna().all()  # constant
    res = summarise(_with_pred(df, df["feat"]), S)
    assert res["mean_quintile_spread"] == pytest.approx(
        res["mean_top_quintile"] - res["mean_bottom_quintile"]
    )
    assert res["spread_nonoverlap_tstat"] > 3.0 and res["mean_top_decile_excess"] > 0.5
    spreads = quantile_spread_by_date(_with_pred(df, df["feat"]))
    assert spread_summary(spreads, S)["effective_n"] == res["effective_n"] == 10


# ------------------------------------------------------------------------ regression fit


@pytest.mark.unit
def test_regression_fit_and_the_units_flag() -> None:
    x = pd.DataFrame(
        {"date": pd.Timestamp("2010-01-04"), "t_idx": 252, "pred_excess": [0.0] * 30,
         "excess": np.linspace(-1.0, 1.0, 30)}
    )
    fit = regression_fit(x)
    assert fit["r2_oos"] == pytest.approx(0.0, abs=1e-12)  # zero forecast: R2 = 0 by definition
    assert fit["mae"] == pytest.approx(np.mean(np.abs(x["excess"])))
    perfect = regression_fit(x.assign(pred_excess=x["excess"]))
    assert perfect["r2_oos"] == pytest.approx(1.0) and perfect["mae"] == pytest.approx(0.0)
    raw = regression_fit(x, units_are_returns=False)  # raw scores are not return forecasts
    assert math.isnan(raw["mae"]) and math.isnan(raw["r2_oos"])
    assert fit["n_obs"] == 30 and fit["n_dates"] == 1 and fit["effective_n"] == 1  # t_idx 252
    empty = regression_fit(x.iloc[0:0])
    assert math.isnan(empty["mae"]) and math.isnan(empty["r2_oos"])
    assert (empty["n_obs"], empty["n_dates"], empty["effective_n"]) == (0, 0, 0)


# ----------------------------------------------------------- classification / calibration


def _calibrated_levels() -> tuple[np.ndarray, np.ndarray]:
    levels = np.arange(0.05, 1.0, 0.1)
    prob = np.repeat(levels, 1000)
    y = np.concatenate(
        [np.r_[np.ones(round(p * 1000)), np.zeros(1000 - round(p * 1000))] for p in levels]
    )
    return prob, y


@pytest.mark.unit
def test_calibration_metrics_on_exactly_calibrated_and_distorted_probabilities() -> None:
    prob, y = _calibrated_levels()
    assert expected_calibration_error(prob, y) == pytest.approx(0.0, abs=1e-12)
    assert expected_calibration_error(np.clip(prob + 0.2, 0.0, 0.99), y) > 0.1
    slope, intercept = calibration_slope_intercept(prob, y)
    assert slope == pytest.approx(1.0, abs=0.02) and intercept == pytest.approx(0.0, abs=0.02)
    table = reliability_table(prob, y, n_bins=10, prob_col="prob_cal")
    assert list(table["n"]) == [1000] * 10 and table["prob_col"].eq("prob_cal").all()
    assert np.allclose(table["mean_prob"], table["frac_pos"])
    flat = calibration_slope_intercept(np.full(100, 0.5), (np.arange(100) % 2).astype(float))
    assert math.isnan(flat[0]) and math.isnan(flat[1])  # constant probabilities: degenerate


@pytest.mark.unit
def test_auc_logloss_and_brier_have_known_values() -> None:
    assert roc_auc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == pytest.approx(0.75)
    assert roc_auc([0, 1], [0.2, 0.2]) == pytest.approx(0.5)  # ties count one half
    assert math.isnan(roc_auc([1, 1, 1], [0.1, 0.2, 0.3]))
    assert log_loss([1, 0], [0.8, 0.3]) == pytest.approx(-(math.log(0.8) + math.log(0.7)) / 2)
    assert log_loss([1], [0.0]) > 30.0  # clipped, finite
    assert brier_score([1, 0], [0.8, 0.3]) == pytest.approx((0.04 + 0.09) / 2)
    rng = np.random.default_rng(0)
    p = rng.uniform(size=20000)
    y = (rng.uniform(size=20000) < p).astype("float64")
    assert 0.8 < roc_auc(y, p) < 0.87 and expected_calibration_error(p, y) < 0.02


@pytest.mark.unit
def test_classification_metrics_are_empty_without_probabilities() -> None:
    df = eval_frame(n_days=100).assign(pred_excess=0.0, prob_raw=np.nan, prob_cal=np.nan)
    df["y_cls"] = (df["excess"] > 0).astype("float64")
    summary, reliability = classification_metrics(df, settings=S)
    assert summary.empty and reliability.empty
    assert list(summary.columns) == list(CLASSIFICATION_COLUMNS)
    assert classification_metrics(df.drop(columns=["prob_raw", "prob_cal"]))[0].empty


@pytest.mark.unit
def test_classification_metrics_for_a_probability_column() -> None:
    df = eval_frame(n_days=100, strength=1.0)
    df["y_cls"] = (df["excess"] > 0).astype("float64")
    df["prob_cal"] = 1.0 / (1.0 + np.exp(-df["feat"]))
    summary, reliability = classification_metrics(df, settings=S)
    assert len(summary) == 1 and len(reliability) == 10
    row = summary.iloc[0]
    assert row["prob_col"] == "prob_cal" and row["n_obs"] == len(df) and row["n_dates"] == 100
    assert row["auc"] > 0.6 and row["precision_top_decile"] > 0.6
    assert row["effective_n"] == 5  # 100 consecutive dates, step 20
    assert {"log_loss", "brier", "ece", "calib_slope", "calib_intercept"} <= set(summary.columns)


# ----------------------------------------------------------------------- attach_labels


def _panel_for(n_days: int = 50, n_names: int = 25) -> pd.DataFrame:
    base = eval_frame(n_days=n_days, n_names=n_names, seed=3)
    out = base[["ticker", "date", "t_idx"]].copy()
    out["eligible"] = True
    out["excess_h20"] = base["excess"].to_numpy()
    out["y_reg_h20"] = np.clip(base["excess"].to_numpy(), -0.5, 0.5)  # a different, clipped target
    out["y_cls_h20"] = (base["excess"].to_numpy() > 0).astype("float64")
    out["has_label_h20"] = True
    return out


@pytest.mark.unit
def test_attach_labels_keeps_only_valid_evaluation_rows() -> None:
    panel = _panel_for()
    panel.loc[panel["ticker"] == "T00", "eligible"] = False
    last = panel["date"].max()
    panel.loc[panel["date"] == last, ["excess_h20", "y_cls_h20"]] = np.nan
    panel.loc[panel["date"] == last, "has_label_h20"] = False
    pred = panel[["ticker", "date"]].assign(pred_excess=np.arange(len(panel), dtype="float64"),
                                            fold_id=2008, model_id="m")
    out = attach_labels(pred, panel, 20)
    assert (out["ticker"] != "T00").all()  # ineligible rows are not evaluated
    assert out["date"].max() < last  # unlabelled rows are neither evaluated nor negatives
    assert out["excess"].notna().all() and out["y_cls"].notna().all()
    assert {"t_idx", "fold_id", "model_id", "pred_excess"} <= set(out.columns)
    merged = out.merge(panel, on=["ticker", "date"])
    assert np.array_equal(merged["excess"], merged["excess_h20"])  # the unclipped label ...
    assert not np.allclose(merged["excess"], merged["y_reg_h20"])  # ... never the clipped target


@pytest.mark.unit
def test_attach_labels_rejects_unmatched_predictions_and_missing_columns() -> None:
    panel = _panel_for(n_days=5)
    pred = panel[["ticker", "date"]].assign(pred_excess=1.0)
    with pytest.raises(PredictiveError, match="no matching panel row"):
        attach_labels(pred.assign(ticker=pred["ticker"] + "x"), panel, 20)
    with pytest.raises(PredictiveError, match="missing column"):
        attach_labels(pred.drop(columns="pred_excess"), panel, 20)
    with pytest.raises(PredictiveError, match="missing column"):
        attach_labels(pred, panel.drop(columns="has_label_h20"), 20)
    nan_pred = pred.assign(pred_excess=np.where(pred["ticker"] == "T01", np.nan, 1.0))
    assert (attach_labels(nan_pred, panel, 20)["ticker"] != "T01").all()


# ------------------------------------------------------- breakdowns and model comparison


@pytest.mark.unit
def test_breakdowns_by_year_fold_and_a_date_level_group() -> None:
    df = eval_frame(n_days=800, strength=0.5)
    df = _with_pred(df, df["feat"])
    df["fold_id"] = df["date"].dt.year
    df["regime"] = np.where(df["date"].dt.month <= 6, "H1", "H2")
    by_year = metrics_by_group(df, "year", S)
    assert list(by_year["group"]) == [2008, 2009, 2010, 2011] and list(by_year.columns) == [
        "group", *METRIC_COLUMNS
    ]
    assert by_year["n_obs"].sum() == len(df)
    assert (by_year.loc[by_year["effective_n"] > 5, "mean_ic"] > 0.1).all()
    assert list(metrics_by_group(df, "fold_id", S)["group"]) == [2008, 2009, 2010, 2011]
    regime = metrics_by_group(df, "regime", S)
    assert list(regime["group"]) == ["H1", "H2"] and (regime["mean_ic"] > 0.1).all()
    bad = df.assign(noise=np.random.default_rng(0).integers(0, 2, len(df)))
    with pytest.raises(PredictiveError, match="not constant within a date"):
        metrics_by_group(bad, "noise", S)
    with pytest.raises(PredictiveError):
        metrics_by_group(df, "no_such_column", S)


@pytest.mark.unit
def test_evaluate_model_and_the_tidy_metrics_frame() -> None:
    df = eval_frame(n_days=500, strength=0.5)
    df = _with_pred(df, df["feat"])
    df["fold_id"] = df["date"].dt.year
    df["regime"] = np.where(df["date"].dt.month <= 6, "H1", "H2")
    ev = evaluate_model(df, S, units_are_returns=False, group_cols=["regime"])
    table = metrics_frame("baseline_x", ev, units_are_returns=False)
    assert list(table.columns) == ["model_id", "scope", "group", *METRIC_COLUMNS, "units_are_returns"]
    assert set(table["scope"]) == {"pooled", "year", "fold", "group:regime"}
    assert table["model_id"].eq("baseline_x").all() and (~table["units_are_returns"]).all()
    assert (table["scope"] == "pooled").sum() == 1
    assert table.loc[table["scope"] == "pooled", "mae"].isna().all()  # raw scores: no MAE / R2
    assert ev.classification.empty and len(ev.ic_series) == 500 and len(ev.spread_series) == 500
    no_fold = evaluate_model(df.drop(columns="fold_id"), S)
    assert no_fold.by_fold.empty and "fold" not in set(metrics_frame("m", no_fold)["scope"])


@pytest.mark.unit
def test_metrics_do_not_depend_on_the_row_order() -> None:
    df = eval_frame(n_days=300, strength=0.5)
    df = _with_pred(df, df["feat"])
    a = summarise(df, S)
    b = summarise(df.sample(frac=1.0, random_state=3), S)
    assert a.keys() == b.keys()
    for key in a:
        assert a[key] == pytest.approx(b[key], nan_ok=True)


@pytest.mark.unit
def test_compare_models_uses_the_common_non_overlapping_dates() -> None:
    a = eval_frame(n_days=800, strength=0.5)
    a = _with_pred(a, a["feat"])
    b = _with_pred(a, np.random.default_rng(5).normal(size=len(a)))
    cmp_full = compare_models(a, b, S)
    row = cmp_full.iloc[0]
    assert row["mean_diff"] > 0.1 and row["t_stat"] > 3.0 and row["ci_low"] > 0.0
    assert row["mean_diff"] == pytest.approx(row["mean_ic_a"] - row["mean_ic_b"])
    assert row["effective_n"] == 40  # 800 dates, one every 20 days
    half = b[b["date"] > b["date"].iloc[len(b) // 2]]  # b only covers the second half
    row_half = compare_models(a, half, S).iloc[0]
    assert row_half["effective_n"] < row["effective_n"]  # intersection of dates, not union
    assert row_half["n_dates_a"] == 800 and row_half["n_dates_b"] < 800
    same = compare_models(a, a, S).iloc[0]
    assert same["mean_diff"] == 0.0 and math.isnan(same["t_stat"])


@pytest.mark.unit
def test_eval_settings_follow_the_project_configuration() -> None:
    s = EvalSettings.from_cfg(load_config())
    assert (s.step, s.anchor, s.n_boot, s.seed, s.min_names) == (20, 252, 2000, 42, 20)
    assert EvalSettings.from_cfg(load_config(overrides=["evaluation.bootstrap_n=50"])).n_boot == 50
    for bad in ({"step": 0}, {"n_boot": 0}, {"min_names": 1}, {"alpha": 1.0}, {"nw_lag": -1}):
        with pytest.raises(PredictiveError):
            EvalSettings(**bad)
