"""Configuration schemas, defaults, and hash utilities for AUREUS-RV 3.0."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureus_rv.models import CostScenarioName


class PairingConfig(BaseModel):
    """Configuration for expiry-aware contract pairing."""

    model_config = ConfigDict(frozen=True)

    min_expiry_gap_days: int = Field(default=7, ge=0, description="Minimum calendar days between near and far expiry")
    max_expiry_gap_days: int = Field(default=135, ge=1, description="Maximum calendar days between near and far expiry")
    min_days_to_expiry_near: int = Field(
        default=6,
        ge=0,
        description="Minimum calendar days to expiry before near leg enters tender/rollover freeze",
    )
    allow_cross_symbol_pairing: bool = Field(
        default=True,
        description="Whether to allow pairing across normalized variants (e.g. GOLD vs GOLDM)",
    )

    @model_validator(mode="after")
    def _validate_gaps(self) -> PairingConfig:
        if self.max_expiry_gap_days < self.min_expiry_gap_days:
            raise ValueError("max_expiry_gap_days must be >= min_expiry_gap_days")
        return self


class LiquidityConfig(BaseModel):
    """Configuration for historical liquidity screening."""

    model_config = ConfigDict(frozen=True)

    min_volume_lots: int = Field(default=50, ge=0)
    min_open_interest_lots: int = Field(default=100, ge=0)
    max_bid_ask_spread_bps: float = Field(default=15.0, gt=0.0)
    max_quote_staleness_seconds: int = Field(default=300, ge=0)
    min_rolling_observations: int = Field(default=20, ge=2)
    rolling_window_bars: int = Field(default=20, ge=2)


class StatisticsConfig(BaseModel):
    """Configuration for rolling statistical spread analysis."""

    model_config = ConfigDict(frozen=True)

    rolling_window: int = Field(default=20, ge=5)
    min_observations: int = Field(default=20, ge=5)
    entry_z_threshold: float = Field(default=2.0, gt=0.0)
    exit_z_threshold: float = Field(default=0.5, ge=0.0)
    stop_z_threshold: float = Field(default=4.5, gt=0.0)
    min_correlation: float = Field(default=0.70, ge=-1.0, le=1.0)
    min_spread_std_inr_per_g: float = Field(default=1e-4, gt=0.0)
    run_adf_stationarity_test: bool = Field(default=False)
    max_adf_pvalue: float = Field(default=0.10, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_thresholds(self) -> StatisticsConfig:
        if self.exit_z_threshold >= self.entry_z_threshold:
            raise ValueError("exit_z_threshold must be strictly less than entry_z_threshold")
        if self.stop_z_threshold <= self.entry_z_threshold:
            raise ValueError("stop_z_threshold must be strictly greater than entry_z_threshold")
        if self.min_observations > self.rolling_window:
            raise ValueError("min_observations cannot exceed rolling_window")
        return self


class CostScheduleScenario(BaseModel):
    """Rate assumptions for a single cost scenario (base, conservative, or stress).

    All bps values are 1 basis point = 0.01% = 0.0001 of turnover.
    Official statutory rates vs research assumptions are explicitly documented.
    """

    model_config = ConfigDict(frozen=True)

    scenario_name: CostScenarioName
    effective_from: date = Field(default=date(2024, 1, 1))
    rate_provenance_note: str = Field(
        default=(
            "Statutory CTT (0.01% on non-agri futures sell leg), Stamp Duty (0.002% on buy leg), "
            "SEBI fee (0.0001% / Rs 10 per crore), and 18% GST on brokerage+exchange+SEBI follow "
            "Indian commodity derivatives norms; brokerage, exchange tariff tier, and slippage are "
            "explicit configurable research assumptions."
        )
    )
    brokerage_bps_per_leg: float = Field(..., ge=0.0, description="Brokerage assumption in bps per leg")
    exchange_txn_bps_per_leg: float = Field(
        default=0.26, ge=0.0, description="MCX transaction charge assumption in bps (Rs 260 per crore = 0.26 bps)"
    )
    sebi_turnover_bps_per_leg: float = Field(
        default=0.01, ge=0.0, description="SEBI fee in bps (Rs 10 per crore = 0.01 bps)"
    )
    ctt_sell_bps: float = Field(
        default=1.0, ge=0.0, description="Commodity Transaction Tax on non-agri futures sell leg (0.01% = 1.0 bps)"
    )
    stamp_duty_buy_bps: float = Field(
        default=0.20, ge=0.0, description="Stamp duty on futures buy leg (0.002% = 0.20 bps)"
    )
    gst_rate_fraction: float = Field(
        default=0.18, ge=0.0, le=1.0, description="GST fraction (18%) applied to brokerage + exchange + SEBI fees"
    )
    slippage_bps_per_leg: float = Field(
        ..., ge=0.0, description="Additional execution slippage assumption per leg in bps"
    )
    half_spread_multiplier: float = Field(
        default=1.0, ge=0.0, description="Multiplier on observed half bid-ask spread per leg execution"
    )


class CostsConfig(BaseModel):
    """Multi-scenario transaction cost configuration and minimum viability thresholds."""

    model_config = ConfigDict(frozen=True)

    default_scenario: CostScenarioName = Field(default=CostScenarioName.BASE)
    min_net_edge_bps: float = Field(default=1.5, ge=0.0, description="Minimum net expected convergence in bps after all round-trip costs")
    min_gross_to_cost_ratio: float = Field(default=1.25, gt=1.0, description="Minimum ratio of gross expected convergence to total round-trip cost")
    scenarios: dict[CostScenarioName, CostScheduleScenario] = Field(
        default_factory=lambda: {
            CostScenarioName.BASE: CostScheduleScenario(
                scenario_name=CostScenarioName.BASE,
                brokerage_bps_per_leg=0.30,
                exchange_txn_bps_per_leg=0.26,
                sebi_turnover_bps_per_leg=0.01,
                ctt_sell_bps=1.0,
                stamp_duty_buy_bps=0.20,
                gst_rate_fraction=0.18,
                slippage_bps_per_leg=0.50,
                half_spread_multiplier=1.0,
            ),
            CostScenarioName.CONSERVATIVE: CostScheduleScenario(
                scenario_name=CostScenarioName.CONSERVATIVE,
                brokerage_bps_per_leg=0.60,
                exchange_txn_bps_per_leg=0.26,
                sebi_turnover_bps_per_leg=0.01,
                ctt_sell_bps=1.0,
                stamp_duty_buy_bps=0.20,
                gst_rate_fraction=0.18,
                slippage_bps_per_leg=1.00,
                half_spread_multiplier=1.25,
            ),
            CostScenarioName.STRESS: CostScheduleScenario(
                scenario_name=CostScenarioName.STRESS,
                brokerage_bps_per_leg=1.00,
                exchange_txn_bps_per_leg=0.26,
                sebi_turnover_bps_per_leg=0.01,
                ctt_sell_bps=1.0,
                stamp_duty_buy_bps=0.20,
                gst_rate_fraction=0.18,
                slippage_bps_per_leg=2.00,
                half_spread_multiplier=1.75,
            ),
        }
    )


class BacktestConfig(BaseModel):
    """Chronological split and walk-forward backtest configuration."""

    model_config = ConfigDict(frozen=True)

    train_fraction: float = Field(default=0.50, gt=0.0, lt=1.0)
    validation_fraction: float = Field(default=0.25, gt=0.0, lt=1.0)
    frozen_test_fraction: float = Field(default=0.25, gt=0.0, lt=1.0)
    max_holding_bars: int = Field(default=15, ge=1)
    max_concurrent_trades_per_pair: int = Field(default=1, ge=1)
    min_completed_trades_for_evidence: int = Field(default=3, ge=1)
    min_bars_for_backtest: int = Field(default=25, ge=10)
    position_notional_grams: float = Field(
        default=1000.0, gt=0.0, description="Target normalized gold notional in grams per spread trade"
    )

    @model_validator(mode="after")
    def _validate_splits(self) -> BacktestConfig:
        total = self.train_fraction + self.validation_fraction + self.frozen_test_fraction
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Chronological splits must sum to 1.0, got {total}")
        return self


class AureusConfig(BaseModel):
    """Master configuration for an AUREUS-RV 3.0 research run."""

    model_config = ConfigDict(frozen=True)

    config_version: str = Field(default="3.0.0")
    random_seed: int = Field(default=42)
    pairing: PairingConfig = Field(default_factory=PairingConfig)
    liquidity: LiquidityConfig = Field(default_factory=LiquidityConfig)
    statistics: StatisticsConfig = Field(default_factory=StatisticsConfig)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of the canonical JSON configuration."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def from_yaml(cls, path: str | Path) -> AureusConfig:
        """Load and validate configuration from a YAML file."""
        raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    def to_yaml(self, path: str | Path) -> None:
        """Serialize configuration to a YAML file."""
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(json.dumps(self.model_dump(mode="json")))
        out_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
