"""CLI wiring for the S1 commands (ingest, validate)."""

from __future__ import annotations

import pytest

from nasdaq100 import cli
from nasdaq100.data.ingest import FrozenDatasetError
from nasdaq100.data.validate import ValidationError


def _fake_manifest() -> dict:
    return {
        "rows": 10, "n_tickers": 2, "date_min": "2000-01-03", "date_max": "2000-01-14",
        "sha256": "abc",
    }


@pytest.mark.unit
def test_ingest_command_success_and_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "run_ingest", _fake_manifest)
    assert cli.main(["ingest"]) == 0
    assert "Ingested 10 rows" in capsys.readouterr().out

    def boom() -> dict:
        raise FrozenDatasetError("hash mismatch")

    monkeypatch.setattr(cli, "run_ingest", boom)
    assert cli.main(["ingest"]) == 1

    def missing() -> dict:
        raise FileNotFoundError("no archive")

    monkeypatch.setattr(cli, "run_ingest", missing)
    assert cli.main(["ingest"]) == 1


@pytest.mark.unit
def test_validate_command_success_and_failure(monkeypatch, capsys) -> None:
    report = {"status": {"soft_warnings": ["x"]}, "dataset_status": "SURVIVOR-BIASED"}
    monkeypatch.setattr(cli, "run_validate", lambda cfg: report)
    assert cli.main(["validate"]) == 0
    out = capsys.readouterr().out
    assert "SURVIVOR-BIASED" in out and "Soft warnings: x" in out

    def boom(cfg) -> dict:
        raise ValidationError("hard check failed")

    monkeypatch.setattr(cli, "run_validate", boom)
    assert cli.main(["validate"]) == 1


@pytest.mark.unit
def test_s1_commands_still_validate_config_first(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(cli, "run_ingest", lambda: called.append(1) or _fake_manifest())
    assert cli.main(["--override", "unknown_section.val=1", "ingest"]) == 1
    assert called == []  # bad config stops the command before any work
