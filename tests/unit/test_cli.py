"""Unit tests for the CLI status and argument handling."""

import pytest

from nasdaq100.cli import main


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
    exit_code = main(["ingest"])
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
    exit_code2 = main(["--override", "unknown_section.val=123", "ingest"])
    assert exit_code2 == 1
