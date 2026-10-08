"""The feature documentation required by Stage S5 exists in ``docs/data_dictionary.md``."""

from __future__ import annotations

import pytest

from nasdaq100.features.market_features import MARKET_SERIES_COLUMNS
from nasdaq100.features.registry import ALL_FEATURES, FAMILIES, FEATURES
from nasdaq100.paths import docs_dir


@pytest.mark.unit
def test_data_dictionary_lists_every_feature_with_family_and_definition() -> None:
    text = (docs_dir() / "data_dictionary.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| ")]
    for spec in FEATURES:
        matching = [r for r in rows if f"`{spec.name}`" in r and spec.family in r]
        assert matching, f"{spec.name} is not documented with its family {spec.family}"
        assert all(len([c for c in r.split("|") if c.strip()]) >= 5 for r in matching)
    assert len(ALL_FEATURES) == 24 and set(FAMILIES) <= set(text.split())
    for fragment in (
        "market_series.parquet",
        "features_raw.parquet",
        "features_model.parquet",
        "rank-gaussed",
        "only among\n  `eligible` rows",
        "features.winsor_pct",
        "includes the stock itself",
        "load_features_model",
    ):
        assert fragment in text, fragment
    for col in MARKET_SERIES_COLUMNS:
        assert f"`{col}`" in text, col
