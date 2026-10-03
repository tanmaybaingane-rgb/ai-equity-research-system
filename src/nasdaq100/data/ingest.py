"""Stage S1 ingestion: raw zip -> bronze table, calendar and frozen-dataset manifest.

Bronze = "raw but typed". Nothing is cleaned or dropped here; problems are measured by
``validate.py`` and flagged by ``flags.py``.

Decision D2: the dataset is frozen. The SHA-256 of the zip and of the CSV is recorded in
``data/raw/MANIFEST.json`` on first ingestion; any later ingestion whose hashes differ raises
``FrozenDatasetError`` before anything is written.
"""

from __future__ import annotations

import datetime
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from nasdaq100 import paths
from nasdaq100.utils.calendar import build_calendar
from nasdaq100.utils.hashing import sha256_file
from nasdaq100.utils.io import write_parquet
from nasdaq100.utils.logging import get_logger

logger = get_logger("data.ingest")

RAW_COLUMNS: tuple[str, ...] = (
    "Ticker",
    "Date",
    "Open",
    "High",
    "Low",
    "Close",
    "Adj Close",
    "Volume",
)
COLUMN_RENAME: dict[str, str] = {
    "Ticker": "ticker",
    "Date": "date",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}
BRONZE_COLUMNS: tuple[str, ...] = tuple(COLUMN_RENAME[c] for c in RAW_COLUMNS)
PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "adj_close")
_RAW_DTYPES: dict[str, Any] = {
    "Ticker": str,
    "Open": "float64",
    "High": "float64",
    "Low": "float64",
    "Close": "float64",
    "Adj Close": "float64",
    "Volume": "int64",
}
MANIFEST_KEYS: tuple[str, ...] = (
    "file_name",
    "sha256",
    "size_bytes",
    "rows",
    "columns",
    "date_min",
    "date_max",
    "n_tickers",
    "created_at",
)


class IngestError(Exception):
    """Base class for ingestion failures."""


class SchemaError(IngestError):
    """The raw file does not have the exact expected columns or parseable types."""


class FrozenDatasetError(IngestError):
    """The raw data hash differs from the one recorded in the existing manifest (D2)."""


def extract_csv_if_needed(zip_path: Path, csv_path: Path) -> Path:
    """Return ``csv_path``, extracting the single CSV member from the zip if it is absent.

    Only the CSV bytes are copied (no ``extractall``), so archive member paths can never
    write outside ``csv_path``.
    """
    zip_path, csv_path = Path(zip_path), Path(csv_path)
    if csv_path.is_file():
        return csv_path
    if not zip_path.is_file():
        raise FileNotFoundError(
            f"Raw dataset not found: neither {csv_path} nor {zip_path} exists. "
            "Copy the frozen archive to data/raw/archive.zip."
        )
    with zipfile.ZipFile(zip_path) as zf:
        members = [
            m for m in zf.infolist() if not m.is_dir() and m.filename.lower().endswith(".csv")
        ]
        named = [m for m in members if Path(m.filename.replace("\\", "/")).name == csv_path.name]
        if len(named) == 1:
            member = named[0]
        elif not named and len(members) == 1:
            member = members[0]
        else:
            raise IngestError(
                f"Cannot choose a CSV in {zip_path.name}: expected exactly one "
                f"{csv_path.name} (found {len(named)} named matches, {len(members)} CSVs)"
            )
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        partial = csv_path.with_name(csv_path.name + ".part")
        with zf.open(member) as src, open(partial, "wb") as dst:
            shutil.copyfileobj(src, dst)
        partial.replace(csv_path)
    logger.info("Extracted %s from %s", csv_path.name, zip_path.name)
    return csv_path


def read_raw_csv(csv_path: Path) -> pd.DataFrame:
    """Read the raw CSV with explicit dtypes and return the bronze table (not yet written).

    Verifies the exact column list, renames per Part II Section II.1, parses ``date`` to
    ``datetime64[ns]`` (midnight, tz-naive) and sorts by (``ticker``, ``date``). No rows are
    dropped; duplicates or gaps are left for ``validate.py`` to report.
    """
    csv_path = Path(csv_path)
    header = tuple(pd.read_csv(csv_path, nrows=0).columns)
    if header != RAW_COLUMNS:
        raise SchemaError(
            f"Unexpected CSV columns in {csv_path.name}: got {list(header)}, "
            f"expected exactly {list(RAW_COLUMNS)}"
        )
    try:
        raw = pd.read_csv(csv_path, dtype=_RAW_DTYPES, parse_dates=["Date"])
    except (ValueError, TypeError) as exc:
        raise SchemaError(f"Could not parse {csv_path.name} with the expected dtypes: {exc}") from exc

    df = raw.rename(columns=COLUMN_RENAME)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize().astype("datetime64[ns]")
    df = df.loc[:, list(BRONZE_COLUMNS)]
    return df.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)


def _file_entry(path: Path) -> dict[str, Any]:
    return {
        "file_name": path.name,
        "sha256": sha256_file(path),
        "size_bytes": int(path.stat().st_size),
    }


def check_frozen(existing: dict[str, Any], primary: dict[str, Any], csv: dict[str, Any]) -> None:
    """Raise ``FrozenDatasetError`` if the hashes differ from an existing manifest (D2)."""
    problems: list[str] = []
    old_csv = existing.get("csv", {})
    if old_csv.get("sha256") != csv["sha256"]:
        problems.append(f"CSV sha256 {csv['sha256']} != manifest {old_csv.get('sha256')}")
    if existing.get("file_name") == primary["file_name"] and existing.get("sha256") != primary["sha256"]:
        problems.append(
            f"{primary['file_name']} sha256 {primary['sha256']} != manifest {existing.get('sha256')}"
        )
    if problems:
        raise FrozenDatasetError(
            "Raw dataset differs from the frozen dataset recorded in MANIFEST.json (D2): "
            + "; ".join(problems)
        )


def read_manifest(path: Path | str | None = None) -> dict[str, Any]:
    """Load ``MANIFEST.json`` (default location from ``nasdaq100.paths``)."""
    p = Path(path) if path is not None else paths.manifest_path()
    if not p.is_file():
        raise FileNotFoundError(f"Manifest not found: {p}. Run `python -m nasdaq100.cli ingest`.")
    manifest = json.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in MANIFEST_KEYS if k not in manifest]
    if missing:
        raise ValueError(f"Manifest {p} is missing keys: {missing}")
    return manifest


def data_hash(path: Path | str | None = None) -> str:
    """The dataset hash recorded by every downstream artifact (manifest ``sha256``)."""
    return str(read_manifest(path)["sha256"])


def run_ingest(
    *,
    zip_path: Path | str | None = None,
    csv_path: Path | str | None = None,
    manifest_file: Path | str | None = None,
    bronze_file: Path | str | None = None,
    calendar_file: Path | str | None = None,
) -> dict[str, Any]:
    """Ingest the raw dataset: extract, hash, guard, type, sort, write bronze/calendar/manifest.

    Paths default to the ``nasdaq100.paths`` helpers; they are parameters so tests can run in a
    temporary directory. Nothing is written if the frozen-dataset guard or schema check fails.
    Re-ingesting identical data leaves an existing manifest untouched.
    Returns the manifest dictionary.
    """
    zip_p = Path(zip_path) if zip_path is not None else paths.raw_zip_path()
    csv_p = Path(csv_path) if csv_path is not None else paths.raw_csv_path()
    manifest_p = Path(manifest_file) if manifest_file is not None else paths.manifest_path()
    bronze_p = Path(bronze_file) if bronze_file is not None else paths.prices_bronze_path()
    calendar_p = Path(calendar_file) if calendar_file is not None else paths.calendar_path()

    csv_p = extract_csv_if_needed(zip_p, csv_p)
    csv_entry = _file_entry(csv_p)
    primary = _file_entry(zip_p) if zip_p.is_file() else dict(csv_entry)

    existing: dict[str, Any] | None = None
    if manifest_p.is_file():
        existing = json.loads(manifest_p.read_text(encoding="utf-8"))
        check_frozen(existing, primary, csv_entry)

    bronze = read_raw_csv(csv_p)
    calendar = build_calendar(bronze["date"])

    if existing is not None:
        manifest = existing
    else:
        manifest = {
            **primary,
            "rows": int(len(bronze)),
            "columns": list(RAW_COLUMNS),
            "date_min": bronze["date"].min().strftime("%Y-%m-%d"),
            "date_max": bronze["date"].max().strftime("%Y-%m-%d"),
            "n_tickers": int(bronze["ticker"].nunique()),
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "csv": csv_entry,
        }

    write_parquet(bronze, bronze_p)
    write_parquet(calendar, calendar_p, sort_keys=("date",))
    if existing is None:
        manifest_p.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(manifest, indent=2) + "\n")
        logger.info("Wrote manifest %s (sha256 %s)", manifest_p.name, manifest["sha256"])
    logger.info(
        "Ingested %d rows, %d tickers, %d calendar dates",
        len(bronze),
        bronze["ticker"].nunique(),
        len(calendar),
    )
    return manifest
