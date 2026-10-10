"""Unit tests for the locked-test guard (``validation/guards.py``)."""

from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nasdaq100
from nasdaq100.validation import guards
from nasdaq100.validation.guards import (
    LockedAccessToken,
    LockedTestError,
    assert_not_locked,
    is_valid_token,
    last_dev_label_idx,
    locked_start_idx,
    open_locked_test,
    require_token,
    tuning_max_idx,
)
from tests.fixtures.s6_validation import bday_calendar, make_cfg, write_protocol

CAL = bday_calendar()
CFG = make_cfg(CAL, first_train_idx=252)
LOCK = locked_start_idx(CFG, CAL)  # first date on or after 2020-01-02


@pytest.mark.unit
def test_boundary_dates_2019_12_31_allowed_2020_01_02_blocked() -> None:
    assert_not_locked("2019-12-31", CFG)
    assert_not_locked(pd.Timestamp("2019-12-31"), CFG)
    assert_not_locked(dt.date(2019, 12, 31), CFG)
    assert_not_locked(np.datetime64("2019-12-31"), CFG)
    for blocked in ("2020-01-02", "2020-01-03", "2026-02-18", pd.Timestamp("2020-01-02"),
                    dt.date(2020, 1, 2), np.datetime64("2020-01-02")):
        with pytest.raises(LockedTestError, match="locked test period"):
            assert_not_locked(blocked, CFG)
    # arrays: one bad value blocks the whole call, the message does not echo the data
    ok = pd.to_datetime(["2019-12-30", "2019-12-31"])
    assert_not_locked(ok, CFG)
    assert_not_locked(pd.Series(ok), CFG)
    with pytest.raises(LockedTestError, match="1 decision date"):
        assert_not_locked(pd.to_datetime(["2019-12-31", "2020-01-02"]), CFG)
    with pytest.raises(LockedTestError, match="2 decision date"):
        assert_not_locked(pd.Series(pd.to_datetime(["2020-01-02", "2021-05-03", "2019-01-02"])), CFG)
    assert_not_locked(pd.to_datetime([pd.NaT, "2019-12-31"]), CFG)  # missing values ignored
    assert_not_locked([], CFG)


@pytest.mark.unit
def test_boundary_t_idx_values() -> None:
    assert_not_locked(LOCK - 1, CFG, calendar=CAL)
    assert_not_locked(np.array([0, 252, LOCK - 1]), CFG, calendar=CAL)
    assert_not_locked(pd.Series([5, 6], dtype="int32"), CFG, calendar=CAL)
    for bad in (LOCK, LOCK + 10, np.array([1, LOCK]), pd.Series([LOCK], dtype="int64")):
        with pytest.raises(LockedTestError, match="t_idx"):
            assert_not_locked(bad, CFG, calendar=CAL)
    assert_not_locked(np.array([1.0, np.nan, 5.0]), CFG, calendar=CAL)  # whole floats, NaN ignored
    with pytest.raises(LockedTestError):
        assert_not_locked(np.array([1.0, float(LOCK)]), CFG, calendar=CAL)
    with pytest.raises(TypeError, match="whole t_idx"):
        assert_not_locked(np.array([1.5]), CFG, calendar=CAL)
    with pytest.raises(TypeError, match="unsupported"):
        assert_not_locked(np.array([True, False]), CFG, calendar=CAL)


@pytest.mark.unit
def test_boundary_follows_the_configured_locked_start() -> None:
    cfg = make_cfg(CAL, first_train_idx=252, locked_test_start="2015-06-01")
    assert_not_locked("2015-05-29", cfg)
    with pytest.raises(LockedTestError):
        assert_not_locked("2015-06-01", cfg)
    idx = locked_start_idx(cfg, CAL)
    assert CAL.date_at(idx) == pd.Timestamp("2015-06-01")
    assert_not_locked(idx - 1, cfg, calendar=CAL)
    with pytest.raises(LockedTestError):
        assert_not_locked(idx, cfg, calendar=CAL)


@pytest.mark.unit
def test_index_helpers_use_the_guide_formulas() -> None:
    assert last_dev_label_idx(CFG, CAL) == LOCK - (20 + 2)
    first_after = int(CAL.dates.searchsorted(np.datetime64("2007-12-31"), side="right"))
    assert tuning_max_idx(CFG, CAL) == first_after - 22
    cfg60 = make_cfg(CAL, horizon=60, first_train_idx=252)
    assert last_dev_label_idx(cfg60, CAL) == LOCK - 62
    assert tuning_max_idx(cfg60, CAL) == first_after - 62
    with pytest.raises(LockedTestError, match="after the calendar"):
        locked_start_idx(make_cfg(CAL, locked_test_start="2050-01-03"), CAL)


@pytest.mark.unit
def test_open_locked_test_refuses_without_a_frozen_protocol(tmp_path: Path) -> None:
    missing = tmp_path / "none.json"
    with pytest.raises(LockedTestError, match="not found"):
        open_locked_test(CFG, missing)
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(LockedTestError, match="unreadable"):
        open_locked_test(CFG, bad_json)
    not_obj = tmp_path / "list.json"
    not_obj.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(LockedTestError, match="JSON object"):
        open_locked_test(CFG, not_obj)
    for name, fields in (("false", {"frozen": False}), ("string", {"frozen": "true"}),
                         ("one", {"frozen": 1}), ("null", {"frozen": None})):
        p = write_protocol(tmp_path / f"{name}.json", **fields)
        before = p.read_text(encoding="utf-8")
        with pytest.raises(LockedTestError, match="not frozen"):
            open_locked_test(CFG, p)
        assert p.read_text(encoding="utf-8") == before  # nothing written on refusal
    nofrozen = tmp_path / "nofrozen.json"
    nofrozen.write_text(json.dumps({"test_opened": False}), encoding="utf-8")
    with pytest.raises(LockedTestError, match="not frozen"):
        open_locked_test(CFG, nofrozen)


@pytest.mark.unit
def test_open_locked_test_records_the_act_and_returns_a_valid_token(tmp_path: Path) -> None:
    p = write_protocol(tmp_path / "p.json", candidates=["a", "b"], config_hash="abc")
    token = open_locked_test(CFG, p)
    assert is_valid_token(token) and require_token(token) is token
    proto = json.loads(p.read_text(encoding="utf-8"))
    assert proto["test_opened"] is True and proto["frozen"] is True
    assert proto["candidates"] == ["a", "b"] and proto["config_hash"] == "abc"  # kept
    opened = dt.datetime.fromisoformat(proto["test_opened_at"])
    assert opened.tzinfo is not None and token.opened_at == proto["test_opened_at"]
    assert abs((dt.datetime.now(dt.UTC) - opened).total_seconds()) < 60
    assert not list(tmp_path.glob("*.tmp"))
    # a later opening keeps the original timestamp and still returns a usable token
    again = open_locked_test(CFG, p)
    assert json.loads(p.read_text(encoding="utf-8"))["test_opened_at"] == proto["test_opened_at"]
    assert is_valid_token(again) and again.nonce != token.nonce
    # a valid token disables assert_not_locked; an invalid one does not
    assert_not_locked("2024-05-06", CFG, token=token)
    with pytest.raises(LockedTestError):
        assert_not_locked("2024-05-06", CFG, token=LockedAccessToken("x", "y"))


@pytest.mark.unit
def test_tokens_cannot_be_forged_or_borrowed() -> None:
    forged = LockedAccessToken(nonce="0" * 32, opened_at="2026-01-01T00:00:00+00:00")
    for bad in (None, forged, "token", 1, {"nonce": forged.nonce}):
        assert not is_valid_token(bad)
        with pytest.raises(LockedTestError, match="requires a token"):
            require_token(bad)
    assert guards._ISSUED_NONCES.isdisjoint({forged.nonce})


def _calls_and_imports(name: str) -> dict[str, list[str]]:
    """Source files under ``src/nasdaq100`` (relative path) that import or call ``name``."""
    root = Path(nasdaq100.__file__).parent
    hits: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == name for a in node.names):
                found.append(f"import@{node.lineno}")
            elif isinstance(node, ast.Call):
                fn = node.func
                if (isinstance(fn, ast.Name) and fn.id == name) or (
                    isinstance(fn, ast.Attribute) and fn.attr == name
                ):
                    found.append(f"call@{node.lineno}")
        if found:
            hits[path.relative_to(root).as_posix()] = found
    return hits


@pytest.mark.unit
def test_nothing_outside_the_guard_module_opens_the_locked_test() -> None:
    """Only S16 may call ``open_locked_test`` (S16 extends this allow-list with its command)."""
    assert _calls_and_imports("open_locked_test") == {}


@pytest.mark.unit
def test_model_code_cannot_bypass_the_panel_loader() -> None:
    """The S4/S5 table readers are building blocks of ``load_panel``; nothing else may use them."""
    allowed = {"data/loaders.py"}
    for name in ("load_labels", "load_features_model", "load_features_raw"):
        users = set(_calls_and_imports(name))
        assert users <= allowed, f"{name} is used outside the panel loader: {sorted(users - allowed)}"
    assert "data/loaders.py" in set(_calls_and_imports("load_labels"))
