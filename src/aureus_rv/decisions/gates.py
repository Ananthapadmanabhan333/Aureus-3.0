"""Deterministic Decision Gate Engine (G0 through G6) for AUREUS-RV 3.0.

Enforces fail-closed evaluation and transitions to one of four states:
- QUIET
- REJECTED
- NO-EDGE
- TRADE SIGNAL
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from aureus_rv.config.settings import AureusConfig
from aureus_rv.costs.waterfall import PairCostWaterfallResult
from aureus_rv.liquidity.screener import LiquidityScreenResult
from aureus_rv.models import (
    CostScenarioName,
    DecisionRecord,
    DecisionState,
    GateEvaluation,
    PairId,
    ReasonCode,
    SpreadDirection,
)
from aureus_rv.pairing.engine import PairEligibilityResult
from aureus_rv.statistics.spread import SpreadDiagnosticsResult


def _build_decision_id(run_id: str, timestamp: datetime, pair_key: str, scenario: str) -> str:
    payload = f"{run_id}|{timestamp.isoformat()}|{pair_key}|{scenario}"
    return "DEC-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16].upper()


def evaluate_decision_gates(
    run_id: str,
    timestamp: datetime,
    pair_id: PairId,
    config: AureusConfig,
    dataset_hash: str,
    is_synthetic: bool,
    g0_data_valid: bool,
    g0_reasons: list[ReasonCode],
    g1_spec_valid: bool,
    g1_reasons: list[ReasonCode],
    pairing_result: PairEligibilityResult | None,
    liquidity_result: LiquidityScreenResult | None,
    stats_result: SpreadDiagnosticsResult | None,
    cost_result: PairCostWaterfallResult | None,
    evidence_sufficient: bool = True,
    evidence_reasons: list[ReasonCode] | None = None,
    evidence_refs: list[str] | None = None,
) -> DecisionRecord:
    """Evaluate gates G0 through G6 deterministically with fail-closed semantics."""
    gates: dict[str, GateEvaluation] = {}
    all_reasons: list[ReasonCode] = []

    # G0: Data Quality
    g0_r = g0_reasons if g0_reasons else ([ReasonCode.VALID_OK] if g0_data_valid else [ReasonCode.ERR_MISSING_REQUIRED_FIELD])
    gates["G0"] = GateEvaluation(
        gate_id="G0",
        gate_name="Data Quality Validation",
        passed=bool(g0_data_valid),
        reason_codes=g0_r,
        metrics={"is_synthetic": is_synthetic},
        explanation="Observation passed data-quality validation" if g0_data_valid else "Data quality validation failed",
    )

    # G1: Contract Specification & Normalization Validity
    g1_r = g1_reasons if g1_reasons else ([ReasonCode.VALID_OK] if g1_spec_valid else [ReasonCode.ERR_SPEC_QUOTATION_MISMATCH])
    gates["G1"] = GateEvaluation(
        gate_id="G1",
        gate_name="Specification & Normalization Validity",
        passed=bool(g1_spec_valid),
        reason_codes=g1_r,
        metrics={"near_symbol": pair_id.near_leg.symbol, "far_symbol": pair_id.far_leg.symbol},
        explanation="Contract specs and 999 INR/g normalization verified" if g1_spec_valid else "Specification validation failed",
    )

    # G2: Pairing & Expiry Eligibility
    if pairing_result is None:
        gates["G2"] = GateEvaluation(
            gate_id="G2",
            gate_name="Pairing & Expiry Eligibility",
            passed=False,
            reason_codes=[ReasonCode.ERR_MISSING_MANDATORY_GATE_INPUT],
            explanation="Missing mandatory pairing eligibility input (fail closed)",
        )
    else:
        gates["G2"] = GateEvaluation(
            gate_id="G2",
            gate_name="Pairing & Expiry Eligibility",
            passed=pairing_result.eligible,
            reason_codes=pairing_result.reason_codes,
            metrics={
                "dte_near": pairing_result.days_to_expiry_near,
                "dte_far": pairing_result.days_to_expiry_far,
                "expiry_gap_days": pairing_result.expiry_gap_days,
                "near_in_rollover": pairing_result.near_in_tender_or_rollover,
            },
            explanation=pairing_result.explanation,
        )

    # G3: Liquidity Screening
    if liquidity_result is None:
        gates["G3"] = GateEvaluation(
            gate_id="G3",
            gate_name="Historical Liquidity Screening",
            passed=False,
            reason_codes=[ReasonCode.ERR_MISSING_MANDATORY_GATE_INPUT],
            explanation="Missing mandatory liquidity screening input (fail closed)",
        )
    else:
        gates["G3"] = GateEvaluation(
            gate_id="G3",
            gate_name="Historical Liquidity Screening",
            passed=liquidity_result.passed,
            reason_codes=liquidity_result.reason_codes,
            metrics={
                "near_volume_lots": liquidity_result.near_volume_lots,
                "far_volume_lots": liquidity_result.far_volume_lots,
                "near_oi_lots": liquidity_result.near_open_interest_lots,
                "far_oi_lots": liquidity_result.far_open_interest_lots,
                "near_ba_bps": liquidity_result.near_bid_ask_spread_bps,
                "far_ba_bps": liquidity_result.far_bid_ask_spread_bps,
                "obs_count": liquidity_result.observation_count_window,
            },
            explanation=liquidity_result.explanation,
        )

    # G4: Statistical Evidence
    if stats_result is None:
        gates["G4"] = GateEvaluation(
            gate_id="G4",
            gate_name="Statistical Spread Diagnostics",
            passed=False,
            reason_codes=[ReasonCode.ERR_MISSING_MANDATORY_GATE_INPUT],
            explanation="Missing mandatory statistical diagnostics input (fail closed)",
        )
    else:
        gates["G4"] = GateEvaluation(
            gate_id="G4",
            gate_name="Statistical Spread Diagnostics",
            passed=stats_result.valid_statistics and stats_result.anomaly_detected,
            reason_codes=stats_result.reason_codes,
            metrics={
                "z_score": stats_result.z_score,
                "norm_spread_inr_g_999": stats_result.norm_spread_inr_g_999,
                "spread_bps": stats_result.spread_bps,
                "correlation": stats_result.correlation,
                "ols_beta": stats_result.ols_beta,
                "expected_reversion_bps": stats_result.expected_reversion_bps,
            },
            explanation=stats_result.explanation,
        )

    # G5: Transaction-Cost & Economic Viability
    if cost_result is None:
        gates["G5"] = GateEvaluation(
            gate_id="G5",
            gate_name="Transaction-Cost & Economic Viability",
            passed=False,
            reason_codes=[ReasonCode.ERR_MISSING_MANDATORY_GATE_INPUT],
            explanation="Missing mandatory transaction-cost waterfall input (fail closed)",
        )
    else:
        gates["G5"] = GateEvaluation(
            gate_id="G5",
            gate_name="Transaction-Cost & Economic Viability",
            passed=cost_result.viable,
            reason_codes=cost_result.reason_codes,
            metrics={
                "gross_expected_bps": cost_result.gross_expected_convergence_bps,
                "total_cost_bps": cost_result.total_round_trip_cost_bps,
                "net_expected_bps": cost_result.net_expected_convergence_bps,
                "gross_to_cost_ratio": cost_result.gross_to_cost_ratio,
            },
            explanation=cost_result.explanation,
        )

    # G6: Research Evidence Sufficiency
    g6_r = evidence_reasons if evidence_reasons else (
        [ReasonCode.EVIDENCE_SUFFICIENT] if evidence_sufficient else [ReasonCode.INSUFFICIENT_EVIDENCE]
    )
    gates["G6"] = GateEvaluation(
        gate_id="G6",
        gate_name="Research Evidence Sufficiency",
        passed=bool(evidence_sufficient),
        reason_codes=g6_r,
        metrics={"evidence_sufficient": bool(evidence_sufficient)},
        explanation="Sufficient historical and walk-forward evidence"
        if evidence_sufficient
        else "Insufficient sample size or walk-forward validation evidence (abstain)",
    )

    # Deterministic State Transition Logic (Fail-Closed)
    state: DecisionState
    primary_reason: ReasonCode
    direction = stats_result.suggested_direction if stats_result is not None else SpreadDirection.FLAT

    for g in gates.values():
        for rc in g.reason_codes:
            if rc not in all_reasons:
                all_reasons.append(rc)

    if not gates["G0"].passed:
        state = DecisionState.REJECTED
        primary_reason = gates["G0"].reason_codes[0]
        direction = SpreadDirection.FLAT
    elif not gates["G1"].passed:
        state = DecisionState.REJECTED
        primary_reason = gates["G1"].reason_codes[0]
        direction = SpreadDirection.FLAT
    elif not gates["G2"].passed:
        state = DecisionState.REJECTED
        primary_reason = gates["G2"].reason_codes[0]
        direction = SpreadDirection.FLAT
    elif not gates["G3"].passed:
        state = DecisionState.REJECTED
        primary_reason = gates["G3"].reason_codes[0]
        direction = SpreadDirection.FLAT
    elif stats_result is None or not stats_result.valid_statistics:
        state = DecisionState.REJECTED
        primary_reason = gates["G4"].reason_codes[0]
        direction = SpreadDirection.FLAT
    elif not stats_result.anomaly_detected:
        state = DecisionState.QUIET
        primary_reason = ReasonCode.STATS_WITHIN_NORMAL_BAND
        direction = SpreadDirection.FLAT
    elif not gates["G5"].passed:
        state = DecisionState.NO_EDGE
        primary_reason = gates["G5"].reason_codes[0]
        direction = SpreadDirection.FLAT
    elif not gates["G6"].passed:
        state = DecisionState.REJECTED
        primary_reason = gates["G6"].reason_codes[0]
        direction = SpreadDirection.FLAT
    else:
        state = DecisionState.TRADE_SIGNAL
        primary_reason = ReasonCode.STATS_ANOMALY_DETECTED

    scenario_used = cost_result.scenario_name if cost_result is not None else config.costs.default_scenario

    summary_metrics: dict[str, float | int | str | bool | None] = {
        "dte_near": pairing_result.days_to_expiry_near if pairing_result else None,
        "dte_far": pairing_result.days_to_expiry_far if pairing_result else None,
        "expiry_gap_days": pairing_result.expiry_gap_days if pairing_result else None,
        "norm_near_inr_g_999": stats_result.norm_near_inr_g_999 if stats_result else None,
        "norm_far_inr_g_999": stats_result.norm_far_inr_g_999 if stats_result else None,
        "norm_spread_inr_g_999": stats_result.norm_spread_inr_g_999 if stats_result else None,
        "spread_bps": stats_result.spread_bps if stats_result else None,
        "z_score": stats_result.z_score if stats_result else None,
        "correlation": stats_result.correlation if stats_result else None,
        "gross_expected_bps": cost_result.gross_expected_convergence_bps if cost_result else None,
        "total_cost_bps": cost_result.total_round_trip_cost_bps if cost_result else None,
        "net_expected_bps": cost_result.net_expected_convergence_bps if cost_result else None,
        "breakeven_bps": cost_result.breakeven_convergence_bps if cost_result else None,
    }

    cfg_hash = config.compute_hash()
    dec_id = _build_decision_id(run_id, timestamp, pair_id.pair_key, scenario_used.value)

    return DecisionRecord(
        decision_id=dec_id,
        run_id=run_id,
        timestamp=timestamp,
        pair_id=pair_id.pair_key,
        near_contract=pair_id.near_leg.contract_id,
        far_contract=pair_id.far_leg.contract_id,
        state=state,
        direction=direction,
        primary_reason_code=primary_reason,
        all_reason_codes=all_reasons,
        gates=gates,
        metrics=summary_metrics,
        cost_scenario=CostScenarioName(scenario_used),
        config_version=config.config_version,
        config_hash=cfg_hash,
        dataset_hash=dataset_hash,
        is_synthetic=is_synthetic,
        evidence_refs=evidence_refs or [f"dataset:{dataset_hash[:12]}", f"config:{cfg_hash[:12]}"],
    )
