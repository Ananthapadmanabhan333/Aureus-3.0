"""Two-leg Indian commodity derivatives transaction-cost waterfall engine.

Implements full round-trip (entry + exit on both legs = 4 executions) cost accounting:
- Brokerage
- MCX Exchange Transaction Charge
- SEBI Turnover Fee
- GST (18% on Brokerage + Exchange + SEBI)
- CTT (Commodity Transaction Tax: 0.01% on non-agri futures sell executions ONLY)
- Stamp Duty (0.002% on futures buy executions ONLY)
- Bid-Ask Half-Spread Crossing
- Execution Slippage

Prevents double-counting and evaluates Base, Conservative, and Stress scenarios.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from aureus_rv.config.settings import CostScheduleScenario, CostsConfig
from aureus_rv.models import CostScenarioName, PairId, ReasonCode, SpreadDirection


class LegRoundTripCostBreakdown(BaseModel):
    """Exact round-trip (1 buy + 1 sell) cost breakdown for a single leg per gram (999) and in INR."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    norm_price_inr_g_999: float
    notional_grams: float
    leg_single_side_notional_inr: float
    brokerage_inr_g: float
    exchange_txn_inr_g: float
    sebi_fee_inr_g: float
    gst_inr_g: float
    ctt_sell_side_inr_g: float
    stamp_duty_buy_side_inr_g: float
    spread_crossing_inr_g: float
    slippage_inr_g: float
    total_leg_round_trip_inr_g: float
    total_leg_round_trip_inr: float
    total_leg_round_trip_bps: float


class PairCostWaterfallResult(BaseModel):
    """Complete two-leg round-trip cost waterfall and economic viability evaluation."""

    model_config = ConfigDict(frozen=True)

    pair_id: PairId
    scenario_name: CostScenarioName
    direction: SpreadDirection
    viable: bool
    reason_codes: list[ReasonCode]
    near_leg_breakdown: LegRoundTripCostBreakdown
    far_leg_breakdown: LegRoundTripCostBreakdown
    reference_mid_inr_g_999: float
    notional_grams: float
    gross_expected_convergence_inr_g_999: float
    gross_expected_convergence_bps: float
    gross_expected_convergence_inr: float
    total_round_trip_cost_inr_g_999: float
    total_round_trip_cost_bps: float
    total_round_trip_cost_inr: float
    net_expected_convergence_inr_g_999: float
    net_expected_convergence_bps: float
    net_expected_convergence_inr: float
    breakeven_convergence_inr_g_999: float
    breakeven_convergence_bps: float
    gross_to_cost_ratio: float
    scenario_sensitivity_net_bps: dict[str, float]
    rate_provenance_note: str
    explanation: str


def compute_single_leg_round_trip_cost(
    symbol: str,
    norm_price_inr_g_999: float,
    bid_ask_spread_bps: float,
    notional_grams: float,
    schedule: CostScheduleScenario,
) -> LegRoundTripCostBreakdown:
    """Compute exact round-trip (1 buy execution + 1 sell execution) cost for a single leg.

    Regardless of whether the leg is entered Long (Buy @ Entry, Sell @ Exit) or
    Short (Sell @ Entry, Buy @ Exit), a complete round-trip on that leg consists of:
    - 2 executions for Brokerage, Exchange Charge, SEBI fee, GST, Half-Spread, and Slippage
    - Exactly 1 Sell execution for CTT (no double-counting on the buy side)
    - Exactly 1 Buy execution for Stamp Duty (no double-counting on the sell side)
    """
    p = float(norm_price_inr_g_999)
    grams = float(notional_grams)
    bps_to_frac = 1e-4

    # Both entry and exit (2 executions) incur brokerage, exchange, SEBI
    brokerage_inr_g = 2.0 * p * (schedule.brokerage_bps_per_leg * bps_to_frac)
    exchange_inr_g = 2.0 * p * (schedule.exchange_txn_bps_per_leg * bps_to_frac)
    sebi_inr_g = 2.0 * p * (schedule.sebi_turnover_bps_per_leg * bps_to_frac)

    # GST applies only to brokerage + exchange + SEBI (never to CTT or Stamp Duty)
    gst_inr_g = schedule.gst_rate_fraction * (brokerage_inr_g + exchange_inr_g + sebi_inr_g)

    # CTT applies ONLY to the 1 sell execution in the round-trip
    ctt_inr_g = 1.0 * p * (schedule.ctt_sell_bps * bps_to_frac)

    # Stamp duty applies ONLY to the 1 buy execution in the round-trip
    stamp_inr_g = 1.0 * p * (schedule.stamp_duty_buy_bps * bps_to_frac)

    # Crossing half-spread at entry + half-spread at exit = 1 full spread * half_spread_multiplier
    # Specifically: each execution pays 0.5 * bid_ask_spread_bps * half_spread_multiplier; 2 executions = 1.0 * bid_ask_spread_bps * half_spread_multiplier
    spread_inr_g = p * (float(bid_ask_spread_bps) * bps_to_frac) * schedule.half_spread_multiplier

    # Slippage on entry + exit (2 executions)
    slippage_inr_g = 2.0 * p * (schedule.slippage_bps_per_leg * bps_to_frac)

    total_inr_g = (
        brokerage_inr_g
        + exchange_inr_g
        + sebi_inr_g
        + gst_inr_g
        + ctt_inr_g
        + stamp_inr_g
        + spread_inr_g
        + slippage_inr_g
    )
    total_inr = total_inr_g * grams
    total_bps = (total_inr_g / p) * 10000.0 if p > 0 else 0.0

    return LegRoundTripCostBreakdown(
        symbol=symbol,
        norm_price_inr_g_999=p,
        notional_grams=grams,
        leg_single_side_notional_inr=p * grams,
        brokerage_inr_g=brokerage_inr_g,
        exchange_txn_inr_g=exchange_inr_g,
        sebi_fee_inr_g=sebi_inr_g,
        gst_inr_g=gst_inr_g,
        ctt_sell_side_inr_g=ctt_inr_g,
        stamp_duty_buy_side_inr_g=stamp_inr_g,
        spread_crossing_inr_g=spread_inr_g,
        slippage_inr_g=slippage_inr_g,
        total_leg_round_trip_inr_g=total_inr_g,
        total_leg_round_trip_inr=total_inr,
        total_leg_round_trip_bps=total_bps,
    )


def evaluate_pair_costs(
    pair_id: PairId,
    direction: SpreadDirection,
    norm_near_inr_g_999: float,
    norm_far_inr_g_999: float,
    near_bid_ask_spread_bps: float,
    far_bid_ask_spread_bps: float,
    gross_expected_convergence_inr_g_999: float,
    notional_grams: float,
    costs_config: CostsConfig,
    scenario: CostScenarioName | None = None,
) -> PairCostWaterfallResult:
    """Evaluate complete two-leg cost waterfall across scenarios and check economic viability."""
    active_scenario = scenario or costs_config.default_scenario
    schedule = costs_config.scenarios[active_scenario]

    near_leg = compute_single_leg_round_trip_cost(
        symbol=pair_id.near_leg.symbol,
        norm_price_inr_g_999=norm_near_inr_g_999,
        bid_ask_spread_bps=near_bid_ask_spread_bps,
        notional_grams=notional_grams,
        schedule=schedule,
    )
    far_leg = compute_single_leg_round_trip_cost(
        symbol=pair_id.far_leg.symbol,
        norm_price_inr_g_999=norm_far_inr_g_999,
        bid_ask_spread_bps=far_bid_ask_spread_bps,
        notional_grams=notional_grams,
        schedule=schedule,
    )

    ref_mid = 0.5 * (norm_near_inr_g_999 + norm_far_inr_g_999)
    total_cost_inr_g = near_leg.total_leg_round_trip_inr_g + far_leg.total_leg_round_trip_inr_g
    total_cost_inr = total_cost_inr_g * notional_grams
    total_cost_bps = (total_cost_inr_g / ref_mid) * 10000.0 if ref_mid > 0 else 0.0

    gross_inr_g = max(0.0, float(gross_expected_convergence_inr_g_999))
    gross_inr = gross_inr_g * notional_grams
    gross_bps = (gross_inr_g / ref_mid) * 10000.0 if ref_mid > 0 else 0.0

    net_inr_g = gross_inr_g - total_cost_inr_g
    net_inr = net_inr_g * notional_grams
    net_bps = gross_bps - total_cost_bps

    ratio = gross_inr_g / total_cost_inr_g if total_cost_inr_g > 0 else 0.0

    # Compute sensitivity across all configured scenarios (base, conservative, stress)
    sensitivity: dict[str, float] = {}
    for scen_name, scen_sched in costs_config.scenarios.items():
        n_leg = compute_single_leg_round_trip_cost(
            symbol=pair_id.near_leg.symbol,
            norm_price_inr_g_999=norm_near_inr_g_999,
            bid_ask_spread_bps=near_bid_ask_spread_bps,
            notional_grams=notional_grams,
            schedule=scen_sched,
        )
        f_leg = compute_single_leg_round_trip_cost(
            symbol=pair_id.far_leg.symbol,
            norm_price_inr_g_999=norm_far_inr_g_999,
            bid_ask_spread_bps=far_bid_ask_spread_bps,
            notional_grams=notional_grams,
            schedule=scen_sched,
        )
        scen_cost_bps = (
            ((n_leg.total_leg_round_trip_inr_g + f_leg.total_leg_round_trip_inr_g) / ref_mid) * 10000.0
            if ref_mid > 0
            else 0.0
        )
        sensitivity[scen_name.value] = gross_bps - scen_cost_bps

    reasons: list[ReasonCode] = []
    explanations: list[str] = []

    if net_inr_g <= 0.0:
        reasons.append(ReasonCode.NO_EDGE_COSTS_EXCEED_SPREAD)
        explanations.append(
            f"Round-trip costs ({total_cost_bps:.2f} bps) exceed or equal gross expected convergence ({gross_bps:.2f} bps)"
        )
    if net_bps < costs_config.min_net_edge_bps:
        reasons.append(ReasonCode.NO_EDGE_BELOW_MIN_NET_BPS)
        explanations.append(
            f"Net expected edge ({net_bps:.2f} bps) < min_net_edge_bps ({costs_config.min_net_edge_bps:.2f} bps)"
        )
    if ratio < costs_config.min_gross_to_cost_ratio:
        reasons.append(ReasonCode.NO_EDGE_INSUFFICIENT_NET_RATIO)
        explanations.append(
            f"Gross-to-cost ratio ({ratio:.2f}x) < min_gross_to_cost_ratio ({costs_config.min_gross_to_cost_ratio:.2f}x)"
        )

    if not reasons:
        reasons = [ReasonCode.COST_VIABLE]
        explanations.append(
            f"Economically viable under '{active_scenario.value}' scenario: "
            f"gross={gross_bps:.2f} bps, cost={total_cost_bps:.2f} bps, net={net_bps:.2f} bps ({ratio:.2f}x)"
        )

    return PairCostWaterfallResult(
        pair_id=pair_id,
        scenario_name=active_scenario,
        direction=direction,
        viable=(reasons == [ReasonCode.COST_VIABLE]),
        reason_codes=reasons,
        near_leg_breakdown=near_leg,
        far_leg_breakdown=far_leg,
        reference_mid_inr_g_999=ref_mid,
        notional_grams=notional_grams,
        gross_expected_convergence_inr_g_999=gross_inr_g,
        gross_expected_convergence_bps=gross_bps,
        gross_expected_convergence_inr=gross_inr,
        total_round_trip_cost_inr_g_999=total_cost_inr_g,
        total_round_trip_cost_bps=total_cost_bps,
        total_round_trip_cost_inr=total_cost_inr,
        net_expected_convergence_inr_g_999=net_inr_g,
        net_expected_convergence_bps=net_bps,
        net_expected_convergence_inr=net_inr,
        breakeven_convergence_inr_g_999=total_cost_inr_g,
        breakeven_convergence_bps=total_cost_bps,
        gross_to_cost_ratio=ratio,
        scenario_sensitivity_net_bps=sensitivity,
        rate_provenance_note=schedule.rate_provenance_note,
        explanation="; ".join(explanations),
    )
