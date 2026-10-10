"""S6 acceptance tests on the real frozen dataset (``needs_data``; auto-skipped if absent).

S1..S5 build once per session into temp dirs, so nothing under ``data/`` or ``artifacts/`` is
written, and the locked-test protocol is a temporary file (the real ``experiments/`` directory is
never touched). Expected numbers: Master Guide Part II Section II.2 and Part III S6.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.adjust import run_build_adjusted
from nasdaq100.data.loaders import load_panel, panel_label_columns
from nasdaq100.data.security_master import run_build_master
from nasdaq100.data.universe import run_build_universe
from nasdaq100.features.build import run_build_features
from nasdaq100.labels.forward_returns import run_build_labels
from nasdaq100.paths import security_master_curated_path
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.validation.folds import (
    build_fold_plan,
    make_dev_folds,
    make_locked_folds,
    make_tuning_folds,
    write_fold_plan,
)
from nasdaq100.validation.guards import (
    LockedTestError,
    assert_not_locked,
    last_dev_label_idx,
    locked_start_idx,
    open_locked_test,
    tuning_max_idx,
)
from nasdaq100.validation.leakage import assert_folds_valid, poison_future

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def s6(real_s1: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("s6_real")
    cfg = load_config()
    silver_file, cal_file = real_s1["silver_file"], real_s1["tmp"] / "calendar.parquet"
    run_build_master(cfg, silver_file=silver_file, curated_file=security_master_curated_path(),
                     master_file=tmp / "security_master.csv")
    run_build_universe(cfg, silver_file=silver_file, master_file=tmp / "security_master.csv",
                       universe_file=tmp / "universe.parquet")
    run_build_adjusted(cfg, silver_file=silver_file, calendar_file=cal_file,
                       adjusted_file=tmp / "adjusted_prices.parquet")
    run_build_labels(cfg, adjusted_file=tmp / "adjusted_prices.parquet",
                     universe_file=tmp / "universe.parquet", calendar_file=cal_file,
                     labels_file=tmp / "labels.parquet")
    run_build_features(cfg, adjusted_file=tmp / "adjusted_prices.parquet",
                       universe_file=tmp / "universe.parquet", market_file=tmp / "market.parquet",
                       raw_file=tmp / "raw.parquet", model_file=tmp / "features_model.parquet")
    files = {"features_file": tmp / "features_model.parquet", "labels_file": tmp / "labels.parquet",
             "universe_file": tmp / "universe.parquet", "calendar_file": cal_file}
    proto = tmp / "locked_test_protocol.json"
    proto.write_text(json.dumps({"frozen": True, "test_opened": False}), encoding="utf-8")
    return {"cfg": cfg, "files": files, "calendar": TradingCalendar.load(cal_file),
            "protocol": proto, "tmp": tmp}


def test_boundary_indices_on_the_real_calendar(s6) -> None:
    cfg, cal = s6["cfg"], s6["calendar"]
    assert locked_start_idx(cfg, cal) == 5031 and cal.date_at(5031) == pd.Timestamp("2020-01-02")
    assert cal.date_at(5030) == pd.Timestamp("2019-12-31")
    assert last_dev_label_idx(cfg, cal) == 5009  # C4
    assert cal.date_at(5009) == pd.Timestamp("2019-11-29")  # last dev evaluation date
    assert tuning_max_idx(cfg, cal) == 1988  # C9
    assert cal.idx_of("2008-01-02") == 2010


def test_worked_example_dev_fold_2008_on_the_real_calendar(s6) -> None:
    cfg, cal = s6["cfg"], s6["calendar"]
    f = make_dev_folds(cfg, cal)[0]
    assert (f.fold_id, f.test_year, f.test_start_idx, f.gap) == ("dev_2008", 2008, 2010, 26)
    assert f.train_end_idx == 1983 and cal.date_at(1983) == pd.Timestamp("2007-11-21")
    assert (f.calib_idx[0], f.calib_idx[-1]) == (1482, 1982)  # strided inside [1480, 1983]
    assert (f.train_core_idx[0], f.train_core_idx[-1]) == (252, 1452)  # strided inside [252, 1453]
    assert 1480 <= f.calib_idx[0] and f.calib_idx[-1] <= 1983
    assert len(f.train_core_idx) == 241 and len(f.calib_idx) == 101
    assert f.test_end_idx == cal.idx_of("2008-12-31")
    unstrided = make_dev_folds(load_config(overrides=["validation.train_stride=1"]), cal)[0]
    assert (unstrided.train_core_idx[0], unstrided.train_core_idx[-1]) == (252, 1453)
    assert (unstrided.calib_idx[0], unstrided.calib_idx[-1]) == (1480, 1983)
    span = unstrided.train_core_idx[-1] - unstrided.train_core_idx[0] + 1
    assert span == 1202 and 4.7 < span / 252 < 4.9  # ~4.8 years, ~1,200 dates before stride


def test_all_fold_families_are_valid_on_the_real_calendar(s6, tmp_path) -> None:
    cfg, cal = s6["cfg"], s6["calendar"]
    kw = {"first_train_idx": 252, "train_stride": 5}
    dev, tun = make_dev_folds(cfg, cal), make_tuning_folds(cfg, cal)
    assert [f.test_year for f in dev] == list(range(2008, 2020)) and len(dev) == 12
    assert dev[-1].test_end_idx == 5030 and cal.date_at(5030) == pd.Timestamp("2019-12-31")
    assert_folds_valid(dev, 20, 5, locked_start_idx=5031, first_test_idx=2010, **kw)
    assert [f.test_year for f in tun] == [2005, 2006, 2007] and tun[-1].test_end_idx == 1988
    assert all(f.calib_idx == [] for f in tun)
    assert_folds_valid(tun, 20, 5, locked_start_idx=5031, **kw)
    token = open_locked_test(cfg, s6["protocol"])
    locked = make_locked_folds(cfg, token, cal)
    assert [f.test_year for f in locked] == list(range(2020, 2027))
    assert locked[0].test_start_idx == 5031 and locked[-1].test_end_idx == cal.last_idx
    assert cal.date_at(locked[-1].test_end_idx) == pd.Timestamp("2026-02-18")
    assert_folds_valid(locked, 20, 5, **kw)
    # sensible fold sizes: growing expanding core, constant calibration
    assert all(100 <= len(f.calib_idx) <= 101 for f in dev)  # 504 dates thinned by stride 5
    assert all(a.train_core_idx[-1] < b.train_core_idx[-1] for a, b in zip(dev, dev[1:], strict=False))
    # the proof of the gap on the real calendar: the last training row's label exits before t0
    for f in dev + tun + locked:
        assert max(f.train_idx) + 1 + 20 < f.test_start_idx
        assert cal.date_at(max(f.train_idx)) < cal.date_at(f.test_start_idx)


def test_fold_plan_matches_the_guide_numbers(s6, tmp_path) -> None:
    cfg, cal = s6["cfg"], s6["calendar"]
    out = tmp_path / "fold_plan.json"
    plan = write_fold_plan(cfg, cal, out)
    assert json.loads(out.read_text(encoding="utf-8")) == plan == build_fold_plan(cfg, cal)
    assert len(plan["dev_folds"]) == 12 and len(plan["tuning_folds"]) == 3
    assert plan["last_dev_label_idx"] == 5009 and plan["tuning_max_idx"] == 1988
    assert plan["locked_test_start_idx"] == 5031 and plan["gap"] == 26
    f08 = plan["dev_folds"][0]
    assert f08["core"]["span_days"] == 1201 and f08["core"]["n_dates"] == 241
    assert f08["calibration"]["span_days"] == 501 and f08["train_end_idx"] == 1983
    assert all(f["test_year"] == y for f, y in zip(plan["dev_folds"], range(2008, 2020), strict=True))
    assert "locked" not in json.dumps(plan["dev_folds"])


def test_dev_panel_boundaries_and_label_masking(s6) -> None:
    cfg = s6["cfg"]
    panel = load_panel(cfg, None, "dev", **s6["files"])
    cols = panel_label_columns(20)
    assert list(panel.columns)[:4] == ["ticker", "date", "t_idx", "eligible"]
    assert list(panel.columns)[4:28] == list(load_panel(cfg, None, "tuning", labels=False,
                                                        **s6["files"]).columns)[4:28]
    assert list(panel.columns)[28:] == cols
    assert panel["date"].max() == pd.Timestamp("2019-12-31") and panel["t_idx"].max() == 5030
    assert_not_locked(panel["date"], cfg)
    late = panel["t_idx"] > 5009
    assert late.sum() > 0 and panel["t_idx"][late].min() == 5010
    for c in cols:
        if not c.startswith(("label_exit_idx", "has_label")):
            assert panel.loc[late, c].isna().all(), c
    assert not panel.loc[late, "has_label_h20"].any()
    assert panel.loc[~late, "has_label_h20"].all()  # every dev date <= 5009 is resolved
    feats = panel.loc[late & panel["eligible"], panel.columns[4:28]]
    assert feats.drop(columns=["beta_126"]).notna().all().all()  # features kept for Dec 2019
    assert panel.loc[panel["t_idx"] == 5009, "ret_fwd_h20"].notna().any()
    assert panel.loc[panel["t_idx"] == 5010, "ret_fwd_h20"].isna().all()
    # eligible labelled rows: the S4 panel restricted to <= 2019-11-29
    labelled = panel[panel["eligible"] & panel["has_label_h20"]]
    assert labelled["excess_h20"].notna().all() and labelled["t_idx"].max() == 5009
    assert labelled["t_idx"].min() == 252  # first eligible decision date


def test_tuning_panel_ends_at_1988_and_locked_panel_needs_the_token(s6, tmp_path) -> None:
    cfg, files = s6["cfg"], s6["files"]
    tuning = load_panel(cfg, ["ret_21", "vol_21"], "tuning", **files)
    cal = s6["calendar"]
    assert tuning["t_idx"].max() == 1988 and tuning["date"].max() == cal.date_at(1988)
    assert tuning["date"].max() < pd.Timestamp("2007-12-31")
    assert tuning.loc[tuning["eligible"], "has_label_h20"].all()
    assert (tuning["label_exit_idx_h20"] < 2010).all()  # labels resolved before 2008
    with pytest.raises(LockedTestError):
        load_panel(cfg, None, "locked", **files)
    with pytest.raises(LockedTestError):
        load_panel(cfg, None, "locked", token="not-a-token", **files)  # type: ignore[arg-type]
    proto = tmp_path / "locked_test_protocol.json"
    proto.write_text(json.dumps({"frozen": False}), encoding="utf-8")
    with pytest.raises(LockedTestError, match="not frozen"):
        open_locked_test(cfg, proto)
    token = open_locked_test(cfg, s6["protocol"])
    full = load_panel(cfg, ["ret_21"], "locked", token=token, **files)
    assert full["t_idx"].max() == 6570 and full["date"].max() == pd.Timestamp("2026-02-18")
    assert full["has_label_h20"].sum() == 511_975  # true, unmasked labels
    assert json.loads(s6["protocol"].read_text(encoding="utf-8"))["test_opened"] is True


def test_dev_panel_does_not_depend_on_locked_tables_and_poison_future_works(s6) -> None:
    cfg = s6["cfg"]
    dev = load_panel(cfg, ["ret_21", "mom_12_1"], "dev", **s6["files"])
    cut = 3000
    poisoned = poison_future(dev, cut)
    assert poisoned.loc[poisoned["t_idx"] <= cut].drop(columns=["label_exit_idx_h20"]).equals(
        dev.loc[dev["t_idx"] <= cut].drop(columns=["label_exit_idx_h20"])
    )
    late = poisoned[poisoned["t_idx"] > cut]
    assert late[["ret_21", "mom_12_1", "excess_h20"]].isna().all().all()
    assert not late["eligible"].any() and not late["has_label_h20"].any()
    assert np.array_equal(poisoned["t_idx"], dev["t_idx"])
