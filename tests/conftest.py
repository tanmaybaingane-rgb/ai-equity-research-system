"""Pytest configuration and global fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from nasdaq100.config import Config, load_config
from tests.fixtures.toy_data import (
    make_null_panel,
    make_planted_signal_panel,
    make_toy_prices,
)


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
