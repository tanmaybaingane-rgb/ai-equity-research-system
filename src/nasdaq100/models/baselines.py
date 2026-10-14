"""Stage S7: rule-based baselines and the ``run-baselines`` pipeline.

Four fit-free scores, computed from ``features_raw`` (read through the guarded ``load_panel`` with
``features_file`` pointing at the raw table), that every later model must beat:

========================  ==============================  =================================
``model_id``              score                           idea
========================  ==============================  =================================
``baseline_mom12_1``      ``mom_12_1``                    buy last year's winners
``baseline_rev21``        ``-ret_21``                     short-term reversal
``baseline_lowvol``       ``-vol_63``                     low volatility
``baseline_random``       seeded uniform noise            keyed by (date, ticker), no signal
========================  ==============================  =================================

Predictions follow the prediction-table contract (Part II Section II.5): one row per
(``ticker``, ``date``, ``model_id``) for every **eligible** row of a development test year that
has a computed score (including the final days whose labels are masked), ``pred_excess`` = the raw
score (**not** in return units: ``units_are_returns = False`` is recorded in the run config and
the metrics, so a downstream cost hurdle / probability gate must disable itself), ``prob_raw`` and
``prob_cal`` = NaN, ``fold_id`` = the test year and ``rank_pct`` = the per-date percentile rank of
the score (1 = best).

``run_baselines`` evaluates only labelled rows (``eligible`` and ``has_label``), never opens the
locked test (it only ever builds the ``"dev"`` panel and development folds) and writes one run
directory per baseline plus ``reports/dev/baseline_metrics.csv``. Time convention: Part II
Section II.2.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from nasdaq100.evaluation.predictive import (
    EvalSettings,
    ModelEvaluation,
    attach_labels,
    evaluate_model,
    metrics_frame,
)
from nasdaq100.utils.logging import get_logger

if TYPE_CHECKING:
    from nasdaq100.config import Config
    from nasdaq100.utils.calendar import TradingCalendar
    from nasdaq100.validation.folds import Fold

logger = get_logger("baselines")

STAGE = "S7"
RANDOM_ID = "baseline_random"
PREDICTION_COLUMNS: tuple[str, ...] = (
    "ticker",
    "date",
    "fold_id",
    "model_id",
    "pred_excess",
    "prob_raw",
    "prob_cal",
    "rank_pct",
)
DATASET_STATUS = "SURVIVOR-BIASED"


class BaselineError(ValueError):
    """Invalid baseline request or inconsistent inputs."""


@dataclass(frozen=True)
class BaselineSpec:
    """``score = sign * <feature>`` (``feature`` is ``None`` for the random baseline)."""

    model_id: str
    feature: str | None
    sign: int
    description: str


BASELINE_SPECS: dict[str, BaselineSpec] = {
    s.model_id: s
    for s in (
        BaselineSpec("baseline_mom12_1", "mom_12_1", 1, "12-1 month momentum"),
        BaselineSpec("baseline_rev21", "ret_21", -1, "short-term reversal (-ret_21)"),
        BaselineSpec("baseline_lowvol", "vol_63", -1, "low volatility (-vol_63)"),
        BaselineSpec(RANDOM_ID, None, 1, "seeded uniform noise keyed by (date, ticker)"),
    )
}
BASELINE_IDS: tuple[str, ...] = tuple(BASELINE_SPECS)


def baseline_meta(model_id: str) -> dict[str, Any]:
    """Metadata stored with a baseline run; ``units_are_returns`` is always ``False``."""
    spec = _spec(model_id)
    return {
        "model_id": spec.model_id,
        "feature": spec.feature,
        "sign": spec.sign,
        "description": spec.description,
        "units_are_returns": False,
    }


def _spec(model_id: str) -> BaselineSpec:
    if model_id not in BASELINE_SPECS:
        raise BaselineError(f"unknown baseline {model_id!r}; valid: {list(BASELINE_IDS)}")
    return BASELINE_SPECS[model_id]


# --------------------------------------------------------------------------------------------
# scores
# --------------------------------------------------------------------------------------------


def random_scores(tickers: Sequence[str], dates: Sequence[Any], seed: int) -> np.ndarray:
    """Uniform [0, 1) noise keyed by (``seed``, date, ticker), independent of row order.

    Each value is the BLAKE2b hash of ``"{seed}|{YYYY-MM-DD}|{ticker}"`` mapped to a float, so a
    given (date, ticker) always receives the same number whatever else is in the frame.
    """
    day = pd.DatetimeIndex(pd.to_datetime(list(dates))).strftime("%Y-%m-%d")
    cache: dict[tuple[str, str], float] = {}
    out = np.empty(len(day), dtype="float64")
    for i, (tk, d) in enumerate(zip(tickers, day, strict=True)):
        key = (tk, d)
        val = cache.get(key)
        if val is None:
            digest = hashlib.blake2b(f"{int(seed)}|{d}|{tk}".encode(), digest_size=8).digest()
            val = int.from_bytes(digest, "big") / 2.0**64
            cache[key] = val
        out[i] = val
    return out


def baseline_score(panel: pd.DataFrame, model_id: str, seed: int = 42) -> pd.Series:
    """The raw score of ``model_id`` for every panel row (NaN where the feature is NaN)."""
    spec = _spec(model_id)
    if spec.feature is None:
        score = random_scores(panel["ticker"].tolist(), panel["date"].tolist(), seed)
        return pd.Series(score, index=panel.index, name="pred_excess")
    if spec.feature not in panel.columns:
        raise BaselineError(f"{model_id}: panel lacks feature column {spec.feature!r}")
    values = panel[spec.feature].to_numpy(dtype="float64")
    values = np.where(np.isfinite(values), values, np.nan)
    return pd.Series(spec.sign * values, index=panel.index, name="pred_excess")


def required_features(model_ids: Sequence[str]) -> list[str]:
    """Raw feature columns needed by ``model_ids`` (registry order of ``BASELINE_IDS``)."""
    feats = [BASELINE_SPECS[m].feature for m in BASELINE_IDS if m in model_ids]
    return [f for f in dict.fromkeys(feats) if f is not None]


def _check_folds(folds: Sequence[Fold]) -> None:
    if not folds:
        raise BaselineError("no folds given")
    bad = [f.fold_id for f in folds if f.kind != "dev"]
    if bad:
        raise BaselineError(f"baselines run on development folds only; got {bad}")


def predict_baseline(
    panel: pd.DataFrame, model_id: str, folds: Sequence[Fold], seed: int = 42
) -> pd.DataFrame:
    """Prediction table of one baseline over the test periods of ``folds`` (no fitting)."""
    _check_folds(folds)
    _spec(model_id)
    need = ["ticker", "date", "t_idx", "eligible"]
    missing = [c for c in need if c not in panel.columns]
    if missing:
        raise BaselineError(f"panel lacks column(s) {missing}")
    score = baseline_score(panel, model_id, seed)
    parts = []
    for fold in folds:
        in_test = (panel["t_idx"] >= fold.test_start_idx) & (panel["t_idx"] <= fold.test_end_idx)
        keep = in_test & panel["eligible"].astype(bool) & score.notna()
        part = panel.loc[keep, ["ticker", "date"]].copy()
        part["fold_id"] = np.int32(fold.test_year)
        part["pred_excess"] = score.loc[keep].to_numpy(dtype="float64")
        parts.append(part)
    out = pd.concat(parts, ignore_index=True)
    out["model_id"] = model_id
    out["prob_raw"] = np.nan
    out["prob_cal"] = np.nan
    out["rank_pct"] = out.groupby("date", sort=False)["pred_excess"].rank(
        method="average", pct=True
    )
    out = out.sort_values(["ticker", "date"], kind="mergesort").reset_index(drop=True)
    return out[list(PREDICTION_COLUMNS)]


def build_predictions(
    panel: pd.DataFrame,
    folds: Sequence[Fold],
    model_ids: Sequence[str] | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Stacked prediction table of several baselines (one row per ticker, date and model)."""
    ids = list(BASELINE_IDS if model_ids is None else model_ids)
    if not ids:
        raise BaselineError("no baselines requested")
    frames = [predict_baseline(panel, m, folds, seed) for m in ids]
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["ticker", "date", "model_id"], kind="mergesort").reset_index(drop=True)


# --------------------------------------------------------------------------------------------
# run-baselines
# --------------------------------------------------------------------------------------------


@dataclass
class BaselineEvaluation:
    """In-memory result of ``evaluate_baselines`` (no file I/O)."""

    predictions: pd.DataFrame
    evaluated: dict[str, pd.DataFrame]
    evaluations: dict[str, ModelEvaluation]
    tables: dict[str, pd.DataFrame]


def evaluate_baselines(
    panel: pd.DataFrame,
    folds: Sequence[Fold],
    model_ids: Sequence[str] | None = None,
    *,
    settings: EvalSettings | None = None,
    horizon: int = 20,
    seed: int = 42,
) -> BaselineEvaluation:
    """Predict and evaluate the baselines on ``panel`` (pure computation).

    Predictions cover every eligible row of the fold test periods; metrics use only the labelled
    rows (``attach_labels``). ``units_are_returns`` is ``False`` for every baseline.
    """
    ids = list(BASELINE_IDS if model_ids is None else model_ids)
    for m in ids:
        _spec(m)
    if len(set(ids)) != len(ids):
        raise BaselineError(f"duplicate baselines requested: {ids}")
    s = settings or EvalSettings()
    predictions = build_predictions(panel, folds, ids, seed)
    if predictions.empty:
        raise BaselineError("no eligible prediction rows in the development test years")
    evaluated: dict[str, pd.DataFrame] = {}
    evaluations: dict[str, ModelEvaluation] = {}
    tables: dict[str, pd.DataFrame] = {}
    for model_id in ids:
        pred_m = predictions.loc[predictions["model_id"] == model_id]
        frame = attach_labels(pred_m, panel, horizon)
        evaluation = evaluate_model(frame, s, units_are_returns=False)
        table = metrics_frame(model_id, evaluation, units_are_returns=False)
        table.insert(1, "dataset_status", DATASET_STATUS)
        evaluated[model_id], evaluations[model_id], tables[model_id] = frame, evaluation, table
    return BaselineEvaluation(predictions, evaluated, evaluations, tables)


@dataclass
class BaselineRunResult:
    """What ``run_baselines`` produced."""

    run_ids: dict[str, str]
    run_dirs: dict[str, Path]
    metrics: pd.DataFrame
    report_path: Path
    registry_rows: list[dict[str, Any]] = field(default_factory=list)
    settings: EvalSettings = field(default_factory=EvalSettings)


def _jsonable(value: Any) -> Any:
    """Recursively convert numpy/pandas scalars to JSON types; NaN / inf become ``None``."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return _jsonable(value.to_dict(orient="records"))
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _timestamp(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


def run_baselines(
    cfg: Config,
    *,
    model_ids: Sequence[str] | None = None,
    panel: pd.DataFrame | None = None,
    calendar: TradingCalendar | None = None,
    folds: Sequence[Fold] | None = None,
    features_file: Path | str | None = None,
    labels_file: Path | str | None = None,
    universe_file: Path | str | None = None,
    calendar_file: Path | str | None = None,
    manifest_file: Path | str | None = None,
    runs_root: Path | str | None = None,
    report_file: Path | str | None = None,
    registry_file: Path | str | None = None,
    data_hash_value: str | None = None,
    git_commit_value: str | None = None,
) -> BaselineRunResult:
    """Build, evaluate and record the baselines for all development test years.

    ``panel`` / ``calendar`` / ``folds`` and the ``*_file`` / output arguments exist for tests;
    by default the guarded ``load_panel(cfg, ..., split="dev")`` reads ``features_raw``, labels
    and universe and ``make_dev_folds`` builds the folds. Writes, per baseline, a run directory
    ``artifacts/{variant}/runs/{run_id}/`` with ``config_resolved.json``,
    ``oof_predictions.parquet`` and ``metrics_model.json`` / ``.csv``; appends one registry row per
    baseline (``counts_as_trial = true``; the registry is append-only, so every execution adds
    rows) and writes the combined development table ``reports/dev/baseline_metrics.csv``.
    """
    from nasdaq100.config import _model_to_json_dict, config_hash
    from nasdaq100.data.ingest import data_hash
    from nasdaq100.data.loaders import load_panel
    from nasdaq100.paths import (
        baseline_metrics_path,
        features_raw_path,
        run_config_resolved_path,
        run_metrics_model_path,
        run_oof_predictions_path,
    )
    from nasdaq100.utils.calendar import TradingCalendar
    from nasdaq100.utils.hashing import get_git_commit
    from nasdaq100.utils.io import append_registry, new_run_id, write_parquet
    from nasdaq100.validation.folds import make_dev_folds
    from nasdaq100.validation.guards import assert_not_locked

    ids = list(BASELINE_IDS if model_ids is None else model_ids)
    for m in ids:
        _spec(m)
    variant = cfg.project.variant
    seed = int(cfg.project.seed)
    horizon = int(cfg.labels.primary_horizon)
    settings = EvalSettings.from_cfg(cfg)

    cal = calendar if calendar is not None else TradingCalendar.load(calendar_file)
    fold_list = list(folds) if folds is not None else make_dev_folds(cfg, cal)
    _check_folds(fold_list)
    if panel is None:
        panel = load_panel(
            cfg,
            required_features(ids),
            "dev",
            True,
            features_file=features_file if features_file is not None else features_raw_path(variant),
            labels_file=labels_file,
            universe_file=universe_file,
            calendar_file=calendar_file,
        )
    # Defence in depth: whatever produced the panel, it must not reach the locked period.
    assert_not_locked(panel["t_idx"], cfg, calendar=cal)
    assert_not_locked(panel["date"], cfg)

    outcome = evaluate_baselines(
        panel, fold_list, ids, settings=settings, horizon=horizon, seed=seed
    )
    predictions = outcome.predictions
    logger.info(
        f"baselines: {len(predictions):,} prediction rows for {len(ids)} models, "
        f"{len(fold_list)} development folds"
    )

    stamp = _timestamp(None)
    cfg_hash = config_hash(cfg)
    try:
        dhash = data_hash_value if data_hash_value is not None else data_hash(manifest_file)
    except Exception as e:  # missing manifest: record it, never invent a hash
        logger.warning(f"data hash unavailable ({e}); recording 'unknown'")
        dhash = "unknown"
    commit = git_commit_value if git_commit_value is not None else get_git_commit()
    cfg_json = _model_to_json_dict(cfg)
    fold_ranges = [
        {"fold_id": f.fold_id, "test_year": f.test_year,
         "test_start_idx": f.test_start_idx, "test_end_idx": f.test_end_idx}
        for f in fold_list
    ]

    run_ids: dict[str, str] = {}
    run_dirs: dict[str, Path] = {}
    metric_frames: list[pd.DataFrame] = []
    registry_rows: list[dict[str, Any]] = []
    for model_id in ids:
        run_id = new_run_id(STAGE, model_id, cfg_hash)
        if runs_root is not None:
            rdir = Path(runs_root) / run_id
            paths = {
                "config": rdir / "config_resolved.json",
                "oof": rdir / "oof_predictions.parquet",
                "json": rdir / "metrics_model.json",
                "csv": rdir / "metrics_model.csv",
            }
        else:
            paths = {
                "config": run_config_resolved_path(run_id, variant),
                "oof": run_oof_predictions_path(run_id, variant),
                "json": run_metrics_model_path(run_id, "json", variant),
                "csv": run_metrics_model_path(run_id, "csv", variant),
            }
        if paths["config"].parent.exists():
            raise BaselineError(f"run directory already exists: {paths['config'].parent}")
        paths["config"].parent.mkdir(parents=True)

        meta = baseline_meta(model_id)
        pred_m = predictions.loc[predictions["model_id"] == model_id]
        evaluated = outcome.evaluated[model_id]
        evaluation = outcome.evaluations[model_id]
        table = outcome.tables[model_id]
        metric_frames.append(table)

        config_doc = {
            "run_id": run_id, "stage": STAGE, "model_id": model_id,
            "created_at": stamp.isoformat(), "git_commit": commit, "data_hash": dhash,
            "config_hash": cfg_hash, "seed": seed, "split": "dev",
            "units_are_returns": False, "baseline": meta,
            "evaluation_settings": settings.as_dict(), "horizon": horizon,
            "folds": fold_ranges, "dataset_status": DATASET_STATUS, "config": cfg_json,
        }
        paths["config"].write_text(json.dumps(_jsonable(config_doc), indent=2) + "\n",
                                   encoding="utf-8")
        write_parquet(pred_m, paths["oof"], sort_keys=("ticker", "date"))
        metrics_doc = {
            "run_id": run_id, "model_id": model_id, "units_are_returns": False,
            "dataset_status": DATASET_STATUS, "horizon": horizon,
            "n_prediction_rows": int(len(pred_m)), "n_evaluated_rows": int(len(evaluated)),
            "settings": settings.as_dict(), "pooled": evaluation.pooled,
            "by_year": evaluation.by_year, "by_fold": evaluation.by_fold,
        }
        paths["json"].write_text(json.dumps(_jsonable(metrics_doc), indent=2) + "\n",
                                 encoding="utf-8")
        table.to_csv(paths["csv"], index=False)

        pooled = evaluation.pooled
        row = {
            "run_id": run_id,
            "timestamp": stamp.isoformat(timespec="seconds"),
            "stage": STAGE,
            "description": f"baseline {model_id}: {meta['description']}",
            "git_commit": commit,
            "config_hash": cfg_hash,
            "data_hash": dhash,
            "seed": seed,
            "split": "dev",
            "counts_as_trial": True,
            "sharpe_net": "",
            "key_metric_name": "rank_ic_mean_nonoverlap",
            "key_metric_value": pooled["mean_ic"],
            "notes": (
                f"units_are_returns=False; effective_n={pooled['effective_n']}; "
                f"{DATASET_STATUS} universe"
            ),
        }
        append_registry(row, registry_file)
        registry_rows.append(row)
        run_ids[model_id] = run_id
        run_dirs[model_id] = paths["config"].parent
        logger.info(f"baseline {model_id}: run {run_id}, mean IC {pooled['mean_ic']:.4f}")

    metrics = pd.concat(metric_frames, ignore_index=True)
    report = Path(report_file) if report_file is not None else baseline_metrics_path(variant)
    report.parent.mkdir(parents=True, exist_ok=True)
    metrics.loc[metrics["scope"].isin(["pooled", "year"])].to_csv(report, index=False)
    return BaselineRunResult(run_ids, run_dirs, metrics, report, registry_rows, settings)


__all__ = [
    "BASELINE_IDS",
    "BASELINE_SPECS",
    "BaselineError",
    "BaselineEvaluation",
    "BaselineRunResult",
    "BaselineSpec",
    "PREDICTION_COLUMNS",
    "baseline_meta",
    "baseline_score",
    "build_predictions",
    "evaluate_baselines",
    "predict_baseline",
    "random_scores",
    "required_features",
    "run_baselines",
]
