"""Command-line interface (CLI) for the NASDAQ-100 Equity Research System.

The CLI is the canonical execution interface per Part II Section II.8.
"""

from __future__ import annotations

import argparse
import sys

from nasdaq100.config import Config, load_config
from nasdaq100.data.adjust import AdjustError, run_build_adjusted
from nasdaq100.data.ingest import IngestError, run_ingest
from nasdaq100.data.security_master import SecurityMasterError, run_build_master
from nasdaq100.data.universe import UniverseError, run_build_universe
from nasdaq100.data.validate import ValidationError, run_validate
from nasdaq100.labels.forward_returns import LabelError, run_build_labels
from nasdaq100.paths import project_state_path
from nasdaq100.utils.logging import get_logger

logger = get_logger("cli")


def cmd_status() -> int:
    """Print the project stage checklist from PROJECT_STATE.md."""
    state_file = project_state_path()
    if not state_file.is_file():
        print(f"Error: {state_file} does not exist.")
        return 1

    content = state_file.read_text(encoding="utf-8")
    print(content)
    return 0


def build_config_from_args(config: str | None, overrides: list[str] | None) -> Config:
    """Resolve the run configuration from the CLI arguments.

    Precedence (Part II Section II.4 / Stage S0):
    ``configs/base.yaml`` < ``--config`` experiment override file < ``--override key=value``.

    ``--config`` is an *override* file layered on top of ``configs/base.yaml``; it never
    replaces the base configuration.
    """
    return load_config(override_file=config, overrides=overrides)


def cmd_ingest(cfg: Config) -> int:
    """S1: extract/hash the frozen raw archive; write manifest, bronze table and calendar."""
    try:
        manifest = run_ingest()
    except (IngestError, FileNotFoundError) as e:
        logger.error(f"ingest failed: {e}")
        return 1
    print(
        f"Ingested {manifest['rows']:,} rows, {manifest['n_tickers']} tickers "
        f"({manifest['date_min']} to {manifest['date_max']}); data hash {manifest['sha256']}"
    )
    return 0


def cmd_validate(cfg: Config) -> int:
    """S1: validate bronze, write silver (flags), validation report and data-quality report."""
    try:
        report = run_validate(cfg)
    except (ValidationError, FileNotFoundError) as e:
        logger.error(f"validate failed: {e}")
        return 1
    warnings = report["status"]["soft_warnings"]
    print(
        "Validation passed (all hard checks). "
        f"Soft warnings: {', '.join(warnings) if warnings else 'none'}. "
        f"Dataset status: {report['dataset_status']}. See docs/data_quality_report.md"
    )
    return 0


def cmd_build_master(cfg: Config) -> int:
    """S2: build data/reference/security_master.csv from silver + curated exceptions."""
    try:
        master = run_build_master(cfg)
    except (SecurityMasterError, FileNotFoundError) as e:
        logger.error(f"build-master failed: {e}")
        return 1
    excluded = master.loc[~master["include_in_universe"], "ticker"].tolist()
    print(
        f"Security master: {len(master)} tickers, {len(master) - len(excluded)} included; "
        f"excluded: {', '.join(excluded) if excluded else 'none'}. Dataset status: SURVIVOR-BIASED"
    )
    return 0


def cmd_build_universe(cfg: Config) -> int:
    """S2: build data/processed/{variant}/universe.parquet (eligibility per ticker and date)."""
    try:
        universe = run_build_universe(cfg)
    except (UniverseError, SecurityMasterError, FileNotFoundError) as e:
        logger.error(f"build-universe failed: {e}")
        return 1
    print(
        f"Universe [variant={cfg.project.variant}]: {len(universe):,} rows, "
        f"{int(universe['eligible'].sum()):,} eligible. Dataset status: SURVIVOR-BIASED"
    )
    return 0


def cmd_build_adjusted(cfg: Config) -> int:
    """S3: build data/processed/{variant}/adjusted_prices.parquet (adjusted OHLC and returns)."""
    try:
        adjusted = run_build_adjusted(cfg)
    except (AdjustError, FileNotFoundError) as e:
        logger.error(f"build-adjusted failed: {e}")
        return 1
    print(
        f"Adjusted prices [variant={cfg.project.variant}]: {len(adjusted):,} rows, "
        f"{adjusted['ticker'].nunique()} tickers, "
        f"{int(adjusted['logret_cc'].isna().sum())} NaN logret_cc (first rows only)"
    )
    return 0


def cmd_build_labels(cfg: Config) -> int:
    """S4: build data/processed/{variant}/labels.parquet (forward returns and labels)."""
    try:
        labels = run_build_labels(cfg)
    except (LabelError, AdjustError, UniverseError, FileNotFoundError) as e:
        logger.error(f"build-labels failed: {e}")
        return 1
    parts = []
    for h in cfg.labels.horizons:
        parts.append(
            f"h={h}: {int(labels[f'has_label_h{h}'].sum()):,} with forward return, "
            f"{int(labels[f'excess_h{h}'].notna().sum()):,} cross-sectional"
        )
    print(f"Labels [variant={cfg.project.variant}]: {len(labels):,} rows; " + "; ".join(parts))
    return 0


def cmd_not_implemented(cmd_name: str) -> int:
    """Fallback handler for stages not yet implemented."""
    print(f"Command '{cmd_name}' is defined in the roadmap but not yet implemented in the current stage.")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="nasdaq100",
        description="AI-Driven Equity Research & Portfolio Decision Support System",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Path to an experiment override YAML, layered on top of configs/base.yaml "
            "(e.g. configs/experiments/<name>.yaml)"
        ),
    )
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        help="Config overrides in key=value format (e.g. --override project.variant=test)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # S0: status
    subparsers.add_parser("status", help="Print the living project state checklist")

    # S1: data ingestion & validation
    subparsers.add_parser("ingest", help="Ingest raw zip and create bronze table")
    subparsers.add_parser("validate", help="Validate bronze table and create silver table")

    # S2: universe & security master
    subparsers.add_parser("build-master", help="Build derived security master table")
    subparsers.add_parser("build-universe", help="Build universe eligibility table")

    # S3: adjusted series
    subparsers.add_parser("build-adjusted", help="Build adjusted prices and log returns")

    # S4, S5: labels and features
    subparsers.add_parser("build-labels", help="Build forward returns and labels")
    subparsers.add_parser("build-features", help="Build raw and normalized features")

    # S12: regimes
    subparsers.add_parser("regimes", help="Build market regimes table")

    # S6: validation & leakage
    subparsers.add_parser("check-leakage", help="Run leakage test suite and generate fold plan")

    # S7, S8: training & models
    subparsers.add_parser("run-baselines", help="Run rule-based baselines")
    subparsers.add_parser("tune", help="Run inner walk-forward hyperparameter tuning")
    wf_parser = subparsers.add_parser("walkforward", help="Run walk-forward model training")
    wf_parser.add_argument("--family", choices=["ridge_logit", "lgbm"], default="ridge_logit")
    wf_parser.add_argument("--split", choices=["dev", "locked"], default="dev")

    # S9: signals
    subparsers.add_parser("signals", help="Generate discrete trade signals")

    # S11: backtest
    subparsers.add_parser("backtest", help="Run full event-driven portfolio backtest")

    # S13, S14: evaluation & explainability
    subparsers.add_parser("evaluate", help="Compute strategy metrics and evidence package")
    subparsers.add_parser("explain", help="Compute feature importance and SHAP values")

    # S16: locked test
    subparsers.add_parser("freeze-protocol", help="Freeze candidate strategies for locked test")
    subparsers.add_parser("locked-test", help="Execute single-run locked test")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "status":
        return cmd_status()

    # Load configuration to verify valid overrides even on unimplemented commands
    try:
        cfg = build_config_from_args(args.config, args.override)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return 1

    if args.command == "ingest":
        return cmd_ingest(cfg)
    if args.command == "validate":
        return cmd_validate(cfg)
    if args.command == "build-master":
        return cmd_build_master(cfg)
    if args.command == "build-universe":
        return cmd_build_universe(cfg)
    if args.command == "build-adjusted":
        return cmd_build_adjusted(cfg)
    if args.command == "build-labels":
        return cmd_build_labels(cfg)

    return cmd_not_implemented(args.command)


if __name__ == "__main__":
    sys.exit(main())
