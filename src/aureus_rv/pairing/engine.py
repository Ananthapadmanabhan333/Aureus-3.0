"""Expiry-aware contract pairing, tender-period rollover checks, and time-to-expiry calculation."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict

from aureus_rv.config.settings import PairingConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.models import ContractInstanceId, PairId, ReasonCode


class PairEligibilityResult(BaseModel):
    """Eligibility evaluation of a candidate contract pair at a specific decision timestamp."""

    model_config = ConfigDict(frozen=True)

    pair_id: PairId
    as_of_date: date
    eligible: bool
    reason_codes: list[ReasonCode]
    days_to_expiry_near: int
    days_to_expiry_far: int
    expiry_gap_days: int
    near_in_tender_or_rollover: bool
    explanation: str


def evaluate_pair_eligibility(
    near_leg: ContractInstanceId,
    far_leg: ContractInstanceId,
    as_of_date: date,
    config: PairingConfig,
    registry: ContractRegistry,
) -> PairEligibilityResult:
    """Evaluate whether `near_leg` and `far_leg` form an eligible relative-value pair on `as_of_date`."""
    reasons: list[ReasonCode] = []
    explanations: list[str] = []

    dte_near = (near_leg.expiry_date - as_of_date).days
    dte_far = (far_leg.expiry_date - as_of_date).days
    gap_days = (far_leg.expiry_date - near_leg.expiry_date).days

    # Check identical instance
    if near_leg == far_leg:
        reasons.append(ReasonCode.ERR_IDENTICAL_CONTRACT_INSTANCE)
        explanations.append("Near and far legs are the exact same contract instance")

    # Check cross-symbol constraint if disabled
    if not config.allow_cross_symbol_pairing and near_leg.symbol.upper() != far_leg.symbol.upper():
        reasons.append(ReasonCode.ERR_SPEC_QUOTATION_MISMATCH)
        explanations.append("Cross-symbol pairing is disabled in PairingConfig")

    # Check expired
    if dte_near <= 0 or dte_far <= 0:
        reasons.append(ReasonCode.ERR_CONTRACT_EXPIRED)
        explanations.append(f"Contract expired or expiring today: dte_near={dte_near}, dte_far={dte_far}")

    # Check inverted expiry
    if gap_days < 0:
        reasons.append(ReasonCode.ERR_INVERTED_PAIR_EXPIRY)
        explanations.append(f"Far leg expiry ({far_leg.expiry_date}) precedes near leg expiry ({near_leg.expiry_date})")

    # Check expiry gap limits (for calendar spreads or cross-expiry spreads)
    # Note: Same-expiry cross-variant spreads (e.g. GOLD vs GOLDM same month) are allowed if min_expiry_gap_days == 0
    if gap_days >= 0:
        if gap_days < config.min_expiry_gap_days:
            reasons.append(ReasonCode.ERR_EXPIRY_DISTANCE_TOO_SMALL)
            explanations.append(
                f"Expiry gap {gap_days}d is less than min_expiry_gap_days ({config.min_expiry_gap_days}d)"
            )
        if gap_days > config.max_expiry_gap_days:
            reasons.append(ReasonCode.ERR_EXPIRY_DISTANCE_TOO_LARGE)
            explanations.append(
                f"Expiry gap {gap_days}d exceeds max_expiry_gap_days ({config.max_expiry_gap_days}d)"
            )

    # Check tender period / rollover freeze on near leg
    near_spec = registry.get_spec(near_leg.symbol, as_of_date)
    rollover_threshold = max(config.min_days_to_expiry_near, near_spec.tender_period_days)
    in_rollover = dte_near < rollover_threshold
    if in_rollover and dte_near > 0:
        reasons.append(ReasonCode.ERR_NEAR_LEG_IN_TENDER_OR_ROLLOVER)
        explanations.append(
            f"Near leg DTE ({dte_near}d) is within tender/rollover freeze threshold ({rollover_threshold}d)"
        )

    if not reasons:
        reasons = [ReasonCode.PAIR_OK]
        explanations.append("Pair passed all expiry and lifecycle eligibility checks")

    return PairEligibilityResult(
        pair_id=PairId(near_leg=near_leg, far_leg=far_leg),
        as_of_date=as_of_date,
        eligible=(reasons == [ReasonCode.PAIR_OK]),
        reason_codes=reasons,
        days_to_expiry_near=dte_near,
        days_to_expiry_far=dte_far,
        expiry_gap_days=gap_days,
        near_in_tender_or_rollover=in_rollover,
        explanation="; ".join(explanations),
    )


def discover_candidate_pairs_at_timestamp(
    df_at_ts: pd.DataFrame,
    timestamp: datetime | pd.Timestamp,
    config: PairingConfig,
    registry: ContractRegistry,
) -> list[PairEligibilityResult]:
    """Discover and evaluate ordered candidate pairs present at `timestamp`."""
    as_of = pd.Timestamp(timestamp).date()
    contracts: list[ContractInstanceId] = []
    for row in df_at_ts[["symbol", "expiry_date"]].drop_duplicates().itertuples(index=False):
        exp_date = row.expiry_date if isinstance(row.expiry_date, date) else pd.Timestamp(row.expiry_date).date()
        contracts.append(ContractInstanceId(symbol=str(row.symbol).upper(), expiry_date=exp_date))

    contracts.sort(key=lambda c: (c.expiry_date, c.symbol))
    results: list[PairEligibilityResult] = []
    for i, c1 in enumerate(contracts):
        for c2 in contracts[i + 1 :]:
            res = evaluate_pair_eligibility(
                near_leg=c1,
                far_leg=c2,
                as_of_date=as_of,
                config=config,
                registry=registry,
            )
            results.append(res)
    return results


def align_pair_history_up_to(
    normalized_df: pd.DataFrame,
    pair_id: PairId,
    as_of_timestamp: datetime | pd.Timestamp,
) -> pd.DataFrame:
    """Build strictly past-only aligned time series for `pair_id` up to and including `as_of_timestamp`.

    Prevents look-ahead leakage by filtering `timestamp <= as_of_timestamp` before joining legs.
    """
    cutoff = pd.Timestamp(as_of_timestamp)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")

    past_df = normalized_df[normalized_df["timestamp"] <= cutoff].copy()
    near_id = pair_id.near_leg.contract_id
    far_id = pair_id.far_leg.contract_id

    near_df = past_df[past_df["contract_id"] == near_id].add_suffix("_near")
    far_df = past_df[past_df["contract_id"] == far_id].add_suffix("_far")

    merged = pd.merge(
        near_df,
        far_df,
        left_on="timestamp_near",
        right_on="timestamp_far",
        how="inner",
    )
    if merged.empty:
        return merged

    merged = merged.rename(columns={"timestamp_near": "timestamp"}).drop(columns=["timestamp_far"])
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    return merged
