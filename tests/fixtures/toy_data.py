"""Deterministic toy data generators for unit tests, pipeline checks, and leakage testing.

Adheres strictly to Part II Section II.7 and Stage S0 specification.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_toy_prices(
    n_tickers: int = 5,
    n_days: int = 100,
    seed: int = 42,
    add_tick_noise: bool = True,
    add_special_dividend: bool = True,
    add_illiquid: bool = True,
    staggered_listing: bool = True,
) -> pd.DataFrame:
    """Generate synthetic long-format price table matching the raw CSV schema.

    Schema: ['Ticker', 'Date', 'Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
    Can reproduce real data quirks:
    - 2-decimal rounding of low prices (tick noise)
    - Special-dividend event (Close drops, Adj Close does not)
    - Staggered listing dates (growing universe)
    - One illiquid ticker with zero volumes
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start="2015-01-05", periods=n_days)

    tickers = [f"TK{i:02d}" for i in range(1, n_tickers + 1)]
    if add_illiquid and n_tickers > 1:
        tickers[-1] = "AZN"

    rows: list[dict] = []

    for t_idx, ticker in enumerate(tickers):
        # Staggered listing: later tickers enter later
        start_day = 0
        if staggered_listing and t_idx > 0:
            start_day = min(t_idx * 15, n_days - 20)

        # Baseline price level
        if add_tick_noise and t_idx == 0:
            price_level = 0.50  # Low price to induce tick quantization
        else:
            price_level = 50.0 + t_idx * 20.0

        daily_returns = rng.normal(loc=0.0005, scale=0.02, size=n_days)
        prices = price_level * np.exp(np.cumsum(daily_returns))

        adj_factor = 1.0

        for d_idx in range(start_day, n_days):
            current_date = dates[d_idx]
            close_val = prices[d_idx]

            # Special dividend event: Close drops, Adj Close stays smooth
            if add_special_dividend and ticker == tickers[1] and d_idx == 40:
                pre_dividend_close = close_val
                close_val = pre_dividend_close * 0.70
                adj_factor *= pre_dividend_close / close_val
            else:
                close_val = prices[d_idx]
                adj_close_val = close_val * adj_factor

            # Quantization: round to 2 decimals
            close_val = np.round(close_val, 2)
            adj_close_val = np.round(adj_close_val, 2)

            # Generate OHLC
            spread = max(0.02, close_val * 0.01)
            open_val = np.round(close_val + rng.uniform(-spread, spread), 2)
            high_val = np.round(max(open_val, close_val) + abs(rng.uniform(0, spread)), 2)
            low_val = np.round(min(open_val, close_val) - abs(rng.uniform(0, spread)), 2)

            # Volume
            if ticker == "AZN" and add_illiquid:
                # Illiquid: 80% zero volume
                volume_val = 0 if rng.random() < 0.8 else int(rng.integers(100, 1000))
            else:
                volume_val = int(rng.integers(500_000, 5_000_000))

            rows.append({
                "Ticker": ticker,
                "Date": current_date.strftime("%Y-%m-%d"),
                "Open": float(open_val),
                "High": float(high_val),
                "Low": float(low_val),
                "Close": float(close_val),
                "Adj Close": float(adj_close_val),
                "Volume": int(volume_val),
            })

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(by=["Ticker", "Date"]).reset_index(drop=True)
    return df


def make_planted_signal_panel(
    seed: int = 42,
    signal_strength: float = 0.5,
    n_tickers: int = 20,
    n_days: int = 150,
) -> pd.DataFrame:
    """Generate synthetic panel where forward return has a planted linear relationship with feature_1.

    Used to verify that the modeling pipeline can discover genuine signal.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start="2016-01-04", periods=n_days)
    tickers = [f"TK{i:02d}" for i in range(1, n_tickers + 1)]

    records: list[dict] = []
    for d_idx, dt in enumerate(dates):
        # Draw features for this date
        f1 = rng.normal(0, 1, size=n_tickers)
        f2 = rng.normal(0, 1, size=n_tickers)
        noise = rng.normal(0, 0.5, size=n_tickers)

        # Planted forward return: signal_strength * f1 + noise
        raw_fwd_ret = signal_strength * f1 + noise

        # Cross-sectional excess return
        excess = raw_fwd_ret - np.mean(raw_fwd_ret)

        for i, ticker in enumerate(tickers):
            records.append({
                "ticker": ticker,
                "date": dt,
                "t_idx": d_idx,
                "eligible": True,
                "feature_1": float(f1[i]),
                "feature_2": float(f2[i]),
                "ret_fwd_h20": float(raw_fwd_ret[i]),
                "excess_h20": float(excess[i]),
                "y_reg_h20": float(excess[i]),
                "y_cls_h20": int(excess[i] > 0),
                "has_label_h20": d_idx + 21 < n_days,
            })

    df = pd.DataFrame(records)
    return df.sort_values(by=["ticker", "date"]).reset_index(drop=True)


def make_null_panel(
    seed: int = 42,
    n_tickers: int = 20,
    n_days: int = 150,
) -> pd.DataFrame:
    """Generate synthetic panel with strictly NO relationship between features and future returns.

    Used for leakage testing: any statistically significant skill detected on this panel indicates leakage.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start="2016-01-04", periods=n_days)
    tickers = [f"TK{i:02d}" for i in range(1, n_tickers + 1)]

    records: list[dict] = []
    for d_idx, dt in enumerate(dates):
        f1 = rng.normal(0, 1, size=n_tickers)
        f2 = rng.normal(0, 1, size=n_tickers)
        raw_fwd_ret = rng.normal(0, 1, size=n_tickers)

        excess = raw_fwd_ret - np.mean(raw_fwd_ret)

        for i, ticker in enumerate(tickers):
            records.append({
                "ticker": ticker,
                "date": dt,
                "t_idx": d_idx,
                "eligible": True,
                "feature_1": float(f1[i]),
                "feature_2": float(f2[i]),
                "ret_fwd_h20": float(raw_fwd_ret[i]),
                "excess_h20": float(excess[i]),
                "y_reg_h20": float(excess[i]),
                "y_cls_h20": int(excess[i] > 0),
                "has_label_h20": d_idx + 21 < n_days,
            })

    df = pd.DataFrame(records)
    return df.sort_values(by=["ticker", "date"]).reset_index(drop=True)
