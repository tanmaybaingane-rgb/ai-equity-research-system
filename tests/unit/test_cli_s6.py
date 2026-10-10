"""CLI wiring for the S6 command (check-leakage)."""

from __future__ import annotations

import json

import pytest

from nasdaq100 import cli
from nasdaq100.validation import folds
from nasdaq100.validation.folds import FoldError
from tests.fixtures.s6_validation import bday_calendar


def _stub_suite(monkeypatch, code=0):
    calls = []
    monkeypatch.setattr(cli, "run_leakage_suite", lambda: calls.append(1) or code)
    return calls


@pytest.mark.unit
def test_check_leakage_writes_the_plan_and_runs_the_suite(monkeypatch, capsys, tmp_path) -> None:
    cal = bday_calendar()
    out = tmp_path / "artifacts" / "base" / "fold_plan.json"
    monkeypatch.setattr(folds, "_calendar", lambda c: cal)
    monkeypatch.setattr(folds, "fold_plan_path", lambda variant="base": out)
    calls = _stub_suite(monkeypatch)
    ov = ["--override", "validation.first_train_decision_date="
          f"{cal.date_at(252).date()}"]
    assert cli.main([*ov, "check-leakage"]) == 0
    assert calls == [1]
    text = capsys.readouterr().out
    assert "12 dev folds" in text and "3 tuning folds" in text and "gap 26" in text
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert len(plan["dev_folds"]) == 12 and plan["gap"] == 26


@pytest.mark.unit
def test_check_leakage_fails_when_tests_fail_or_the_plan_cannot_be_written(monkeypatch) -> None:
    monkeypatch.setattr(cli, "write_fold_plan", lambda cfg: {"dev_folds": [], "tuning_folds": [],
                                                              "gap": 26, "last_dev_label_idx": 1,
                                                              "tuning_max_idx": 1})
    calls = _stub_suite(monkeypatch, code=1)
    assert cli.main(["check-leakage"]) == 1  # a failing leakage test fails the command
    assert calls == [1]
    for exc in (FileNotFoundError("no calendar"), FoldError("bad")):
        def boom(cfg, exc=exc):
            raise exc

        monkeypatch.setattr(cli, "write_fold_plan", boom)
        calls = _stub_suite(monkeypatch, code=0)
        assert cli.main(["check-leakage"]) == 1  # no plan: failure ...
        assert calls == [1]  # ... but the leakage tests are still run


@pytest.mark.unit
def test_check_leakage_validates_config_first(monkeypatch) -> None:
    calls = _stub_suite(monkeypatch)
    assert cli.main(["--override", "unknown_section.x=1", "check-leakage"]) == 1
    assert calls == []
