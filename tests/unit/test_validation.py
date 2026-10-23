"""Unit tests for data ingestion, schema checking, data-quality validation, and quarantine."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.ingestion.loader import load_raw_dataset
from aureus_rv.models import AureusError, ReasonCode
from aureus_rv.pipeline import generate_synthetic_demo_dataset
from aureus_rv.validation.validator import validate_dataset


def test_validation_quarantines_invalid_rows_with_explicit_reasons() -> None:
    """Verify that invalid prices, inverted bid-ask, unknown units, dishonest synthetic flags, and duplicates are quarantined."""
    raw_df = generate_synthetic_demo_dataset(seed=42, n_bars=30)
    registry = ContractRegistry()
    clean_df, report = validate_dataset(raw_df, registry)

    assert report.quarantined_rows == 5
    assert report.valid_rows == report.total_rows - 5
    assert len(clean_df) == report.valid_rows

    reasons_seen = set(report.reason_counts.keys())
    assert ReasonCode.ERR_NON_POSITIVE_PRICE.value in reasons_seen
    assert ReasonCode.ERR_BID_ASK_INVERTED.value in reasons_seen
    assert ReasonCode.ERR_UNKNOWN_QUOTATION_UNIT.value in reasons_seen
    assert ReasonCode.ERR_UNMARKED_SYNTHETIC_SOURCE.value in reasons_seen
    assert ReasonCode.ERR_DUPLICATE_OBSERVATION.value in reasons_seen


def test_ingestion_csv_and_parquet_roundtrip(tmp_path: Path) -> None:
    """Verify both CSV and Parquet loading and SHA-256 manifest generation."""
    df = generate_synthetic_demo_dataset(seed=7, n_bars=15)
    csv_file = tmp_path / "test_data.csv"
    pq_file = tmp_path / "test_data.parquet"
    df.to_csv(csv_file, index=False)
    df.to_parquet(pq_file, index=False)

    df_csv, man_csv = load_raw_dataset(csv_file)
    df_pq, man_pq = load_raw_dataset(pq_file)

    assert len(df_csv) == len(df)
    assert len(df_pq) == len(df)
    assert len(man_csv.sha256_hash) == 64
    assert len(man_pq.sha256_hash) == 64


def test_incompatible_schema_rejected(tmp_path: Path) -> None:
    """Verify datasets missing required columns fail closed on ingestion."""
    bad_df = pd.DataFrame({"timestamp": ["2026-05-01"], "symbol": ["GOLD"]})
    bad_path = tmp_path / "bad.csv"
    bad_df.to_csv(bad_path, index=False)

    with pytest.raises(AureusError) as exc_info:
        load_raw_dataset(bad_path)
    assert exc_info.value.reason_code == ReasonCode.ERR_MISSING_REQUIRED_FIELD
