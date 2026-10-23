"""Historical liquidity screening for contract pairs (volume, OI, bid-ask spread, freshness, observation count).

Strictly uses only historical observations available up to the decision timestamp.
Proxy liquidity metrics are explicitly labeled.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict

from aureus_rv.config.settings import LiquidityConfig
from aureus_rv.models import PairId, ReasonCode


class LiquidityScreenResult(BaseModel):
    """Result of screening both legs of a pair for executable liquidity at a historical timestamp."""

    model_config = ConfigDict(frozen=True)

    pair_id: PairId
    passed: bool
    reason_codes: list[ReasonCode]
    observation_count_window: int
    near_volume_lots: float
    far_volume_lots: float
    near_open_interest_lots: float
    far_open_interest_lots: float
    near_bid_ask_spread_bps: float
    far_bid_ask_spread_bps: float
    near_quote_age_seconds: float
    far_quote_age_seconds: float
    proxy_turnover_ratio_near: float
    proxy_turnover_ratio_far: float
    proxy_liquidity_label: str = "PROXY_BAR_VOLUME_OI_BIDASK (Not Full L2 Orderbook Depth)"
    explanation: str


def screen_pair_liquidity(
    aligned_history: pd.DataFrame,
    pair_id: PairId,
    config: LiquidityConfig,
) -> LiquidityScreenResult:
    """Evaluate liquidity of both legs at the latest row of `aligned_history` (which is already truncated <= T)."""
    if aligned_history.empty:
        return LiquidityScreenResult(
            pair_id=pair_id,
            passed=False,
            reason_codes=[ReasonCode.ERR_MISSING_LIQUIDITY_DATA],
            observation_count_window=0,
            near_volume_lots=0.0,
            far_volume_lots=0.0,
            near_open_interest_lots=0.0,
            far_open_interest_lots=0.0,
            near_bid_ask_spread_bps=0.0,
            far_bid_ask_spread_bps=0.0,
            near_quote_age_seconds=0.0,
            far_quote_age_seconds=0.0,
            proxy_turnover_ratio_near=0.0,
            proxy_turnover_ratio_far=0.0,
            explanation="No aligned historical observations available at decision timestamp",
        )

    window_df = aligned_history.tail(config.rolling_window_bars)
    obs_count = len(window_df)
    latest = aligned_history.iloc[-1]

    near_vol = float(latest["volume_lots_near"])
    far_vol = float(latest["volume_lots_far"])
    near_oi = float(latest["open_interest_lots_near"])
    far_oi = float(latest["open_interest_lots_far"])
    near_ba_bps = float(latest["bid_ask_spread_bps_near"])
    far_ba_bps = float(latest["bid_ask_spread_bps_far"])
    near_age = float(latest["quote_age_seconds_near"])
    far_age = float(latest["quote_age_seconds_far"])

    proxy_ratio_near = near_vol / max(near_oi, 1.0)
    proxy_ratio_far = far_vol / max(far_oi, 1.0)

    reasons: list[ReasonCode] = []
    explanations: list[str] = []

    if obs_count < config.min_rolling_observations:
        reasons.append(ReasonCode.ERR_INSUFFICIENT_OBSERVATION_COUNT)
        explanations.append(
            f"Rolling observation count ({obs_count}) < min_rolling_observations ({config.min_rolling_observations})"
        )

    if near_vol < config.min_volume_lots or far_vol < config.min_volume_lots:
        reasons.append(ReasonCode.ERR_LOW_VOLUME)
        explanations.append(
            f"Volume below threshold ({config.min_volume_lots}): near={near_vol}, far={far_vol}"
        )

    if near_oi < config.min_open_interest_lots or far_oi < config.min_open_interest_lots:
        reasons.append(ReasonCode.ERR_LOW_OPEN_INTEREST)
        explanations.append(
            f"Open interest below threshold ({config.min_open_interest_lots}): near={near_oi}, far={far_oi}"
        )

    if near_ba_bps > config.max_bid_ask_spread_bps or far_ba_bps > config.max_bid_ask_spread_bps:
        reasons.append(ReasonCode.ERR_WIDE_BID_ASK_SPREAD)
        explanations.append(
            f"Bid-ask spread exceeds {config.max_bid_ask_spread_bps} bps: near={near_ba_bps:.2f}, far={far_ba_bps:.2f}"
        )

    if near_age > config.max_quote_staleness_seconds or far_age > config.max_quote_staleness_seconds:
        reasons.append(ReasonCode.ERR_STALE_QUOTE)
        explanations.append(
            f"Quote age exceeds {config.max_quote_staleness_seconds}s: near={near_age}s, far={far_age}s"
        )

    if not reasons:
        reasons = [ReasonCode.LIQUIDITY_OK]
        explanations.append("Both legs passed volume, open interest, bid-ask spread, freshness, and count checks")

    return LiquidityScreenResult(
        pair_id=pair_id,
        passed=(reasons == [ReasonCode.LIQUIDITY_OK]),
        reason_codes=reasons,
        observation_count_window=obs_count,
        near_volume_lots=near_vol,
        far_volume_lots=far_vol,
        near_open_interest_lots=near_oi,
        far_open_interest_lots=far_oi,
        near_bid_ask_spread_bps=near_ba_bps,
        far_bid_ask_spread_bps=far_ba_bps,
        near_quote_age_seconds=near_age,
        far_quote_age_seconds=far_age,
        proxy_turnover_ratio_near=proxy_ratio_near,
        proxy_turnover_ratio_far=proxy_ratio_far,
        explanation="; ".join(explanations),
    )
