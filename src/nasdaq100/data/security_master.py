"""Stage S2: security master (ticker-level reference table).

``security_master.csv`` = hand-curated exceptions (``security_master_curated.csv``) with defaults
for every other ticker, plus derived descriptive columns computed from the S1 silver table.

Important distinction (Part III S2, pitfalls): ``first_date``, ``last_date`` and ``n_obs`` here are
*whole-history descriptors for reports*. They must never be used to decide eligibility at a date
(that would be look-ahead); the universe builder does not read them. ``include_in_universe`` is a
static, ticker-level curation decision (curated exclusions plus the zero-volume quality rule) and
is, by specification, based on the full history; see ``docs/survivorship.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from nasdaq100 import paths
from nasdaq100.utils.io import read_parquet
from nasdaq100.utils.logging import get_logger

if TYPE_CHECKING:
    from nasdaq100.config import Config

logger = get_logger("data.security_master")

CURATED_COLUMNS: tuple[str, ...] = (
    "ticker",
    "issuer_id",
    "share_class",
    "exclusion_reason",
    "stitching_suspect",
    "notes",
)
DERIVED_COLUMNS: tuple[str, ...] = (
    "first_date",
    "last_date",
    "n_obs",
    "cohort",
    "zero_volume_share",
    "median_dollar_volume_last_year",
    "include_in_universe",
    "status_reason",
)
MASTER_COLUMNS: tuple[str, ...] = (*CURATED_COLUMNS, *DERIVED_COLUMNS)

#: A ticker whose first observation is this date belongs to the ``orig2000`` cohort (Part II
#: Section II.5). On the real calendar this is the first trading date (55 tickers).
ORIG2000_FIRST_DATE = pd.Timestamp("2000-01-03")
#: ``median_dollar_volume_last_year`` uses the ticker's last 252 observations (about one year).
LAST_YEAR_OBS = 252
#: Silver columns this stage reads.
SILVER_INPUT_COLUMNS: tuple[str, ...] = ("ticker", "date", "close", "volume")

_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no", ""}


class SecurityMasterError(Exception):
    """The curated file or the inputs of the security master are invalid."""


def read_silver(path: Path | str | None = None) -> pd.DataFrame:
    """Read ``prices_silver.parquet`` (S1 output) with ``date`` as ``datetime64[ns]``."""
    p = Path(path) if path is not None else paths.prices_silver_path()
    if not p.is_file():
        raise FileNotFoundError(
            f"Silver table not found: {p}. Run `python -m nasdaq100.cli ingest` and `validate`."
        )
    df = read_parquet(p)
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df


def load_curated(path: Path | str | None = None) -> pd.DataFrame:
    """Load and validate the hand-curated exceptions file.

    The file lists *only exceptions*. Validation: exact column list, unique non-blank tickers,
    ``stitching_suspect`` parseable as a boolean. Blank ``issuer_id`` defaults to the ticker.
    """
    p = Path(path) if path is not None else paths.security_master_curated_path()
    if not p.is_file():
        raise FileNotFoundError(f"Curated security master not found: {p}")
    raw = pd.read_csv(p, dtype=str, keep_default_na=False)
    return normalise_curated(raw, source=p.name)


def normalise_curated(raw: pd.DataFrame, source: str = "curated") -> pd.DataFrame:
    """Validate a curated frame and return it normalised (strings stripped, bool parsed)."""
    if tuple(raw.columns) != CURATED_COLUMNS:
        raise SecurityMasterError(
            f"{source}: columns {list(raw.columns)} != expected {list(CURATED_COLUMNS)}"
        )
    df = raw.copy()
    for c in CURATED_COLUMNS:
        df[c] = df[c].astype(str).str.strip()
    if (df["ticker"] == "").any():
        raise SecurityMasterError(f"{source}: blank ticker")
    dup = df.loc[df["ticker"].duplicated(), "ticker"].tolist()
    if dup:
        raise SecurityMasterError(f"{source}: duplicate tickers {sorted(set(dup))}")

    def parse_bool(v: str) -> bool:
        low = v.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise SecurityMasterError(f"{source}: stitching_suspect must be true/false, got {v!r}")

    df["stitching_suspect"] = df["stitching_suspect"].map(parse_bool).astype(bool)
    df["issuer_id"] = df["issuer_id"].where(df["issuer_id"] != "", df["ticker"])
    return df.reset_index(drop=True)


def build_security_master(
    silver: pd.DataFrame,
    curated: pd.DataFrame,
    max_zero_volume_share: float,
    *,
    orig2000_first_date: pd.Timestamp = ORIG2000_FIRST_DATE,
) -> pd.DataFrame:
    """Return the security master: curated defaults + derived columns, one row per ticker.

    * Defaults for tickers absent from ``curated``: ``issuer_id=ticker``, blank share class,
      no exclusion, ``stitching_suspect=False``.
    * ``cohort``: ``orig2000`` if ``first_date == orig2000_first_date`` else ``later``.
    * ``zero_volume_share``: share of the ticker's rows with ``volume == 0``.
    * ``median_dollar_volume_last_year``: median of ``close * volume`` over the ticker's last
      ``LAST_YEAR_OBS`` observations (fewer if the ticker has fewer).
    * ``include_in_universe``: no ``exclusion_reason`` AND
      ``zero_volume_share <= max_zero_volume_share``. The quality rule works on its own: it
      excludes an illiquid series even if the curated file has no entry for it.
    * ``status_reason``: explains every exclusion (blank for included tickers).

    Silver rows are never modified.
    """
    missing = [c for c in SILVER_INPUT_COLUMNS if c not in silver.columns]
    if missing:
        raise SecurityMasterError(f"silver is missing columns {missing}")
    if silver[list(SILVER_INPUT_COLUMNS)].isna().any().any():
        raise SecurityMasterError("silver contains NaN in ticker/date/close/volume; run validate")
    if curated is None:
        curated = pd.DataFrame({c: pd.Series(dtype="object") for c in CURATED_COLUMNS})
    curated = normalise_curated(curated, source="curated")
    tickers = sorted(silver["ticker"].astype(str).unique())
    unknown = sorted(set(curated["ticker"]) - set(tickers))
    if unknown:
        raise SecurityMasterError(
            f"curated file lists tickers that are not in the data: {unknown}"
        )

    df = silver.loc[:, list(SILVER_INPUT_COLUMNS)].copy()
    df["ticker"] = df["ticker"].astype(str)
    df = df.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)
    df["dollar_volume"] = df["close"].astype("float64") * df["volume"].astype("float64")
    grouped = df.groupby("ticker", sort=True)

    derived = pd.DataFrame(
        {
            "first_date": grouped["date"].min(),
            "last_date": grouped["date"].max(),
            "n_obs": grouped.size().astype("int64"),
            "zero_volume_share": (df["volume"] == 0).groupby(df["ticker"]).mean(),
            "median_dollar_volume_last_year": df.groupby("ticker", sort=True)
            .tail(LAST_YEAR_OBS)
            .groupby("ticker", sort=True)["dollar_volume"]
            .median(),
        }
    )
    derived["cohort"] = np.where(derived["first_date"] == orig2000_first_date, "orig2000", "later")

    base = pd.DataFrame({"ticker": tickers})
    base["issuer_id"] = base["ticker"]
    base["share_class"] = ""
    base["exclusion_reason"] = ""
    base["stitching_suspect"] = False
    base["notes"] = ""
    if len(curated):
        cur = curated.set_index("ticker")
        base = base.set_index("ticker")
        base.loc[cur.index, list(CURATED_COLUMNS[1:])] = cur[list(CURATED_COLUMNS[1:])].to_numpy()
        base = base.reset_index()
    base["stitching_suspect"] = base["stitching_suspect"].astype(bool)

    out = base.merge(derived.reset_index(), on="ticker", how="left", validate="one_to_one")
    quality_fail = out["zero_volume_share"] > max_zero_volume_share
    curated_fail = out["exclusion_reason"] != ""
    out["include_in_universe"] = ~(quality_fail | curated_fail)

    def reason(row: pd.Series) -> str:
        parts: list[str] = []
        if row["exclusion_reason"]:
            parts.append(f"curated: {row['exclusion_reason']}")
        if row["zero_volume_share"] > max_zero_volume_share:
            parts.append(
                f"quality rule: zero-volume share {row['zero_volume_share']:.1%} "
                f"> {max_zero_volume_share:.1%}"
            )
        return "; ".join(parts)

    out["status_reason"] = out.apply(reason, axis=1) if len(out) else ""
    out["n_obs"] = out["n_obs"].astype("int64")
    return out.loc[:, list(MASTER_COLUMNS)].sort_values("ticker").reset_index(drop=True)


def write_security_master(master: pd.DataFrame, path: Path | str | None = None) -> Path:
    """Write ``security_master.csv`` deterministically (sorted, LF line endings, ISO dates)."""
    p = Path(path) if path is not None else paths.security_master_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = master.loc[:, list(MASTER_COLUMNS)].sort_values("ticker").copy()
    for c in ("first_date", "last_date"):
        out[c] = pd.to_datetime(out[c]).dt.strftime("%Y-%m-%d")
    for c in ("stitching_suspect", "include_in_universe"):
        out[c] = out[c].map({True: "true", False: "false"})
    out.to_csv(p, index=False, lineterminator="\n")
    return p


def load_security_master(path: Path | str | None = None) -> pd.DataFrame:
    """Load ``security_master.csv`` with typed columns (dates, bool, int, float)."""
    p = Path(path) if path is not None else paths.security_master_path()
    if not p.is_file():
        raise FileNotFoundError(
            f"Security master not found: {p}. Run `python -m nasdaq100.cli build-master`."
        )
    raw = pd.read_csv(p, dtype=str, keep_default_na=False)
    if tuple(raw.columns) != MASTER_COLUMNS:
        raise SecurityMasterError(
            f"{p.name}: columns {list(raw.columns)} != expected {list(MASTER_COLUMNS)}"
        )
    df = raw.copy()
    df["stitching_suspect"] = df["stitching_suspect"].str.lower().isin(_TRUE)
    df["include_in_universe"] = df["include_in_universe"].str.lower().isin(_TRUE)
    for c in ("first_date", "last_date"):
        df[c] = pd.to_datetime(df[c]).astype("datetime64[ns]")
    df["n_obs"] = df["n_obs"].astype("int64")
    for c in ("zero_volume_share", "median_dollar_volume_last_year"):
        df[c] = df[c].astype("float64")
    return df


def run_build_master(
    cfg: Config,
    *,
    silver_file: Path | str | None = None,
    curated_file: Path | str | None = None,
    master_file: Path | str | None = None,
) -> pd.DataFrame:
    """Build and write ``security_master.csv`` from silver + curated exceptions."""
    silver = read_silver(silver_file)
    curated = load_curated(curated_file)
    master = build_security_master(silver, curated, cfg.flags.max_zero_volume_share_ticker)
    out_path = write_security_master(master, master_file)
    excluded = master[~master["include_in_universe"]]
    logger.info(
        "Security master: %d tickers, %d included, %d excluded (%s) -> %s",
        len(master),
        int(master["include_in_universe"].sum()),
        len(excluded),
        ", ".join(excluded["ticker"]) or "none",
        out_path.name,
    )
    for row in excluded.itertuples():
        logger.warning("Excluded %s: %s", row.ticker, row.status_reason)
    return master
