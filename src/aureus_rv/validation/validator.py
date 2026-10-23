"""Data-quality validation and quarantine engine for AUREUS-RV 3.0.

Enforces zero silent imputation: invalid, missing, duplicate, or specification-mismatched
observations are quarantined with explicit reason codes and explanations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.ingestion.loader import REQUIRED_SCHEMA_COLUMNS
from aureus_rv.models import QuarantinedRow, ReasonCode, SourceProvenance


class ValidationReport(BaseModel):
    """Summary of dataset validation and quarantine results."""

    model_config = ConfigDict(frozen=True)

    total_rows: int
    valid_rows: int
    quarantined_rows: int
    reason_counts: dict[str, int]
    is_synthetic_dataset: bool
    quarantined_records: list[QuarantinedRow]


def _is_null(val: Any) -> bool:
    if val is None:
        return True
    try:
        return bool(pd.isna(val))
    except Exception:
        return False


def validate_dataset(
    raw_df: pd.DataFrame,
    registry: ContractRegistry,
) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate every observation in `raw_df`, quarantine invalid rows, and return clean DataFrame + report."""
    now_utc = datetime.now(UTC)
    quarantined: list[QuarantinedRow] = []
    valid_indices: list[int] = []
    reason_counts: dict[str, int] = {}

    seen_keys: set[tuple[str, str, str]] = set()

    for idx, row_series in raw_df.iterrows():
        row_dict = row_series.to_dict()
        row_reasons: list[ReasonCode] = []
        explanations: list[str] = []

        # 1. Check missing required fields
        missing_fields = [col for col in REQUIRED_SCHEMA_COLUMNS if col not in row_dict or _is_null(row_dict[col])]
        if missing_fields:
            row_reasons.append(ReasonCode.ERR_MISSING_REQUIRED_FIELD)
            explanations.append(f"Missing/null required fields: {missing_fields}")

        # Parse timestamp & expiry_date if present
        parsed_ts: pd.Timestamp | None = None
        parsed_expiry: pd.Timestamp | None = None
        if "timestamp" not in missing_fields:
            try:
                parsed_ts = pd.Timestamp(row_dict["timestamp"])
                if pd.isna(parsed_ts):
                    raise ValueError("NaT timestamp")
            except Exception:
                row_reasons.append(ReasonCode.ERR_INVALID_TIMESTAMP)
                explanations.append(f"Invalid timestamp: {row_dict.get('timestamp')}")

        if "expiry_date" not in missing_fields:
            try:
                parsed_expiry = pd.Timestamp(row_dict["expiry_date"])
                if pd.isna(parsed_expiry):
                    raise ValueError("NaT expiry_date")
            except Exception:
                row_reasons.append(ReasonCode.ERR_INVALID_TIMESTAMP)
                explanations.append(f"Invalid expiry_date: {row_dict.get('expiry_date')}")

        # Check duplicate (timestamp, symbol, expiry_date)
        if parsed_ts is not None and parsed_expiry is not None and "symbol" not in missing_fields:
            dedup_key = (
                parsed_ts.isoformat(),
                str(row_dict["symbol"]).strip().upper(),
                parsed_expiry.date().isoformat(),
            )
            if dedup_key in seen_keys:
                row_reasons.append(ReasonCode.ERR_DUPLICATE_OBSERVATION)
                explanations.append(f"Duplicate observation for {dedup_key}")
            else:
                seen_keys.add(dedup_key)

        # Check expiry relative to observation date
        if parsed_ts is not None and parsed_expiry is not None:
            if parsed_expiry.date() < parsed_ts.date():
                row_reasons.append(ReasonCode.ERR_EXPIRED_AT_OBSERVATION)
                explanations.append(
                    f"Contract expiry {parsed_expiry.date()} precedes observation date {parsed_ts.date()}"
                )

        # Check prices (open, high, low, close, bid, ask)
        price_cols = ("open", "high", "low", "close", "bid", "ask")
        if not any(c in missing_fields for c in price_cols):
            try:
                prices = {c: float(row_dict[c]) for c in price_cols}
                if any(v <= 0.0 or pd.isna(v) for v in prices.values()):
                    row_reasons.append(ReasonCode.ERR_NON_POSITIVE_PRICE)
                    explanations.append(f"Non-positive price detected in {prices}")
                else:
                    if prices["bid"] > prices["ask"]:
                        row_reasons.append(ReasonCode.ERR_BID_ASK_INVERTED)
                        explanations.append(f"Bid ({prices['bid']}) > Ask ({prices['ask']})")
                    if (
                        prices["high"] < prices["low"]
                        or prices["high"] < prices["open"]
                        or prices["high"] < prices["close"]
                        or prices["low"] > prices["open"]
                        or prices["low"] > prices["close"]
                    ):
                        row_reasons.append(ReasonCode.ERR_HIGH_LOW_INVERTED)
                        explanations.append(f"OHLC range inconsistent: {prices}")
            except (TypeError, ValueError):
                row_reasons.append(ReasonCode.ERR_NON_POSITIVE_PRICE)
                explanations.append("Non-numeric price field")

        # Check volume, OI, quote age
        if "volume_lots" not in missing_fields and "open_interest_lots" not in missing_fields:
            try:
                vol = float(row_dict["volume_lots"])
                oi = float(row_dict["open_interest_lots"])
                q_age = float(row_dict["quote_age_seconds"]) if "quote_age_seconds" not in missing_fields else 0.0
                if vol < 0 or oi < 0 or q_age < 0:
                    row_reasons.append(ReasonCode.ERR_NEGATIVE_VOLUME_OR_OI)
                    explanations.append(f"Negative liquidity/age metric: vol={vol}, oi={oi}, age={q_age}")
            except (TypeError, ValueError):
                row_reasons.append(ReasonCode.ERR_NEGATIVE_VOLUME_OR_OI)
                explanations.append("Non-numeric volume or open interest")

        # Check provenance and synthetic labeling honesty
        if "source_provenance" not in missing_fields and "is_synthetic" not in missing_fields:
            prov_str = str(row_dict["source_provenance"]).strip()
            is_synth = bool(row_dict["is_synthetic"])
            try:
                prov = SourceProvenance(prov_str)
                if prov == SourceProvenance.SYNTHETIC_DEMO and not is_synth:
                    row_reasons.append(ReasonCode.ERR_UNMARKED_SYNTHETIC_SOURCE)
                    explanations.append("source_provenance is SYNTHETIC_DEMO but is_synthetic=False")
                if is_synth and prov == SourceProvenance.MCX_HISTORICAL_VERIFIED:
                    row_reasons.append(ReasonCode.ERR_UNMARKED_SYNTHETIC_SOURCE)
                    explanations.append(
                        "Synthetic row cannot claim MCX_HISTORICAL_VERIFIED provenance"
                    )
            except ValueError:
                row_reasons.append(ReasonCode.ERR_UNKNOWN_PROVENANCE)
                explanations.append(f"Unknown source_provenance: '{prov_str}'")

        # Check contract registry specification compatibility
        spec_fields = ("symbol", "quotation_unit", "purity_fineness", "lot_size_grams")
        if parsed_ts is not None and not any(f in missing_fields for f in spec_fields):
            try:
                spec_reasons = registry.validate_observation_against_spec(
                    symbol=str(row_dict["symbol"]),
                    as_of_date=parsed_ts.date(),
                    quotation_unit=str(row_dict["quotation_unit"]),
                    purity_fineness=int(row_dict["purity_fineness"]),
                    lot_size_grams=float(row_dict["lot_size_grams"]),
                )
                for sr in spec_reasons:
                    row_reasons.append(sr)
                    explanations.append(f"Contract spec validation failed: {sr.value}")
            except (TypeError, ValueError) as exc:
                row_reasons.append(ReasonCode.ERR_INVALID_PURITY_FINENESS)
                explanations.append(f"Invalid numeric contract spec field: {exc}")

        if row_reasons:
            unique_reasons = list(dict.fromkeys(row_reasons))
            for r in unique_reasons:
                reason_counts[r.value] = reason_counts.get(r.value, 0) + 1
            quarantined.append(
                QuarantinedRow(
                    row_index=int(idx) if isinstance(idx, int) else -1,
                    raw_payload={k: (None if _is_null(v) else str(v)) for k, v in row_dict.items()},
                    reason_codes=unique_reasons,
                    explanation="; ".join(explanations),
                    quarantined_at=now_utc,
                )
            )
        else:
            valid_indices.append(idx)

    clean_df = raw_df.loc[valid_indices].copy().reset_index(drop=True)
    if not clean_df.empty:
        clean_df["timestamp"] = pd.to_datetime(clean_df["timestamp"], utc=True)
        clean_df["expiry_date"] = pd.to_datetime(clean_df["expiry_date"]).dt.date
        clean_df["symbol"] = clean_df["symbol"].astype(str).str.strip().str.upper()
        clean_df = clean_df.sort_values(["timestamp", "symbol", "expiry_date"]).reset_index(drop=True)

    is_synth_dataset = bool(clean_df["is_synthetic"].any()) if not clean_df.empty else True

    report = ValidationReport(
        total_rows=len(raw_df),
        valid_rows=len(clean_df),
        quarantined_rows=len(quarantined),
        reason_counts=reason_counts,
        is_synthetic_dataset=is_synth_dataset,
        quarantined_records=quarantined,
    )
    return clean_df, report
