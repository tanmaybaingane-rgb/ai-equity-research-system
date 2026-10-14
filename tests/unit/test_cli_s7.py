"""CLI wiring for the S7 command (run-baselines)."""

from __future__ import annotations

import pandas as pd
import pytest

from nasdaq100 import cli
from nasdaq100.data.loaders import LoaderError
from nasdaq100.evaluation.predictive import PredictiveError
from nasdaq100.models.baselines import BaselineError, BaselineRunResult
from nasdaq100.validation.folds import FoldError
from nasdaq100.validation.guards import LockedTestError


def _result(tmp_path) -> BaselineRunResult:
    metrics = pd.DataFrame(
        {
            "model_id": ["baseline_mom12_1", "baseline_mom12_1", "baseline_random"],
            "scope": ["pooled", "year", "pooled"],
            "mean_ic": [0.0123, 0.5, -0.0042],
            "ic_tstat": [1.5, 9.9, -0.3],
            "ic_ci_low": [-0.004, 0.0, -0.03],
            "ic_ci_high": [0.029, 1.0, 0.02],
            "mean_quintile_spread": [0.004, 0.9, -0.001],
            "effective_n": [144, 12, 144],
        }
    )
    return BaselineRunResult({}, {}, metrics, tmp_path / "baseline_metrics.csv")


@pytest.mark.unit
def test_run_baselines_prints_one_line_per_model_and_the_survivorship_status(
    monkeypatch, capsys, tmp_path
) -> None:
    calls = []
    monkeypatch.setattr(cli, "run_baselines", lambda cfg: calls.append(cfg) or _result(tmp_path))
    assert cli.main(["run-baselines"]) == 0
    assert len(calls) == 1 and calls[0].project.variant == "base"
    out = capsys.readouterr().out
    assert "not yet implemented" not in out
    assert "baseline_mom12_1: rank IC 0.0123 (t=1.50" in out and "effective_n=144" in out
    assert "baseline_random: rank IC -0.0042" in out
    assert "baseline_metrics.csv" in out and "units_are_returns=False" in out
    assert "SURVIVOR-BIASED" in out
    assert out.count("rank IC") == 2  # pooled rows only, not the per-year rows


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        BaselineError("bad"),
        PredictiveError("bad"),
        LoaderError("bad"),
        FoldError("bad"),
        LockedTestError("bad"),
        FileNotFoundError("no labels"),
    ],
)
def test_run_baselines_reports_failures_with_exit_code_1(monkeypatch, error) -> None:
    def boom(cfg):
        raise error

    monkeypatch.setattr(cli, "run_baselines", boom)
    assert cli.main(["run-baselines"]) == 1


@pytest.mark.unit
def test_run_baselines_validates_the_configuration_first(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(cli, "run_baselines", lambda cfg: calls.append(cfg))
    assert cli.main(["--override", "unknown_section.x=1", "run-baselines"]) == 1
    assert calls == []
