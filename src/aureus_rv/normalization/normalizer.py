"""Price normalization to INR per gram at 999 fineness and separation from contract notional."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict

from aureus_rv.contracts.registry import ContractRegistry, ContractSpec
from aureus_rv.models import AureusError, QuotationUnit, ReasonCode

TARGET_FINENESS: int = 999

QUOTATION_UNIT_TO_GRAMS: dict[QuotationUnit, float] = {
    QuotationUnit.INR_PER_10G: 10.0,
    QuotationUnit.INR_PER_8G: 8.0,
    QuotationUnit.INR_PER_1G: 1.0,
}


class NormalizedPriceBreakdown(BaseModel):
    """Explicit separation between raw quoted price, normalized unit price, and contract lot notional."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    spec_version: str
    raw_quoted_price: float
    quotation_unit: QuotationUnit
    quotation_grams: float
    purity_fineness: int
    purity_conversion_factor: float
    unit_grams_divisor: float
    normalized_inr_per_g_999: float
    lot_size_grams: float
    price_multiplier_per_lot: float
    raw_contract_notional_inr: float


def compute_purity_factor(purity_fineness: int, target_fineness: int = TARGET_FINENESS) -> float:
    """Return purity conversion multiplier (target_fineness / purity_fineness).

    For 995 fineness -> 999 / 995.
    For 999 fineness -> 999 / 999 = 1.0.
    """
    if not isinstance(purity_fineness, int) or purity_fineness < 900 or purity_fineness > 999:
        raise AureusError(
            f"Unsupported or invalid gold purity fineness: {purity_fineness}",
            reason_code=ReasonCode.ERR_INVALID_PURITY_FINENESS,
            details={"purity_fineness": purity_fineness},
        )
    return float(target_fineness) / float(purity_fineness)


def resolve_quotation_divisor(quotation_unit: str | QuotationUnit) -> tuple[QuotationUnit, float]:
    """Validate quotation unit and return (QuotationUnit, grams_divisor)."""
    try:
        unit_enum = QuotationUnit(quotation_unit)
    except ValueError as exc:
        raise AureusError(
            f"Unknown quotation unit '{quotation_unit}'. Cannot guess conversion.",
            reason_code=ReasonCode.ERR_UNKNOWN_QUOTATION_UNIT,
            details={"quotation_unit": str(quotation_unit)},
        ) from exc
    return unit_enum, QUOTATION_UNIT_TO_GRAMS[unit_enum]


def normalize_price_to_inr_per_g_999(
    raw_price: float,
    quotation_unit: str | QuotationUnit,
    purity_fineness: int,
) -> float:
    """Convert a raw gold quotation to normalized INR per gram at 999 fineness.

    Formula:
        normalized_inr_per_g_999 = raw_price * (999 / purity_fineness) / quotation_grams

    Illustrative case (INR per 10g at 995 fineness):
        normalized = quoted_inr_per_10g * (999 / 995) / 10
    """
    if raw_price <= 0.0 or pd.isna(raw_price):
        raise AureusError(
            f"Raw price must be strictly positive, got {raw_price}",
            reason_code=ReasonCode.ERR_NON_POSITIVE_PRICE,
            details={"raw_price": raw_price},
        )
    _, divisor = resolve_quotation_divisor(quotation_unit)
    purity_factor = compute_purity_factor(int(purity_fineness))
    return float(raw_price) * purity_factor / divisor


def compute_normalized_breakdown(
    raw_price: float,
    spec: ContractSpec,
) -> NormalizedPriceBreakdown:
    """Compute full normalized price breakdown while preserving separate raw contract lot notional."""
    norm_price = normalize_price_to_inr_per_g_999(
        raw_price=raw_price,
        quotation_unit=spec.quotation_unit,
        purity_fineness=spec.purity_fineness,
    )
    purity_factor = compute_purity_factor(spec.purity_fineness)
    raw_notional = float(raw_price) * spec.price_multiplier_per_lot
    return NormalizedPriceBreakdown(
        symbol=spec.symbol,
        spec_version=spec.spec_version,
        raw_quoted_price=float(raw_price),
        quotation_unit=spec.quotation_unit,
        quotation_grams=spec.quotation_grams,
        purity_fineness=spec.purity_fineness,
        purity_conversion_factor=purity_factor,
        unit_grams_divisor=spec.quotation_grams,
        normalized_inr_per_g_999=norm_price,
        lot_size_grams=spec.lot_size_grams,
        price_multiplier_per_lot=spec.price_multiplier_per_lot,
        raw_contract_notional_inr=raw_notional,
    )


def normalize_dataframe_observations(
    df: pd.DataFrame,
    registry: ContractRegistry,
) -> pd.DataFrame:
    """Enrich a validated DataFrame of observations with normalized INR/g (999) prices and lot notionals.

    Preserves all raw columns (`open`, `high`, `low`, `close`, `bid`, `ask`) and adds:
    - `spec_version`
    - `price_multiplier_per_lot`
    - `norm_open_inr_g_999`
    - `norm_high_inr_g_999`
    - `norm_low_inr_g_999`
    - `norm_close_inr_g_999`
    - `norm_bid_inr_g_999`
    - `norm_ask_inr_g_999`
    - `norm_mid_inr_g_999`
    - `raw_notional_per_lot_inr`
    - `bid_ask_spread_bps`
    """
    if df.empty:
        return df.copy()

    out = df.copy()
    spec_versions: list[str] = []
    multipliers: list[float] = []
    conversion_factors: list[float] = []

    for row in out.itertuples(index=False):
        obs_date = pd.Timestamp(row.timestamp).date()
        spec = registry.get_spec(str(row.symbol), obs_date)
        reasons = registry.validate_observation_against_spec(
            symbol=str(row.symbol),
            as_of_date=obs_date,
            quotation_unit=str(row.quotation_unit),
            purity_fineness=int(row.purity_fineness),
            lot_size_grams=float(row.lot_size_grams),
        )
        if reasons:
            raise AureusError(
                f"Observation failed contract specification check: {reasons}",
                reason_code=reasons[0],
                details={"symbol": row.symbol, "reasons": [r.value for r in reasons]},
            )
        purity_factor = compute_purity_factor(spec.purity_fineness)
        _, divisor = resolve_quotation_divisor(spec.quotation_unit)
        spec_versions.append(spec.spec_version)
        multipliers.append(spec.price_multiplier_per_lot)
        conversion_factors.append(purity_factor / divisor)

    conv_series = pd.Series(conversion_factors, index=out.index, dtype="float64")
    mult_series = pd.Series(multipliers, index=out.index, dtype="float64")

    out["spec_version"] = spec_versions
    out["price_multiplier_per_lot"] = mult_series
    out["norm_open_inr_g_999"] = out["open"].astype(float) * conv_series
    out["norm_high_inr_g_999"] = out["high"].astype(float) * conv_series
    out["norm_low_inr_g_999"] = out["low"].astype(float) * conv_series
    out["norm_close_inr_g_999"] = out["close"].astype(float) * conv_series
    out["norm_bid_inr_g_999"] = out["bid"].astype(float) * conv_series
    out["norm_ask_inr_g_999"] = out["ask"].astype(float) * conv_series
    out["norm_mid_inr_g_999"] = 0.5 * (out["norm_bid_inr_g_999"] + out["norm_ask_inr_g_999"])
    out["raw_notional_per_lot_inr"] = out["close"].astype(float) * mult_series
    out["bid_ask_spread_bps"] = (
        (out["norm_ask_inr_g_999"] - out["norm_bid_inr_g_999"]) / out["norm_mid_inr_g_999"]
    ) * 10000.0
    out["contract_id"] = (
        out["symbol"].astype(str).str.upper()
        + "_"
        + pd.to_datetime(out["expiry_date"]).dt.strftime("%Y-%m-%d")
    )
    return out
