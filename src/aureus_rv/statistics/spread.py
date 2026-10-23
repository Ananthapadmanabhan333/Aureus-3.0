"""Statistical spread analysis, rolling regressions, z-scores, and stationarity diagnostics.

Strictly past-only: operates on aligned historical data up to the decision timestamp `T`.
Distinguishes raw spreads, normalized spreads, regression residuals, and statistical anomalies.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict
from scipy import stats
from statsmodels.tsa.stattools import adfuller

from aureus_rv.config.settings import StatisticsConfig
from aureus_rv.models import PairId, ReasonCode, SpreadDirection


class SpreadDiagnosticsResult(BaseModel):
    """Comprehensive statistical diagnostics for a pair at a specific historical decision point."""

    model_config = ConfigDict(frozen=True)

    pair_id: PairId
    valid_statistics: bool
    anomaly_detected: bool
    suggested_direction: SpreadDirection
    reason_codes: list[ReasonCode]
    observations_used: int
    raw_near_close: float
    raw_far_close: float
    raw_unnormalized_diff: float
    norm_near_inr_g_999: float
    norm_far_inr_g_999: float
    norm_mid_reference_inr_g_999: float
    norm_spread_inr_g_999: float
    percentage_spread_pct: float
    spread_bps: float
    rolling_mean_inr_g_999: float
    rolling_std_inr_g_999: float
    z_score: float
    expected_reversion_inr_g_999: float
    expected_reversion_bps: float
    ols_alpha: float
    ols_beta: float
    ols_r_squared: float
    latest_residual_inr_g_999: float
    standardized_residual_z: float
    correlation: float
    adf_pvalue: float | None
    explanation: str


def analyze_pair_spread_up_to(
    aligned_history: pd.DataFrame,
    pair_id: PairId,
    config: StatisticsConfig,
) -> SpreadDiagnosticsResult:
    """Compute strictly past-only statistical diagnostics on `aligned_history` (truncated <= T)."""
    n_total = len(aligned_history)
    if n_total == 0:
        return _empty_stats_result(
            pair_id=pair_id,
            reason=ReasonCode.ERR_INSUFFICIENT_HISTORY,
            explanation="Zero historical observations available",
        )

    window_df = aligned_history.tail(config.rolling_window).copy()
    n_obs = len(window_df)
    latest = window_df.iloc[-1]

    raw_near = float(latest["close_near"])
    raw_far = float(latest["close_far"])
    raw_diff = raw_near - raw_far

    near_series = window_df["norm_close_inr_g_999_near"].astype(float).to_numpy()
    far_series = window_df["norm_close_inr_g_999_far"].astype(float).to_numpy()

    if np.isnan(near_series).any() or np.isnan(far_series).any():
        return _empty_stats_result(
            pair_id=pair_id,
            reason=ReasonCode.ERR_INSUFFICIENT_HISTORY,
            explanation="NaN values detected in normalized price window",
        )

    # Spread definition: Far minus Near (or Near minus Far).
    # In relative value: let spread S_t = norm_near_t - norm_far_t.
    # If S_t >> rolling_mean (positive z-score), Near is rich relative to Far -> SHORT_SPREAD (Short Near, Long Far).
    # If S_t << rolling_mean (negative z-score), Near is cheap relative to Far -> LONG_SPREAD (Long Near, Short Far).
    spread_series = near_series - far_series
    norm_near = float(near_series[-1])
    norm_far = float(far_series[-1])
    norm_ref_mid = 0.5 * (norm_near + norm_far)
    current_spread = float(spread_series[-1])
    pct_spread = (current_spread / norm_ref_mid) * 100.0 if norm_ref_mid > 0 else 0.0
    spread_bps = (current_spread / norm_ref_mid) * 10000.0 if norm_ref_mid > 0 else 0.0

    if n_obs < config.min_observations:
        return SpreadDiagnosticsResult(
            pair_id=pair_id,
            valid_statistics=False,
            anomaly_detected=False,
            suggested_direction=SpreadDirection.FLAT,
            reason_codes=[ReasonCode.ERR_INSUFFICIENT_HISTORY],
            observations_used=n_obs,
            raw_near_close=raw_near,
            raw_far_close=raw_far,
            raw_unnormalized_diff=raw_diff,
            norm_near_inr_g_999=norm_near,
            norm_far_inr_g_999=norm_far,
            norm_mid_reference_inr_g_999=norm_ref_mid,
            norm_spread_inr_g_999=current_spread,
            percentage_spread_pct=pct_spread,
            spread_bps=spread_bps,
            rolling_mean_inr_g_999=float(np.mean(spread_series)),
            rolling_std_inr_g_999=0.0,
            z_score=0.0,
            expected_reversion_inr_g_999=0.0,
            expected_reversion_bps=0.0,
            ols_alpha=0.0,
            ols_beta=1.0,
            ols_r_squared=0.0,
            latest_residual_inr_g_999=0.0,
            standardized_residual_z=0.0,
            correlation=0.0,
            adf_pvalue=None,
            explanation=f"Observations ({n_obs}) < min_observations ({config.min_observations})",
        )

    mean_spread = float(np.mean(spread_series))
    std_spread = float(np.std(spread_series, ddof=1))

    reasons: list[ReasonCode] = []
    explanations: list[str] = []

    if std_spread < config.min_spread_std_inr_per_g:
        reasons.append(ReasonCode.ERR_ZERO_SPREAD_VARIANCE)
        explanations.append(
            f"Spread rolling std ({std_spread:.6f}) below minimum ({config.min_spread_std_inr_per_g})"
        )
        z_score = 0.0
    else:
        z_score = (current_spread - mean_spread) / std_spread

    # Correlation & OLS Regression: near = alpha + beta * far + eps
    std_near = float(np.std(near_series, ddof=1))
    std_far = float(np.std(far_series, ddof=1))
    if std_near < 1e-8 or std_far < 1e-8:
        reasons.append(ReasonCode.ERR_UNSTABLE_REGRESSION)
        explanations.append("Near or Far price series has near-zero variance in window")
        corr = 0.0
        alpha, beta, r_sq = 0.0, 1.0, 0.0
        latest_resid = 0.0
        std_resid_z = 0.0
    else:
        lin_res = stats.linregress(far_series, near_series)
        beta = float(lin_res.slope)
        alpha = float(lin_res.intercept)
        corr = float(lin_res.rvalue)
        r_sq = corr * corr
        residuals = near_series - (alpha + beta * far_series)
        resid_std = float(np.std(residuals, ddof=1))
        latest_resid = float(residuals[-1])
        std_resid_z = latest_resid / resid_std if resid_std > 1e-8 else 0.0

        if not np.isfinite(beta) or beta <= 0.2 or beta >= 5.0:
            reasons.append(ReasonCode.ERR_UNSTABLE_REGRESSION)
            explanations.append(f"OLS beta ({beta:.4f}) outside stable physical bounds [0.2, 5.0]")

        if corr < config.min_correlation:
            reasons.append(ReasonCode.ERR_LOW_CORRELATION)
            explanations.append(f"Rolling correlation ({corr:.4f}) < min_correlation ({config.min_correlation})")

    # Optional ADF stationarity check
    adf_pval: float | None = None
    if config.run_adf_stationarity_test and std_spread >= config.min_spread_std_inr_per_g and n_obs >= 12:
        try:
            adf_stat = adfuller(spread_series, maxlag=1, autolag=None, result_object=False)
            adf_pval = float(adf_stat[1])
            if adf_pval > config.max_adf_pvalue:
                reasons.append(ReasonCode.ERR_NON_STATIONARY_SPREAD)
                explanations.append(f"ADF p-value ({adf_pval:.4f}) > max_adf_pvalue ({config.max_adf_pvalue})")
        except Exception as exc:
            reasons.append(ReasonCode.ERR_NON_STATIONARY_SPREAD)
            explanations.append(f"ADF test failed: {exc}")

    # Expected reversion to exit_z_threshold (conservative convergence target)
    abs_z = abs(z_score)
    if abs_z > config.exit_z_threshold and std_spread >= config.min_spread_std_inr_per_g:
        expected_rev_inr_g = (abs_z - config.exit_z_threshold) * std_spread
    else:
        expected_rev_inr_g = 0.0
    expected_rev_bps = (expected_rev_inr_g / norm_ref_mid) * 10000.0 if norm_ref_mid > 0 else 0.0

    # Determine statistical state
    valid_stats = len(reasons) == 0
    anomaly = False
    direction = SpreadDirection.FLAT

    if valid_stats:
        if abs_z >= config.stop_z_threshold:
            reasons.append(ReasonCode.ERR_ZSCORE_EXTREME_STOP)
            explanations.append(
                f"|z_score| ({abs_z:.2f}) >= stop_z_threshold ({config.stop_z_threshold}); structural break guard"
            )
            valid_stats = False
        elif abs_z >= config.entry_z_threshold:
            anomaly = True
            direction = SpreadDirection.SHORT_SPREAD if z_score > 0 else SpreadDirection.LONG_SPREAD
            reasons.append(ReasonCode.STATS_ANOMALY_DETECTED)
            explanations.append(
                f"Statistical spread anomaly detected: z={z_score:.2f} ({direction.value}), "
                f"expected convergence={expected_rev_bps:.2f} bps"
            )
        else:
            reasons.append(ReasonCode.STATS_WITHIN_NORMAL_BAND)
            explanations.append(
                f"|z_score| ({abs_z:.2f}) < entry_z_threshold ({config.entry_z_threshold}); spread within normal band"
            )

    return SpreadDiagnosticsResult(
        pair_id=pair_id,
        valid_statistics=valid_stats,
        anomaly_detected=anomaly,
        suggested_direction=direction,
        reason_codes=reasons,
        observations_used=n_obs,
        raw_near_close=raw_near,
        raw_far_close=raw_far,
        raw_unnormalized_diff=raw_diff,
        norm_near_inr_g_999=norm_near,
        norm_far_inr_g_999=norm_far,
        norm_mid_reference_inr_g_999=norm_ref_mid,
        norm_spread_inr_g_999=current_spread,
        percentage_spread_pct=pct_spread,
        spread_bps=spread_bps,
        rolling_mean_inr_g_999=mean_spread,
        rolling_std_inr_g_999=std_spread,
        z_score=z_score,
        expected_reversion_inr_g_999=expected_rev_inr_g,
        expected_reversion_bps=expected_rev_bps,
        ols_alpha=alpha,
        ols_beta=beta,
        ols_r_squared=r_sq,
        latest_residual_inr_g_999=latest_resid,
        standardized_residual_z=std_resid_z,
        correlation=corr,
        adf_pvalue=adf_pval,
        explanation="; ".join(explanations),
    )


def _empty_stats_result(
    pair_id: PairId,
    reason: ReasonCode,
    explanation: str,
) -> SpreadDiagnosticsResult:
    return SpreadDiagnosticsResult(
        pair_id=pair_id,
        valid_statistics=False,
        anomaly_detected=False,
        suggested_direction=SpreadDirection.FLAT,
        reason_codes=[reason],
        observations_used=0,
        raw_near_close=0.0,
        raw_far_close=0.0,
        raw_unnormalized_diff=0.0,
        norm_near_inr_g_999=0.0,
        norm_far_inr_g_999=0.0,
        norm_mid_reference_inr_g_999=0.0,
        norm_spread_inr_g_999=0.0,
        percentage_spread_pct=0.0,
        spread_bps=0.0,
        rolling_mean_inr_g_999=0.0,
        rolling_std_inr_g_999=0.0,
        z_score=0.0,
        expected_reversion_inr_g_999=0.0,
        expected_reversion_bps=0.0,
        ols_alpha=0.0,
        ols_beta=1.0,
        ols_r_squared=0.0,
        latest_residual_inr_g_999=0.0,
        standardized_residual_z=0.0,
        correlation=0.0,
        adf_pvalue=None,
        explanation=explanation,
    )
