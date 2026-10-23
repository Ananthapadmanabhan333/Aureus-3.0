"""Regression test suite verifying physical conversion invariants, cost symmetry, and gate determinism."""

from __future__ import annotations

from datetime import date

import pytest

from aureus_rv.config.settings import AureusConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.costs.waterfall import evaluate_pair_costs
from aureus_rv.models import (
    ContractInstanceId,
    CostScenarioName,
    PairId,
    QuotationUnit,
    SpreadDirection,
)
from aureus_rv.normalization.normalizer import normalize_price_to_inr_per_g_999


def test_physical_parity_across_all_mcx_contract_variants() -> None:
    """Verify that identical underlying 999 gold value per gram normalizes to the exact same INR/g across all 4 MCX variants."""
    true_999_inr_per_g = 7250.0

    # Equivalent raw quotations:
    # 1. GOLD (10g at 995 fineness): 7250 * 10 * (995 / 999)
    raw_gold_10g_995 = true_999_inr_per_g * 10.0 * (995.0 / 999.0)
    # 2. GOLDM (10g at 999 fineness): 7250 * 10
    raw_goldm_10g_999 = true_999_inr_per_g * 10.0
    # 3. GOLDGUINEA (8g at 999 fineness): 7250 * 8
    raw_guinea_8g_999 = true_999_inr_per_g * 8.0
    # 4. GOLDPETAL (1g at 999 fineness): 7250 * 1
    raw_petal_1g_999 = true_999_inr_per_g * 1.0

    n_gold = normalize_price_to_inr_per_g_999(raw_gold_10g_995, QuotationUnit.INR_PER_10G, 995)
    n_goldm = normalize_price_to_inr_per_g_999(raw_goldm_10g_999, QuotationUnit.INR_PER_10G, 999)
    n_guinea = normalize_price_to_inr_per_g_999(raw_guinea_8g_999, QuotationUnit.INR_PER_8G, 999)
    n_petal = normalize_price_to_inr_per_g_999(raw_petal_1g_999, QuotationUnit.INR_PER_1G, 999)

    assert n_gold == pytest.approx(true_999_inr_per_g, rel=1e-12)
    assert n_goldm == pytest.approx(true_999_inr_per_g, rel=1e-12)
    assert n_guinea == pytest.approx(true_999_inr_per_g, rel=1e-12)
    assert n_petal == pytest.approx(true_999_inr_per_g, rel=1e-12)


def test_round_trip_cost_direction_symmetry() -> None:
    """Verify that round-trip cost on a pair is identical for LONG_SPREAD and SHORT_SPREAD (since each leg executes 1 buy + 1 sell)."""
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 8, 5)),
        far_leg=ContractInstanceId(symbol="GOLDM", expiry_date=date(2026, 8, 28)),
    )
    cfg = AureusConfig()
    cost_short = evaluate_pair_costs(
        pair_id=pair_id,
        direction=SpreadDirection.SHORT_SPREAD,
        norm_near_inr_g_999=7210.0,
        norm_far_inr_g_999=7200.0,
        near_bid_ask_spread_bps=1.2,
        far_bid_ask_spread_bps=1.4,
        gross_expected_convergence_inr_g_999=8.0,
        notional_grams=1000.0,
        costs_config=cfg.costs,
        scenario=CostScenarioName.CONSERVATIVE,
    )
    cost_long = evaluate_pair_costs(
        pair_id=pair_id,
        direction=SpreadDirection.LONG_SPREAD,
        norm_near_inr_g_999=7210.0,
        norm_far_inr_g_999=7200.0,
        near_bid_ask_spread_bps=1.2,
        far_bid_ask_spread_bps=1.4,
        gross_expected_convergence_inr_g_999=8.0,
        notional_grams=1000.0,
        costs_config=cfg.costs,
        scenario=CostScenarioName.CONSERVATIVE,
    )
    assert cost_short.total_round_trip_cost_inr == pytest.approx(cost_long.total_round_trip_cost_inr, rel=1e-15)
    assert len(ContractRegistry().list_specs()) >= 4
