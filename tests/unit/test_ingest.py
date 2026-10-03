"""Unit tests for S1 ingestion: extraction, typing, sorting, manifest and frozen guard."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest
import yaml

from nasdaq100.data.ingest import (
    BRONZE_COLUMNS,
    RAW_COLUMNS,
    FrozenDatasetError,
    IngestError,
    SchemaError,
    data_hash,
    run_ingest,
)
from nasdaq100.paths import data_expectations_path
from nasdaq100.utils.hashing import sha256_file
from tests.fixtures.s1_prices import make_clean_raw_prices

CSV_NAME = "NASDAQ100_Historical_Data.csv"


def _paths(tmp: Path) -> dict[str, Path]:
    return {
        "zip_path": tmp / "archive.zip",
        "csv_path": tmp / CSV_NAME,
        "manifest_file": tmp / "MANIFEST.json",
        "bronze_file": tmp / "prices_bronze.parquet",
        "calendar_file": tmp / "calendar.parquet",
    }


def _write_zip(zip_path: Path, csv_text: str, member: str = CSV_NAME) -> None:
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(member, csv_text)


def _csv_text(raw: pd.DataFrame) -> str:
    out = raw.copy()
    out["Date"] = out["Date"].dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False, lineterminator="\n")


def _setup(tmp: Path, raw: pd.DataFrame | None = None) -> tuple[dict[str, Path], pd.DataFrame]:
    raw = make_clean_raw_prices() if raw is None else raw
    p = _paths(tmp)
    _write_zip(p["zip_path"], _csv_text(raw))
    return p, raw


@pytest.mark.unit
def test_raw_columns_constant_matches_data_expectations() -> None:
    expected = yaml.safe_load(data_expectations_path().read_text(encoding="utf-8"))
    assert list(RAW_COLUMNS) == expected["dataset"]["expected_columns"]
    assert BRONZE_COLUMNS == (
        "ticker", "date", "open", "high", "low", "close", "adj_close", "volume"
    )


@pytest.mark.unit
def test_ingest_extracts_csv_and_writes_typed_sorted_bronze(tmp_path: Path) -> None:
    p, raw = _setup(tmp_path)
    assert not p["csv_path"].exists()
    manifest = run_ingest(**p)
    assert p["csv_path"].is_file()  # extracted from the zip

    bronze = pd.read_parquet(p["bronze_file"])
    assert tuple(bronze.columns) == BRONZE_COLUMNS
    assert len(bronze) == len(raw)
    assert str(bronze["date"].dtype) == "datetime64[ns]"  # parsed, not left as strings
    assert str(bronze["volume"].dtype) == "int64"
    assert all(str(bronze[c].dtype) == "float64" for c in ("open", "high", "low", "close", "adj_close"))
    assert bronze["date"].dt.hour.eq(0).all()
    keys = list(zip(bronze["ticker"], bronze["date"], strict=True))
    assert keys == sorted(keys)

    cal = pd.read_parquet(p["calendar_file"])
    assert cal["t_idx"].tolist() == list(range(raw["Date"].nunique()))
    assert manifest["rows"] == len(raw) and manifest["n_tickers"] == 3


@pytest.mark.unit
def test_ingest_sorts_date_major_input_by_ticker_then_date(tmp_path: Path) -> None:
    raw = make_clean_raw_prices()
    shuffled = raw.sort_values(["Date", "Ticker"]).reset_index(drop=True)  # date-sorted CSV
    p, _ = _setup(tmp_path, shuffled)
    run_ingest(**p)
    bronze = pd.read_parquet(p["bronze_file"])
    assert bronze["ticker"].is_monotonic_increasing
    for _, g in bronze.groupby("ticker"):
        assert g["date"].is_monotonic_increasing


@pytest.mark.unit
def test_manifest_contents(tmp_path: Path) -> None:
    p, raw = _setup(tmp_path)
    manifest = run_ingest(**p)
    on_disk = json.loads(p["manifest_file"].read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert manifest["file_name"] == "archive.zip"
    assert manifest["sha256"] == sha256_file(p["zip_path"])
    assert manifest["size_bytes"] == p["zip_path"].stat().st_size
    assert manifest["csv"]["sha256"] == sha256_file(p["csv_path"])
    assert manifest["columns"] == list(RAW_COLUMNS)
    assert manifest["date_min"] == raw["Date"].min().strftime("%Y-%m-%d")
    assert manifest["date_max"] == raw["Date"].max().strftime("%Y-%m-%d")
    assert manifest["created_at"]
    assert data_hash(p["manifest_file"]) == manifest["sha256"]


@pytest.mark.unit
def test_ingest_uses_existing_csv_and_is_idempotent(tmp_path: Path) -> None:
    p, _ = _setup(tmp_path)
    first = run_ingest(**p)
    before = p["manifest_file"].read_bytes()
    second = run_ingest(**p)  # same data again: allowed, manifest untouched
    assert second == first
    assert p["manifest_file"].read_bytes() == before


@pytest.mark.unit
def test_ingest_does_not_drop_bad_rows(tmp_path: Path) -> None:
    raw = make_clean_raw_prices()
    dup = pd.concat([raw, raw.iloc[[3]]]).reset_index(drop=True)  # duplicate key
    p, _ = _setup(tmp_path, dup)
    run_ingest(**p)
    assert len(pd.read_parquet(p["bronze_file"])) == len(dup)  # validate.py reports, not ingest


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda df: df.drop(columns=["Volume"]),
        lambda df: df.rename(columns={"Adj Close": "AdjClose"}),
        lambda df: df[[*df.columns[::-1]]],
        lambda df: df.assign(Extra=1),
    ],
)
def test_wrong_column_list_raises_schema_error(tmp_path: Path, mutate) -> None:
    raw = mutate(make_clean_raw_prices())
    p, _ = _setup(tmp_path, raw)
    with pytest.raises(SchemaError, match="columns"):
        run_ingest(**p)
    assert not p["bronze_file"].exists() and not p["manifest_file"].exists()


@pytest.mark.unit
def test_unparseable_price_or_volume_raises_schema_error(tmp_path: Path) -> None:
    raw = make_clean_raw_prices()
    text = _csv_text(raw).replace(str(raw.loc[0, "Close"]), "abc", 1)
    p = _paths(tmp_path)
    _write_zip(p["zip_path"], text)
    with pytest.raises(SchemaError, match="dtypes"):
        run_ingest(**p)

    p2 = _paths(tmp_path / "v")
    p2["zip_path"].parent.mkdir()
    bad_vol = _csv_text(raw).replace(f",{raw.loc[1, 'Volume']}\n", ",12.5\n", 1)
    _write_zip(p2["zip_path"], bad_vol)
    with pytest.raises(SchemaError):
        run_ingest(**p2)


@pytest.mark.unit
def test_missing_raw_data_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="archive.zip"):
        run_ingest(**_paths(tmp_path))


@pytest.mark.unit
def test_zip_member_selection(tmp_path: Path) -> None:
    raw = make_clean_raw_prices()
    p = _paths(tmp_path)
    # a single CSV with a different name (inside a folder) is accepted
    _write_zip(p["zip_path"], _csv_text(raw), member="nested/other_name.csv")
    run_ingest(**p)
    assert p["csv_path"].read_text(encoding="utf-8") == _csv_text(raw)

    # two CSVs and none with the expected name: ambiguous -> error
    p2 = _paths(tmp_path / "amb")
    p2["zip_path"].parent.mkdir()
    with zipfile.ZipFile(p2["zip_path"], "w") as zf:
        zf.writestr("a.csv", "x")
        zf.writestr("b.csv", "y")
    with pytest.raises(IngestError, match="Cannot choose"):
        run_ingest(**p2)


@pytest.mark.unit
def test_frozen_guard_raises_when_csv_changes(tmp_path: Path) -> None:
    p, raw = _setup(tmp_path)
    run_ingest(**p)
    manifest_bytes = p["manifest_file"].read_bytes()
    bronze_bytes = p["bronze_file"].read_bytes()

    altered = raw.copy()
    altered.loc[0, "Close"] = altered.loc[0, "Close"] + 1.0
    p["csv_path"].write_text(_csv_text(altered), encoding="utf-8")  # tamper with extracted CSV
    with pytest.raises(FrozenDatasetError, match="frozen"):
        run_ingest(**p)
    assert p["manifest_file"].read_bytes() == manifest_bytes  # nothing overwritten
    assert p["bronze_file"].read_bytes() == bronze_bytes


@pytest.mark.unit
def test_frozen_guard_raises_when_zip_changes(tmp_path: Path) -> None:
    p, raw = _setup(tmp_path)
    run_ingest(**p)
    _write_zip(p["zip_path"], _csv_text(raw) + "\n")  # new archive bytes, CSV untouched
    with pytest.raises(FrozenDatasetError, match="archive.zip"):
        run_ingest(**p)
