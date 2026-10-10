"""Unit tests for the panel loader (``data/loaders.py``)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.loaders import (
    SPLITS,
    LoaderError,
    build_panel,
    load_panel,
    panel_label_columns,
)
from nasdaq100.features.build import run_build_features
from nasdaq100.labels.forward_returns import run_build_labels
from nasdaq100.utils.io import write_parquet
from nasdaq100.validation.guards import (
    LockedTestError,
    last_dev_label_idx,
    locked_start_idx,
    tuning_max_idx,
)
from tests.fixtures.s5_features import make_feature_panel
from tests.fixtures.s6_validation import H, bday_calendar, issue_token, make_cfg, panel_tables

CAL = bday_calendar("2017-01-02", periods=1300)  # 2017-01-02 .. 2021-12 (business days)
CFG = make_cfg(CAL, tuning_end_date="2018-06-29")
LABELS = panel_label_columns(H)
LOCK = locked_start_idx(CFG, CAL)
CAP = last_dev_label_idx(CFG, CAL)


def _panel(split="dev", labels=True, features=None, token=None):
    fm, lab, uni = panel_tables(CAL)
    return build_panel(fm, lab, uni, CAL, CFG, features, split, labels, token)


@pytest.mark.unit
def test_dev_panel_stops_at_the_last_dev_date_and_masks_late_labels() -> None:
    p = _panel("dev")
    assert list(p.columns) == ["ticker", "date", "t_idx", "eligible", "f1", "f2", *LABELS]
    assert p["date"].max() == pd.Timestamp("2019-12-31") and p["t_idx"].max() == LOCK - 1
    assert (p["t_idx"] < LOCK).all() and (p["date"] < pd.Timestamp("2020-01-02")).all()
    beyond, within = p["t_idx"] > CAP, p["t_idx"] <= CAP
    assert beyond.sum() > 0 and within.sum() > 0
    for col in LABELS:
        if col in ("label_exit_idx_h20", "has_label_h20"):
            continue
        assert p.loc[beyond, col].isna().all(), col  # NaN beyond last_dev_label_idx
    assert not p.loc[beyond, "has_label_h20"].any()
    assert p.loc[beyond, "label_exit_idx_h20"].notna().all()  # a calendar number, kept
    assert p.loc[within & p["eligible"], "excess_h20"].notna().all()
    assert p.loc[within, "has_label_h20"].all()  # every dev date <= CAP resolves before the lock
    # exact boundary: t_idx == CAP keeps its label, CAP + 1 loses it
    for tk in ("AAA",):
        at = p[(p["ticker"] == tk) & (p["t_idx"] == CAP)].iloc[0]
        nxt = p[(p["ticker"] == tk) & (p["t_idx"] == CAP + 1)].iloc[0]
        assert at["has_label_h20"] and not nxt["has_label_h20"]
        assert at["ret_fwd_h20"] == CAP + 0.25 and np.isnan(nxt["ret_fwd_h20"])
    # features are still returned for the final December-2019 dates
    assert p.loc[beyond, ["f1", "f2"]].notna().all().all()
    assert (p.loc[beyond, "f1"] == p.loc[beyond, "t_idx"]).all()


@pytest.mark.unit
def test_dev_panel_never_contains_locked_information_even_before_masking() -> None:
    fm, lab, uni = panel_tables(CAL)
    p = build_panel(fm, lab, uni, CAL, CFG, None, "dev")
    locked_values = set(lab.loc[lab["date"] >= pd.Timestamp("2020-01-02"), "excess_h20"].dropna())
    assert locked_values and not locked_values & set(p["excess_h20"].dropna())
    assert p["f1"].max() == LOCK - 1  # no feature value from 2020 either


@pytest.mark.unit
def test_tuning_panel_ends_at_tuning_max_idx_with_all_labels_resolved() -> None:
    p = _panel("tuning")
    cap = tuning_max_idx(CFG, CAL)
    assert p["t_idx"].max() == cap and cap < CAP
    assert p["date"].max() < pd.Timestamp("2018-07-01")
    assert p.loc[p["t_idx"] <= cap, "has_label_h20"].all()
    # the label exit of the last tuning row is before the first date after tuning_end_date
    first_after = int(CAL.dates.searchsorted(pd.Timestamp("2018-06-29"), side="right"))
    assert (p["label_exit_idx_h20"] < first_after).all()


@pytest.mark.unit
def test_locked_panel_needs_a_valid_token_and_is_complete_with_it(tmp_path) -> None:
    fm, lab, uni = panel_tables(CAL)
    for bad in (None, "token"):
        with pytest.raises(LockedTestError):
            build_panel(fm, lab, uni, CAL, CFG, None, "locked", True, bad)
    token = issue_token(CFG, tmp_path)
    p = build_panel(fm, lab, uni, CAL, CFG, None, "locked", True, token)
    assert p["t_idx"].max() == CAL.last_idx and p["date"].max() == CAL.last_date
    assert len(p) == len(fm)
    unmasked = (p["t_idx"] > CAP) & (p["t_idx"] + 1 + H <= CAL.last_idx)
    assert p.loc[unmasked, "has_label_h20"].all()  # true labels, nothing masked
    assert p.loc[p["eligible"] & unmasked, "excess_h20"].notna().all()


@pytest.mark.unit
def test_feature_selection_label_switch_and_validation() -> None:
    p = _panel("dev", features=["f2"])
    assert list(p.columns) == ["ticker", "date", "t_idx", "eligible", "f2", *LABELS]
    q = _panel("dev", labels=False, features=["f1", "f2", "f1"])
    assert list(q.columns) == ["ticker", "date", "t_idx", "eligible", "f1", "f2"]
    assert not any(c.endswith("h20") for c in q.columns)
    with pytest.raises(LoaderError, match="Unknown feature"):
        _panel("dev", features=["nope"])
    with pytest.raises(LoaderError, match="Unknown split"):
        _panel("train")
    assert SPLITS == ("dev", "tuning", "locked")
    assert p["t_idx"].dtype == "int32" and p["date"].dtype == "datetime64[ns]"
    assert p["ticker"].is_monotonic_increasing or p.sort_values(["ticker", "date"]).equals(p)


@pytest.mark.unit
def test_join_consistency_checks() -> None:
    fm, lab, uni = panel_tables(CAL)
    with pytest.raises(LoaderError, match="labels and features_model"):
        build_panel(fm, lab.iloc[:-1], uni, CAL, CFG, None, "dev")
    with pytest.raises(LoaderError, match="universe and features_model"):
        build_panel(fm, lab, uni.iloc[:-1], CAL, CFG, None, "dev")
    flipped = uni.copy()
    flipped.loc[5, "eligible"] = ~flipped.loc[5, "eligible"]
    with pytest.raises(LoaderError, match="differs from the universe"):
        build_panel(fm, lab, flipped, CAL, CFG, None, "dev")
    with pytest.raises(LoaderError, match="lacks the primary-horizon"):
        build_panel(fm, lab.drop(columns=["y_cls_h20"]), uni, CAL, CFG, None, "dev")
    shifted = fm.copy()
    shifted["date"] = shifted["date"] + pd.Timedelta(days=1)  # off the calendar and not equal
    with pytest.raises(LoaderError):
        build_panel(shifted, lab, uni, CAL, CFG, None, "dev")


@pytest.mark.unit
def test_primary_horizon_selects_the_label_columns_and_the_mask() -> None:
    cfg60 = make_cfg(CAL, horizon=60, tuning_end_date="2018-06-29")
    fm, lab, uni = panel_tables(CAL, h=60)
    p = build_panel(fm, lab, uni, CAL, cfg60, None, "dev")
    assert [c for c in p.columns if c.endswith("h60")] == panel_label_columns(60)
    cap60 = last_dev_label_idx(cfg60, CAL)
    assert cap60 == LOCK - 62
    assert p.loc[p["t_idx"] > cap60, "has_label_h60"].eq(False).all()
    assert p.loc[p["t_idx"] <= cap60, "has_label_h60"].all()


@pytest.mark.unit
def test_load_panel_from_files_end_to_end(tmp_path) -> None:
    """The file-based path with the real S2..S5 builders on a toy panel."""
    adjusted, universe, cal = make_feature_panel(n_tickers=24, n_days=330, seed=9, min_obs=40)
    cfg = load_config(overrides=["validation.locked_test_start=2020-12-01",
                                 "validation.tuning_end_date=2020-07-31"])
    files = {n: tmp_path / f"{n}.parquet" for n in
             ("adjusted", "universe", "calendar", "labels", "market", "raw", "model")}
    write_parquet(adjusted, files["adjusted"])
    write_parquet(universe, files["universe"])
    write_parquet(cal.frame, files["calendar"], sort_keys=("date",))
    run_build_labels(cfg, adjusted_file=files["adjusted"], universe_file=files["universe"],
                     calendar_file=files["calendar"], labels_file=files["labels"])
    run_build_features(cfg, adjusted_file=files["adjusted"], universe_file=files["universe"],
                       market_file=files["market"], raw_file=files["raw"],
                       model_file=files["model"])
    kw = {"features_file": files["model"], "labels_file": files["labels"],
          "universe_file": files["universe"], "calendar_file": files["calendar"]}
    dev = load_panel(cfg, ["ret_21", "vol_21"], "dev", **kw)
    lock = locked_start_idx(cfg, cal)
    assert dev["t_idx"].max() == lock - 1 and dev["date"].max() < pd.Timestamp("2020-12-01")
    assert list(dev.columns)[:6] == ["ticker", "date", "t_idx", "eligible", "ret_21", "vol_21"]
    cap = last_dev_label_idx(cfg, cal)
    assert dev.loc[dev["t_idx"] > cap, "has_label_h20"].eq(False).all()
    assert dev.loc[dev["t_idx"] > cap, "excess_h20"].isna().all()
    assert dev.loc[(dev["t_idx"] <= cap) & dev["eligible"], "ret_fwd_h20"].notna().any()
    tun = load_panel(cfg, None, "tuning", labels=False, **kw)
    assert tun["t_idx"].max() == tuning_max_idx(cfg, cal) and "has_label_h20" not in tun
    assert tun.shape[1] == 4 + 24  # every feature of the configured families
    with pytest.raises(LockedTestError):
        load_panel(cfg, None, "locked", **kw)
    full = load_panel(cfg, ["ret_21"], "locked", token=issue_token(cfg, tmp_path), **kw)
    assert full["t_idx"].max() == cal.last_idx
    with pytest.raises(LoaderError, match="Unknown split"):
        load_panel(cfg, None, "test", **kw)
