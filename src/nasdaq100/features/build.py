"""Stage S5: orchestration of the feature pipeline and the on-disk tables.

``build_features`` is pure (tables in, tables out); ``run_build_features`` reads
``adjusted_prices.parquet`` (S3) and ``universe.parquet`` (S2) and writes, per ``project.variant``:

* ``market_series.parquet``  : ``date, mkt_logret, mkt_index, n_eligible``
* ``features_raw.parquet``   : ``ticker, date, eligible`` + raw stock-level + market-level features
* ``features_model.parquet`` : ``ticker, date, eligible`` + per-date winsorised and rank-gaussed
  stock-level features + the market-level features (raw)

Only the families in ``features.families`` are written (registry order). Rows are never dropped.
Later stages read the tables through ``load_features_raw`` / ``load_features_model`` /
``load_market_series``. Locked-test masking (D19) belongs to S6/S16.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import numpy as np
import pandas as pd

from nasdaq100.data.adjust import load_adjusted
from nasdaq100.data.ingest import read_manifest
from nasdaq100.data.universe import load_universe
from nasdaq100.features.market_features import (
    MARKET_SERIES_COLUMNS,
    build_market_series,
    compute_market_features,
)
from nasdaq100.features.normalize import check_winsor, rank_gauss_per_date
from nasdaq100.features.registry import (
    FeatureError,
    check_families,
    required_stock_features,
    selected_features,
)
from nasdaq100.features.stock_features import compute_stock_features
from nasdaq100.paths import (
    features_model_path,
    features_raw_path,
    manifest_path,
    market_series_path,
)
from nasdaq100.utils.io import read_parquet, write_parquet
from nasdaq100.utils.logging import get_logger

if TYPE_CHECKING:
    from nasdaq100.config import Config

logger = get_logger("features.build")

KEY_COLUMNS: tuple[str, ...] = ("ticker", "date")
ID_COLUMNS: tuple[str, ...] = ("ticker", "date", "eligible")
ADJUSTED_INPUT_COLUMNS: tuple[str, ...] = (
    "ticker",
    "date",
    "t_idx",
    "adj_high",
    "adj_low",
    "adj_close",
    "dollar_volume",
    "logret_cc",
)
UNIVERSE_INPUT_COLUMNS: tuple[str, ...] = ("ticker", "date", "eligible")
PRICE_INPUTS: tuple[str, ...] = ("adj_high", "adj_low", "adj_close")


class FeatureTables(NamedTuple):
    """The three S5 tables."""

    market_series: pd.DataFrame
    features_raw: pd.DataFrame
    features_model: pd.DataFrame


def feature_columns(families: list[str] | tuple[str, ...]) -> list[str]:
    """Feature columns written for ``families`` (stock-level first, then market-level)."""
    return [
        *selected_features(families, "stock"),
        *selected_features(families, "market"),
    ]


def _check_inputs(adjusted: pd.DataFrame, universe: pd.DataFrame) -> None:
    for name, frame, cols in (
        ("adjusted prices", adjusted, ADJUSTED_INPUT_COLUMNS),
        ("universe", universe, UNIVERSE_INPUT_COLUMNS),
    ):
        missing = [c for c in cols if c not in frame.columns]
        if missing:
            raise FeatureError(f"{name} table is missing columns: {missing}")
        if len(frame) == 0:
            raise FeatureError(f"{name} table is empty")
        if frame.duplicated(list(KEY_COLUMNS)).any():
            raise FeatureError(f"{name} table has duplicate (ticker, date) rows")
    for col in (*PRICE_INPUTS, "dollar_volume", "t_idx"):
        if adjusted[col].isna().any():
            raise FeatureError(f"adjusted prices contain NaN in {col!r}")
    for col in PRICE_INPUTS:
        if not (adjusted[col].to_numpy(dtype="float64") > 0).all():
            raise FeatureError(f"adjusted prices contain non-positive {col!r}")
    if not (adjusted["dollar_volume"].to_numpy(dtype="float64") >= 0).all():
        raise FeatureError("adjusted prices contain negative dollar_volume")
    if np.isinf(adjusted["logret_cc"].to_numpy(dtype="float64")).any():
        raise FeatureError("adjusted prices contain infinite logret_cc")
    if universe["eligible"].isna().any():
        raise FeatureError("universe contains NaN in 'eligible'")


def build_features(
    adjusted: pd.DataFrame, universe: pd.DataFrame, features_cfg: object
) -> FeatureTables:
    """Build the market series, raw features and model-input features.

    ``features_cfg`` is ``cfg.features`` (``families``, ``winsor_pct``). The row set equals the
    adjusted table's and must equal the universe's. The result is sorted by (ticker, date).
    Raises ``FeatureError`` on invalid input or configuration, on a key mismatch between the
    two tables, or when ``t_idx`` is not consecutive within a ticker (trailing windows are only
    valid under that contiguity).
    """
    families = check_families(features_cfg.families)  # type: ignore[attr-defined]
    winsor = check_winsor(features_cfg.winsor_pct)  # type: ignore[attr-defined]
    _check_inputs(adjusted, universe)

    df = adjusted.loc[:, list(ADJUSTED_INPUT_COLUMNS)].copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df = df.sort_values(list(KEY_COLUMNS), kind="mergesort").reset_index(drop=True)
    uni = universe.loc[:, list(UNIVERSE_INPUT_COLUMNS)].copy()
    uni["date"] = pd.to_datetime(uni["date"]).astype("datetime64[ns]")
    uni = uni.sort_values(list(KEY_COLUMNS), kind="mergesort").reset_index(drop=True)
    if len(df) != len(uni) or not df[list(KEY_COLUMNS)].equals(uni[list(KEY_COLUMNS)]):
        raise FeatureError(
            "adjusted prices and universe do not have identical (ticker, date) keys "
            f"({len(df)} vs {len(uni)} rows); rebuild with build-adjusted and build-universe"
        )
    df["eligible"] = uni["eligible"].to_numpy(dtype=bool)

    step = df.groupby("ticker", sort=False)["t_idx"].diff()
    bad = step.notna() & (step != 1)
    if bad.any():
        row = df.loc[bad].iloc[0]
        raise FeatureError(
            f"t_idx is not consecutive within ticker {row['ticker']} at {row['date'].date()}; "
            "trailing windows would not be trading-day windows"
        )
    first = ~df.duplicated("ticker")
    if df.loc[~first, "logret_cc"].isna().any():
        raise FeatureError("logret_cc is NaN on a row that is not the first row of its ticker")

    market = build_market_series(df)
    df["mkt_logret"] = df["date"].map(market.set_index("date")["mkt_logret"]).astype("float64")

    stock_names = selected_features(families, "stock")
    market_names = selected_features(families, "market")
    needed = required_stock_features([*stock_names, *market_names])
    stock = compute_stock_features(df, needed)

    out_raw = df.loc[:, list(ID_COLUMNS)].copy()
    for name in stock_names:
        out_raw[name] = stock[name].to_numpy()
    if market_names:
        ctx = df.loc[:, ["date", "eligible"]].join(stock)
        mfeat = compute_market_features(market, ctx, market_names)
        for name in market_names:
            out_raw[name] = df["date"].map(mfeat[name]).to_numpy(dtype="float64")

    out_model = df.loc[:, list(ID_COLUMNS)].copy()
    if stock_names:
        z = rank_gauss_per_date(
            out_raw[list(stock_names)], df["date"], df["eligible"], list(winsor)
        )
        for name in stock_names:
            out_model[name] = z[name].to_numpy()
    for name in market_names:
        out_model[name] = out_raw[name].to_numpy()

    if np.isinf(out_raw[feature_columns(families)].to_numpy(dtype="float64")).any():
        raise FeatureError("internal error: infinite feature values")  # pragma: no cover
    return FeatureTables(market, out_raw.reset_index(drop=True), out_model.reset_index(drop=True))


def run_build_features(
    cfg: Config,
    *,
    adjusted_file: Path | str | None = None,
    universe_file: Path | str | None = None,
    market_file: Path | str | None = None,
    raw_file: Path | str | None = None,
    model_file: Path | str | None = None,
) -> FeatureTables:
    """Build and write the three S5 tables for ``cfg.project.variant``.

    Requires ``adjusted_prices.parquet`` (S3) and ``universe.parquet`` (S2) of the same variant.
    Missing inputs raise ``FileNotFoundError`` naming the command that produces them.
    """
    adjusted = load_adjusted(cfg, adjusted_file)
    universe = load_universe(cfg, universe_file)
    tables = build_features(adjusted, universe, cfg.features)
    variant = cfg.project.variant
    paths = {
        "market_series": Path(market_file) if market_file else market_series_path(variant),
        "features_raw": Path(raw_file) if raw_file else features_raw_path(variant),
        "features_model": Path(model_file) if model_file else features_model_path(variant),
    }
    write_parquet(tables.market_series, paths["market_series"], sort_keys=("date",))
    write_parquet(tables.features_raw, paths["features_raw"])
    write_parquet(tables.features_model, paths["features_model"])

    try:
        data_hash = read_manifest(manifest_path())["sha256"]
    except (FileNotFoundError, ValueError):
        data_hash = "unknown"
    cols = feature_columns(list(cfg.features.families))
    elig = tables.features_model["eligible"].to_numpy()
    logger.info(
        "Features [variant=%s, data hash %s]: %d rows, %d features (%s), %d eligible rows, "
        "%d market-series dates -> %s",
        variant,
        str(data_hash)[:12],
        len(tables.features_raw),
        len(cols),
        ", ".join(check_families(cfg.features.families)),
        int(elig.sum()),
        len(tables.market_series),
        paths["features_model"].name,
    )
    return tables


def _load(cfg: Config, path: Path | str | None, default: Path, expected: list[str]) -> pd.DataFrame:
    p = Path(path) if path is not None else default
    if not p.is_file():
        raise FileNotFoundError(
            f"{p.name} not found for variant {cfg.project.variant!r}: {p}. "
            "Run `python -m nasdaq100.cli build-features`."
        )
    df = read_parquet(p)
    if list(df.columns) != expected:
        raise FeatureError(f"{p.name}: columns {list(df.columns)} != expected {expected}")
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df


def load_features_raw(cfg: Config, path: Path | str | None = None) -> pd.DataFrame:
    """Return ``features_raw`` for ``cfg.project.variant`` (columns follow ``families``)."""
    cols = [*ID_COLUMNS, *feature_columns(cfg.features.families)]
    return _load(cfg, path, features_raw_path(cfg.project.variant), cols)


def load_features_model(cfg: Config, path: Path | str | None = None) -> pd.DataFrame:
    """Return ``features_model`` for ``cfg.project.variant`` (columns follow ``families``)."""
    cols = [*ID_COLUMNS, *feature_columns(cfg.features.families)]
    return _load(cfg, path, features_model_path(cfg.project.variant), cols)


def load_market_series(cfg: Config, path: Path | str | None = None) -> pd.DataFrame:
    """Return the market series for ``cfg.project.variant``."""
    return _load(cfg, path, market_series_path(cfg.project.variant), list(MARKET_SERIES_COLUMNS))
