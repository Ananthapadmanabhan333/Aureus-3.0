"""Typed domain models, enumerations, reason codes, and structured errors for AUREUS-RV 3.0."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuotationUnit(StrEnum):
    """Supported raw quotation units for gold futures."""

    INR_PER_10G = "INR_PER_10G"
    INR_PER_8G = "INR_PER_8G"
    INR_PER_1G = "INR_PER_1G"


class SourceProvenance(StrEnum):
    """Data source provenance classifications."""

    MCX_HISTORICAL_VERIFIED = "MCX_HISTORICAL_VERIFIED"
    VENDOR_FEED = "VENDOR_FEED"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"


class DecisionState(StrEnum):
    """Deterministic research classification states."""

    QUIET = "QUIET"
    REJECTED = "REJECTED"
    NO_EDGE = "NO-EDGE"
    TRADE_SIGNAL = "TRADE SIGNAL"


class CostScenarioName(StrEnum):
    """Supported transaction cost scenarios."""

    BASE = "base"
    CONSERVATIVE = "conservative"
    STRESS = "stress"


class SpreadDirection(StrEnum):
    """Spread position direction relative to Leg A minus Leg B."""

    SHORT_SPREAD = "SHORT_SPREAD"  # Short Leg A (rich), Long Leg B (cheap); expects spread to fall
    LONG_SPREAD = "LONG_SPREAD"    # Long Leg A (cheap), Short Leg B (rich); expects spread to rise
    FLAT = "FLAT"


class ReasonCode(StrEnum):
    """Explicit machine-readable reason codes across validation, pairing, liquidity, stats, costs, and gates."""

    # Data Validation & Ingestion (G0)
    VALID_OK = "VALID_OK"
    ERR_MISSING_REQUIRED_FIELD = "ERR_MISSING_REQUIRED_FIELD"
    ERR_INVALID_TIMESTAMP = "ERR_INVALID_TIMESTAMP"
    ERR_DUPLICATE_OBSERVATION = "ERR_DUPLICATE_OBSERVATION"
    ERR_NON_POSITIVE_PRICE = "ERR_NON_POSITIVE_PRICE"
    ERR_BID_ASK_INVERTED = "ERR_BID_ASK_INVERTED"
    ERR_HIGH_LOW_INVERTED = "ERR_HIGH_LOW_INVERTED"
    ERR_NEGATIVE_VOLUME_OR_OI = "ERR_NEGATIVE_VOLUME_OR_OI"
    ERR_EXPIRED_AT_OBSERVATION = "ERR_EXPIRED_AT_OBSERVATION"
    ERR_UNKNOWN_PROVENANCE = "ERR_UNKNOWN_PROVENANCE"
    ERR_UNMARKED_SYNTHETIC_SOURCE = "ERR_UNMARKED_SYNTHETIC_SOURCE"

    # Contract Specification & Normalization (G1)
    ERR_UNKNOWN_CONTRACT_SYMBOL = "ERR_UNKNOWN_CONTRACT_SYMBOL"
    ERR_UNKNOWN_QUOTATION_UNIT = "ERR_UNKNOWN_QUOTATION_UNIT"
    ERR_INVALID_PURITY_FINENESS = "ERR_INVALID_PURITY_FINENESS"
    ERR_SPEC_LOT_MISMATCH = "ERR_SPEC_LOT_MISMATCH"
    ERR_SPEC_QUOTATION_MISMATCH = "ERR_SPEC_QUOTATION_MISMATCH"
    ERR_SPEC_PURITY_MISMATCH = "ERR_SPEC_PURITY_MISMATCH"
    ERR_SPEC_NOT_EFFECTIVE = "ERR_SPEC_NOT_EFFECTIVE"

    # Pairing & Expiry Eligibility (G2)
    PAIR_OK = "PAIR_OK"
    ERR_IDENTICAL_CONTRACT_INSTANCE = "ERR_IDENTICAL_CONTRACT_INSTANCE"
    ERR_INVERTED_PAIR_EXPIRY = "ERR_INVERTED_PAIR_EXPIRY"
    ERR_EXPIRY_DISTANCE_TOO_LARGE = "ERR_EXPIRY_DISTANCE_TOO_LARGE"
    ERR_EXPIRY_DISTANCE_TOO_SMALL = "ERR_EXPIRY_DISTANCE_TOO_SMALL"
    ERR_NEAR_LEG_IN_TENDER_OR_ROLLOVER = "ERR_NEAR_LEG_IN_TENDER_OR_ROLLOVER"
    ERR_CONTRACT_EXPIRED = "ERR_CONTRACT_EXPIRED"

    # Liquidity Screening (G3)
    LIQUIDITY_OK = "LIQUIDITY_OK"
    ERR_LOW_VOLUME = "ERR_LOW_VOLUME"
    ERR_LOW_OPEN_INTEREST = "ERR_LOW_OPEN_INTEREST"
    ERR_WIDE_BID_ASK_SPREAD = "ERR_WIDE_BID_ASK_SPREAD"
    ERR_STALE_QUOTE = "ERR_STALE_QUOTE"
    ERR_INSUFFICIENT_OBSERVATION_COUNT = "ERR_INSUFFICIENT_OBSERVATION_COUNT"
    ERR_MISSING_LIQUIDITY_DATA = "ERR_MISSING_LIQUIDITY_DATA"

    # Statistical Analysis (G4)
    STATS_ANOMALY_DETECTED = "STATS_ANOMALY_DETECTED"
    STATS_WITHIN_NORMAL_BAND = "STATS_WITHIN_NORMAL_BAND"
    ERR_INSUFFICIENT_HISTORY = "ERR_INSUFFICIENT_HISTORY"
    ERR_ZERO_SPREAD_VARIANCE = "ERR_ZERO_SPREAD_VARIANCE"
    ERR_UNSTABLE_REGRESSION = "ERR_UNSTABLE_REGRESSION"
    ERR_LOW_CORRELATION = "ERR_LOW_CORRELATION"
    ERR_ZSCORE_EXTREME_STOP = "ERR_ZSCORE_EXTREME_STOP"
    ERR_NON_STATIONARY_SPREAD = "ERR_NON_STATIONARY_SPREAD"

    # Economic Viability & Costs (G5)
    COST_VIABLE = "COST_VIABLE"
    NO_EDGE_COSTS_EXCEED_SPREAD = "NO_EDGE_COSTS_EXCEED_SPREAD"
    NO_EDGE_BELOW_MIN_NET_BPS = "NO_EDGE_BELOW_MIN_NET_BPS"
    NO_EDGE_INSUFFICIENT_NET_RATIO = "NO_EDGE_INSUFFICIENT_NET_RATIO"

    # Research Evidence Sufficiency (G6)
    EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ERR_MISSING_MANDATORY_GATE_INPUT = "ERR_MISSING_MANDATORY_GATE_INPUT"


class AureusError(Exception):
    """Base structured exception for AUREUS-RV 3.0."""

    def __init__(
        self,
        message: str,
        reason_code: ReasonCode,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason_code = reason_code
        self.details = details or {}


class ContractInstanceId(BaseModel):
    """Unambiguous symbol-plus-expiry contract instance identifier."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., min_length=1, description="Base contract symbol, e.g., GOLD, GOLDM")
    expiry_date: date = Field(..., description="Contract maturity / expiry date")

    @property
    def contract_id(self) -> str:
        return f"{self.symbol.upper()}_{self.expiry_date.isoformat()}"

    def __str__(self) -> str:
        return self.contract_id


class PairId(BaseModel):
    """Unambiguous identifier for an ordered pair of contract instances (Leg A vs Leg B)."""

    model_config = ConfigDict(frozen=True)

    near_leg: ContractInstanceId = Field(..., description="Near-expiry or primary leg (Leg A)")
    far_leg: ContractInstanceId = Field(..., description="Far-expiry or secondary leg (Leg B)")

    @property
    def pair_key(self) -> str:
        return f"{self.near_leg.contract_id}__VS__{self.far_leg.contract_id}"

    def __str__(self) -> str:
        return self.pair_key


class QuarantinedRow(BaseModel):
    """Record of an invalid or rejected input observation."""

    row_index: int
    raw_payload: dict[str, Any]
    reason_codes: list[ReasonCode]
    explanation: str
    quarantined_at: datetime


class GateEvaluation(BaseModel):
    """Result of a single decision gate (G0 through G6)."""

    gate_id: str = Field(..., description="Gate identifier G0..G6")
    gate_name: str
    passed: bool
    reason_codes: list[ReasonCode]
    metrics: dict[str, Any] = Field(default_factory=dict)
    explanation: str


class DecisionRecord(BaseModel):
    """Complete auditable decision record emitted by the Decision Engine."""

    decision_id: str
    run_id: str
    timestamp: datetime
    pair_id: str
    near_contract: str
    far_contract: str
    state: DecisionState
    direction: SpreadDirection
    primary_reason_code: ReasonCode
    all_reason_codes: list[ReasonCode]
    gates: dict[str, GateEvaluation]
    metrics: dict[str, float | int | str | bool | None]
    cost_scenario: CostScenarioName
    config_version: str
    config_hash: str
    dataset_hash: str
    is_synthetic: bool
    evidence_refs: list[str]
    disclaimer: str = (
        "RESEARCH CLASSIFICATION ONLY: Not an automated execution order or profitability guarantee."
    )
