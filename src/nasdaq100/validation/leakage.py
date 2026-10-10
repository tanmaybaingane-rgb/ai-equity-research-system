"""Stage S6: leakage tooling (tests L6, L9, L11 harness).

* ``assert_folds_valid``: structural validity of fold lists (chronology, disjointness, exact
  purge gap for every training and calibration row, stride, dev/locked separation).
* ``poison_future``: copy of a panel whose information dated after ``t_idx`` is destroyed.
* ``null_panel_test``: harness (skeleton, used by S8) that runs a full fit-predict-evaluate
  pipeline on null panels and asserts that no significant skill is found.
* ``SpyEstimator``: wrapper recording the largest ``t_idx`` seen in ``fit`` (S8, L9).
* ``run_leakage_suite``: the ``check-leakage`` CLI runner (``pytest -m leakage``).

Time convention: Part II Section II.2.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from nasdaq100.paths import repo_root
from nasdaq100.validation.folds import DEV, TUNING, Fold, purge_gap


class LeakageError(AssertionError):
    """A fold, panel or pipeline violates a time-safety rule."""


def _fail(fold: Fold, msg: str) -> None:
    raise LeakageError(f"{fold.fold_id}: {msg}")


def assert_folds_valid(
    folds: Sequence[Fold],
    horizon: int,
    embargo_days: int,
    *,
    first_train_idx: int | None = None,
    first_test_idx: int | None = None,
    locked_start_idx: int | None = None,
    train_stride: int | None = None,
) -> None:
    """Raise ``LeakageError`` unless every fold is valid (test L6).

    For every fold: chronological (``max(core) < min(calib) < min(test)``), core / calibration /
    test pairwise disjoint, ``gap == h + 1 + embargo``, ``train_end == t0 - gap - 1``, **every**
    training *and calibration* row satisfies ``t + gap < t0`` (so its label exit ``t + 1 + h`` is
    before ``t0``), the core is purged from the calibration block (``max(core) + gap < min(calib)``),
    the test period is the full contiguous range ``t0 .. t_end`` (never thinned), and the folds
    are ordered with disjoint test periods. Optional: no training row before ``first_train_idx``,
    no test date before ``first_test_idx``, stride alignment, and (``locked_start_idx``) dev and
    tuning folds containing no date at or after the locked start.
    """
    expected_gap = purge_gap(horizon, embargo_days)
    prev_end = None
    for f in folds:
        t0 = f.test_start_idx
        core, calib = list(f.train_core_idx), list(f.calib_idx)
        if not core:
            _fail(f, "empty training core")
        if f.gap != expected_gap:
            _fail(f, f"gap {f.gap} != h + 1 + embargo = {expected_gap}")
        if f.train_end_idx != t0 - expected_gap - 1:
            _fail(f, f"train_end {f.train_end_idx} != t0 - gap - 1 = {t0 - expected_gap - 1}")
        if f.test_end_idx < t0:
            _fail(f, "test period is empty or reversed")
        for name, block in (("core", core), ("calibration", calib)):
            if block != sorted(set(block)):
                _fail(f, f"{name} dates are not strictly increasing")
        if set(core) & set(calib):
            _fail(f, "core and calibration blocks overlap")
        train = core + calib
        if max(train) >= t0 or (set(train) & set(f.test_idx)):
            _fail(f, "training rows overlap or follow the test period")
        if calib and not max(core) < min(calib) < t0:
            _fail(f, "blocks are not chronological (core < calibration < test)")
        worst = max(train)
        if worst + expected_gap >= t0:
            _fail(f, f"training row {worst} violates the gap: {worst} + {expected_gap} >= {t0}")
        if worst + 1 + horizon >= t0:
            _fail(f, f"label exit of training row {worst} is {worst + 1 + horizon} >= {t0}")
        if worst > f.train_end_idx:
            _fail(f, f"training row {worst} is after train_end {f.train_end_idx}")
        if calib and max(core) + expected_gap >= min(calib):
            _fail(f, "core is not purged from the calibration block")
        if first_train_idx is not None and min(train) < first_train_idx:
            _fail(f, f"training row {min(train)} before first_train_idx {first_train_idx}")
        if train_stride is not None and first_train_idx is not None:
            if any((t - first_train_idx) % train_stride for t in train):
                _fail(f, f"training dates do not follow train_stride={train_stride}")
        if first_test_idx is not None and t0 < first_test_idx:
            _fail(f, f"test date {t0} before the first test date {first_test_idx}")
        if locked_start_idx is not None and f.kind in (DEV, TUNING):
            if f.test_end_idx >= locked_start_idx or worst >= locked_start_idx:
                _fail(f, f"{f.kind} fold contains dates at or after the locked start")
        if prev_end is not None and t0 <= prev_end:
            _fail(f, "folds are not chronological with disjoint test periods")
        prev_end = f.test_end_idx


def poison_future(
    panel: pd.DataFrame,
    t_idx: int,
    *,
    keep: Iterable[str] = ("ticker", "date", "t_idx"),
) -> pd.DataFrame:
    """Copy of ``panel`` with all information dated after ``t_idx`` destroyed.

    Rows with ``panel["t_idx"] > t_idx`` keep only the identifier columns ``keep``; every other
    column is replaced: floats and integers by NaN (integer columns become float64), booleans
    (``eligible``, ``has_label_*``) by False, datetimes by NaT, other columns by NaN. Used by the
    feature / label poisoned-future tests. The input is not modified.
    """
    if "t_idx" not in panel.columns:
        raise ValueError("poison_future needs a 't_idx' column")
    keep_set = set(keep)
    out = panel.copy()
    late = (out["t_idx"] > t_idx).to_numpy()
    if not late.any():
        return out
    for col in out.columns:
        if col in keep_set:
            continue
        kind = out[col].dtype.kind
        if kind == "b":
            out.loc[late, col] = False
        elif kind in "iu":
            out[col] = out[col].astype("float64")
            out.loc[late, col] = np.nan
        elif kind == "M":
            out.loc[late, col] = pd.NaT
        else:
            out.loc[late, col] = np.nan
    return out


class SpyEstimator:
    """Wrap an estimator and record the largest ``t_idx`` it is ever fitted on (test L9).

    ``fit(X, y, t_idx=..., **fit_params)`` takes the decision dates of the rows in ``t_idx``
    (or from a ``t_idx`` column / index name of ``X`` when ``t_idx`` is not given), records them,
    and forwards the call without it. Everything else (``predict``, ``predict_proba``, attributes)
    is forwarded to the wrapped estimator.
    """

    def __init__(self, estimator: Any) -> None:
        self.estimator = estimator
        self.fit_calls: list[dict[str, int]] = []

    @staticmethod
    def _split_dates(X: Any, t_idx: Any) -> tuple[Any, np.ndarray]:
        """Return ``(X without a t_idx column, decision dates of its rows)``."""
        if isinstance(X, pd.DataFrame) and "t_idx" in X.columns:
            if t_idx is None:
                t_idx = X["t_idx"]
            X = X.drop(columns=["t_idx"])
        elif t_idx is None and isinstance(X, pd.DataFrame) and X.index.name == "t_idx":
            t_idx = X.index
        if t_idx is None:
            raise ValueError("SpyEstimator.fit needs t_idx (argument, X column or index name)")
        arr = np.asarray(t_idx)
        if arr.size == 0:
            raise ValueError("SpyEstimator.fit received no rows")
        return X, arr

    def fit(self, X: Any, y: Any = None, *args: Any, t_idx: Any = None, **kwargs: Any):
        X, arr = self._split_dates(X, t_idx)
        self.fit_calls.append(
            {"n_rows": int(arr.size), "min_t_idx": int(arr.min()), "max_t_idx": int(arr.max())}
        )
        self.estimator.fit(X, y, *args, **kwargs)
        return self

    @property
    def max_t_idx_seen(self) -> int | None:
        """Largest ``t_idx`` of any row passed to ``fit`` so far (``None`` before the first fit)."""
        return max((c["max_t_idx"] for c in self.fit_calls), default=None)

    def assert_max_t_idx(self, limit: int) -> None:
        """Raise ``LeakageError`` if any ``fit`` saw a row with ``t_idx`` above ``limit``."""
        seen = self.max_t_idx_seen
        if seen is not None and seen > limit:
            raise LeakageError(f"estimator was fitted on t_idx {seen} > allowed maximum {limit}")

    def __getattr__(self, name: str) -> Any:
        if name in ("estimator", "fit_calls"):
            raise AttributeError(name)
        return getattr(self.estimator, name)


def _extract(result: Any) -> tuple[np.ndarray, float | None]:
    if isinstance(result, Mapping):
        ic, auc = result["ic_by_date"], result.get("auc")
    else:
        ic, auc = result.ic_by_date, getattr(result, "auc", None)
    arr = np.asarray(ic, dtype="float64")
    arr = arr[np.isfinite(arr)]
    return arr, (None if auc is None else float(auc))


def null_panel_test(
    pipeline_fn: Callable[[pd.DataFrame, int], Any],
    seeds: Sequence[int] = tuple(range(10)),
    panel_factory: Callable[[int], pd.DataFrame] | None = None,
    *,
    min_seeds: int = 10,
    se_multiple: float = 2.5,
    t_threshold: float = 2.0,
    max_extreme_runs: int | None = None,
    auc_tolerance: float = 0.02,
) -> dict[str, float]:
    """Skeleton harness for the null-panel test (L11; wired to the real pipeline in S8).

    For every seed, ``panel = panel_factory(seed)`` (default: ``make_null_panel`` of the test
    fixtures: features and labels with no relationship) and ``pipeline_fn(panel, seed)`` runs the
    *full* fit-predict-evaluate pipeline. It returns a mapping or object with ``ic_by_date`` (the
    non-overlapping per-date rank ICs) and optionally ``auc``. The harness asserts:

    * pooled mean IC within ``se_multiple`` standard errors of zero;
    * at most ``max_extreme_runs`` (default: 20% of the seeds, i.e. 2 of 10) runs with
      ``|t| > t_threshold``;
    * if AUCs are reported: their mean within ``auc_tolerance`` of 0.5.

    Failure raises ``LeakageError``: skill on data without signal means leakage. Returns the
    summary statistics.
    """
    seeds = list(seeds)
    if len(seeds) < min_seeds:
        raise ValueError(f"null_panel_test needs at least {min_seeds} seeds, got {len(seeds)}")
    if panel_factory is None:
        try:
            from tests.fixtures.toy_data import make_null_panel
        except ImportError as e:  # pragma: no cover - only without the test fixtures
            raise ValueError("pass panel_factory (test fixtures are not importable)") from e
        panel_factory = make_null_panel

    all_ic: list[np.ndarray] = []
    t_stats: list[float] = []
    aucs: list[float] = []
    for seed in seeds:
        ic, auc = _extract(pipeline_fn(panel_factory(seed), seed))
        if len(ic) < 2 or float(np.std(ic, ddof=1)) == 0.0:
            raise ValueError(f"seed {seed}: need at least 2 non-constant ICs")
        all_ic.append(ic)
        t_stats.append(float(ic.mean() / (ic.std(ddof=1) / np.sqrt(len(ic)))))
        if auc is not None:
            aucs.append(auc)

    pooled = np.concatenate(all_ic)
    mean_ic = float(pooled.mean())
    se = float(pooled.std(ddof=1) / np.sqrt(len(pooled)))
    n_extreme = int(sum(abs(t) > t_threshold for t in t_stats))
    allowed = int(0.2 * len(seeds)) if max_extreme_runs is None else max_extreme_runs
    summary = {"mean_ic": mean_ic, "se": se, "n_extreme_runs": float(n_extreme),
               "n_seeds": float(len(seeds))}
    if abs(mean_ic) > se_multiple * se:
        raise LeakageError(
            f"null panel: mean IC {mean_ic:.4f} is beyond {se_multiple} SE ({se:.4f}); leakage?"
        )
    if n_extreme > allowed:
        raise LeakageError(
            f"null panel: {n_extreme} of {len(seeds)} runs have |t| > {t_threshold} "
            f"(allowed {allowed}); leakage?"
        )
    if aucs:
        mean_auc = float(np.mean(aucs))
        summary["mean_auc"] = mean_auc
        if abs(mean_auc - 0.5) > auc_tolerance:
            raise LeakageError(
                f"null panel: mean AUC {mean_auc:.4f} differs from 0.5 by more than "
                f"{auc_tolerance}; leakage?"
            )
    return summary


def run_leakage_suite(extra_args: Sequence[str] = ()) -> int:
    """Run the leakage-marked tests (``pytest -m leakage``) from the repository root.

    Returns pytest's exit code (0: all passed). Used by the ``check-leakage`` command.
    """
    cmd = [sys.executable, "-m", "pytest", "-m", "leakage", "-q", "-p", "no:cacheprovider",
           *extra_args]
    return subprocess.run(cmd, cwd=repo_root(), check=False).returncode
