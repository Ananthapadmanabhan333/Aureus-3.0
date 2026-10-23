"""Versioned MCX Gold Futures Contract Specification Registry with effective dates."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureus_rv.models import AureusError, QuotationUnit, ReasonCode


class ContractSpec(BaseModel):
    """Specification for a commodity futures contract variant over an effective date range."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., min_length=1)
    spec_version: str = Field(..., min_length=1)
    exchange: str = Field(default="MCX")
    effective_from: date
    effective_to: date | None = Field(default=None)
    quotation_unit: QuotationUnit
    quotation_grams: float = Field(..., gt=0.0, description="Grams corresponding to the raw quoted price")
    purity_fineness: int = Field(..., ge=900, le=999, description="Fineness in parts per thousand (e.g. 995 or 999)")
    lot_size_grams: float = Field(..., gt=0.0, description="Total physical grams represented by 1 contract lot")
    tick_size_inr: float = Field(default=1.0, gt=0.0, description="Minimum price tick in raw quotation currency")
    tender_period_days: int = Field(default=5, ge=0, description="Days prior to expiry when tender/delivery period starts")
    description: str = Field(default="")

    @property
    def price_multiplier_per_lot(self) -> float:
        """Number of raw quoted units in one contract lot (lot_size_grams / quotation_grams).

        For example:
        - GOLD (1000g lot, quoted per 10g): multiplier = 1000 / 10 = 100.
          Rs 1 change in quoted price per 10g = Rs 100 change per lot.
        - GOLDM (100g lot, quoted per 10g): multiplier = 100 / 10 = 10.
        - GOLDPETAL (1g lot, quoted per 1g): multiplier = 1 / 1 = 1.
        - GOLDGUINEA (8g lot, quoted per 8g): multiplier = 8 / 8 = 1.
        """
        return self.lot_size_grams / self.quotation_grams

    @model_validator(mode="after")
    def _validate_dates_and_units(self) -> ContractSpec:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        expected_grams = {
            QuotationUnit.INR_PER_10G: 10.0,
            QuotationUnit.INR_PER_8G: 8.0,
            QuotationUnit.INR_PER_1G: 1.0,
        }[self.quotation_unit]
        if abs(self.quotation_grams - expected_grams) > 1e-6:
            raise ValueError(
                f"quotation_grams ({self.quotation_grams}) does not match {self.quotation_unit} ({expected_grams}g)"
            )
        return self


DEFAULT_MCX_SPECS: tuple[ContractSpec, ...] = (
    ContractSpec(
        symbol="GOLD",
        spec_version="MCX-GOLD-995-v1",
        effective_from=date(2015, 1, 1),
        effective_to=None,
        quotation_unit=QuotationUnit.INR_PER_10G,
        quotation_grams=10.0,
        purity_fineness=995,
        lot_size_grams=1000.0,
        tick_size_inr=1.0,
        tender_period_days=5,
        description="MCX Standard Gold 1 kg contract quoted in INR per 10g at 995 fineness",
    ),
    ContractSpec(
        symbol="GOLDM",
        spec_version="MCX-GOLDM-999-v1",
        effective_from=date(2015, 1, 1),
        effective_to=None,
        quotation_unit=QuotationUnit.INR_PER_10G,
        quotation_grams=10.0,
        purity_fineness=999,
        lot_size_grams=100.0,
        tick_size_inr=1.0,
        tender_period_days=5,
        description="MCX Gold Mini 100g contract quoted in INR per 10g at 999 fineness",
    ),
    ContractSpec(
        symbol="GOLDPETAL",
        spec_version="MCX-GOLDPETAL-999-v1",
        effective_from=date(2015, 1, 1),
        effective_to=None,
        quotation_unit=QuotationUnit.INR_PER_1G,
        quotation_grams=1.0,
        purity_fineness=999,
        lot_size_grams=1.0,
        tick_size_inr=1.0,
        tender_period_days=5,
        description="MCX Gold Petal 1g contract quoted in INR per 1g at 999 fineness",
    ),
    ContractSpec(
        symbol="GOLDGUINEA",
        spec_version="MCX-GOLDGUINEA-999-v1",
        effective_from=date(2015, 1, 1),
        effective_to=None,
        quotation_unit=QuotationUnit.INR_PER_8G,
        quotation_grams=8.0,
        purity_fineness=999,
        lot_size_grams=8.0,
        tick_size_inr=1.0,
        tender_period_days=5,
        description="MCX Gold Guinea 8g contract quoted in INR per 8g at 999 fineness",
    ),
)


class ContractRegistry:
    """Versioned registry for looking up and validating contract specifications by symbol and observation date."""

    def __init__(self, specs: list[ContractSpec] | tuple[ContractSpec, ...] | None = None) -> None:
        self._specs: list[ContractSpec] = list(specs if specs is not None else DEFAULT_MCX_SPECS)

    def register(self, spec: ContractSpec) -> None:
        """Register an additional contract specification version."""
        self._specs.append(spec)

    def list_specs(self) -> list[ContractSpec]:
        """Return all registered contract specifications."""
        return list(self._specs)

    def get_spec(self, symbol: str, as_of_date: date) -> ContractSpec:
        """Resolve the active ContractSpec for `symbol` at `as_of_date`."""
        norm_symbol = symbol.strip().upper()
        symbol_matches = [s for s in self._specs if s.symbol.upper() == norm_symbol]
        if not symbol_matches:
            raise AureusError(
                f"Unknown contract symbol: '{symbol}'",
                reason_code=ReasonCode.ERR_UNKNOWN_CONTRACT_SYMBOL,
                details={"symbol": symbol},
            )

        effective_matches = [
            s
            for s in symbol_matches
            if s.effective_from <= as_of_date and (s.effective_to is None or as_of_date <= s.effective_to)
        ]
        if not effective_matches:
            raise AureusError(
                f"No effective contract specification for symbol '{symbol}' on {as_of_date.isoformat()}",
                reason_code=ReasonCode.ERR_SPEC_NOT_EFFECTIVE,
                details={"symbol": symbol, "as_of_date": as_of_date.isoformat()},
            )

        # If multiple specs match, select the one with the latest effective_from
        effective_matches.sort(key=lambda s: s.effective_from, reverse=True)
        return effective_matches[0]

    def validate_observation_against_spec(
        self,
        symbol: str,
        as_of_date: date,
        quotation_unit: str,
        purity_fineness: int,
        lot_size_grams: float,
    ) -> list[ReasonCode]:
        """Verify that an observation's claimed quotation unit, purity, and lot size match the registry."""
        reasons: list[ReasonCode] = []
        try:
            spec = self.get_spec(symbol=symbol, as_of_date=as_of_date)
        except AureusError as exc:
            return [exc.reason_code]

        try:
            parsed_unit = QuotationUnit(quotation_unit)
        except ValueError:
            reasons.append(ReasonCode.ERR_UNKNOWN_QUOTATION_UNIT)
            parsed_unit = None

        if parsed_unit is not None and parsed_unit != spec.quotation_unit:
            reasons.append(ReasonCode.ERR_SPEC_QUOTATION_MISMATCH)

        if int(purity_fineness) != spec.purity_fineness:
            reasons.append(ReasonCode.ERR_SPEC_PURITY_MISMATCH)

        if abs(float(lot_size_grams) - spec.lot_size_grams) > 1e-4:
            reasons.append(ReasonCode.ERR_SPEC_LOT_MISMATCH)

        return reasons
