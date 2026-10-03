"""Unit tests for synthetic toy data generators."""

import numpy as np
import pandas as pd
import pytest

from tests.fixtures.toy_data import (
    make_null_panel,
    make_planted_signal_panel,
    make_toy_prices,
)


@pytest.mark.unit
def test_toy_prices_determinism() -> None:
    """Verify make_toy_prices produces bit-for-bit identical results for the same seed."""
    df1 = make_toy_prices(n_tickers=4, n_days=50, seed=42)
    df2 = make_toy_prices(n_tickers=4, n_days=50, seed=42)
    pd.testing.assert_frame_equal(df1, df2)

    df3 = make_toy_prices(n_tickers=4, n_days=50, seed=99)
    assert not df1["Close"].equals(df3["Close"])


@pytest.mark.unit
def test_toy_prices_schema_and_quirks() -> None:
    """Verify toy prices match raw schema and include low-price tick noise, illiquid ticker, and dividends."""
    df = make_toy_prices(n_tickers=5, n_days=60, seed=42)
    expected_cols = ["Ticker", "Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    assert list(df.columns) == expected_cols

    # Illiquid ticker present with zero volumes
    assert "AZN" in df["Ticker"].values
    azn_df = df[df["Ticker"] == "AZN"]
    assert (azn_df["Volume"] == 0).sum() > 0

    # Low prices (< 5.0) are quantized to 2 decimals
    tk1_df = df[df["Ticker"] == "TK01"]
    assert (tk1_df["Close"] < 5.0).sum() > 0
    decimals = (tk1_df["Close"] * 100).round() - (tk1_df["Close"] * 100)
    assert np.allclose(decimals, 0.0)

    # Special dividend event: Close drops while Adj Close does not
    tk2_df = df[df["Ticker"] == "TK02"].reset_index(drop=True)
    # TK02 starts at d_idx=15, so the dividend at d_idx=40
    # appears at row 25 after resetting the index.
    if len(tk2_df) > 25:
     close_ret = tk2_df["Close"].iloc[25] / tk2_df["Close"].iloc[24] - 1.0
     adj_ret = tk2_df["Adj Close"].iloc[25] / tk2_df["Adj Close"].iloc[24] - 1.0

    # Dividend event caused Close to drop significantly more than Adj Close.
    assert close_ret < adj_ret


@pytest.mark.unit
def test_planted_and_null_panels_determinism_and_shapes() -> None:
    """Verify planted and null panel generators produce valid deterministic panels."""
    p1 = make_planted_signal_panel(seed=42, n_tickers=5, n_days=30)
    p2 = make_planted_signal_panel(seed=42, n_tickers=5, n_days=30)
    pd.testing.assert_frame_equal(p1, p2)

    n1 = make_null_panel(seed=42, n_tickers=5, n_days=30)
    n2 = make_null_panel(seed=42, n_tickers=5, n_days=30)
    pd.testing.assert_frame_equal(n1, n2)

    expected_cols = [
        "ticker",
        "date",
        "t_idx",
        "eligible",
        "feature_1",
        "feature_2",
        "ret_fwd_h20",
        "excess_h20",
        "y_reg_h20",
        "y_cls_h20",
        "has_label_h20",
    ]
    for col in expected_cols:
        assert col in p1.columns
        assert col in n1.columns
