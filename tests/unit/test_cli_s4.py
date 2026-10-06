"""CLI wiring for the S4 command (build-labels)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100 import cli
from nasdaq100.data.adjust import AdjustError
from nasdaq100.data.universe import UniverseError
from nasdaq100.labels.forward_returns import LabelError


@pytest.mark.unit
def test_build_labels_command(monkeypatch, capsys) -> None:
    seen = []

    def fake(cfg):
        seen.append((cfg.project.variant, list(cfg.labels.horizons)))
        return pd.DataFrame(
            {
                "has_label_h5": [True, True, False],
                "excess_h5": [0.1, np.nan, np.nan],
                "has_label_h20": [True, False, False],
                "excess_h20": [np.nan, np.nan, np.nan],
            }
        )

    monkeypatch.setattr(cli, "run_build_labels", fake)
    args = ["--override", "project.variant=exp1", "--override", "labels.horizons=[5,20]",
            "build-labels"]
    assert cli.main(args) == 0
    assert seen == [("exp1", [5, 20])]
    out = capsys.readouterr().out
    assert "variant=exp1" in out and "3 rows" in out
    assert "h=5: 2 with forward return, 1 cross-sectional" in out
    assert "h=20: 1 with forward return, 0 cross-sectional" in out


@pytest.mark.unit
def test_build_labels_failures_exit_1(monkeypatch) -> None:
    for exc in (LabelError("bad"), AdjustError("bad"), UniverseError("bad"),
                FileNotFoundError("no adjusted prices")):
        def boom(cfg, exc=exc):
            raise exc

        monkeypatch.setattr(cli, "run_build_labels", boom)
        assert cli.main(["build-labels"]) == 1


@pytest.mark.unit
def test_build_labels_validates_config_first(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(cli, "run_build_labels", lambda cfg: called.append(1))
    assert cli.main(["--override", "unknown_section.x=1", "build-labels"]) == 1
    assert called == []
