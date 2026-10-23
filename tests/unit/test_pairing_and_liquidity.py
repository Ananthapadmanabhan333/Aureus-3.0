"""Unit tests for expiry-aware contract pairing, tender-period rollover checks, and liquidity screening."""

from __future__ import annotations

from datetime import date

import pandas as pd

from aureus_rv.config.settings import LiquidityConfig, PairingConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.liquidity.screener import screen_pair_liquidity
from aureus_rv.models import ContractInstanceId, PairId, ReasonCode
from aureus_rv.pairing.engine import evaluate_pair_eligibility


def test_pairing_eligibility_and_rejection_reasons() -> None:
    """Verify valid pair, tender/rollover rejection, excessive gap rejection, and inverted expiry rejection."""
    registry = ContractRegistry()
    config = PairingConfig(min_expiry_gap_days=7, max_expiry_gap_days=135, min_days_to_expiry_near=6)
    as_of = date(2026, 6, 1)

    near_ok = ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 8, 5))
    far_ok = ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 10, 5))
    res_ok = evaluate_pair_eligibility(near_ok, far_ok, as_of, config, registry)
    assert res_ok.eligible is True
    assert res_ok.reason_codes == [ReasonCode.PAIR_OK]
    assert res_ok.expiry_gap_days == 61

    # Rollover/tender period rejection (DTE = 3 days < 6)
    near_tender = ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 6, 4))
    res_tender = evaluate_pair_eligibility(near_tender, far_ok, as_of, config, registry)
    assert res_tender.eligible is False
    assert ReasonCode.ERR_NEAR_LEG_IN_TENDER_OR_ROLLOVER in res_tender.reason_codes

    # Excessive expiry gap (> 135 days)
    far_distant = ContractInstanceId(symbol="GOLD", expiry_date=date(2027, 4, 5))
    res_distant = evaluate_pair_eligibility(near_ok, far_distant, as_of, config, registry)
    assert res_distant.eligible is False
    assert ReasonCode.ERR_EXPIRY_DISTANCE_TOO_LARGE in res_distant.reason_codes

    # Inverted expiry
    res_inv = evaluate_pair_eligibility(far_ok, near_ok, as_of, config, registry)
    assert res_inv.eligible is False
    assert ReasonCode.ERR_INVERTED_PAIR_EXPIRY in res_inv.reason_codes


def test_liquidity_screening_thresholds() -> None:
    """Verify liquidity screening flags low volume, low OI, wide bid-ask spread, stale quotes, and low observation count."""
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 8, 5)),
        far_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 10, 5)),
    )
    cfg = LiquidityConfig(
        min_volume_lots=50,
        min_open_interest_lots=100,
        max_bid_ask_spread_bps=15.0,
        max_quote_staleness_seconds=300,
        min_rolling_observations=10,
        rolling_window_bars=10,
    )

    # Create 10 aligned rows with poor liquidity on the last row
    rows = []
    for i in range(10):
        rows.append(
            {
                "timestamp": f"2026-05-{10 + i:02d}T10:00:00Z",
                "volume_lots_near": 10 if i == 9 else 200,
                "volume_lots_far": 200,
                "open_interest_lots_near": 50 if i == 9 else 500,
                "open_interest_lots_far": 500,
                "bid_ask_spread_bps_near": 25.0 if i == 9 else 2.0,
                "bid_ask_spread_bps_far": 2.0,
                "quote_age_seconds_near": 600 if i == 9 else 10,
                "quote_age_seconds_far": 10,
            }
        )
    df = pd.DataFrame(rows)
    res = screen_pair_liquidity(df, pair_id, cfg)
    assert res.passed is False
    assert ReasonCode.ERR_LOW_VOLUME in res.reason_codes
    assert ReasonCode.ERR_LOW_OPEN_INTEREST in res.reason_codes
    assert ReasonCode.ERR_WIDE_BID_ASK_SPREAD in res.reason_codes
    assert ReasonCode.ERR_STALE_QUOTE in res.reason_codes
    assert "PROXY_BAR_VOLUME_OI_BIDASK" in res.proxy_liquidity_label
