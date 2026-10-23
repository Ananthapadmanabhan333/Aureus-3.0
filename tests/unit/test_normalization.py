"""Unit tests for versioned contract registry and price normalization to INR/g at 999 fineness."""

from __future__ import annotations

from datetime import date

import pytest

from aureus_rv.contracts.registry import ContractRegistry, ContractSpec
from aureus_rv.models import AureusError, QuotationUnit, ReasonCode
from aureus_rv.normalization.normalizer import (
    compute_normalized_breakdown,
    compute_purity_factor,
    normalize_price_to_inr_per_g_999,
)


def test_illustrative_995_10g_to_999_1g_conversion() -> None:
    """Verify exact formula: quoted INR per 10g * (999 / 995) / 10."""
    quoted_price = 72000.0
    expected = 72000.0 * (999.0 / 995.0) / 10.0
    actual = normalize_price_to_inr_per_g_999(
        raw_price=quoted_price,
        quotation_unit=QuotationUnit.INR_PER_10G,
        purity_fineness=995,
    )
    assert actual == pytest.approx(expected, rel=1e-12)
    assert actual == pytest.approx(7228.94472361809, rel=1e-10)


def test_supported_variant_conversions() -> None:
    """Verify GOLDM (10g/999), GOLDPETAL (1g/999), and GOLDGUINEA (8g/999) conversions."""
    # GOLDM: 72,500 per 10g at 999 -> 7,250.0 INR/g
    assert normalize_price_to_inr_per_g_999(72500.0, QuotationUnit.INR_PER_10G, 999) == pytest.approx(7250.0)
    # GOLDPETAL: 7,255 per 1g at 999 -> 7,255.0 INR/g
    assert normalize_price_to_inr_per_g_999(7255.0, QuotationUnit.INR_PER_1G, 999) == pytest.approx(7255.0)
    # GOLDGUINEA: 58,000 per 8g at 999 -> 7,250.0 INR/g
    assert normalize_price_to_inr_per_g_999(58000.0, QuotationUnit.INR_PER_8G, 999) == pytest.approx(7250.0)


def test_separation_of_normalized_unit_price_and_contract_notional() -> None:
    """Ensure normalized INR/g price is kept strictly separate from lot size and contract notional."""
    registry = ContractRegistry()
    gold_spec = registry.get_spec("GOLD", date(2026, 5, 1))
    breakdown = compute_normalized_breakdown(raw_price=72000.0, spec=gold_spec)

    # GOLD is 1000g lot quoted per 10g -> multiplier = 100
    assert breakdown.price_multiplier_per_lot == pytest.approx(100.0)
    assert breakdown.raw_contract_notional_inr == pytest.approx(72000.0 * 100.0)
    assert breakdown.normalized_inr_per_g_999 == pytest.approx(72000.0 * (999.0 / 995.0) / 10.0)


def test_reject_unknown_quotation_unit_and_invalid_purity() -> None:
    """Reject unknown quotation units and out-of-range purities rather than guessing."""
    with pytest.raises(AureusError) as exc_info:
        normalize_price_to_inr_per_g_999(2300.0, "USD_PER_OZ", 999)
    assert exc_info.value.reason_code == ReasonCode.ERR_UNKNOWN_QUOTATION_UNIT

    with pytest.raises(AureusError) as exc_purity:
        compute_purity_factor(500)
    assert exc_purity.value.reason_code == ReasonCode.ERR_INVALID_PURITY_FINENESS

    with pytest.raises(AureusError) as exc_neg:
        normalize_price_to_inr_per_g_999(0.0, QuotationUnit.INR_PER_10G, 995)
    assert exc_neg.value.reason_code == ReasonCode.ERR_NON_POSITIVE_PRICE


def test_contract_registry_effective_dates_and_versioning() -> None:
    """Verify effective-dated contract specification resolution and rejection of out-of-range dates."""
    registry = ContractRegistry()
    # Register a historical spec effective only in 2010-2014
    registry.register(
        ContractSpec(
            symbol="GOLD_LEGACY",
            spec_version="MCX-GOLD-LEGACY-v0",
            effective_from=date(2010, 1, 1),
            effective_to=date(2014, 12, 31),
            quotation_unit=QuotationUnit.INR_PER_10G,
            quotation_grams=10.0,
            purity_fineness=995,
            lot_size_grams=1000.0,
        )
    )
    spec = registry.get_spec("GOLD_LEGACY", date(2012, 6, 15))
    assert spec.spec_version == "MCX-GOLD-LEGACY-v0"

    with pytest.raises(AureusError) as exc_not_eff:
        registry.get_spec("GOLD_LEGACY", date(2020, 1, 1))
    assert exc_not_eff.value.reason_code == ReasonCode.ERR_SPEC_NOT_EFFECTIVE

    with pytest.raises(AureusError) as exc_unknown:
        registry.get_spec("SILVER", date(2026, 5, 1))
    assert exc_unknown.value.reason_code == ReasonCode.ERR_UNKNOWN_CONTRACT_SYMBOL
