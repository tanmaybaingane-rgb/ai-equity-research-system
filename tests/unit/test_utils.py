"""Unit tests for utility functions: seeds, hashing, io, and registry."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nasdaq100.utils.hashing import sha256_file, sha256_json
from nasdaq100.utils.io import append_registry, new_run_id, read_parquet, write_parquet
from nasdaq100.utils.seeds import set_global_seed


@pytest.mark.unit
def test_seeds_produce_identical_draws() -> None:
    """Verify that set_global_seed guarantees repeatable NumPy draws."""
    set_global_seed(42)
    draw1 = np.random.normal(size=10)

    set_global_seed(42)
    draw2 = np.random.normal(size=10)

    np.testing.assert_array_equal(draw1, draw2)

    # Different seed produces different draws
    set_global_seed(99)
    draw3 = np.random.normal(size=10)
    assert not np.array_equal(draw1, draw3)


@pytest.mark.unit
def test_sha256_file_and_json(tmp_path: Path) -> None:
    """Verify sha256_file and sha256_json behaviour."""
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("hello world\n", encoding="utf-8")
    file_hash = sha256_file(sample_file)
    assert isinstance(file_hash, str)
    assert len(file_hash) == 64

    # sha256_json is independent of key insertion order
    d1 = {"b": 2, "a": 1, "c": [1, 2]}
    d2 = {"a": 1, "c": [1, 2], "b": 2}
    assert sha256_json(d1) == sha256_json(d2)


@pytest.mark.unit
def test_parquet_io_sorting_and_roundtrip(tmp_path: Path) -> None:
    """Verify write_parquet enforces sorting and read_parquet roundtrips accurately."""
    df = pd.DataFrame({
        "ticker": ["MSFT", "AAPL", "GOOGL"],
        "date": pd.to_datetime(["2020-01-02", "2020-01-01", "2020-01-03"]),
        "value": [10.0, 20.0, 30.0],
    })

    target_path = tmp_path / "sub" / "test.parquet"
    write_parquet(df, target_path)

    loaded = read_parquet(target_path)
    assert list(loaded["ticker"]) == ["AAPL", "GOOGL", "MSFT"]
    pd.testing.assert_frame_equal(
        loaded,
        df.sort_values(by=["ticker", "date"]).reset_index(drop=True),
    )


@pytest.mark.unit
def test_registry_append_and_schema_validation(tmp_path: Path) -> None:
    """Verify registry appends rows without overwriting and rejects invalid schemas."""
    reg_file = tmp_path / "registry.csv"

    valid_row = {
        "run_id": "20260101-120000_s8_lgbm_12345678",
        "timestamp": "2026-01-01T12:00:00",
        "stage": "S8",
        "description": "Dev run",
        "git_commit": "abc1234",
        "config_hash": "1234567890abcdef",
        "data_hash": "fedcba0987654321",
        "seed": 42,
        "split": "dev",
        "counts_as_trial": True,
        "sharpe_net": 1.25,
        "key_metric_name": "rank_ic",
        "key_metric_value": 0.045,
        "notes": "Testing",
    }

    # First append creates file with header + 1 row
    append_registry(valid_row, path=reg_file)
    content1 = reg_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(content1) == 2  # header + row 1

    # Second append adds another row without overwriting
    valid_row2 = dict(valid_row, run_id="run_2")
    append_registry(valid_row2, path=reg_file)
    content2 = reg_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(content2) == 3

    # Reject missing column
    invalid_row_missing = dict(valid_row)
    del invalid_row_missing["git_commit"]
    with pytest.raises(ValueError, match="Missing columns"):
        append_registry(invalid_row_missing, path=reg_file)

    # Reject unexpected column
    invalid_row_extra = dict(valid_row, extra_col="bad")
    with pytest.raises(ValueError, match="Unexpected columns"):
        append_registry(invalid_row_extra, path=reg_file)


@pytest.mark.unit
def test_new_run_id_format() -> None:
    """Verify new_run_id format: YYYYMMDD-HHMMSS_{stage}_{model_or_name}_{confighash8}."""
    rid = new_run_id("s8", "lgbm", "abcdef1234567890")
    parts = rid.split("_")
    assert len(parts) == 4
    assert parts[1] == "s8"
    assert parts[2] == "lgbm"
    assert parts[3] == "abcdef12"  # exactly first 8 characters
