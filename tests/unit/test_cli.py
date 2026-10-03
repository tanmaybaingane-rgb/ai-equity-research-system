"""Unit tests for the CLI status and argument handling."""

from pathlib import Path

import pytest

from nasdaq100.cli import build_config_from_args, main


@pytest.mark.unit
def test_cli_status(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify that 'status' command exits with code 0 and prints the PROJECT_STATE checklist."""
    exit_code = main(["status"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Stage Checklist" in captured.out
    assert "S0" in captured.out
    assert "Foundations" in captured.out


@pytest.mark.unit
def test_cli_unimplemented_command(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify that commands for future stages exit with 1 and informative message."""
    exit_code = main(["build-master"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "not yet implemented" in captured.out


@pytest.mark.unit
def test_cli_invalid_config_override() -> None:
    """Verify that invalid overrides raise error / exit with code 1."""
    exit_code = main(["--override", "invalid_key_missing_equals", "status"])
    # "status" runs directly without config parsing
    assert exit_code == 0

    # Non-status command verifies config
    exit_code2 = main(["--override", "unknown_section.val=123", "build-master"])
    assert exit_code2 == 1


@pytest.mark.unit
def test_config_flag_layers_override_on_top_of_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--config is an override file: base.yaml stays the base (regression for S0 close-out).

    The base file below sets a distinctive value that differs from every built-in default.
    If --config *replaced* the base (the old behaviour), min_close would fall back to 5.0.
    """
    base = tmp_path / "base.yaml"
    base.write_text("universe:\n  min_close: 7.0\nbacktest:\n  cost_bps_per_side: 9.0\n")
    override = tmp_path / "experiment.yaml"
    override.write_text("backtest:\n  cost_bps_per_side: 20.0\nproject:\n  variant: exp1\n")
    monkeypatch.setattr("nasdaq100.config.base_config_path", lambda: base)

    cfg = build_config_from_args(str(override), ["validation.train_stride=1"])

    assert cfg.universe.min_close == 7.0  # taken from base.yaml (not replaced by --config)
    assert cfg.backtest.cost_bps_per_side == 20.0  # --config beats base.yaml
    assert cfg.project.variant == "exp1"  # --config value applied
    assert cfg.validation.train_stride == 1  # --override beats both

    # Without --config the base file alone applies.
    cfg_base_only = build_config_from_args(None, [])
    assert cfg_base_only.universe.min_close == 7.0
    assert cfg_base_only.backtest.cost_bps_per_side == 9.0

    # --override takes precedence over --config
    cfg_override_wins = build_config_from_args(str(override), ["backtest.cost_bps_per_side=40"])
    assert cfg_override_wins.backtest.cost_bps_per_side == 40.0


@pytest.mark.unit
def test_cli_accepts_valid_config_file_and_rejects_bad_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A valid --config file loads (the stub then reports 'not yet implemented'); bad ones fail."""
    good = tmp_path / "good.yaml"
    good.write_text("project:\n  variant: exp1\n")
    assert main(["--config", str(good), "build-master"]) == 1
    assert "not yet implemented" in capsys.readouterr().out

    unknown_key = tmp_path / "unknown_key.yaml"
    unknown_key.write_text("universe:\n  not_a_real_key: 1\n")
    assert main(["--config", str(unknown_key), "build-master"]) == 1
    assert "not yet implemented" not in capsys.readouterr().out  # failed at config validation

    missing = tmp_path / "does_not_exist.yaml"
    assert main(["--config", str(missing), "build-master"]) == 1
    assert "not yet implemented" not in capsys.readouterr().out
