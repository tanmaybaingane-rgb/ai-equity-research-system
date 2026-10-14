"""The S7 artifacts and metrics are documented in ``docs/data_dictionary.md``."""

from __future__ import annotations

import pytest

from nasdaq100.evaluation.predictive import METRIC_COLUMNS
from nasdaq100.models.baselines import BASELINE_IDS, PREDICTION_COLUMNS
from nasdaq100.paths import docs_dir


@pytest.mark.unit
def test_data_dictionary_documents_the_s7_artifacts() -> None:
    text = (docs_dir() / "data_dictionary.md").read_text(encoding="utf-8")
    for column in PREDICTION_COLUMNS:
        assert f"`{column}`" in text, column
    for model_id in BASELINE_IDS:
        assert f"`{model_id}`" in text, model_id
    for column in METRIC_COLUMNS:
        assert f"`{column}`" in text, column
    for fragment in (
        "oof_predictions.parquet",
        "units_are_returns",
        "(t_idx - 252) % 20 == 0",
        "SURVIVOR-BIASED",
        "baseline_metrics.csv",
        "features_raw_path",
        "counts_as_trial",
    ):
        assert fragment in text, fragment
