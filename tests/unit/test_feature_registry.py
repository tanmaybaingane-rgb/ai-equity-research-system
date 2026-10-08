"""Unit tests for the S5 feature registry (``features/registry.py``)."""

from __future__ import annotations

import pytest

from nasdaq100.features import registry as reg
from nasdaq100.features.registry import (
    ALL_FEATURES,
    FAMILIES,
    FEATURES,
    MARKET_FEATURES,
    STOCK_FEATURES,
    FeatureError,
    check_families,
    get_spec,
    required_stock_features,
    selected_features,
)

GUIDE_STOCK = (
    "ret_5 ret_21 ret_63 ret_126 ret_252 mom_12_1 "
    "vol_21 vol_63 downvol_63 vol_ratio_21_63 parkinson_21 beta_126 "
    "px_sma_50 px_sma_200 dist_52w_high "
    "log_dvol_63 rel_dvol_21_63 amihud_63"
).split()
GUIDE_MARKET = "mkt_ret_21 mkt_ret_63 mkt_vol_21 mkt_trend_200 mkt_breadth_50 xs_disp_21".split()


@pytest.mark.unit
def test_registry_holds_exactly_the_24_mvp_features_in_guide_order() -> None:
    assert list(STOCK_FEATURES) == GUIDE_STOCK and len(STOCK_FEATURES) == 18
    assert list(MARKET_FEATURES) == GUIDE_MARKET and len(MARKET_FEATURES) == 6
    assert ALL_FEATURES == STOCK_FEATURES + MARKET_FEATURES and len(set(ALL_FEATURES)) == 24
    assert FAMILIES == ("momentum", "volatility", "trend", "liquidity", "market")
    fam_counts = {f: sum(s.family == f for s in FEATURES) for f in FAMILIES}
    assert fam_counts == {"momentum": 6, "volatility": 6, "trend": 3, "liquidity": 3, "market": 6}
    assert all((s.level == "market") == (s.family == "market") for s in FEATURES)


@pytest.mark.unit
def test_specs_are_consistent() -> None:
    names = set(ALL_FEATURES)
    for s in FEATURES:
        assert s.lookback >= 1 and 0 <= s.warmup <= s.lookback + 1
        assert s.inputs and set(s.depends_on) <= names
        assert get_spec(s.name) is s
    # no absolute price-level, calendar or oscillator features (D7, section IV.3)
    banned = {"rsi", "macd", "boll", "bollinger", "atr", "dow", "weekday", "month", "year",
              "season", "price", "level", "close", "open"}
    assert not [n for n in ALL_FEATURES if banned & set(n.split("_"))]
    # only adjusted series and the market series are ever read (D3): no raw close/open/volume
    used = {c for s in FEATURES for c in s.inputs}
    assert used <= {"adj_close", "adj_high", "adj_low", "logret_cc", "dollar_volume",
                    "mkt_logret", "mkt_index", "eligible"}
    with pytest.raises(FeatureError, match="Unknown feature"):
        get_spec("rsi_14")


@pytest.mark.unit
def test_family_selection_is_ordered_and_validated() -> None:
    assert check_families(["market", "momentum"]) == ("momentum", "market")  # registry order
    assert check_families(["trend", "trend"]) == ("trend",)
    assert selected_features(FAMILIES) == ALL_FEATURES
    assert selected_features(["trend", "liquidity"]) == (
        "px_sma_50", "px_sma_200", "dist_52w_high", "log_dvol_63", "rel_dvol_21_63", "amihud_63",
    )
    assert selected_features(["momentum", "market"], "stock") == STOCK_FEATURES[:6]
    assert selected_features(["momentum", "market"], "market") == MARKET_FEATURES
    assert selected_features(["volatility"], "market") == ()
    with pytest.raises(FeatureError, match="Unknown feature families"):
        check_families(["momentum", "sentiment"])
    with pytest.raises(FeatureError, match="empty"):
        check_families([])


@pytest.mark.unit
def test_required_stock_features_closure() -> None:
    # market breadth and dispersion read px_sma_50 / ret_21 even if trend / momentum are off
    assert required_stock_features(["mkt_breadth_50", "xs_disp_21"]) == ("ret_21", "px_sma_50")
    assert required_stock_features(["mkt_ret_21"]) == ()
    assert required_stock_features(["vol_ratio_21_63"]) == (
        "vol_21", "vol_63", "vol_ratio_21_63",
    )
    assert required_stock_features(ALL_FEATURES) == STOCK_FEATURES
    assert reg.STOCK == "stock" and reg.MARKET == "market"
