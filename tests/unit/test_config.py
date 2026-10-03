"""Unit tests for configuration loading, validation, immutability, and hashing."""

import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from nasdaq100.config import Config, config_hash, load_config


@pytest.mark.unit
def test_config_loads_defaults(base_config: Config) -> None:
    """Verify that default config loads cleanly from base.yaml with expected defaults."""
    assert base_config.project.seed == 42
    assert base_config.project.variant == "base"
    assert base_config.data.raw_csv_name == "NASDAQ100_Historical_Data.csv"
    assert base_config.universe.min_close == 5.0
    assert base_config.validation.first_train_decision_date == datetime.date(2001, 1, 2)
    assert base_config.validation.locked_test_start == datetime.date(2020, 1, 2)
    assert base_config.signals.r_enter == 0.80
    assert base_config.backtest.cost_bps_per_side == 5.0


@pytest.mark.unit
def test_config_immutability(base_config: Config) -> None:
    """Verify that configuration objects are frozen and cannot be mutated."""
    with pytest.raises(ValidationError):
        base_config.project.seed = 99  # type: ignore


@pytest.mark.unit
def test_config_unknown_key_raises(tmp_path: Path) -> None:
    """Verify that unknown keys in configuration raise a validation error."""
    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_yaml.write_text("unknown_section:\n  foo: bar\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(override_file=invalid_yaml)


@pytest.mark.unit
def test_override_precedence(tmp_path: Path) -> None:
    """Verify precedence: CLI overrides > override file > base.yaml."""
    override_yaml = tmp_path / "override.yaml"
    override_yaml.write_text(
        """
project:
  variant: "override_file_variant"
universe:
  min_close: 10.0
backtest:
  cost_bps_per_side: 15.0
""",
        encoding="utf-8",
    )

    # 1. Base + override file
    cfg1 = load_config(override_file=override_yaml)
    assert cfg1.project.variant == "override_file_variant"
    assert cfg1.universe.min_close == 10.0
    assert cfg1.backtest.cost_bps_per_side == 15.0

    # 2. Base + override file + CLI override
    cfg2 = load_config(
        override_file=override_yaml,
        overrides=["universe.min_close=12.5", "project.variant=cli_variant"],
    )
    assert cfg2.project.variant == "cli_variant"
    assert cfg2.universe.min_close == 12.5
    assert cfg2.backtest.cost_bps_per_side == 15.0


@pytest.mark.unit
def test_config_hash_stability_and_sensitivity(base_config: Config) -> None:
    """Verify config hash is deterministic and changes whenever any value changes."""
    h1 = config_hash(base_config)
    h2 = config_hash(base_config)
    assert h1 == h2
    assert len(h1) == 64

    # Change a value -> hash must change
    modified_cfg = load_config(overrides=["universe.min_close=7.5"])
    h_mod = config_hash(modified_cfg)
    assert h_mod != h1
