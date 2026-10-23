"""Unit tests for the two-leg Indian commodity derivatives transaction-cost waterfall against manually verified examples."""

from __future__ import annotations

from datetime import date

import pytest

from aureus_rv.config.settings import CostScheduleScenario, CostsConfig
from aureus_rv.costs.waterfall import compute_single_leg_round_trip_cost, evaluate_pair_costs
from aureus_rv.models import (
    ContractInstanceId,
    CostScenarioName,
    PairId,
    ReasonCode,
    SpreadDirection,
)


def test_single_leg_round_trip_cost_manual_verification() -> None:
    """Test single-leg round-trip cost arithmetic against a manually calculated numerical example.

    Let:
    - Normalized price P = 7,000.0 INR/g (999)
    - Notional = 1,000.0 g (so single-side notional = Rs 7,000,000)
    - Bid-ask spread = 1.0 bps
    - Base schedule:
      * brokerage = 0.30 bps per execution -> 2 executions = 0.60 bps -> 7000 * 0.000060 = 0.42 INR/g
      * exchange = 0.26 bps per execution -> 2 executions = 0.52 bps -> 7000 * 0.000052 = 0.364 INR/g
      * sebi = 0.01 bps per execution -> 2 executions = 0.02 bps -> 7000 * 0.000002 = 0.014 INR/g
      * taxable sum = 0.42 + 0.364 + 0.014 = 0.798 INR/g (1.14 bps)
      * GST (18%) = 0.18 * 0.798 = 0.14364 INR/g (0.2052 bps)
      * CTT (sell side ONLY, 1 execution at 1.0 bps) = 7000 * 0.0001 = 0.70 INR/g (1.00 bps)
      * Stamp duty (buy side ONLY, 1 execution at 0.20 bps) = 7000 * 0.00002 = 0.14 INR/g (0.20 bps)
      * Spread crossing (1.0 bps * 1.0 multiplier) = 7000 * 0.0001 = 0.70 INR/g (1.00 bps)
      * Slippage (0.50 bps per execution * 2 executions = 1.00 bps) = 7000 * 0.0001 = 0.70 INR/g (1.00 bps)
      * Total per gram = 0.798 + 0.14364 + 0.70 + 0.14 + 0.70 + 0.70 = 3.18164 INR/g (4.5452 bps)
      * Total for 1000g lot = Rs 3,181.64
    """
    schedule = CostScheduleScenario(
        scenario_name=CostScenarioName.BASE,
        brokerage_bps_per_leg=0.30,
        exchange_txn_bps_per_leg=0.26,
        sebi_turnover_bps_per_leg=0.01,
        ctt_sell_bps=1.0,
        stamp_duty_buy_bps=0.20,
        gst_rate_fraction=0.18,
        slippage_bps_per_leg=0.50,
        half_spread_multiplier=1.0,
    )

    leg = compute_single_leg_round_trip_cost(
        symbol="GOLD",
        norm_price_inr_g_999=7000.0,
        bid_ask_spread_bps=1.0,
        notional_grams=1000.0,
        schedule=schedule,
    )

    assert leg.brokerage_inr_g == pytest.approx(0.42, rel=1e-12)
    assert leg.exchange_txn_inr_g == pytest.approx(0.364, rel=1e-12)
    assert leg.sebi_fee_inr_g == pytest.approx(0.014, rel=1e-12)
    assert leg.gst_inr_g == pytest.approx(0.14364, rel=1e-12)
    assert leg.ctt_sell_side_inr_g == pytest.approx(0.70, rel=1e-12)
    assert leg.stamp_duty_buy_side_inr_g == pytest.approx(0.14, rel=1e-12)
    assert leg.spread_crossing_inr_g == pytest.approx(0.70, rel=1e-12)
    assert leg.slippage_inr_g == pytest.approx(0.70, rel=1e-12)
    assert leg.total_leg_round_trip_inr_g == pytest.approx(3.18164, rel=1e-12)
    assert leg.total_leg_round_trip_inr == pytest.approx(3181.64, rel=1e-12)
    assert leg.total_leg_round_trip_bps == pytest.approx(4.5452, rel=1e-12)


def test_two_leg_pair_cost_scenarios_and_no_edge_detection() -> None:
    """Verify two-leg waterfall across base, conservative, and stress scenarios and NO-EDGE classification."""
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 8, 5)),
        far_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 10, 5)),
    )
    costs_cfg = CostsConfig()

    # Case 1: Small gross convergence (3.0 INR/g on 7000 INR/g = 4.28 bps) < two-leg round-trip cost (~9.09 bps)
    res_no_edge = evaluate_pair_costs(
        pair_id=pair_id,
        direction=SpreadDirection.SHORT_SPREAD,
        norm_near_inr_g_999=7000.0,
        norm_far_inr_g_999=7000.0,
        near_bid_ask_spread_bps=1.0,
        far_bid_ask_spread_bps=1.0,
        gross_expected_convergence_inr_g_999=3.0,
        notional_grams=1000.0,
        costs_config=costs_cfg,
        scenario=CostScenarioName.BASE,
    )
    assert res_no_edge.viable is False
    assert ReasonCode.NO_EDGE_COSTS_EXCEED_SPREAD in res_no_edge.reason_codes
    assert res_no_edge.net_expected_convergence_inr < 0.0

    # Case 2: Large gross convergence (10.0 INR/g on 7000 INR/g = 14.2857 bps) > two-leg cost (9.0904 bps)
    res_viable = evaluate_pair_costs(
        pair_id=pair_id,
        direction=SpreadDirection.SHORT_SPREAD,
        norm_near_inr_g_999=7000.0,
        norm_far_inr_g_999=7000.0,
        near_bid_ask_spread_bps=1.0,
        far_bid_ask_spread_bps=1.0,
        gross_expected_convergence_inr_g_999=10.0,
        notional_grams=1000.0,
        costs_config=costs_cfg,
        scenario=CostScenarioName.BASE,
    )
    assert res_viable.viable is True
    assert res_viable.reason_codes == [ReasonCode.COST_VIABLE]
    # Verify monotonic cost increase from base -> conservative -> stress
    assert (
        res_viable.scenario_sensitivity_net_bps["base"]
        > res_viable.scenario_sensitivity_net_bps["conservative"]
        > res_viable.scenario_sensitivity_net_bps["stress"]
    )
