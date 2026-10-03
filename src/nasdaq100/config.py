"""Configuration system: validation, immutability, hashing, and hierarchical overrides.

Adheres strictly to Part II Section II.4 and Stage S0 specification.
Compatible with both Pydantic v1 and v2.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from nasdaq100.paths import base_config_path
from nasdaq100.utils.hashing import sha256_json

# Compatibility layer for Pydantic v1 and v2
try:
    from pydantic import ConfigDict  # type: ignore # v2

    class BaseConfigModel(BaseModel):
        """Base model enforcing immutability and forbidding unknown keys."""

        model_config = ConfigDict(extra="forbid", frozen=True)

    def _model_to_json_dict(model: BaseModel) -> dict[str, Any]:
        return model.model_dump(mode="json")

except ImportError:  # v1
    from pydantic import Extra  # type: ignore

    class BaseConfigModel(BaseModel):  # type: ignore
        """Base model enforcing immutability and forbidding unknown keys."""

        class Config:
            extra = Extra.forbid
            allow_mutation = False

    def _model_to_json_dict(model: BaseModel) -> dict[str, Any]:
        return json.loads(model.json())


class ProjectConfig(BaseConfigModel):
    seed: int = 42
    variant: str = "base"


class DataConfig(BaseConfigModel):
    raw_zip: str = "data/raw/archive.zip"
    raw_csv_name: str = "NASDAQ100_Historical_Data.csv"


class FlagsConfig(BaseConfigModel):
    tick_noise_min_close: float = 5.0
    corp_action_ret_gap: float = 0.03
    corp_action_min_prev_close: float = 5.0
    extreme_move_abs_ret: float = 0.40
    max_zero_volume_share_ticker: float = 0.05


class UniverseConfig(BaseConfigModel):
    seasoning_days: int = 252
    min_close: float = 5.0
    require_positive_volume: bool = True
    min_median_dollar_volume_63: float = 1000000.0
    cohort_filter: str | None = None
    drop_stitched: bool = False


class LabelsConfig(BaseConfigModel):
    horizons: list[int] = Field(default_factory=lambda: [20])
    primary_horizon: int = 20
    winsor_pct: list[float] = Field(default_factory=lambda: [0.01, 0.99])


class FeaturesConfig(BaseConfigModel):
    families: list[str] = Field(
        default_factory=lambda: ["momentum", "volatility", "trend", "liquidity", "market"]
    )
    winsor_pct: list[float] = Field(default_factory=lambda: [0.01, 0.99])


class ValidationConfig(BaseConfigModel):
    first_train_decision_date: datetime.date = datetime.date(2001, 1, 2)
    dev_test_years: list[int] = Field(default_factory=lambda: list(range(2008, 2020)))
    locked_test_start: datetime.date = datetime.date(2020, 1, 2)
    embargo_days: int = 5
    calibration_days: int = 504
    train_window_days: int | None = None
    train_stride: int = 5
    tuning_end_date: datetime.date = datetime.date(2007, 12, 31)
    tuning_valid_years: list[int] = Field(default_factory=lambda: [2005, 2006, 2007])


class RidgeConfig(BaseConfigModel):
    alpha_grid: list[float] = Field(
        default_factory=lambda: [1.0, 10.0, 100.0, 1000.0, 10000.0]
    )


class LogisticConfig(BaseConfigModel):
    C_grid: list[float] = Field(default_factory=lambda: [0.001, 0.01, 0.1, 1.0])


class LgbmFixedConfig(BaseConfigModel):
    objective: str = "regression"
    learning_rate: float = 0.03
    max_depth: int = 4
    subsample: float = 0.7
    subsample_freq: int = 1
    colsample_bytree: float = 0.7
    reg_lambda: float = 10.0
    deterministic: bool = True
    force_row_wise: bool = True
    verbose: int = -1


class LgbmGridConfig(BaseConfigModel):
    num_leaves: list[int] = Field(default_factory=lambda: [7, 15])
    n_estimators: list[int] = Field(default_factory=lambda: [150, 300, 600])
    min_child_samples: list[int] = Field(default_factory=lambda: [200, 1000])


class LgbmConfig(BaseConfigModel):
    fixed: LgbmFixedConfig = Field(default_factory=LgbmFixedConfig)
    grid: LgbmGridConfig = Field(default_factory=LgbmGridConfig)


class ModelsConfig(BaseConfigModel):
    ridge: RidgeConfig = Field(default_factory=RidgeConfig)
    logistic: LogisticConfig = Field(default_factory=LogisticConfig)
    lgbm: LgbmConfig = Field(default_factory=LgbmConfig)


class CalibrationConfig(BaseConfigModel):
    method: str = "platt"


class SignalsProbGateConfig(BaseConfigModel):
    enabled: bool = False
    margin: float = 0.02


class SignalsCostHurdleConfig(BaseConfigModel):
    enabled: bool = True
    kappa: float = 1.0


class SignalsVolVetoConfig(BaseConfigModel):
    enabled: bool = True
    max_vol_pct: float = 0.90


class SignalsConfig(BaseConfigModel):
    r_enter: float = 0.80
    r_exit: float = 0.50
    r_avoid: float = 0.20
    prob_gate: SignalsProbGateConfig = Field(default_factory=SignalsProbGateConfig)
    cost_hurdle: SignalsCostHurdleConfig = Field(default_factory=SignalsCostHurdleConfig)
    vol_veto: SignalsVolVetoConfig = Field(default_factory=SignalsVolVetoConfig)


class RiskConfig(BaseConfigModel):
    max_weight: float = 0.10


class PortfolioConfig(BaseConfigModel):
    top_fraction: float = 0.20
    min_n: int = 10
    max_n: int = 25
    weighting: str = "equal_target"


class BacktestConfig(BaseConfigModel):
    rebalance_every_days: int = 20
    rebalance_anchor_idx: int = 252
    cost_bps_per_side: float = 5.0
    fill: str = "next_open"
    initial_capital: float = 1000000.0
    liquidate_at_end: bool = True
    participation_warn_frac: float = 0.01


class RegimesConfig(BaseConfigModel):
    vol_lookback_days: int = 21
    trend_sma_days: int = 200
    min_history_days: int = 252


class EvaluationConfig(BaseConfigModel):
    bootstrap_block_days: int = 20
    bootstrap_n: int = 2000
    risk_free_annual: float = 0.0
    tail_stress_q_annual: float = 0.03
    tail_stress_loss: float = 0.60


class Config(BaseConfigModel):
    """Immutable, fully validated configuration model."""

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    flags: FlagsConfig = Field(default_factory=FlagsConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    labels: LabelsConfig = Field(default_factory=LabelsConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    regimes: RegimesConfig = Field(default_factory=RegimesConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override dictionary into base dictionary."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _parse_override_val(val: str) -> Any:
    """Parse override value string into bool, int, float, list, or str."""
    lower = val.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "none"):
        return None
    # Check if integer
    try:
        return int(val)
    except ValueError:
        pass
    # Check if float
    try:
        return float(val)
    except ValueError:
        pass
    # Check if json list / dict
    if (val.startswith("[") and val.endswith("]")) or (val.startswith("{") and val.endswith("}")):
        try:
            return json.loads(val)
        except Exception:
            pass
    return val


def _apply_cli_overrides(cfg_dict: dict[str, Any], overrides: list[str]) -> dict[str, Any]:
    """Apply list of 'section.key=value' dot-separated overrides."""
    result = dict(cfg_dict)
    for override in overrides:
        if "=" not in override:
            raise ValueError(f"Invalid override format (expected key=value): '{override}'")
        key_path, val_str = override.split("=", 1)
        keys = key_path.strip().split(".")
        val = _parse_override_val(val_str.strip())

        curr = result
        for k in keys[:-1]:
            if k not in curr or not isinstance(curr[k], dict):
                curr[k] = {}
            curr = curr[k]
        curr[keys[-1]] = val
    return result


def load_config(
    config_path: Path | str | None = None,
    override_file: Path | str | None = None,
    overrides: list[str] | None = None,
) -> Config:
    """Load configuration from base YAML, optional override YAML, and CLI overrides.

    Precedence:
    1. CLI overrides (--override key=value)
    2. Override YAML file (``override_file``; this is what the CLI ``--config`` flag maps to)
    3. Base YAML file (``configs/base.yaml``)

    ``config_path`` *replaces* the base YAML. It exists for tests and tooling only; the CLI
    never passes it, so ``configs/base.yaml`` is always the base of a command-line run.
    """
    path = Path(config_path) if config_path is not None else base_config_path()
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if override_file is not None:
        ov_path = Path(override_file)
        if not ov_path.is_file():
            raise FileNotFoundError(f"Override configuration file not found: {ov_path}")
        with open(ov_path, encoding="utf-8") as f:
            override_data = yaml.safe_load(f) or {}
        data = _deep_merge(data, override_data)

    if overrides:
        data = _apply_cli_overrides(data, overrides)

    return Config(**data)


def config_hash(cfg: Config) -> str:
    """Compute deterministic SHA-256 fingerprint over canonical sorted JSON.

    The first 8 characters are used in run IDs per Part II Section II.6.
    """
    dump = _model_to_json_dict(cfg)
    return sha256_json(dump)
