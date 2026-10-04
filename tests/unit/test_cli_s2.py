"""CLI wiring for the S2 commands (build-master, build-universe)."""

from __future__ import annotations

import pandas as pd
import pytest

from nasdaq100 import cli
from nasdaq100.data.security_master import SecurityMasterError
from nasdaq100.data.universe import UniverseError


@pytest.mark.unit
def test_build_master_command(monkeypatch, capsys) -> None:
    master = pd.DataFrame({"ticker": ["AAA", "AZN"], "include_in_universe": [True, False]})
    monkeypatch.setattr(cli, "run_build_master", lambda cfg: master)
    assert cli.main(["build-master"]) == 0
    out = capsys.readouterr().out
    assert "2 tickers, 1 included" in out and "AZN" in out and "SURVIVOR-BIASED" in out

    for exc in (SecurityMasterError("bad curated"), FileNotFoundError("no silver")):
        def boom(cfg, exc=exc):
            raise exc

        monkeypatch.setattr(cli, "run_build_master", boom)
        assert cli.main(["build-master"]) == 1


@pytest.mark.unit
def test_build_universe_command_passes_variant(monkeypatch, capsys) -> None:
    seen = []

    def fake(cfg):
        seen.append(cfg.project.variant)
        return pd.DataFrame({"eligible": [True, False, True]})

    monkeypatch.setattr(cli, "run_build_universe", fake)
    assert cli.main(["--override", "project.variant=exp1", "build-universe"]) == 0
    assert seen == ["exp1"]
    out = capsys.readouterr().out
    assert "variant=exp1" in out and "3 rows" in out and "2 eligible" in out
    assert "SURVIVOR-BIASED" in out

    for exc in (UniverseError("bad"), SecurityMasterError("bad"), FileNotFoundError("x")):
        def boom(cfg, exc=exc):
            raise exc

        monkeypatch.setattr(cli, "run_build_universe", boom)
        assert cli.main(["build-universe"]) == 1


@pytest.mark.unit
def test_s2_commands_validate_config_first(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(cli, "run_build_master", lambda cfg: called.append(1))
    monkeypatch.setattr(cli, "run_build_universe", lambda cfg: called.append(2))
    assert cli.main(["--override", "unknown_section.x=1", "build-master"]) == 1
    assert cli.main(["--override", "unknown_section.x=1", "build-universe"]) == 1
    assert called == []
