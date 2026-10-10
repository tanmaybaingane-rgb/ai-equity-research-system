"""Stage S6: the panel loader, the only supported way for models to read features and labels.

``load_panel`` joins ``features_model``, ``labels`` (primary horizon) and ``eligible`` on
(``ticker``, ``date``) and enforces the split rules of the validation framework:

* ``"dev"``: decision dates up to 2019-12-31 only. Label columns are set to NaN and
  ``has_label_h`` to False for decision dates with ``t_idx > last_dev_label_idx`` (5009 = locked
  start index - (h + 2), decision C4); features are still returned for the final December-2019
  dates (predictions only need features). ``label_exit_idx_h`` stays populated (it is a number
  computed from the calendar, not information about prices).
* ``"tuning"``: rows with ``t_idx <= tuning_max_idx`` (1988, labels resolved before 2008, C9).
* ``"locked"``: the complete panel (every date, true labels, the later locked folds may train on
  earlier locked years) and **only with the token** returned by ``open_locked_test`` (S16).

The dev and tuning panels are checked with ``assert_not_locked`` before they are returned. The
S4 / S5 table readers (``load_labels``, ``load_features_model``, ``load_features_raw``) are
building blocks: model code must not call them directly (a structural test enforces this).

Time convention: Part II Section II.2.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from nasdaq100.data.universe import load_universe
from nasdaq100.features.build import load_features_model
from nasdaq100.labels.forward_returns import LABEL_STEMS, load_labels
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.validation.guards import (
    LockedAccessToken,
    assert_not_locked,
    last_dev_label_idx,
    locked_start_idx,
    require_token,
    tuning_max_idx,
)

if TYPE_CHECKING:
    from nasdaq100.config import Config

SPLITS: tuple[str, ...] = ("dev", "tuning", "locked")
ID_COLUMNS: tuple[str, ...] = ("ticker", "date", "t_idx", "eligible")
#: Label columns that are NaN-masked beyond the last dev label (``has_label`` becomes False).
MASKED_STEMS: tuple[str, ...] = ("ret_fwd_h", "excess_h", "y_reg_h", "y_cls_h", "rank_pct_h")


class LoaderError(ValueError):
    """Invalid request or inconsistent input tables for the panel loader."""


def panel_label_columns(horizon: int) -> list[str]:
    """Label columns of the primary horizon, in ``labels.parquet`` order."""
    return [f"{stem}{int(horizon)}" for stem in LABEL_STEMS]


def build_panel(
    features_model: pd.DataFrame,
    labels: pd.DataFrame,
    universe: pd.DataFrame,
    calendar: TradingCalendar,
    cfg: Config,
    features: Sequence[str] | None,
    split: str,
    labels_wanted: bool = True,
    token: LockedAccessToken | None = None,
) -> pd.DataFrame:
    """Pure panel construction from the tables (see the module docstring for the rules)."""
    if split not in SPLITS:
        raise LoaderError(f"Unknown split {split!r}; valid: {list(SPLITS)}")
    if split == "locked":
        require_token(token, "the locked-test panel")
    h = int(cfg.labels.primary_horizon)
    label_cols = panel_label_columns(h)

    available = [c for c in features_model.columns if c not in ("ticker", "date", "eligible")]
    chosen = list(dict.fromkeys(available if features is None else features))
    unknown = [c for c in chosen if c not in available]
    if unknown:
        raise LoaderError(f"Unknown feature column(s) {unknown}; available: {available}")
    missing_labels = [c for c in label_cols if c not in labels.columns]
    if missing_labels:
        raise LoaderError(
            f"labels table lacks the primary-horizon columns {missing_labels}; rebuild labels"
        )

    keys = ["ticker", "date"]
    fm = features_model.loc[:, [*keys, "eligible", *chosen]].copy()
    for name, frame in (("labels", labels), ("universe", universe)):
        if len(frame) != len(fm) or not frame[keys].reset_index(drop=True).equals(
            fm[keys].reset_index(drop=True)
        ):
            raise LoaderError(
                f"{name} and features_model do not have identical (ticker, date) keys; "
                "rebuild with build-universe, build-labels and build-features"
            )
    if not np.array_equal(
        fm["eligible"].to_numpy(dtype=bool), universe["eligible"].to_numpy(dtype=bool)
    ):
        raise LoaderError("features_model.eligible differs from the universe; rebuild features")

    panel = fm
    if labels_wanted:
        lab = labels.loc[:, [*keys, *label_cols]]
        panel = fm.merge(lab, on=keys, how="inner", validate="one_to_one")
        if len(panel) != len(fm):
            raise LoaderError("join of features_model and labels lost rows")
    pos = calendar.dates.get_indexer(pd.DatetimeIndex(panel["date"]))
    if (pos < 0).any():
        raise LoaderError("panel contains a date that is not on the trading calendar")
    panel.insert(2, "t_idx", pos.astype("int32"))
    panel = panel.sort_values(keys, kind="mergesort").reset_index(drop=True)

    if split == "dev":
        panel = panel[panel["t_idx"] < locked_start_idx(cfg, calendar)]
        cap = last_dev_label_idx(cfg, calendar)
    elif split == "tuning":
        cap = tuning_max_idx(cfg, calendar)
        panel = panel[panel["t_idx"] <= cap]
    else:
        cap = None
    panel = panel.reset_index(drop=True)

    if labels_wanted and cap is not None:
        beyond = (panel["t_idx"] > cap).to_numpy()
        if beyond.any():
            for stem in MASKED_STEMS:
                panel.loc[beyond, f"{stem}{h}"] = np.nan
            panel.loc[beyond, f"has_label_h{h}"] = False

    if split != "locked":
        assert_not_locked(panel["t_idx"], cfg, calendar=calendar)
        assert_not_locked(panel["date"], cfg)
    return panel


def load_panel(
    cfg: Config,
    features: Sequence[str] | None,
    split: str,
    labels: bool = True,
    *,
    token: LockedAccessToken | None = None,
    features_file: Path | str | None = None,
    labels_file: Path | str | None = None,
    universe_file: Path | str | None = None,
    calendar_file: Path | str | None = None,
) -> pd.DataFrame:
    """Load the (features, labels) panel for ``split`` in ``{"dev", "tuning", "locked"}``.

    Columns: ``ticker, date, t_idx, eligible``, the requested ``features`` (``None``: every
    feature of ``features.families``), then, if ``labels`` is true, the seven primary-horizon label
    columns (``ret_fwd_h20 ... has_label_h20``). The ``locked`` split raises ``LockedTestError``
    unless ``token`` comes from ``open_locked_test``; nothing is read before that check.
    The ``*_file`` arguments override the default locations (tests).
    """
    if split not in SPLITS:
        raise LoaderError(f"Unknown split {split!r}; valid: {list(SPLITS)}")
    if split == "locked":
        require_token(token, "the locked-test panel")
    cal = TradingCalendar.load(calendar_file)
    return build_panel(
        load_features_model(cfg, features_file),
        load_labels(cfg, labels_file),
        load_universe(cfg, universe_file),
        cal,
        cfg,
        features,
        split,
        labels_wanted=labels,
        token=token,
    )


__all__ = [
    "ID_COLUMNS",
    "LoaderError",
    "SPLITS",
    "build_panel",
    "load_panel",
    "panel_label_columns",
]
