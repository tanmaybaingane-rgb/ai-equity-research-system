"""Synthetic silver tables and configs for S2 tests (security master and universe).

Built on the clean S1 generator (no flag triggers), with volumes large enough that the liquidity
rule passes (about $10-20M traded per day), so each test can break exactly one rule.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nasdaq100.config import Config, UniverseConfig, load_config
from nasdaq100.data.flags import add_flags
from nasdaq100.data.security_master import build_security_master
from tests.fixtures.s1_prices import make_clean_raw_prices, to_bronze


def make_silver(
    tickers: tuple[str, ...] = ("AAA", "BBB"),
    n_days: int = 300,
    start_offsets: dict[str, int] | None = None,
    seed: int = 11,
) -> pd.DataFrame:
    """Silver table (bronze + n_obs + flags) with liquid, clean, >= $5 prices."""
    raw = make_clean_raw_prices(tickers, n_days=n_days, start_offsets=start_offsets, seed=seed)
    rng = np.random.default_rng(seed + 1)
    raw["Volume"] = rng.integers(200_000, 400_000, size=len(raw)).astype("int64")
    return add_flags(to_bronze(raw), load_config().flags)


def make_curated(rows: list[dict] | None = None) -> pd.DataFrame:
    """Curated exceptions frame (columns as in the real file); empty by default."""
    cols = ["ticker", "issuer_id", "share_class", "exclusion_reason", "stitching_suspect", "notes"]
    base = pd.DataFrame(rows or [], columns=cols)
    for c in ("issuer_id", "share_class", "exclusion_reason", "notes"):
        base[c] = base[c].fillna("").astype(str)
    base["stitching_suspect"] = base["stitching_suspect"].fillna(False).map(
        lambda v: "true" if v is True or str(v).lower() == "true" else "false"
    )
    return base


def make_master(silver: pd.DataFrame, curated: pd.DataFrame | None = None) -> pd.DataFrame:
    """Security master for ``silver`` using the default 5% zero-volume quality limit."""
    return build_security_master(
        silver,
        make_curated() if curated is None else curated,
        load_config().flags.max_zero_volume_share_ticker,
    )


def universe_cfg(*overrides: str) -> UniverseConfig:
    """``cfg.universe`` with ``section.key=value`` overrides, e.g. ``universe.min_close=10``."""
    return load_config(overrides=list(overrides)).universe


def cfg_with(*overrides: str) -> Config:
    """Full config with overrides."""
    return load_config(overrides=list(overrides))
