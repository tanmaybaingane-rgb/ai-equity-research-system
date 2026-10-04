"""CLI wiring for the S3 command (build-adjusted)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100 import cli
from nasdaq100.data.adjust import AdjustError


@pytest.mark.unit
def test_build_adjusted_command(monkeypatch, capsys) -> None:
    seen = []

    def fake(cfg):
        seen.append(cfg.project.variant)
        return pd.DataFrame(
            {"ticker": ["A", "A", "B"], "logret_cc": [np.nan, 0.01, np.nan]}
        )

    monkeypatch.setattr(cli, "run_build_adjusted", fake)
    assert cli.main(["--override", "project.variant=exp1", "build-adjusted"]) == 0
    assert seen == ["exp1"]
    out = capsys.readouterr().out
    assert "variant=exp1" in out and "3 rows" in out and "2 tickers" in out
    assert "2 NaN logret_cc" in out


@pytest.mark.unit
def test_build_adjusted_failures_exit_1(monkeypatch) -> None:
    for exc in (AdjustError("bad"), FileNotFoundError("no silver")):
        def boom(cfg, exc=exc):
            raise exc

        monkeypatch.setattr(cli, "run_build_adjusted", boom)
        assert cli.main(["build-adjusted"]) == 1


@pytest.mark.unit
def test_build_adjusted_validates_config_first(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(cli, "run_build_adjusted", lambda cfg: called.append(1))
    assert cli.main(["--override", "unknown_section.x=1", "build-adjusted"]) == 1
    assert called == []
