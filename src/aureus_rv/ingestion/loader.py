"""CSV and Parquet dataset ingestion with file SHA-256 provenance hashing."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

from aureus_rv.models import AureusError, ReasonCode

REQUIRED_SCHEMA_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "expiry_date",
    "open",
    "high",
    "low",
    "close",
    "bid",
    "ask",
    "volume_lots",
    "open_interest_lots",
    "quotation_unit",
    "purity_fineness",
    "lot_size_grams",
    "quote_age_seconds",
    "source_provenance",
    "is_synthetic",
)


class IngestionManifest(BaseModel):
    """Metadata captured when loading a raw market dataset."""

    model_config = ConfigDict(frozen=True)

    source_path: str
    file_format: str
    sha256_hash: str
    raw_row_count: int
    columns: list[str]


def compute_file_sha256(path: str | Path) -> str:
    """Compute SHA-256 hex digest of a file on disk."""
    file_path = Path(path)
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_raw_dataset(path: str | Path) -> tuple[pd.DataFrame, IngestionManifest]:
    """Load a raw dataset from CSV or Parquet and verify schema presence without mutating values."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(file_path)
        fmt = "csv"
    elif suffix in {".parquet", ".pq"}:
        df = pd.read_parquet(file_path)
        fmt = "parquet"
    else:
        raise AureusError(
            f"Unsupported dataset file extension '{suffix}'. Expected .csv or .parquet.",
            reason_code=ReasonCode.ERR_MISSING_REQUIRED_FIELD,
            details={"path": str(file_path), "suffix": suffix},
        )

    missing_cols = [c for c in REQUIRED_SCHEMA_COLUMNS if c not in df.columns]
    if missing_cols:
        raise AureusError(
            f"Incompatible dataset schema. Missing required columns: {missing_cols}",
            reason_code=ReasonCode.ERR_MISSING_REQUIRED_FIELD,
            details={"missing_columns": missing_cols, "found_columns": list(df.columns)},
        )

    manifest = IngestionManifest(
        source_path=str(file_path.resolve()),
        file_format=fmt,
        sha256_hash=compute_file_sha256(file_path),
        raw_row_count=len(df),
        columns=list(df.columns),
    )
    return df, manifest
