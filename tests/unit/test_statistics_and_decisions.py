"""Unit tests for statistical spread analysis, look-ahead leakage prevention, and G0-G6 decision transitions."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from aureus_rv.config.settings import AureusConfig, StatisticsConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.decisions.gates import evaluate_decision_gates
from aureus_rv.models import ContractInstanceId, DecisionState, PairId, ReasonCode
from aureus_rv.normalization.normalizer import normalize_dataframe_observations
from aureus_rv.pairing.engine import align_pair_history_up_to
from aureus_rv.pipeline import generate_synthetic_demo_dataset
from aureus_rv.statistics.spread import analyze_pair_spread_up_to
from aureus_rv.validation.validator import validate_dataset


def test_lookahead_leakage_prevention() -> None:
    """Prove that corrupting future prices at t > T has zero effect on statistical diagnostics at t = T."""
    raw_df = generate_synthetic_demo_dataset(seed=42, n_bars=40)
    registry = ContractRegistry()
    clean_df, _ = validate_dataset(raw_df, registry)
    norm_df = normalize_dataframe_observations(clean_df, registry)

    pair_id = PairId(
        near_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 8, 5)),
        far_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 10, 5)),
    )
    timestamps = sorted(norm_df["timestamp"].unique())
    decision_ts = timestamps[25]

    aligned_clean = align_pair_history_up_to(norm_df, pair_id, decision_ts)
    stats_clean = analyze_pair_spread_up_to(aligned_clean, pair_id, StatisticsConfig())

    # Now massively shock all future observations strictly after decision_ts
    shocked_df = norm_df.copy()
    future_mask = shocked_df["timestamp"] > decision_ts
    shocked_df.loc[future_mask, "norm_close_inr_g_999"] *= 5.0

    aligned_shocked = align_pair_history_up_to(shocked_df, pair_id, decision_ts)
    stats_shocked = analyze_pair_spread_up_to(aligned_shocked, pair_id, StatisticsConfig())

    assert stats_clean.z_score == pytest.approx(stats_shocked.z_score, rel=1e-15)
    assert stats_clean.rolling_mean_inr_g_999 == pytest.approx(stats_shocked.rolling_mean_inr_g_999, rel=1e-15)
    assert stats_clean.rolling_std_inr_g_999 == pytest.approx(stats_shocked.rolling_std_inr_g_999, rel=1e-15)
    assert stats_clean.ols_beta == pytest.approx(stats_shocked.ols_beta, rel=1e-15)


def test_zero_variance_and_insufficient_history_handling() -> None:
    """Verify safe handling of constant spreads (zero variance) and short histories."""
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 8, 5)),
        far_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 10, 5)),
    )
    cfg = StatisticsConfig(rolling_window=20, min_observations=20)

    # 1. Insufficient history (only 5 bars)
    short_df = pd.DataFrame(
        {
            "close_near": np.full(5, 72000.0),
            "close_far": np.full(5, 72500.0),
            "norm_close_inr_g_999_near": np.full(5, 7200.0),
            "norm_close_inr_g_999_far": np.full(5, 7250.0),
        }
    )
    res_short = analyze_pair_spread_up_to(short_df, pair_id, cfg)
    assert res_short.valid_statistics is False
    assert ReasonCode.ERR_INSUFFICIENT_HISTORY in res_short.reason_codes

    # 2. Constant spread (zero variance over 20 bars)
    const_df = pd.DataFrame(
        {
            "close_near": np.linspace(72000.0, 72200.0, 20),
            "close_far": np.linspace(72500.0, 72700.0, 20),
            "norm_close_inr_g_999_near": np.linspace(7200.0, 7220.0, 20),
            "norm_close_inr_g_999_far": np.linspace(7250.0, 7270.0, 20),
        }
    )
    res_const = analyze_pair_spread_up_to(const_df, pair_id, cfg)
    assert res_const.valid_statistics is False
    assert ReasonCode.ERR_ZERO_SPREAD_VARIANCE in res_const.reason_codes


def test_decision_engine_fails_closed_on_missing_inputs() -> None:
    """Verify Decision Engine fails closed to REJECTED when mandatory gate inputs are None."""
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 8, 5)),
        far_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 10, 5)),
    )
    dec = evaluate_decision_gates(
        run_id="RUN-TEST",
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        pair_id=pair_id,
        config=AureusConfig(),
        dataset_hash="abc123456789",
        is_synthetic=True,
        g0_data_valid=True,
        g0_reasons=[ReasonCode.VALID_OK],
        g1_spec_valid=True,
        g1_reasons=[ReasonCode.VALID_OK],
        pairing_result=None,
        liquidity_result=None,
        stats_result=None,
        cost_result=None,
    )
    assert dec.state == DecisionState.REJECTED
    assert dec.primary_reason_code == ReasonCode.ERR_MISSING_MANDATORY_GATE_INPUT
