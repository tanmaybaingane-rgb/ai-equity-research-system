"""Stage S7: predictive evaluation library (the measuring stick before any machine learning).

Every metric works on an *evaluation frame*: one row per (``ticker``, ``date``) with at least
``date``, ``t_idx``, ``pred_excess`` and the **unclipped** cross-sectional label ``excess``
(``y_cls`` and ``prob_raw`` / ``prob_cal`` are optional). ``attach_labels`` builds that frame from
a prediction table and a ``load_panel`` panel and keeps only valid observations: ``eligible``,
``has_label`` and a finite label and prediction. Unlabelled rows (for example the last December
2019 dates, whose labels are masked) are never evaluated and never treated as negatives.

Conventions (decision C7):

* **Rank IC** is the per-date Spearman correlation between ``pred_excess`` and ``excess``; dates
  with fewer than ``min_names`` (20) names are skipped and a constant predictor gives NaN.
* 20-day labels overlap across consecutive days, so headline aggregates (mean, std, t-stat, hit
  rate, bootstrap CI) use only the **non-overlapping** dates ``(t_idx - anchor) % step == 0``
  (anchor 252, step = the label horizon). The daily mean IC with a Newey-West t-statistic
  (lag 20) is reported as a secondary view.
* ``n_dates`` counts the evaluation dates with a finite daily IC; ``effective_n`` is the number of
  those dates on the non-overlapping grid, i.e. the sample size behind the headline t-statistic.
* Quantile spreads use the per-date percentile rank of the prediction (1 = best): top quintile
  ``rank_pct >= 0.8``, bottom quintile ``rank_pct <= 0.2``, top decile ``rank_pct >= 0.9``.
* ``units_are_returns=False`` (the baselines) turns MAE and out-of-sample R^2 into NaN: a raw
  score is not a return forecast.
* Series, group and comparison results are tidy DataFrames; the one-sample aggregation helpers
  (``ic_summary``, ``spread_summary``, ``regression_fit``, ``summarise``) return flat dictionaries
  that always include the date counts (``n_dates`` / ``effective_n``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from nasdaq100.evaluation.stats import (
    iid_bootstrap_ci,
    newey_west_tstat,
    paired_difference_test,
)

PRED_COL = "pred_excess"
LABEL_COL = "excess"
CLS_COL = "y_cls"
PROB_COLS: tuple[str, ...] = ("prob_raw", "prob_cal")
MIN_NAMES = 20
NONOVERLAP_ANCHOR = 252
TOP_QUANTILE = 0.8
BOTTOM_QUANTILE = 0.2
DECILE_QUANTILE = 0.9

#: Columns of the flat per-group metric dictionary (``summarise``), in output order.
METRIC_COLUMNS: tuple[str, ...] = (
    "n_obs",
    "n_dates",
    "effective_n",
    "mean_ic",
    "std_ic",
    "ic_tstat",
    "hit_rate",
    "ic_ci_low",
    "ic_ci_high",
    "daily_mean_ic",
    "daily_ic_nw_t",
    "mean_top_quintile",
    "mean_bottom_quintile",
    "mean_quintile_spread",
    "spread_nonoverlap_mean",
    "spread_nonoverlap_tstat",
    "mean_top_decile_excess",
    "mae",
    "r2_oos",
)

CLASSIFICATION_COLUMNS: tuple[str, ...] = (
    "prob_col",
    "n_obs",
    "n_dates",
    "effective_n",
    "auc",
    "log_loss",
    "brier",
    "ece",
    "calib_slope",
    "calib_intercept",
    "precision_top_decile",
)

RELIABILITY_COLUMNS: tuple[str, ...] = ("prob_col", "bin", "n", "mean_prob", "frac_pos")


class PredictiveError(ValueError):
    """Invalid input to the predictive evaluation (missing columns, unmatched rows, ...)."""


@dataclass(frozen=True)
class EvalSettings:
    """Evaluation parameters (defaults follow the guide; ``from_cfg`` reads the project config)."""

    step: int = 20
    anchor: int = NONOVERLAP_ANCHOR
    n_boot: int = 2000
    seed: int = 42
    min_names: int = MIN_NAMES
    nw_lag: int = 20
    alpha: float = 0.05

    def __post_init__(self) -> None:
        if self.step < 1 or self.n_boot < 1 or self.nw_lag < 0:
            raise PredictiveError(f"invalid evaluation settings: {self}")
        if self.min_names < 2 or not 0.0 < self.alpha < 1.0:
            raise PredictiveError(f"invalid evaluation settings: {self}")

    @classmethod
    def from_cfg(cls, cfg: Any) -> EvalSettings:
        """Non-overlap step = primary label horizon, anchor = ``backtest.rebalance_anchor_idx``,
        bootstrap size = ``evaluation.bootstrap_n``, seed = ``project.seed``.
        """
        return cls(
            step=int(cfg.labels.primary_horizon),
            anchor=int(cfg.backtest.rebalance_anchor_idx),
            n_boot=int(cfg.evaluation.bootstrap_n),
            seed=int(cfg.project.seed),
        )

    def as_dict(self) -> dict[str, float]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# --------------------------------------------------------------------------------------------
# frame preparation
# --------------------------------------------------------------------------------------------


def _require(df: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise PredictiveError(f"missing column(s) {missing}; have {list(df.columns)}")


def nonoverlap_mask(t_idx: Any, step: int = 20, anchor: int = NONOVERLAP_ANCHOR) -> np.ndarray:
    """Boolean mask of the non-overlapping decision dates ``(t_idx - anchor) % step == 0``."""
    if int(step) < 1:
        raise PredictiveError(f"step must be >= 1, got {step}")
    arr = np.asarray(t_idx, dtype="int64")
    return (arr - int(anchor)) % int(step) == 0


def attach_labels(predictions: pd.DataFrame, panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Join predictions to the labelled panel and keep the valid evaluation rows.

    ``predictions`` needs ``ticker``, ``date`` and ``pred_excess`` (other prediction-table columns
    are carried along). ``panel`` is a ``load_panel`` panel (``t_idx``, ``eligible``,
    ``excess_h{h}``, ``y_cls_h{h}``, ``has_label_h{h}``). The result has the unclipped
    ``excess`` and ``y_cls`` columns plus ``t_idx`` and keeps only rows that are eligible, have
    ``has_label`` and a finite ``excess`` and ``pred_excess``. A prediction without a matching
    panel row is an error.
    """
    h = int(horizon)
    lab = [f"excess_h{h}", f"y_cls_h{h}", f"has_label_h{h}"]
    _require(predictions, ["ticker", "date", PRED_COL])
    _require(panel, ["ticker", "date", "t_idx", "eligible", *lab])
    keys = ["ticker", "date"]
    right = panel.loc[:, [*keys, "t_idx", "eligible", *lab]].rename(
        columns={f"excess_h{h}": LABEL_COL, f"y_cls_h{h}": CLS_COL, f"has_label_h{h}": "has_label"}
    )
    left = predictions.drop(columns=[c for c in right.columns if c not in keys], errors="ignore")
    merged = left.merge(right, on=keys, how="left", validate="many_to_one", indicator=True)
    unmatched = int((merged["_merge"] != "both").sum())
    if unmatched:
        raise PredictiveError(f"{unmatched} prediction row(s) have no matching panel row")
    merged = merged.drop(columns="_merge")
    valid = (
        merged["eligible"].fillna(False).astype(bool)
        & merged["has_label"].fillna(False).astype(bool)
        & np.isfinite(merged[LABEL_COL].to_numpy(dtype="float64"))
        & np.isfinite(merged[PRED_COL].to_numpy(dtype="float64"))
    )
    return merged.loc[valid].drop(columns=["eligible", "has_label"]).reset_index(drop=True)


def _finite(df: pd.DataFrame, pred_col: str, label_col: str) -> pd.DataFrame:
    _require(df, ["date", "t_idx", pred_col, label_col])
    x = df[pred_col].to_numpy(dtype="float64")
    y = df[label_col].to_numpy(dtype="float64")
    return df.loc[np.isfinite(x) & np.isfinite(y), ["date", "t_idx", pred_col, label_col]].copy()


# --------------------------------------------------------------------------------------------
# rank IC
# --------------------------------------------------------------------------------------------


def rank_ic_by_date(
    df: pd.DataFrame,
    pred_col: str = PRED_COL,
    label_col: str = LABEL_COL,
    min_names: int = MIN_NAMES,
) -> pd.DataFrame:
    """Per-date Spearman rank correlation of ``pred_col`` and ``label_col``.

    Returns ``date, t_idx, n_names, ic`` (one row per date with at least ``min_names`` finite
    pairs, ascending dates). A date on which either side is constant has ``ic = NaN``.
    """
    d = _finite(df, pred_col, label_col).rename(columns={pred_col: "_x", label_col: "_y"})
    empty = pd.DataFrame(
        {"date": pd.Series(dtype="datetime64[ns]"), "t_idx": pd.Series(dtype="int64"),
         "n_names": pd.Series(dtype="int64"), "ic": pd.Series(dtype="float64")}
    )
    if d.empty:
        return empty
    d = d[d.groupby("date", sort=True)["_x"].transform("size") >= int(min_names)].copy()
    if d.empty:
        return empty
    g = d.groupby("date", sort=True)
    d["_rx"] = g["_x"].rank(method="average")
    d["_ry"] = g["_y"].rank(method="average")
    g = d.groupby("date", sort=True)
    d["_rx"] = d["_rx"] - g["_rx"].transform("mean")
    d["_ry"] = d["_ry"] - g["_ry"].transform("mean")
    d["_xy"] = d["_rx"] * d["_ry"]
    d["_xx"] = d["_rx"] ** 2
    d["_yy"] = d["_ry"] ** 2
    agg = d.groupby("date", sort=True).agg(
        t_idx=("t_idx", "first"), n_names=("_x", "size"), sxy=("_xy", "sum"),
        sxx=("_xx", "sum"), syy=("_yy", "sum"), xmin=("_x", "min"), xmax=("_x", "max"),
        ymin=("_y", "min"), ymax=("_y", "max"),
    )
    degenerate = (agg["xmin"] == agg["xmax"]) | (agg["ymin"] == agg["ymax"])
    denom = np.sqrt(agg["sxx"] * agg["syy"])
    ic = (agg["sxy"] / denom).where(~degenerate & (denom > 0.0))
    out = pd.DataFrame(
        {"date": agg.index, "t_idx": agg["t_idx"].to_numpy(dtype="int64"),
         "n_names": agg["n_names"].to_numpy(dtype="int64"),
         "ic": np.clip(ic.to_numpy(dtype="float64"), -1.0, 1.0)}
    )
    return out.reset_index(drop=True)


def _nonoverlap(frame: pd.DataFrame, settings: EvalSettings) -> pd.DataFrame:
    return frame.loc[nonoverlap_mask(frame["t_idx"], settings.step, settings.anchor)]


def ic_summary(ic: pd.DataFrame, settings: EvalSettings | None = None) -> dict[str, float]:
    """Aggregate an IC series (``rank_ic_by_date`` output).

    Headline (non-overlapping dates): ``effective_n, mean_ic, std_ic, ic_tstat, hit_rate`` and an
    iid-bootstrap ``ic_ci_low / ic_ci_high``. Secondary (all dates): ``n_dates, daily_mean_ic``
    and the Newey-West t-statistic ``daily_ic_nw_t``.
    """
    s = settings or EvalSettings()
    nan = float("nan")
    finite = ic.loc[np.isfinite(ic["ic"].to_numpy(dtype="float64"))]
    vals = _nonoverlap(finite, s)["ic"].to_numpy(dtype="float64")
    n = int(vals.size)
    mean = float(vals.mean()) if n else nan
    std = float(np.std(vals, ddof=1)) if n > 1 else nan
    tstat = mean / (std / np.sqrt(n)) if n > 1 and std > 0.0 else nan
    lo, hi = iid_bootstrap_ci(vals, np.mean, n=s.n_boot, seed=s.seed, alpha=s.alpha)
    daily = finite["ic"].to_numpy(dtype="float64")
    return {
        "n_dates": int(daily.size),
        "effective_n": n,
        "mean_ic": mean,
        "std_ic": std,
        "ic_tstat": float(tstat),
        "hit_rate": float((vals > 0).mean()) if n else nan,
        "ic_ci_low": lo,
        "ic_ci_high": hi,
        "daily_mean_ic": float(daily.mean()) if daily.size else nan,
        "daily_ic_nw_t": newey_west_tstat(daily, s.nw_lag),
    }


# --------------------------------------------------------------------------------------------
# quantile spreads
# --------------------------------------------------------------------------------------------


def quantile_spread_by_date(
    df: pd.DataFrame,
    pred_col: str = PRED_COL,
    label_col: str = LABEL_COL,
    min_names: int = MIN_NAMES,
) -> pd.DataFrame:
    """Per date: mean excess of the top quintile, bottom quintile and top decile, and the spread.

    Returns ``date, t_idx, n_names, top_mean, bottom_mean, spread, top_decile_mean``;
    ``spread = top_mean - bottom_mean`` (NaN when a bucket is empty, e.g. a constant predictor).
    """
    d = _finite(df, pred_col, label_col).rename(columns={pred_col: "_x", label_col: "_y"})
    cols = ["date", "t_idx", "n_names", "top_mean", "bottom_mean", "spread", "top_decile_mean"]
    if d.empty:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in cols}).astype(
            {"date": "datetime64[ns]", "t_idx": "int64", "n_names": "int64"}
        )
    d = d[d.groupby("date", sort=True)["_x"].transform("size") >= int(min_names)].copy()
    if d.empty:
        return quantile_spread_by_date(d.iloc[0:0], "_x", "_y", min_names).iloc[0:0]
    d["_rp"] = d.groupby("date", sort=True)["_x"].rank(method="average", pct=True)
    d["_top"] = d["_y"].where(d["_rp"] >= TOP_QUANTILE)
    d["_bot"] = d["_y"].where(d["_rp"] <= BOTTOM_QUANTILE)
    d["_dec"] = d["_y"].where(d["_rp"] >= DECILE_QUANTILE)
    agg = d.groupby("date", sort=True).agg(
        t_idx=("t_idx", "first"), n_names=("_y", "size"), top_mean=("_top", "mean"),
        bottom_mean=("_bot", "mean"), top_decile_mean=("_dec", "mean"),
    )
    out = agg.reset_index()
    out["spread"] = out["top_mean"] - out["bottom_mean"]
    out["t_idx"] = out["t_idx"].astype("int64")
    out["n_names"] = out["n_names"].astype("int64")
    return out[cols]


def spread_summary(spread: pd.DataFrame, settings: EvalSettings | None = None) -> dict[str, float]:
    """Aggregate ``quantile_spread_by_date``: means over all dates, plus the non-overlapping
    mean spread with its t-statistic (and the date counts ``n_dates`` / ``effective_n``).
    """
    s = settings or EvalSettings()
    nan = float("nan")

    def mean(col: str) -> float:
        v = spread[col].to_numpy(dtype="float64")
        v = v[np.isfinite(v)]
        return float(v.mean()) if v.size else nan

    all_spreads = spread["spread"].to_numpy(dtype="float64")
    sub = _nonoverlap(spread, s)["spread"].to_numpy(dtype="float64")
    sub = sub[np.isfinite(sub)]
    sd = float(np.std(sub, ddof=1)) if sub.size > 1 else nan
    return {
        "n_dates": int(np.isfinite(all_spreads).sum()),
        "effective_n": int(sub.size),
        "mean_top_quintile": mean("top_mean"),
        "mean_bottom_quintile": mean("bottom_mean"),
        "mean_quintile_spread": mean("spread"),
        "spread_nonoverlap_mean": float(sub.mean()) if sub.size else nan,
        "spread_nonoverlap_tstat": (
            float(sub.mean() / (sd / np.sqrt(sub.size))) if sub.size > 1 and sd > 0 else nan
        ),
        "mean_top_decile_excess": mean("top_decile_mean"),
    }


# --------------------------------------------------------------------------------------------
# regression fit
# --------------------------------------------------------------------------------------------


def regression_fit(
    df: pd.DataFrame,
    pred_col: str = PRED_COL,
    label_col: str = LABEL_COL,
    units_are_returns: bool = True,
    settings: EvalSettings | None = None,
) -> dict[str, float]:
    """MAE and out-of-sample R^2 versus a zero-excess prediction (secondary; expect ~ 0).

    ``r2_oos = 1 - sum((y - yhat)^2) / sum(y^2)`` on the unclipped excess return. With
    ``units_are_returns=False`` (raw scores) both are NaN. The result also carries the sample
    sizes ``n_obs``, ``n_dates`` and ``effective_n`` (dates on the non-overlapping grid).
    """
    s = settings or EvalSettings()
    d = _finite(df, pred_col, label_col)
    nan = float("nan")
    dates = d.drop_duplicates("date")
    out: dict[str, float] = {
        "n_obs": int(len(d)),
        "n_dates": int(len(dates)),
        "effective_n": int(nonoverlap_mask(dates["t_idx"], s.step, s.anchor).sum()),
        "mae": nan,
        "r2_oos": nan,
    }
    if d.empty or not units_are_returns:
        return out
    y = d[label_col].to_numpy(dtype="float64")
    p = d[pred_col].to_numpy(dtype="float64")
    denom = float(np.sum(y**2))
    out["mae"] = float(np.mean(np.abs(y - p)))
    out["r2_oos"] = float(1.0 - np.sum((y - p) ** 2) / denom) if denom > 0.0 else nan
    return out


# --------------------------------------------------------------------------------------------
# classification / calibration
# --------------------------------------------------------------------------------------------


def roc_auc(y: Any, score: Any) -> float:
    """Pooled ROC-AUC via the rank (Mann-Whitney) formula; NaN if one class is missing."""
    yv = np.asarray(y, dtype="float64").reshape(-1)
    sv = np.asarray(score, dtype="float64").reshape(-1)
    pos = yv > 0.5
    n1, n0 = int(pos.sum()), int((~pos).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = rankdata(sv)
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def log_loss(y: Any, prob: Any, eps: float = 1e-15) -> float:
    yv = np.asarray(y, dtype="float64").reshape(-1)
    p = np.clip(np.asarray(prob, dtype="float64").reshape(-1), eps, 1.0 - eps)
    return float(-np.mean(yv * np.log(p) + (1.0 - yv) * np.log(1.0 - p)))


def brier_score(y: Any, prob: Any) -> float:
    yv = np.asarray(y, dtype="float64").reshape(-1)
    p = np.asarray(prob, dtype="float64").reshape(-1)
    return float(np.mean((p - yv) ** 2))


def reliability_table(
    prob: Any, y: Any, n_bins: int = 10, prob_col: str = "prob"
) -> pd.DataFrame:
    """Equal-frequency reliability table: ``prob_col, bin, n, mean_prob, frac_pos``.

    Observations are ordered by probability (stable for ties) and cut into ``n_bins`` bins of
    (almost) equal size.
    """
    p = np.asarray(prob, dtype="float64").reshape(-1)
    yv = np.asarray(y, dtype="float64").reshape(-1)
    m = p.size
    if m == 0:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in RELIABILITY_COLUMNS})
    order = np.argsort(p, kind="mergesort")
    bins = np.empty(m, dtype="int64")
    bins[order] = (np.arange(m) * int(n_bins)) // m
    frame = pd.DataFrame({"bin": bins, "p": p, "y": yv})
    agg = frame.groupby("bin", sort=True).agg(n=("p", "size"), mean_prob=("p", "mean"),
                                              frac_pos=("y", "mean")).reset_index()
    agg.insert(0, "prob_col", prob_col)
    return agg[list(RELIABILITY_COLUMNS)]


def expected_calibration_error(prob: Any, y: Any, n_bins: int = 10) -> float:
    """ECE with equal-frequency bins: ``sum_b (n_b / N) * |mean_prob_b - frac_pos_b|``."""
    table = reliability_table(prob, y, n_bins)
    if table.empty:
        return float("nan")
    weights = table["n"].to_numpy(dtype="float64") / table["n"].sum()
    gap = np.abs(table["mean_prob"].to_numpy() - table["frac_pos"].to_numpy())
    return float(np.sum(weights * gap))


def calibration_slope_intercept(prob: Any, y: Any, eps: float = 1e-6) -> tuple[float, float]:
    """``(slope, intercept)`` of the logistic recalibration ``y ~ intercept + slope * logit(p)``.

    A perfectly calibrated forecast has slope 1 and intercept 0. Fitted by Newton-Raphson;
    ``(nan, nan)`` if the fit is degenerate (constant probabilities, one class, separation).
    """
    p = np.clip(np.asarray(prob, dtype="float64").reshape(-1), eps, 1.0 - eps)
    yv = np.asarray(y, dtype="float64").reshape(-1)
    nan = (float("nan"), float("nan"))
    if p.size < 3 or float(np.ptp(p)) == 0.0 or float(np.ptp(yv)) == 0.0:
        return nan
    x = np.column_stack([np.ones_like(p), np.log(p / (1.0 - p))])
    beta = np.array([0.0, 1.0])
    for _ in range(100):
        mu = 1.0 / (1.0 + np.exp(-(x @ beta)))
        w = mu * (1.0 - mu)
        hess = x.T @ (x * w[:, None])
        try:
            step = np.linalg.solve(hess, x.T @ (yv - mu))
        except np.linalg.LinAlgError:
            return nan
        beta = beta + step
        if not np.all(np.isfinite(beta)) or float(np.max(np.abs(beta))) > 50.0:
            return nan
        if float(np.max(np.abs(step))) < 1e-9:
            return (float(beta[1]), float(beta[0]))
    return nan


def classification_metrics(
    df: pd.DataFrame,
    prob_cols: Sequence[str] = PROB_COLS,
    label_col: str = CLS_COL,
    settings: EvalSettings | None = None,
    n_bins: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Classification metrics for every probability column that has finite values.

    Returns ``(summary, reliability)``: one summary row per ``prob_col`` with pooled ROC-AUC,
    log-loss, Brier score, ECE (``n_bins`` equal-frequency bins), calibration slope / intercept
    and the precision among the top-decile probabilities (pooled: ``prob >= its 90th
    percentile``), plus the long reliability table. Both are empty when no ``prob_*`` column has
    data (the baselines).
    """
    s = settings or EvalSettings()
    rows: list[dict[str, Any]] = []
    tables: list[pd.DataFrame] = []
    for col in prob_cols:
        if col not in df.columns or label_col not in df.columns:
            continue
        sub = df.loc[:, [c for c in ("date", "t_idx", col, label_col) if c in df.columns]]
        p_all = sub[col].to_numpy(dtype="float64")
        y_all = sub[label_col].to_numpy(dtype="float64")
        sub = sub.loc[np.isfinite(p_all) & np.isfinite(y_all)]
        if sub.empty:
            continue
        p = sub[col].to_numpy(dtype="float64")
        y = sub[label_col].to_numpy(dtype="float64")
        top = p >= np.quantile(p, 0.9)
        slope, intercept = calibration_slope_intercept(p, y)
        dates = sub["date"] if "date" in sub.columns else pd.Series(dtype="float64")
        eff = int(nonoverlap_mask(sub["t_idx"].drop_duplicates(), s.step, s.anchor).sum()) \
            if "t_idx" in sub.columns else 0
        rows.append({
            "prob_col": col, "n_obs": int(p.size), "n_dates": int(dates.nunique()),
            "effective_n": eff, "auc": roc_auc(y, p), "log_loss": log_loss(y, p),
            "brier": brier_score(y, p), "ece": expected_calibration_error(p, y, n_bins),
            "calib_slope": slope, "calib_intercept": intercept,
            "precision_top_decile": float(y[top].mean()) if top.any() else float("nan"),
        })
        tables.append(reliability_table(p, y, n_bins, prob_col=col))
    summary = pd.DataFrame(rows, columns=list(CLASSIFICATION_COLUMNS))
    reliability = (
        pd.concat(tables, ignore_index=True)
        if tables
        else pd.DataFrame({c: pd.Series(dtype="float64") for c in RELIABILITY_COLUMNS})
    )
    return summary, reliability


# --------------------------------------------------------------------------------------------
# aggregation, breakdowns, comparison
# --------------------------------------------------------------------------------------------


def summarise(
    df: pd.DataFrame,
    settings: EvalSettings | None = None,
    *,
    pred_col: str = PRED_COL,
    label_col: str = LABEL_COL,
    units_are_returns: bool = True,
) -> dict[str, float]:
    """All headline metrics of one sample as a flat dictionary (keys: ``METRIC_COLUMNS``)."""
    s = settings or EvalSettings()
    d = _finite(df, pred_col, label_col)
    ic = rank_ic_by_date(d, pred_col, label_col, s.min_names)
    spread = quantile_spread_by_date(d, pred_col, label_col, s.min_names)
    out: dict[str, float] = {"n_obs": int(len(d))}
    out.update(regression_fit(d, pred_col, label_col, units_are_returns, s))
    out.update(spread_summary(spread, s))
    out.update(ic_summary(ic, s))  # last: the IC sample sizes define n_dates / effective_n
    return {k: out[k] for k in METRIC_COLUMNS}


def _group_values(df: pd.DataFrame, by: str) -> pd.Series:
    if by == "year":
        _require(df, ["date"])
        return pd.Series(pd.DatetimeIndex(df["date"]).year, index=df.index)
    _require(df, [by])
    if by != "fold_id":
        per_date = df.groupby("date")[by].nunique(dropna=False)
        if (per_date > 1).any():
            raise PredictiveError(f"grouping column {by!r} is not constant within a date")
    return df[by]


def metrics_by_group(
    df: pd.DataFrame,
    by: str,
    settings: EvalSettings | None = None,
    *,
    pred_col: str = PRED_COL,
    label_col: str = LABEL_COL,
    units_are_returns: bool = True,
) -> pd.DataFrame:
    """Headline metrics per group: ``by`` is ``"year"``, ``"fold_id"`` or any date-level column
    of ``df`` (for example a regime label). Returns ``group`` plus ``METRIC_COLUMNS``.
    """
    s = settings or EvalSettings()
    groups = _group_values(df, by)
    rows = []
    for key in sorted(groups.dropna().unique()):
        part = df.loc[groups == key]
        row = {"group": key}
        row.update(summarise(part, s, pred_col=pred_col, label_col=label_col,
                             units_are_returns=units_are_returns))
        rows.append(row)
    return pd.DataFrame(rows, columns=["group", *METRIC_COLUMNS])


@dataclass
class ModelEvaluation:
    """Everything ``evaluate_model`` computes for one model."""

    pooled: dict[str, float]
    by_year: pd.DataFrame
    by_fold: pd.DataFrame
    ic_series: pd.DataFrame
    spread_series: pd.DataFrame
    classification: pd.DataFrame
    reliability: pd.DataFrame
    by_extra: dict[str, pd.DataFrame] = field(default_factory=dict)


def evaluate_model(
    df: pd.DataFrame,
    settings: EvalSettings | None = None,
    *,
    pred_col: str = PRED_COL,
    label_col: str = LABEL_COL,
    units_are_returns: bool = True,
    group_cols: Sequence[str] = (),
) -> ModelEvaluation:
    """Pooled metrics, breakdowns by year / fold / ``group_cols``, series and classification."""
    s = settings or EvalSettings()
    kw: dict[str, Any] = {"pred_col": pred_col, "label_col": label_col,
                          "units_are_returns": units_are_returns}
    d = _finite(df, pred_col, label_col)
    ic = rank_ic_by_date(d, pred_col, label_col, s.min_names)
    spread = quantile_spread_by_date(d, pred_col, label_col, s.min_names)
    by_fold = (
        metrics_by_group(df, "fold_id", s, **kw)
        if "fold_id" in df.columns
        else pd.DataFrame(columns=["group", *METRIC_COLUMNS])
    )
    cls_summary, reliability = classification_metrics(df, settings=s)
    return ModelEvaluation(
        pooled=summarise(df, s, **kw),
        by_year=metrics_by_group(df, "year", s, **kw),
        by_fold=by_fold,
        ic_series=ic,
        spread_series=spread,
        classification=cls_summary,
        reliability=reliability,
        by_extra={c: metrics_by_group(df, c, s, **kw) for c in group_cols},
    )


def metrics_frame(
    model_id: str,
    evaluation: ModelEvaluation,
    *,
    units_are_returns: bool = True,
) -> pd.DataFrame:
    """Tidy table ``model_id, scope, group, <METRIC_COLUMNS>, units_are_returns`` with one
    ``pooled`` row and one row per year, fold and extra group.
    """
    parts = [pd.DataFrame([{"scope": "pooled", "group": "all", **evaluation.pooled}])]
    for scope, frame in (("year", evaluation.by_year), ("fold", evaluation.by_fold),
                         *((f"group:{k}", v) for k, v in evaluation.by_extra.items())):
        if len(frame):
            parts.append(frame.assign(scope=scope))
    out = pd.concat(parts, ignore_index=True)
    out["group"] = out["group"].astype(str)
    out.insert(0, "model_id", model_id)
    out["units_are_returns"] = bool(units_are_returns)
    return out[["model_id", "scope", "group", *METRIC_COLUMNS, "units_are_returns"]]


def compare_models(
    a: pd.DataFrame,
    b: pd.DataFrame,
    settings: EvalSettings | None = None,
    *,
    pred_col: str = PRED_COL,
    label_col: str = LABEL_COL,
    block: int | None = None,
) -> pd.DataFrame:
    """Paired rank-IC difference ``a - b`` over the **same** non-overlapping dates.

    Both frames are reduced to their daily IC series; only dates present (and finite) in both and
    on the non-overlapping grid are compared, so the models are never compared on different date
    sets. Returns one row: ``n_dates_a, n_dates_b, effective_n, mean_ic_a, mean_ic_b, mean_diff,
    std_diff, t_stat, ci_low, ci_high``.
    """
    s = settings or EvalSettings()
    ics = []
    for frame in (a, b):
        ic = rank_ic_by_date(frame, pred_col, label_col, s.min_names)
        ic = ic.loc[np.isfinite(ic["ic"].to_numpy(dtype="float64"))]
        ics.append(ic.set_index("date"))
    joined = ics[0][["t_idx", "ic"]].join(ics[1][["ic"]], how="inner", lsuffix="_a", rsuffix="_b")
    common = joined.loc[nonoverlap_mask(joined["t_idx"], s.step, s.anchor)]
    test = paired_difference_test(
        common["ic_a"], common["ic_b"], n=s.n_boot, seed=s.seed, block=block, alpha=s.alpha
    )
    nan = float("nan")
    return pd.DataFrame([{
        "n_dates_a": int(len(ics[0])), "n_dates_b": int(len(ics[1])),
        "effective_n": test.n,
        "mean_ic_a": float(common["ic_a"].mean()) if len(common) else nan,
        "mean_ic_b": float(common["ic_b"].mean()) if len(common) else nan,
        "mean_diff": test.mean_diff, "std_diff": test.std_diff, "t_stat": test.t_stat,
        "ci_low": test.ci_low, "ci_high": test.ci_high,
    }])


__all__ = [
    "CLASSIFICATION_COLUMNS",
    "EvalSettings",
    "METRIC_COLUMNS",
    "ModelEvaluation",
    "PredictiveError",
    "RELIABILITY_COLUMNS",
    "attach_labels",
    "brier_score",
    "calibration_slope_intercept",
    "classification_metrics",
    "compare_models",
    "evaluate_model",
    "expected_calibration_error",
    "ic_summary",
    "log_loss",
    "metrics_by_group",
    "metrics_frame",
    "nonoverlap_mask",
    "quantile_spread_by_date",
    "rank_ic_by_date",
    "regression_fit",
    "reliability_table",
    "roc_auc",
    "spread_summary",
    "summarise",
]
