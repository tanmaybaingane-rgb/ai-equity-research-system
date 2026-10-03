"""Clean synthetic raw-schema prices for S1 tests.

Unlike ``toy_data.make_toy_prices`` (which deliberately injects quirks), every row produced here
is valid and triggers NO data-quality flag, so tests can inject exactly one problem at a time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RAW_COLUMNS = ["Ticker", "Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]


def make_clean_raw_prices(
    tickers: tuple[str, ...] = ("AAA", "BBB", "CCC"),
    n_days: int = 30,
    start_offsets: dict[str, int] | None = None,
    seed: int = 7,
) -> pd.DataFrame:
    """Return a (Ticker, Date)-sorted frame in the raw CSV schema.

    Prices stay around 50 (>= 5, no tick noise), moves are ~1% (no extreme moves), bars are never
    flat, ``Adj Close = 0.9 * Close`` (constant factor, so no corporate-action gap) and volume is
    always positive. ``start_offsets`` delays a ticker's first date by that many trading days.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-06", periods=n_days)
    offsets = start_offsets or {}
    rows: list[dict] = []
    for k, tk in enumerate(tickers):
        price = 50.0 + 10.0 * k
        for i in range(offsets.get(tk, 0), n_days):
            price *= float(np.exp(rng.normal(0.0, 0.01)))
            close = round(price, 2)
            open_ = round(close * (1 + rng.uniform(-0.004, 0.004)), 2)
            high = round(max(open_, close) + 0.05, 2)
            low = round(min(open_, close) - 0.05, 2)
            rows.append(
                {
                    "Ticker": tk,
                    "Date": dates[i],
                    "Open": open_,
                    "High": high,
                    "Low": low,
                    "Close": close,
                    "Adj Close": round(close * 0.9, 2),
                    "Volume": int(rng.integers(1_000, 9_000)),
                }
            )
    df = pd.DataFrame(rows, columns=RAW_COLUMNS)
    return df.sort_values(["Ticker", "Date"]).reset_index(drop=True)


def to_bronze(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename raw columns to bronze names with the exact bronze dtypes (no I/O)."""
    from nasdaq100.data.ingest import COLUMN_RENAME

    df = raw.rename(columns=COLUMN_RENAME).copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df["volume"] = df["volume"].astype("int64")
    return df.reset_index(drop=True)
