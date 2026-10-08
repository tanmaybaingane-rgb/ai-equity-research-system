"""CLI wiring for the S5 command (build-features)."""

from __future__ import annotations

import pandas as pd
import pytest

from nasdaq100 import cli
from nasdaq100.data.adjust import AdjustError
from nasdaq100.data.universe import UniverseError
from nasdaq100.features.build import FeatureTables
from nasdaq100.features.registry import FeatureError


@pytest.mark.unit
def test_build_features_command(monkeypatch, capsys) -> None:
    seen = []

    def fake(cfg):
        seen.append((cfg.project.variant, list(cfg.features.families)))
        model = pd.DataFrame({"eligible": [True, False, True]})
        return FeatureTables(pd.DataFrame({"date": [1, 2]}), model, model)

    monkeypatch.setattr(cli, "run_build_features", fake)
    args = ["--override", "project.variant=exp1", "--override", 'features.families=["momentum"]',
            "build-features"]
    assert cli.main(args) == 0
    assert seen == [("exp1", ["momentum"])]
    out = capsys.readouterr().out
    assert "variant=exp1" in out and "3 rows" in out and "6 features (momentum)" in out
    assert "2 eligible rows" in out and "2 market-series dates" in out


@pytest.mark.unit
def test_build_features_failures_exit_1(monkeypatch) -> None:
    for exc in (FeatureError("bad"), AdjustError("bad"), UniverseError("bad"),
                FileNotFoundError("no adjusted prices")):
        def boom(cfg, exc=exc):
            raise exc

        monkeypatch.setattr(cli, "run_build_features", boom)
        assert cli.main(["build-features"]) == 1


@pytest.mark.unit
def test_build_features_validates_config_first(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(cli, "run_build_features", lambda cfg: called.append(1))
    assert cli.main(["--override", "unknown_section.x=1", "build-features"]) == 1
    assert called == []
