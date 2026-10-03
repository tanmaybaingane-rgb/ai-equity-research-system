"""Input/output utilities for Parquet panels and experiment registry management."""

from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from nasdaq100.paths import ensure_parent_dir, registry_path

REGISTRY_COLUMNS: tuple[str, ...] = (
    "run_id",
    "timestamp",
    "stage",
    "description",
    "git_commit",
    "config_hash",
    "data_hash",
    "seed",
    "split",
    "counts_as_trial",
    "sharpe_net",
    "key_metric_name",
    "key_metric_value",
    "notes",
)


def write_parquet(
    df: pd.DataFrame,
    path: Path | str,
    sort_keys: tuple[str, ...] = ("ticker", "date"),
) -> Path:
    """Write DataFrame to Parquet enforcing sorted order on write.

    Ensures parent directory exists and does not store the DataFrame index.
    """
    out_path = Path(path)
    ensure_parent_dir(out_path)

    # Enforce sorting by keys present in DataFrame
    active_keys = [k for k in sort_keys if k in df.columns]
    if active_keys:
        df = df.sort_values(by=active_keys).reset_index(drop=True)

    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
    return out_path


def read_parquet(path: Path | str) -> pd.DataFrame:
    """Read a Parquet file into a pandas DataFrame."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Parquet file does not exist: {p}")
    return pd.read_parquet(p, engine="pyarrow")


def append_registry(
    row: dict[str, Any],
    path: Path | str | None = None,
) -> None:
    """Validate columns and append a run record to experiments/registry.csv.

    Never rewrites existing lines. Raises ValueError if columns do not exactly match
    the specification in Part II Section II.5.
    """
    target_path = Path(path) if path is not None else registry_path()
    ensure_parent_dir(target_path)

    row_keys = set(row.keys())
    expected_keys = set(REGISTRY_COLUMNS)

    missing = expected_keys - row_keys
    unexpected = row_keys - expected_keys
    if missing or unexpected:
        error_parts = []
        if missing:
            error_parts.append(f"Missing columns: {sorted(missing)}")
        if unexpected:
            error_parts.append(f"Unexpected columns: {sorted(unexpected)}")
        raise ValueError(f"Invalid registry row schema. {'; '.join(error_parts)}")

    # Check if header needs to be written
    write_header = not target_path.exists() or target_path.stat().st_size == 0

    ordered_row = [row[col] for col in REGISTRY_COLUMNS]

    with open(target_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(REGISTRY_COLUMNS)
        writer.writerow(ordered_row)


def new_run_id(stage: str, model_or_name: str, config_hash_val: str) -> str:
    """Generate canonical run ID per Part II Section II.6: YYYYMMDD-HHMMSS_{stage}_{model_or_name}_{confighash8}."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    confighash8 = config_hash_val[:8]
    return f"{timestamp}_{stage}_{model_or_name}_{confighash8}"
