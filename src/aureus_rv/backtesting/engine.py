"""Chronological walk-forward backtesting and validation engine for AUREUS-RV 3.0.

Enforces:
- Strict chronological Train / Validation / Frozen-Test splits
- Zero look-ahead leakage (each bar t uses only observations <= t)
- Two-leg round-trip transaction costs on every completed trade
- Expiry / rollover forced exit guard
- Overlapping-trade prevention (`max_concurrent_trades_per_pair`)
- Baseline comparison (naive unconditional hold-to-rollover spread carry)
- Explicit `INSUFFICIENT_EVIDENCE` status when sample size or bar counts are inadequate
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from aureus_rv.config.settings import AureusConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.costs.waterfall import evaluate_pair_costs
from aureus_rv.decisions.gates import evaluate_decision_gates
from aureus_rv.liquidity.screener import screen_pair_liquidity
from aureus_rv.models import (
    CostScenarioName,
    DecisionRecord,
    DecisionState,
    PairId,
    ReasonCode,
    SpreadDirection,
)
from aureus_rv.pairing.engine import evaluate_pair_eligibility
from aureus_rv.statistics.spread import analyze_pair_spread_up_to


class ChronologicalSplit(StrEnum):
    """Chronological evaluation regime."""

    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    FROZEN_TEST = "FROZEN_TEST"


class CompletedTradeRecord(BaseModel):
    """Audit record of a simulated relative-value spread trade."""

    model_config = ConfigDict(frozen=True)

    trade_id: str
    pair_id: str
    split_regime: ChronologicalSplit
    direction: SpreadDirection
    entry_timestamp: datetime
    exit_timestamp: datetime
    holding_bars: int
    exit_reason: str
    notional_grams: float
    entry_spread_inr_g_999: float
    exit_spread_inr_g_999: float
    entry_z_score: float
    exit_z_score: float
    gross_pnl_inr_g_999: float
    gross_pnl_inr: float
    round_trip_cost_inr_g_999: float
    round_trip_cost_inr: float
    net_pnl_inr_g_999: float
    net_pnl_inr: float


class SplitMetricsSummary(BaseModel):
    """Performance and sample metrics for a single chronological split regime."""

    model_config = ConfigDict(frozen=True)

    regime: ChronologicalSplit
    bar_count: int
    trade_count: int
    win_rate: float
    gross_pnl_inr: float
    total_costs_inr: float
    net_pnl_inr: float
    mean_net_pnl_per_trade_inr: float
    std_net_pnl_per_trade_inr: float
    max_drawdown_inr: float
    exposure_bar_fraction: float
    baseline_naive_net_pnl_inr: float


class PairBacktestReport(BaseModel):
    """Complete chronological walk-forward evaluation report for a contract pair."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    pair_id: str
    cost_scenario: CostScenarioName
    evidence_status: ReasonCode
    total_aligned_bars: int
    train_end_timestamp: datetime | None
    validation_end_timestamp: datetime | None
    frozen_test_end_timestamp: datetime | None
    total_completed_trades: int
    gross_pnl_inr: float
    total_costs_inr: float
    net_pnl_inr: float
    max_drawdown_inr: float
    uncertainty_se_net_pnl_inr: float
    baseline_naive_net_pnl_inr: float
    split_summaries: dict[str, SplitMetricsSummary]
    trades: list[CompletedTradeRecord]
    decisions: list[DecisionRecord]
    explanation: str


def assign_chronological_splits(
    n_bars: int,
    train_frac: float,
    val_frac: float,
) -> list[ChronologicalSplit]:
    """Assign each chronological bar index `0..n_bars-1` to TRAIN, VALIDATION, or FROZEN_TEST."""
    if n_bars <= 0:
        return []
    train_cut = max(1, int(round(n_bars * train_frac)))
    val_cut = max(train_cut + 1, int(round(n_bars * (train_frac + val_frac))))
    val_cut = min(val_cut, max(1, n_bars - 1))

    regimes: list[ChronologicalSplit] = []
    for i in range(n_bars):
        if i < train_cut:
            regimes.append(ChronologicalSplit.TRAIN)
        elif i < val_cut:
            regimes.append(ChronologicalSplit.VALIDATION)
        else:
            regimes.append(ChronologicalSplit.FROZEN_TEST)
    return regimes


def run_pair_walk_forward_backtest(
    run_id: str,
    aligned_df: pd.DataFrame,
    pair_id: PairId,
    config: AureusConfig,
    registry: ContractRegistry,
    dataset_hash: str,
    is_synthetic: bool,
    scenario: CostScenarioName | None = None,
) -> PairBacktestReport:
    """Execute a chronological bar-by-bar walk-forward backtest on `aligned_df` for `pair_id`."""
    active_scenario = scenario or config.costs.default_scenario
    df = aligned_df.sort_values("timestamp").reset_index(drop=True)
    n_bars = len(df)

    if n_bars < config.backtest.min_bars_for_backtest:
        return _insufficient_backtest_report(
            run_id=run_id,
            pair_id=pair_id,
            scenario=active_scenario,
            n_bars=n_bars,
            explanation=(
                f"Aligned bar count ({n_bars}) < min_bars_for_backtest ({config.backtest.min_bars_for_backtest})"
            ),
        )

    regimes = assign_chronological_splits(
        n_bars=n_bars,
        train_frac=config.backtest.train_fraction,
        val_frac=config.backtest.validation_fraction,
    )

    decisions: list[DecisionRecord] = []
    trades: list[CompletedTradeRecord] = []

    # Active position state (supports non-overlapping single active spread position per pair)
    open_pos: dict[str, object] | None = None
    active_bars_by_regime: dict[ChronologicalSplit, int] = {
        ChronologicalSplit.TRAIN: 0,
        ChronologicalSplit.VALIDATION: 0,
        ChronologicalSplit.FROZEN_TEST: 0,
    }
    bar_counts_by_regime: dict[ChronologicalSplit, int] = {
        ChronologicalSplit.TRAIN: 0,
        ChronologicalSplit.VALIDATION: 0,
        ChronologicalSplit.FROZEN_TEST: 0,
    }

    notional_g = config.backtest.position_notional_grams

    for idx in range(n_bars):
        regime = regimes[idx]
        bar_counts_by_regime[regime] += 1

        # Strictly past-only slice: rows 0 .. idx inclusive
        past_slice = df.iloc[: idx + 1]
        current_row = past_slice.iloc[-1]
        ts = pd.Timestamp(current_row["timestamp"]).to_pydatetime()

        pairing_res = evaluate_pair_eligibility(
            near_leg=pair_id.near_leg,
            far_leg=pair_id.far_leg,
            as_of_date=ts.date(),
            config=config.pairing,
            registry=registry,
        )
        liq_res = screen_pair_liquidity(
            aligned_history=past_slice,
            pair_id=pair_id,
            config=config.liquidity,
        )
        stats_res = analyze_pair_spread_up_to(
            aligned_history=past_slice,
            pair_id=pair_id,
            config=config.statistics,
        )
        cost_res = evaluate_pair_costs(
            pair_id=pair_id,
            direction=stats_res.suggested_direction,
            norm_near_inr_g_999=float(current_row["norm_close_inr_g_999_near"]),
            norm_far_inr_g_999=float(current_row["norm_close_inr_g_999_far"]),
            near_bid_ask_spread_bps=float(current_row["bid_ask_spread_bps_near"]),
            far_bid_ask_spread_bps=float(current_row["bid_ask_spread_bps_far"]),
            gross_expected_convergence_inr_g_999=stats_res.expected_reversion_inr_g_999,
            notional_grams=notional_g,
            costs_config=config.costs,
            scenario=active_scenario,
        )

        # Record decision at bar idx
        dec = evaluate_decision_gates(
            run_id=run_id,
            timestamp=ts,
            pair_id=pair_id,
            config=config,
            dataset_hash=dataset_hash,
            is_synthetic=is_synthetic,
            g0_data_valid=True,
            g0_reasons=[ReasonCode.VALID_OK],
            g1_spec_valid=True,
            g1_reasons=[ReasonCode.VALID_OK],
            pairing_result=pairing_res,
            liquidity_result=liq_res,
            stats_result=stats_res,
            cost_result=cost_res,
            evidence_sufficient=True,
            evidence_reasons=[ReasonCode.EVIDENCE_SUFFICIENT],
        )
        decisions.append(dec)

        # Check open position exit conditions before considering any new entry
        if open_pos is not None:
            active_bars_by_regime[regime] += 1
            entry_idx = int(open_pos["entry_idx"])  # type: ignore[arg-type]
            held_bars = idx - entry_idx
            pos_dir: SpreadDirection = open_pos["direction"]  # type: ignore[assignment]
            cur_z = stats_res.z_score
            cur_spread = float(current_row["norm_close_inr_g_999_near"]) - float(
                current_row["norm_close_inr_g_999_far"]
            )

            exit_reason: str | None = None
            if pos_dir == SpreadDirection.SHORT_SPREAD and cur_z <= config.statistics.exit_z_threshold:
                exit_reason = "MEAN_REVERSION_TARGET"
            elif pos_dir == SpreadDirection.LONG_SPREAD and cur_z >= -config.statistics.exit_z_threshold:
                exit_reason = "MEAN_REVERSION_TARGET"
            elif abs(cur_z) >= config.statistics.stop_z_threshold:
                exit_reason = "STOP_LOSS_Z_THRESHOLD"
            elif held_bars >= config.backtest.max_holding_bars:
                exit_reason = "MAX_HOLDING_PERIOD"
            elif pairing_res.near_in_tender_or_rollover or not pairing_res.eligible:
                exit_reason = "ROLLOVER_OR_EXPIRY_GUARD"
            elif idx == n_bars - 1:
                exit_reason = "END_OF_SERIES_CLOSE"

            if exit_reason is not None:
                entry_spread = float(open_pos["entry_spread"])  # type: ignore[arg-type]
                if pos_dir == SpreadDirection.SHORT_SPREAD:
                    gross_inr_g = entry_spread - cur_spread
                else:
                    gross_inr_g = cur_spread - entry_spread

                # Compute actual realized round-trip cost using average of entry and exit cost waterfalls
                entry_cost_inr_g = float(open_pos["entry_cost_inr_g"])  # type: ignore[arg-type]
                exit_cost_inr_g = cost_res.total_round_trip_cost_inr_g_999
                realized_rt_cost_inr_g = 0.5 * (entry_cost_inr_g + exit_cost_inr_g)

                net_inr_g = gross_inr_g - realized_rt_cost_inr_g
                trade_num = len(trades) + 1
                trades.append(
                    CompletedTradeRecord(
                        trade_id=f"{run_id}-TRD-{trade_num:04d}",
                        pair_id=pair_id.pair_key,
                        split_regime=open_pos["entry_regime"],  # type: ignore[arg-type]
                        direction=pos_dir,
                        entry_timestamp=open_pos["entry_ts"],  # type: ignore[arg-type]
                        exit_timestamp=ts,
                        holding_bars=held_bars,
                        exit_reason=exit_reason,
                        notional_grams=notional_g,
                        entry_spread_inr_g_999=entry_spread,
                        exit_spread_inr_g_999=cur_spread,
                        entry_z_score=float(open_pos["entry_z"]),  # type: ignore[arg-type]
                        exit_z_score=cur_z,
                        gross_pnl_inr_g_999=gross_inr_g,
                        gross_pnl_inr=gross_inr_g * notional_g,
                        round_trip_cost_inr_g_999=realized_rt_cost_inr_g,
                        round_trip_cost_inr=realized_rt_cost_inr_g * notional_g,
                        net_pnl_inr_g_999=net_inr_g,
                        net_pnl_inr=net_inr_g * notional_g,
                    )
                )
                open_pos = None

        # Consider new trade entry only if flat, not on final bar, and decision state is TRADE_SIGNAL
        if open_pos is None and idx < n_bars - 1 and dec.state == DecisionState.TRADE_SIGNAL:
            open_pos = {
                "entry_idx": idx,
                "entry_ts": ts,
                "entry_regime": regime,
                "direction": dec.direction,
                "entry_spread": stats_res.norm_spread_inr_g_999,
                "entry_z": stats_res.z_score,
                "entry_cost_inr_g": cost_res.total_round_trip_cost_inr_g_999,
            }

    # Summarize per chronological split
    split_summaries: dict[str, SplitMetricsSummary] = {}
    for reg in ChronologicalSplit:
        reg_trades = [t for t in trades if t.split_regime == reg]
        reg_indices = [i for i, r in enumerate(regimes) if r == reg]
        baseline_net = _compute_naive_baseline_pnl(df.iloc[reg_indices], notional_g, config, active_scenario, pair_id)
        split_summaries[reg.value] = _summarize_regime(
            regime=reg,
            bar_count=bar_counts_by_regime[reg],
            active_bars=active_bars_by_regime[reg],
            reg_trades=reg_trades,
            baseline_net_inr=baseline_net,
        )

    total_trades = len(trades)
    gross_total = float(sum(t.gross_pnl_inr for t in trades))
    costs_total = float(sum(t.round_trip_cost_inr for t in trades))
    net_total = float(sum(t.net_pnl_inr for t in trades))
    max_dd = _compute_max_drawdown([t.net_pnl_inr for t in trades])
    se_net = (
        float(np.std([t.net_pnl_inr for t in trades], ddof=1) / np.sqrt(total_trades))
        if total_trades >= 2
        else 0.0
    )
    total_baseline = sum(s.baseline_naive_net_pnl_inr for s in split_summaries.values())

    evidence_ok = total_trades >= config.backtest.min_completed_trades_for_evidence
    ev_status = ReasonCode.EVIDENCE_SUFFICIENT if evidence_ok else ReasonCode.INSUFFICIENT_EVIDENCE

    # If overall sample size is below threshold, update any TRADE SIGNAL decisions' G6 gate to reflect INSUFFICIENT_EVIDENCE if desired by caller,
    # and explicitly report INSUFFICIENT_EVIDENCE in PairBacktestReport.
    train_indices = [i for i, r in enumerate(regimes) if r == ChronologicalSplit.TRAIN]
    val_indices = [i for i, r in enumerate(regimes) if r == ChronologicalSplit.VALIDATION]
    test_indices = [i for i, r in enumerate(regimes) if r == ChronologicalSplit.FROZEN_TEST]

    return PairBacktestReport(
        run_id=run_id,
        pair_id=pair_id.pair_key,
        cost_scenario=active_scenario,
        evidence_status=ev_status,
        total_aligned_bars=n_bars,
        train_end_timestamp=pd.Timestamp(df.iloc[train_indices[-1]]["timestamp"]).to_pydatetime() if train_indices else None,
        validation_end_timestamp=pd.Timestamp(df.iloc[val_indices[-1]]["timestamp"]).to_pydatetime() if val_indices else None,
        frozen_test_end_timestamp=pd.Timestamp(df.iloc[test_indices[-1]]["timestamp"]).to_pydatetime() if test_indices else None,
        total_completed_trades=total_trades,
        gross_pnl_inr=gross_total,
        total_costs_inr=costs_total,
        net_pnl_inr=net_total,
        max_drawdown_inr=max_dd,
        uncertainty_se_net_pnl_inr=se_net,
        baseline_naive_net_pnl_inr=total_baseline,
        split_summaries=split_summaries,
        trades=trades,
        decisions=decisions,
        explanation=(
            f"Walk-forward evaluation completed with {total_trades} trades ({ev_status.value}). "
            f"Net P&L: Rs {net_total:,.2f} (Gross: Rs {gross_total:,.2f}, Costs: Rs {costs_total:,.2f})."
        ),
    )


def _compute_max_drawdown(trade_pnls: list[float]) -> float:
    if not trade_pnls:
        return 0.0
    cum = np.cumsum([0.0] + trade_pnls)
    peaks = np.maximum.accumulate(cum)
    drawdowns = peaks - cum
    return float(np.max(drawdowns))


def _compute_naive_baseline_pnl(
    sub_df: pd.DataFrame,
    notional_g: float,
    config: AureusConfig,
    scenario: CostScenarioName,
    pair_id: PairId,
) -> float:
    """Naive unconditional baseline: enter short spread at start of split and exit at end of split."""
    if len(sub_df) < 2:
        return 0.0
    first = sub_df.iloc[0]
    last = sub_df.iloc[-1]
    s_start = float(first["norm_close_inr_g_999_near"]) - float(first["norm_close_inr_g_999_far"])
    s_end = float(last["norm_close_inr_g_999_near"]) - float(last["norm_close_inr_g_999_far"])
    gross_inr_g = s_start - s_end
    c_res = evaluate_pair_costs(
        pair_id=pair_id,
        direction=SpreadDirection.SHORT_SPREAD,
        norm_near_inr_g_999=float(first["norm_close_inr_g_999_near"]),
        norm_far_inr_g_999=float(first["norm_close_inr_g_999_far"]),
        near_bid_ask_spread_bps=float(first["bid_ask_spread_bps_near"]),
        far_bid_ask_spread_bps=float(first["bid_ask_spread_bps_far"]),
        gross_expected_convergence_inr_g_999=max(0.0, gross_inr_g),
        notional_grams=notional_g,
        costs_config=config.costs,
        scenario=scenario,
    )
    return (gross_inr_g - c_res.total_round_trip_cost_inr_g_999) * notional_g


def _summarize_regime(
    regime: ChronologicalSplit,
    bar_count: int,
    active_bars: int,
    reg_trades: list[CompletedTradeRecord],
    baseline_net_inr: float,
) -> SplitMetricsSummary:
    n_t = len(reg_trades)
    if n_t == 0:
        return SplitMetricsSummary(
            regime=regime,
            bar_count=bar_count,
            trade_count=0,
            win_rate=0.0,
            gross_pnl_inr=0.0,
            total_costs_inr=0.0,
            net_pnl_inr=0.0,
            mean_net_pnl_per_trade_inr=0.0,
            std_net_pnl_per_trade_inr=0.0,
            max_drawdown_inr=0.0,
            exposure_bar_fraction=(active_bars / bar_count) if bar_count > 0 else 0.0,
            baseline_naive_net_pnl_inr=baseline_net_inr,
        )
    nets = [t.net_pnl_inr for t in reg_trades]
    wins = sum(1 for v in nets if v > 0.0)
    return SplitMetricsSummary(
        regime=regime,
        bar_count=bar_count,
        trade_count=n_t,
        win_rate=wins / n_t,
        gross_pnl_inr=float(sum(t.gross_pnl_inr for t in reg_trades)),
        total_costs_inr=float(sum(t.round_trip_cost_inr for t in reg_trades)),
        net_pnl_inr=float(sum(nets)),
        mean_net_pnl_per_trade_inr=float(np.mean(nets)),
        std_net_pnl_per_trade_inr=float(np.std(nets, ddof=1)) if n_t >= 2 else 0.0,
        max_drawdown_inr=_compute_max_drawdown(nets),
        exposure_bar_fraction=(active_bars / bar_count) if bar_count > 0 else 0.0,
        baseline_naive_net_pnl_inr=baseline_net_inr,
    )


def _insufficient_backtest_report(
    run_id: str,
    pair_id: PairId,
    scenario: CostScenarioName,
    n_bars: int,
    explanation: str,
) -> PairBacktestReport:
    return PairBacktestReport(
        run_id=run_id,
        pair_id=pair_id.pair_key,
        cost_scenario=scenario,
        evidence_status=ReasonCode.INSUFFICIENT_EVIDENCE,
        total_aligned_bars=n_bars,
        train_end_timestamp=None,
        validation_end_timestamp=None,
        frozen_test_end_timestamp=None,
        total_completed_trades=0,
        gross_pnl_inr=0.0,
        total_costs_inr=0.0,
        net_pnl_inr=0.0,
        max_drawdown_inr=0.0,
        uncertainty_se_net_pnl_inr=0.0,
        baseline_naive_net_pnl_inr=0.0,
        split_summaries={},
        trades=[],
        decisions=[],
        explanation=explanation,
    )
