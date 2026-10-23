# AUREUS-RV 3.0 — Known Limitations & Future Work

## 1. Current Scope & Honest Limitations

1. **Synthetic Demo Data vs. Verified Exchange Feeds:**
   - The repository ships with a deterministic, multi-scenario synthetic dataset (`SYNTHETIC_DEMO`) designed to exercise all validation, normalization, pairing, cost, and decision-gate edge cases offline without paid data subscriptions.
   - While AUREUS-RV 3.0 supports ingesting real historical MCX CSV/Parquet files conforming to `REQUIRED_SCHEMA_COLUMNS`, **the system has not been independently validated on live tick-by-tick MCX order-book feeds**.
2. **Proxy Liquidity Metrics:**
   - Liquidity screening (`src/aureus_rv/liquidity/screener.py`) uses bar-level traded volume (`volume_lots`), open interest (`open_interest_lots`), top-of-book bid-ask spread (`bid_ask_spread_bps`), and quote age (`quote_age_seconds`).
   - These are explicitly labeled `PROXY_BAR_VOLUME_OI_BIDASK (Not Full L2 Orderbook Depth)` and do not model full Level-2/Level-3 limit-order-book market impact for large institutional clips.
3. **Execution Legging Risk:**
   - Spread trades across two futures legs (`GOLD` vs `GOLDM` or calendar months) carry execution legging risk if one leg fills while the other moves. This is approximated via configurable `slippage_bps_per_leg` and `half_spread_multiplier` in the cost waterfall (`base`, `conservative`, `stress`), rather than a continuous-time microstructure simulator.
4. **Physical Delivery & Margin Funding Costs:**
   - Near-month contracts are automatically frozen prior to the tender period (`ERR_NEAR_LEG_IN_TENDER_OR_ROLLOVER`), so physical delivery charges and warehouse assaying fees are not modeled. Initial/maintenance SPAN margin funding costs are not included in the transaction-cost waterfall.
5. **Cryptographic Hash Scope:**
   - SHA-256 hashes in `run_manifest.json` verify computational reproducibility and post-run artifact immutability; they do not attest to the external authenticity of an uploaded market dataset.

## 2. Planned Future Work (Not Claimed as Implemented)

- Integration with historical L2 order-book snapshots for depth-weighted execution slippage.
- SPAN / exposure margin capital-usage accounting in net return-on-margin metrics.
- Intraday bar frequency calibration (1-minute / 5-minute bars with session boundary filters).
