"""Stage S5: feature registry (decision D7).

Every feature is registered with its name, family, lookback (window length in trading days), the
columns it needs and the other features it builds on. ``features.families`` selects which are
built (ablation switch). The registry provides the ordered name lists used by models:
``STOCK_FEATURES`` (18, normalised per date) and ``MARKET_FEATURES`` (6, copied raw).

Definitions (all use data up to and including the decision date ``t``; windows are trading
observations per ticker, a feature is NaN unless its full window is available; ``logret`` is
``logret_cc``) are documented in ``docs/data_dictionary.md`` and implemented in
``stock_features.py`` / ``market_features.py``.

Never registered (decision D7, Part IV Section IV.3): absolute price levels, calendar or
seasonality features, and oscillators (RSI, MACD, Bollinger, ATR; ablation only, Advanced A6).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

STOCK = "stock"
MARKET = "market"
#: ``features.families`` values, in registry order.
FAMILIES: tuple[str, ...] = ("momentum", "volatility", "trend", "liquidity", "market")


class FeatureError(Exception):
    """Invalid inputs or configuration for the feature builders."""


@dataclass(frozen=True)
class FeatureSpec:
    """One registered feature.

    ``lookback`` is the window length in trading days. ``warmup`` is the number of leading
    NaN rows of the series the feature is computed on: per ticker for stock-level features, and
    counted from the first date on which the market series is defined (the first date after
    which any name was eligible) for market-level ones. ``inputs`` are the columns of
    ``adjusted_prices`` (or of the market series) the feature reads, ``depends_on`` other features
    it is built from.
    """

    name: str
    family: str
    level: str
    lookback: int
    warmup: int
    inputs: tuple[str, ...]
    depends_on: tuple[str, ...] = ()


def _s(
    name: str,
    family: str,
    lookback: int,
    warmup: int,
    inputs: tuple[str, ...],
    depends_on: tuple[str, ...] = (),
) -> FeatureSpec:
    return FeatureSpec(name, family, STOCK, lookback, warmup, inputs, depends_on)


def _m(
    name: str,
    lookback: int,
    warmup: int,
    inputs: tuple[str, ...],
    depends_on: tuple[str, ...] = (),
) -> FeatureSpec:
    return FeatureSpec(name, "market", MARKET, lookback, warmup, inputs, depends_on)


#: All 24 MVP features in their canonical order (Part III S5 table).
FEATURES: tuple[FeatureSpec, ...] = (
    # momentum
    _s("ret_5", "momentum", 5, 5, ("adj_close",)),
    _s("ret_21", "momentum", 21, 21, ("adj_close",)),
    _s("ret_63", "momentum", 63, 63, ("adj_close",)),
    _s("ret_126", "momentum", 126, 126, ("adj_close",)),
    _s("ret_252", "momentum", 252, 252, ("adj_close",)),
    _s("mom_12_1", "momentum", 252, 252, ("adj_close",)),
    # volatility
    _s("vol_21", "volatility", 21, 21, ("logret_cc",)),
    _s("vol_63", "volatility", 63, 63, ("logret_cc",)),
    _s("downvol_63", "volatility", 63, 63, ("logret_cc",)),
    _s("vol_ratio_21_63", "volatility", 63, 63, ("logret_cc",), ("vol_21", "vol_63")),
    _s("parkinson_21", "volatility", 21, 20, ("adj_high", "adj_low")),
    _s("beta_126", "volatility", 126, 126, ("logret_cc", "mkt_logret")),
    # trend
    _s("px_sma_50", "trend", 50, 49, ("adj_close",)),
    _s("px_sma_200", "trend", 200, 199, ("adj_close",)),
    _s("dist_52w_high", "trend", 252, 251, ("adj_close",)),
    # liquidity
    _s("log_dvol_63", "liquidity", 63, 62, ("dollar_volume",)),
    _s("rel_dvol_21_63", "liquidity", 63, 62, ("dollar_volume",)),
    _s("amihud_63", "liquidity", 63, 63, ("logret_cc", "dollar_volume")),
    # market (date-level; identical for every ticker on a date)
    _m("mkt_ret_21", 21, 20, ("mkt_logret",)),
    _m("mkt_ret_63", 63, 62, ("mkt_logret",)),
    _m("mkt_vol_21", 21, 20, ("mkt_logret",)),
    _m("mkt_trend_200", 200, 199, ("mkt_index",)),
    _m("mkt_breadth_50", 50, 0, ("eligible",), ("px_sma_50",)),
    _m("xs_disp_21", 21, 0, ("eligible",), ("ret_21",)),
)

STOCK_FEATURES: tuple[str, ...] = tuple(f.name for f in FEATURES if f.level == STOCK)
MARKET_FEATURES: tuple[str, ...] = tuple(f.name for f in FEATURES if f.level == MARKET)
ALL_FEATURES: tuple[str, ...] = STOCK_FEATURES + MARKET_FEATURES
_BY_NAME: dict[str, FeatureSpec] = {f.name: f for f in FEATURES}


def get_spec(name: str) -> FeatureSpec:
    """Return the registry entry of ``name`` (``FeatureError`` if it is not registered)."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise FeatureError(f"Unknown feature {name!r}") from None


def check_families(families: Iterable[str]) -> tuple[str, ...]:
    """Validate ``features.families`` and return it in registry order (no duplicates)."""
    fam = list(families)
    unknown = sorted(set(fam) - set(FAMILIES))
    if unknown:
        raise FeatureError(f"Unknown feature families {unknown}; valid: {list(FAMILIES)}")
    if not fam:
        raise FeatureError("features.families is empty")
    return tuple(f for f in FAMILIES if f in set(fam))


def selected_features(families: Iterable[str], level: str | None = None) -> tuple[str, ...]:
    """Ordered names of the features of the selected ``families`` (optionally one level)."""
    chosen = set(check_families(families))
    return tuple(
        f.name
        for f in FEATURES
        if f.family in chosen and (level is None or f.level == level)
    )


def required_stock_features(names: Iterable[str]) -> tuple[str, ...]:
    """Stock-level features that must be computed to build ``names`` (transitive closure).

    Market features ``mkt_breadth_50`` and ``xs_disp_21`` read ``px_sma_50`` and ``ret_21`` even
    when the trend / momentum families are switched off; ``vol_ratio_21_63`` reads ``vol_21`` and
    ``vol_63``. Output order is the registry order.
    """
    needed: set[str] = set()
    stack = list(names)
    while stack:
        spec = get_spec(stack.pop())
        if spec.level == STOCK and spec.name not in needed:
            needed.add(spec.name)
        stack.extend(d for d in spec.depends_on if d not in needed)
    return tuple(n for n in STOCK_FEATURES if n in needed)
