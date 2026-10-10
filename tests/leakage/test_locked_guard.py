"""L8: the locked-test guard.

It refuses without a frozen protocol and blocks 2020-01-02 while allowing 2019-12-31. No test in
this module touches the real ``experiments/locked_test_protocol.json``: every protocol is a
temporary file, and the default protocol path is redirected to a temporary directory.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from nasdaq100.data.loaders import build_panel, load_panel
from nasdaq100.validation import guards
from nasdaq100.validation.folds import make_locked_folds
from nasdaq100.validation.guards import (
    LockedTestError,
    assert_not_locked,
    open_locked_test,
    require_token,
)
from tests.fixtures.s6_validation import bday_calendar, make_cfg, panel_tables, write_protocol

pytestmark = pytest.mark.leakage

CAL = bday_calendar()
CFG = make_cfg(CAL, first_train_idx=252)


@pytest.fixture(autouse=True)
def _isolate_default_protocol(tmp_path, monkeypatch):
    """The default protocol path must never point at the real repository file in these tests."""
    monkeypatch.setattr(guards, "locked_test_protocol_path", lambda: tmp_path / "absent.json")


def test_boundary_2019_12_31_allowed_2020_01_02_blocked() -> None:
    assert_not_locked("2019-12-31", CFG)
    assert_not_locked(pd.Timestamp("2019-12-31"), CFG)
    with pytest.raises(LockedTestError):
        assert_not_locked("2020-01-02", CFG)
    with pytest.raises(LockedTestError):
        assert_not_locked(pd.Timestamp("2020-01-02"), CFG)
    lock = guards.locked_start_idx(CFG, CAL)
    assert CAL.date_at(lock - 1) == pd.Timestamp("2019-12-31")
    assert_not_locked(lock - 1, CFG, calendar=CAL)
    with pytest.raises(LockedTestError):
        assert_not_locked(lock, CFG, calendar=CAL)


def test_refuses_without_a_frozen_protocol(tmp_path) -> None:
    with pytest.raises(LockedTestError, match="not found"):
        open_locked_test(CFG)  # default path (redirected): no protocol at all
    for fields in ({"frozen": False}, {"frozen": None}, {}):
        p = tmp_path / "p.json"
        p.write_text(json.dumps({"test_opened": False, **fields}), encoding="utf-8")
        with pytest.raises(LockedTestError, match="not frozen"):
            open_locked_test(CFG, p)
        assert json.loads(p.read_text(encoding="utf-8"))["test_opened"] is False


def test_public_loaders_never_return_locked_data_without_the_token(tmp_path) -> None:
    fm, lab, uni = panel_tables(CAL)
    for split in ("dev", "tuning"):
        panel = build_panel(fm, lab, uni, CAL, make_cfg(CAL, first_train_idx=252), None, split)
        assert panel["date"].max() < pd.Timestamp("2020-01-02")
    for bad in (None, "token", object()):
        with pytest.raises(LockedTestError):
            build_panel(fm, lab, uni, CAL, CFG, None, "locked", True, bad)  # type: ignore[arg-type]
        with pytest.raises(LockedTestError):
            make_locked_folds(CFG, bad, CAL)  # type: ignore[arg-type]
        with pytest.raises(LockedTestError):
            require_token(bad)
    # load_panel refuses before reading any file (these paths do not exist)
    with pytest.raises(LockedTestError):
        load_panel(CFG, None, "locked", features_file=tmp_path / "x", labels_file=tmp_path / "y")
    # a frozen protocol (temporary file) opens the door exactly once the deliberate act is made
    token = open_locked_test(CFG, write_protocol(tmp_path / "frozen.json"))
    assert build_panel(fm, lab, uni, CAL, CFG, None, "locked", True, token)["date"].max() == (
        CAL.last_date
    )
    assert make_locked_folds(CFG, token, CAL)[0].test_year == 2020
