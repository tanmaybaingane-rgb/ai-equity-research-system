"""Centralized path helpers for all artifacts and directories.

Single source of truth for artifact paths per Part II Section II.5.
No other module should construct paths directly.
"""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the absolute path to the repository root."""
    return Path(__file__).resolve().parent.parent.parent


def ensure_parent_dir(path: Path | str) -> Path:
    """Ensure the parent directory of a path exists before writing.

    Returns the Path object.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# Data Directories
def data_dir() -> Path:
    """Return path to data/ directory."""
    return repo_root() / "data"


def raw_dir() -> Path:
    """Return path to data/raw/ directory."""
    return data_dir() / "raw"


def raw_zip_path() -> Path:
    """Return path to frozen dataset zip archive."""
    return raw_dir() / "archive.zip"


def raw_csv_path() -> Path:
    """Return path to extracted raw dataset CSV."""
    return raw_dir() / "NASDAQ100_Historical_Data.csv"


def manifest_path() -> Path:
    """Return path to data/raw/MANIFEST.json."""
    return raw_dir() / "MANIFEST.json"


def interim_dir() -> Path:
    """Return path to data/interim/ directory."""
    return data_dir() / "interim"


def prices_bronze_path() -> Path:
    """Return path to data/interim/prices_bronze.parquet."""
    return interim_dir() / "prices_bronze.parquet"


def calendar_path() -> Path:
    """Return path to data/interim/calendar.parquet."""
    return interim_dir() / "calendar.parquet"


def prices_silver_path() -> Path:
    """Return path to data/interim/prices_silver.parquet."""
    return interim_dir() / "prices_silver.parquet"


def reports_dir() -> Path:
    """Return path to data/reports/ directory."""
    return data_dir() / "reports"


def validation_report_path() -> Path:
    """Return path to data/reports/validation_report.json."""
    return reports_dir() / "validation_report.json"


def reference_dir() -> Path:
    """Return path to data/reference/ directory."""
    return data_dir() / "reference"


def security_master_curated_path() -> Path:
    """Return path to hand-curated security master reference CSV."""
    return reference_dir() / "security_master_curated.csv"


def security_master_path() -> Path:
    """Return path to derived security master CSV."""
    return reference_dir() / "security_master.csv"


def ndx_index_path() -> Path:
    """Return path to optional external NDX index benchmark CSV."""
    return reference_dir() / "ndx_index.csv"


# Processed Data (Namespaced by project.variant)
def processed_dir(variant: str = "base") -> Path:
    """Return path to data/processed/{variant}/ directory."""
    return data_dir() / "processed" / variant


def adjusted_prices_path(variant: str = "base") -> Path:
    """Return path to adjusted prices parquet."""
    return processed_dir(variant) / "adjusted_prices.parquet"


def universe_path(variant: str = "base") -> Path:
    """Return path to universe eligibility parquet."""
    return processed_dir(variant) / "universe.parquet"


def labels_path(variant: str = "base") -> Path:
    """Return path to forward returns and labels parquet."""
    return processed_dir(variant) / "labels.parquet"


def features_raw_path(variant: str = "base") -> Path:
    """Return path to raw features parquet."""
    return processed_dir(variant) / "features_raw.parquet"


def features_model_path(variant: str = "base") -> Path:
    """Return path to normalised model features parquet."""
    return processed_dir(variant) / "features_model.parquet"


def market_series_path(variant: str = "base") -> Path:
    """Return path to equal-weighted market benchmark series parquet."""
    return processed_dir(variant) / "market_series.parquet"


def regimes_path(variant: str = "base") -> Path:
    """Return path to market regimes parquet."""
    return processed_dir(variant) / "regimes.parquet"


# Artifacts and Runs (Namespaced by project.variant)
def artifacts_dir(variant: str = "base") -> Path:
    """Return path to artifacts/{variant}/ directory."""
    return repo_root() / "artifacts" / variant


def fold_plan_path(variant: str = "base") -> Path:
    """Return path to fold_plan.json."""
    return artifacts_dir(variant) / "fold_plan.json"


def tuning_results_path(variant: str = "base") -> Path:
    """Return path to tuning_results.csv."""
    return artifacts_dir(variant) / "tuning_results.csv"


def runs_dir(variant: str = "base") -> Path:
    """Return path to artifacts/{variant}/runs/ directory."""
    return artifacts_dir(variant) / "runs"


def run_dir(run_id: str, variant: str = "base") -> Path:
    """Return path to artifacts/{variant}/runs/{run_id}/ directory."""
    return runs_dir(variant) / run_id


def run_config_resolved_path(run_id: str, variant: str = "base") -> Path:
    """Return path to resolved config for a run."""
    return run_dir(run_id, variant) / "config_resolved.json"


def run_oof_predictions_path(run_id: str, variant: str = "base") -> Path:
    """Return path to out-of-fold predictions parquet for a run."""
    return run_dir(run_id, variant) / "oof_predictions.parquet"


def run_models_dir(run_id: str, fold_k: int | str, variant: str = "base") -> Path:
    """Return path to models directory for fold k of a run."""
    return run_dir(run_id, variant) / "models" / f"fold_{fold_k}"


def run_metrics_model_path(run_id: str, ext: str = "json", variant: str = "base") -> Path:
    """Return path to model metrics (json or csv) for a run."""
    return run_dir(run_id, variant) / f"metrics_model.{ext}"


def run_signals_path(run_id: str, variant: str = "base") -> Path:
    """Return path to signals parquet for a run."""
    return run_dir(run_id, variant) / "signals.parquet"


def run_target_weights_path(run_id: str, variant: str = "base") -> Path:
    """Return path to target weights parquet for a run."""
    return run_dir(run_id, variant) / "target_weights.parquet"


def run_trades_path(run_id: str, variant: str = "base") -> Path:
    """Return path to trades parquet for a run."""
    return run_dir(run_id, variant) / "trades.parquet"


def run_equity_daily_path(run_id: str, variant: str = "base") -> Path:
    """Return path to daily equity parquet for a run."""
    return run_dir(run_id, variant) / "equity_daily.parquet"


def run_positions_daily_path(run_id: str, variant: str = "base") -> Path:
    """Return path to daily positions parquet for a run."""
    return run_dir(run_id, variant) / "positions_daily.parquet"


def run_metrics_strategy_path(run_id: str, variant: str = "base") -> Path:
    """Return path to strategy metrics json for a run."""
    return run_dir(run_id, variant) / "metrics_strategy.json"


def run_shap_values_path(run_id: str, variant: str = "base") -> Path:
    """Return path to SHAP values parquet for a run."""
    return run_dir(run_id, variant) / "shap_values.parquet"


def run_importance_path(run_id: str, variant: str = "base") -> Path:
    """Return path to permutation importance csv for a run."""
    return run_dir(run_id, variant) / "importance.csv"


def run_summary_path(run_id: str, variant: str = "base") -> Path:
    """Return path to run summary json for a run."""
    return run_dir(run_id, variant) / "run_summary.json"


# Shared Artifacts & Logs
def logs_dir() -> Path:
    """Return path to artifacts/logs/ directory."""
    return repo_root() / "artifacts" / "logs"


# Experiments Registry & Protocol
def experiments_dir() -> Path:
    """Return path to experiments/ directory."""
    return repo_root() / "experiments"


def registry_path() -> Path:
    """Return path to experiments/registry.csv."""
    return experiments_dir() / "registry.csv"


def locked_test_protocol_path() -> Path:
    """Return path to experiments/locked_test_protocol.json."""
    return experiments_dir() / "locked_test_protocol.json"


# Configs & Documentation
def configs_dir() -> Path:
    """Return path to configs/ directory."""
    return repo_root() / "configs"


def base_config_path() -> Path:
    """Return path to configs/base.yaml."""
    return configs_dir() / "base.yaml"


def data_expectations_path() -> Path:
    """Return path to configs/data_expectations.yaml."""
    return configs_dir() / "data_expectations.yaml"


def tuned_params_path() -> Path:
    """Return path to configs/tuned_params.yaml."""
    return configs_dir() / "tuned_params.yaml"


def docs_dir() -> Path:
    """Return path to docs/ directory."""
    return repo_root() / "docs"


def data_quality_report_path() -> Path:
    """Return path to docs/data_quality_report.md."""
    return docs_dir() / "data_quality_report.md"


def project_state_path() -> Path:
    """Return path to PROJECT_STATE.md in repo root."""
    return repo_root() / "PROJECT_STATE.md"


# Reports Directories
def reports_root_dir() -> Path:
    """Return path to reports/ directory."""
    return repo_root() / "reports"


def dev_reports_dir() -> Path:
    """Return path to reports/dev/ directory."""
    return reports_root_dir() / "dev"


def locked_reports_dir() -> Path:
    """Return path to reports/locked/ directory."""
    return reports_root_dir() / "locked"
