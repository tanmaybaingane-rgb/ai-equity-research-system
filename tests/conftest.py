"""Pytest configuration and global fixtures."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest

from nasdaq100.config import Config, load_config
from nasdaq100.paths import raw_csv_path, raw_zip_path
from tests.fixtures.toy_data import (
    make_null_panel,
    make_planted_signal_panel,
    make_toy_prices,
)

NEEDS_DATA_SKIP_REASON = (
    "raw dataset not found: place data/raw/archive.zip (or the extracted "
    "NASDAQ100_Historical_Data.csv) to run needs_data tests"
)


def raw_data_available(zip_path: Path | None = None, csv_path: Path | None = None) -> bool:
    """Return True if the frozen raw dataset (archive or extracted CSV) exists on disk."""
    zip_p = Path(zip_path) if zip_path is not None else raw_zip_path()
    csv_p = Path(csv_path) if csv_path is not None else raw_csv_path()
    return zip_p.is_file() or csv_p.is_file()


def apply_needs_data_skip(items: Sequence[pytest.Item], data_available: bool) -> int:
    """Mark every ``needs_data`` test as skipped when the raw dataset is missing.

    Returns the number of tests that were marked as skipped. Tests without the
    ``needs_data`` marker are never touched.
    """
    if data_available:
        return 0
    skip_marker = pytest.mark.skip(reason=NEEDS_DATA_SKIP_REASON)
    skipped = 0
    for item in items:
        if item.get_closest_marker("needs_data") is not None:
            item.add_marker(skip_marker)
            skipped += 1
    return skipped


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-skip ``needs_data`` tests when the raw dataset is absent (Part II Section II.7)."""
    apply_needs_data_skip(items, raw_data_available())


@pytest.fixture
def base_config() -> Config:
    """Fixture returning immutable default configuration."""
    return load_config()


@pytest.fixture
def toy_prices() -> pd.DataFrame:
    """Fixture returning synthetic price panel in raw CSV schema."""
    return make_toy_prices(n_tickers=5, n_days=60, seed=42)


@pytest.fixture
def planted_panel() -> pd.DataFrame:
    """Fixture returning synthetic panel with planted linear signal."""
    return make_planted_signal_panel(seed=42, signal_strength=0.5, n_tickers=10, n_days=50)


@pytest.fixture
def null_panel() -> pd.DataFrame:
    """Fixture returning synthetic panel with pure noise (no signal)."""
    return make_null_panel(seed=42, n_tickers=10, n_days=50)
