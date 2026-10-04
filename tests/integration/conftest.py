"""Shared session fixtures for ``needs_data`` integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nasdaq100.config import load_config
from nasdaq100.data.ingest import run_ingest
from nasdaq100.data.validate import run_validate
from nasdaq100.paths import raw_csv_path, raw_zip_path


@pytest.fixture(scope="session")
def real_s1(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Run S1 (ingest + validate) once per session into a temp dir; ``data/`` is not written."""
    tmp: Path = tmp_path_factory.mktemp("s1_for_s2")
    csv_p = raw_csv_path() if raw_csv_path().is_file() else tmp / raw_csv_path().name
    kw = {
        "zip_path": raw_zip_path(),
        "csv_path": csv_p,
        "manifest_file": tmp / "MANIFEST.json",
        "bronze_file": tmp / "prices_bronze.parquet",
        "calendar_file": tmp / "calendar.parquet",
    }
    manifest = run_ingest(**kw)
    run_validate(
        load_config(),
        bronze_file=kw["bronze_file"],
        calendar_file=kw["calendar_file"],
        manifest_file=kw["manifest_file"],
        silver_file=tmp / "prices_silver.parquet",
        report_file=tmp / "validation_report.json",
        markdown_file=tmp / "data_quality_report.md",
    )
    return {"tmp": tmp, "manifest": manifest, "silver_file": tmp / "prices_silver.parquet"}
