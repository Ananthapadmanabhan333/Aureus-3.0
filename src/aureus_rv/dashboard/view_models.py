"""Pure-Python view-model builders and upload validators for the AUREUS-RV 3.0 dashboard.

Separating view-model transformations into typed pure functions allows every page's data
contract to be unit- and integration-tested independently of the Streamlit browser runtime.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from aureus_rv.config.settings import AureusConfig, CostScheduleScenario, CostsConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.costs.waterfall import PairCostWaterfallResult, evaluate_pair_costs
from aureus_rv.evidence.manifest import verify_run_manifest
from aureus_rv.ingestion.loader import REQUIRED_SCHEMA_COLUMNS
from aureus_rv.liquidity.screener import LiquidityScreenResult, screen_pair_liquidity
from aureus_rv.models import (
    AureusError,
    ContractInstanceId,
    CostScenarioName,
    DecisionState,
    PairId,
    ReasonCode,
    SpreadDirection,
)
from aureus_rv.normalization.normalizer import normalize_dataframe_observations
from aureus_rv.pairing.engine import (
    PairEligibilityResult,
    align_pair_history_up_to,
    evaluate_pair_eligibility,
)
from aureus_rv.pipeline import ResearchPipelineResult
from aureus_rv.statistics.spread import SpreadDiagnosticsResult, analyze_pair_spread_up_to
from aureus_rv.validation.validator import ValidationReport, validate_dataset

MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024  # 25 MB safety limit
ALLOWED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset({".csv", ".parquet", ".pq"})


class ExecutiveOverviewVM(BaseModel):
    """View model for Page A: Executive Overview."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    software_version: str
    methodology_version: str
    dataset_sha256: str
    config_sha256: str
    manifest_self_sha256: str
    manifest_verified: bool
    is_synthetic_data: bool
    evaluation_period_start: str | None
    evaluation_period_end: str | None
    raw_row_count: int
    valid_row_count: int
    quarantined_row_count: int
    evaluated_pair_count: int
    eligible_pair_count: int
    quiet_count: int
    rejected_count: int
    no_edge_count: int
    trade_signal_count: int
    sufficient_evidence_pairs: int
    insufficient_evidence_pairs: int
    warnings: list[str]


def build_executive_overview_vm(result: ResearchPipelineResult) -> ExecutiveOverviewVM:
    """Construct verified ExecutiveOverviewVM from a completed ResearchPipelineResult."""
    verified, _ = verify_run_manifest(result.manifest_path)
    state_counts = {s: 0 for s in DecisionState}
    eligible_pairs = 0
    for d in result.snapshot_decisions:
        state_counts[d.state] = state_counts.get(d.state, 0) + 1
        if d.gates.get("G2") and d.gates["G2"].passed:
            eligible_pairs += 1

    suff_count = sum(1 for b in result.backtest_reports if b.evidence_status == ReasonCode.EVIDENCE_SUFFICIENT)
    insuff_count = sum(1 for b in result.backtest_reports if b.evidence_status == ReasonCode.INSUFFICIENT_EVIDENCE)

    return ExecutiveOverviewVM(
        run_id=result.run_id,
        software_version=result.manifest.software_version,
        methodology_version=result.manifest.methodology_version,
        dataset_sha256=result.manifest.dataset_sha256,
        config_sha256=result.manifest.config_sha256,
        manifest_self_sha256=result.manifest.manifest_self_sha256,
        manifest_verified=verified,
        is_synthetic_data=result.manifest.is_synthetic_data,
        evaluation_period_start=result.manifest.evaluation_period_start,
        evaluation_period_end=result.manifest.evaluation_period_end,
        raw_row_count=result.validation_report.total_rows,
        valid_row_count=result.validation_report.valid_rows,
        quarantined_row_count=result.validation_report.quarantined_rows,
        evaluated_pair_count=len(result.snapshot_decisions),
        eligible_pair_count=eligible_pairs,
        quiet_count=state_counts[DecisionState.QUIET],
        rejected_count=state_counts[DecisionState.REJECTED],
        no_edge_count=state_counts[DecisionState.NO_EDGE],
        trade_signal_count=state_counts[DecisionState.TRADE_SIGNAL],
        sufficient_evidence_pairs=suff_count,
        insufficient_evidence_pairs=insuff_count,
        warnings=result.manifest.warnings,
    )


def build_contract_explorer_tables(
    norm_df: pd.DataFrame,
    registry: ContractRegistry,
    config: AureusConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build (registry_specs_df, latest_contract_snapshots_df) for Page B: Contract Explorer."""
    spec_rows = [
        {
            "symbol": s.symbol,
            "spec_version": s.spec_version,
            "exchange": s.exchange,
            "quotation_unit": s.quotation_unit.value,
            "quotation_grams": s.quotation_grams,
            "purity_fineness": s.purity_fineness,
            "purity_factor_to_999": round(999.0 / s.purity_fineness, 6),
            "lot_size_grams": s.lot_size_grams,
            "price_multiplier_per_lot": s.price_multiplier_per_lot,
            "tender_period_days": s.tender_period_days,
            "effective_from": s.effective_from.isoformat(),
            "effective_to": s.effective_to.isoformat() if s.effective_to else "ACTIVE",
            "description": s.description,
        }
        for s in registry.list_specs()
    ]
    specs_df = pd.DataFrame(spec_rows)

    if norm_df.empty:
        return specs_df, pd.DataFrame()

    latest_ts = norm_df["timestamp"].max()
    as_of = pd.Timestamp(latest_ts).date()
    latest_rows = norm_df[norm_df["timestamp"] == latest_ts].copy()

    snap_records: list[dict[str, Any]] = []
    for row in latest_rows.itertuples(index=False):
        exp_date = row.expiry_date
        dte = (exp_date - as_of).days
        spec = registry.get_spec(str(row.symbol), as_of)
        rollover_limit = max(config.pairing.min_days_to_expiry_near, spec.tender_period_days)
        eligible_near = dte >= rollover_limit
        snap_records.append(
            {
                "contract_id": row.contract_id,
                "symbol": row.symbol,
                "expiry_date": str(exp_date),
                "days_to_expiry": dte,
                "spec_version": row.spec_version,
                "quotation_unit": row.quotation_unit,
                "purity_fineness": int(row.purity_fineness),
                "raw_close_price": round(float(row.close), 2),
                "norm_close_inr_g_999": round(float(row.norm_close_inr_g_999), 4),
                "lot_size_grams": float(row.lot_size_grams),
                "price_multiplier_per_lot": float(row.price_multiplier_per_lot),
                "raw_notional_per_lot_inr": round(float(row.raw_notional_per_lot_inr), 2),
                "volume_lots": int(row.volume_lots),
                "open_interest_lots": int(row.open_interest_lots),
                "bid_ask_spread_bps": round(float(row.bid_ask_spread_bps), 2),
                "near_leg_eligible": eligible_near,
                "eligibility_status": "ELIGIBLE" if eligible_near else f"TENDER/ROLLOVER (<{rollover_limit}d)",
                "source_provenance": row.source_provenance,
            }
        )
    return specs_df, pd.DataFrame(snap_records).sort_values(["expiry_date", "symbol"]).reset_index(drop=True)


def evaluate_interactive_spread_research(
    norm_df: pd.DataFrame,
    near_contract_id: str,
    far_contract_id: str,
    config: AureusConfig,
    registry: ContractRegistry,
    as_of_timestamp: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, PairEligibilityResult, LiquidityScreenResult, SpreadDiagnosticsResult]:
    """Run real backend pairing, liquidity, and statistical engines for Page C: Spread Research."""
    near_parts = near_contract_id.split("_", 1)
    far_parts = far_contract_id.split("_", 1)
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol=near_parts[0], expiry_date=pd.Timestamp(near_parts[1]).date()),
        far_leg=ContractInstanceId(symbol=far_parts[0], expiry_date=pd.Timestamp(far_parts[1]).date()),
    )
    cutoff_ts = as_of_timestamp if as_of_timestamp is not None else norm_df["timestamp"].max()
    aligned = align_pair_history_up_to(norm_df, pair_id, cutoff_ts)

    pairing_res = evaluate_pair_eligibility(
        near_leg=pair_id.near_leg,
        far_leg=pair_id.far_leg,
        as_of_date=pd.Timestamp(cutoff_ts).date(),
        config=config.pairing,
        registry=registry,
    )
    liq_res = screen_pair_liquidity(aligned, pair_id, config.liquidity)
    stats_res = analyze_pair_spread_up_to(aligned, pair_id, config.statistics)

    # Enrich aligned DataFrame with rolling spread series for charting (strictly past-only rolling window)
    if not aligned.empty:
        chart_df = aligned.copy()
        w = config.statistics.rolling_window
        chart_df["raw_spread_unnormalized"] = chart_df["close_near"] - chart_df["close_far"]
        chart_df["norm_spread_inr_g_999"] = (
            chart_df["norm_close_inr_g_999_near"] - chart_df["norm_close_inr_g_999_far"]
        )
        chart_df["norm_mid_ref_inr_g_999"] = 0.5 * (
            chart_df["norm_close_inr_g_999_near"] + chart_df["norm_close_inr_g_999_far"]
        )
        chart_df["spread_bps"] = (chart_df["norm_spread_inr_g_999"] / chart_df["norm_mid_ref_inr_g_999"]) * 10000.0
        chart_df["rolling_mean_inr_g_999"] = chart_df["norm_spread_inr_g_999"].rolling(w, min_periods=5).mean()
        chart_df["rolling_std_inr_g_999"] = chart_df["norm_spread_inr_g_999"].rolling(w, min_periods=5).std(ddof=1)
        chart_df["rolling_z_score"] = (
            chart_df["norm_spread_inr_g_999"] - chart_df["rolling_mean_inr_g_999"]
        ) / chart_df["rolling_std_inr_g_999"].replace(0.0, float("nan"))
    else:
        chart_df = aligned

    return chart_df, pairing_res, liq_res, stats_res


def run_interactive_cost_lab(
    pair_id: PairId,
    direction: SpreadDirection,
    norm_near_inr_g_999: float,
    norm_far_inr_g_999: float,
    near_bid_ask_spread_bps: float,
    far_bid_ask_spread_bps: float,
    gross_expected_convergence_inr_g_999: float,
    notional_grams: float,
    active_scenario: CostScenarioName,
    custom_brokerage_bps: float,
    custom_exchange_bps: float,
    custom_sebi_bps: float,
    custom_ctt_sell_bps: float,
    custom_stamp_buy_bps: float,
    custom_gst_fraction: float,
    custom_slippage_bps: float,
    custom_half_spread_mult: float,
    min_net_edge_bps: float,
    min_gross_to_cost_ratio: float,
) -> PairCostWaterfallResult:
    """Recalculate full two-leg transaction cost waterfall through the real cost engine for Page D."""
    base_costs = CostsConfig(
        default_scenario=active_scenario,
        min_net_edge_bps=min_net_edge_bps,
        min_gross_to_cost_ratio=min_gross_to_cost_ratio,
    )
    scenarios_map = dict(base_costs.scenarios)
    scenarios_map[active_scenario] = CostScheduleScenario(
        scenario_name=active_scenario,
        brokerage_bps_per_leg=custom_brokerage_bps,
        exchange_txn_bps_per_leg=custom_exchange_bps,
        sebi_turnover_bps_per_leg=custom_sebi_bps,
        ctt_sell_bps=custom_ctt_sell_bps,
        stamp_duty_buy_bps=custom_stamp_buy_bps,
        gst_rate_fraction=custom_gst_fraction,
        slippage_bps_per_leg=custom_slippage_bps,
        half_spread_multiplier=custom_half_spread_mult,
    )
    updated_cfg = base_costs.model_copy(update={"scenarios": scenarios_map})
    return evaluate_pair_costs(
        pair_id=pair_id,
        direction=direction,
        norm_near_inr_g_999=norm_near_inr_g_999,
        norm_far_inr_g_999=norm_far_inr_g_999,
        near_bid_ask_spread_bps=near_bid_ask_spread_bps,
        far_bid_ask_spread_bps=far_bid_ask_spread_bps,
        gross_expected_convergence_inr_g_999=gross_expected_convergence_inr_g_999,
        notional_grams=notional_grams,
        costs_config=updated_cfg,
        scenario=active_scenario,
    )


def validate_and_ingest_uploaded_bytes(
    filename: str,
    raw_bytes: bytes,
    registry: ContractRegistry,
    save_dir: str | Path,
) -> tuple[Path, pd.DataFrame, ValidationReport, str]:
    """Safely validate file extension, size, schema, and rows of an uploaded dataset without executing anything."""
    if not raw_bytes:
        raise AureusError(
            "Uploaded file is empty (0 bytes).",
            reason_code=ReasonCode.ERR_MISSING_REQUIRED_FIELD,
        )
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise AureusError(
            f"Uploaded file exceeds maximum size limit ({MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
            reason_code=ReasonCode.ERR_MISSING_REQUIRED_FIELD,
        )

    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise AureusError(
            f"Unsupported upload extension '{suffix}'. Allowed: {sorted(ALLOWED_UPLOAD_EXTENSIONS)}",
            reason_code=ReasonCode.ERR_MISSING_REQUIRED_FIELD,
        )

    sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
    target_dir = Path(save_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_path = target_dir / f"upload_{sha256_hex[:10]}_{safe_name}"
    saved_path.write_bytes(raw_bytes)

    if suffix == ".csv":
        raw_df = pd.read_csv(saved_path)
    else:
        raw_df = pd.read_parquet(saved_path)

    missing_cols = [c for c in REQUIRED_SCHEMA_COLUMNS if c not in raw_df.columns]
    if missing_cols:
        raise AureusError(
            f"Uploaded dataset is missing required schema columns: {missing_cols}",
            reason_code=ReasonCode.ERR_MISSING_REQUIRED_FIELD,
            details={"missing_columns": missing_cols},
        )

    clean_df, val_report = validate_dataset(raw_df, registry)
    norm_df = normalize_dataframe_observations(clean_df, registry)
    return saved_path, norm_df, val_report, sha256_hex
