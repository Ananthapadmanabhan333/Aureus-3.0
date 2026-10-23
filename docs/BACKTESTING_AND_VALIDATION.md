# AUREUS-RV 3.0 — Backtesting & Walk-Forward Validation

## 1. Chronological Split Architecture

Every eligible contract pair's aligned time series of length $N$ bars is partitioned chronologically without shuffling:
- **`TRAIN` (default 50%):** Initial historical regime `[0 .. train_cut - 1]`.
- **`VALIDATION` (default 25%):** Intermediate out-of-sample regime `[train_cut .. val_cut - 1]`.
- **`FROZEN_TEST` (default 25%):** Final held-out chronological evaluation regime `[val_cut .. N - 1]`.

Parameters are never optimized on the `FROZEN_TEST` split.

## 2. Leakage Prevention Protocol

At each chronological bar index $k \in \{0, \dots, N-1\}$:
1. The engine slices `past_slice = aligned_df.iloc[: k + 1]`.
2. Pairing eligibility (`evaluate_pair_eligibility`), liquidity screening (`screen_pair_liquidity`), spread statistics (`analyze_pair_spread_up_to`), and cost evaluation (`evaluate_pair_costs`) are executed solely on `past_slice`.
3. Automated unit test `test_lookahead_leakage_prevention` proves that multiplying all future prices ($t > T$) by $5\times$ changes rolling means, standard deviations, z-scores, and OLS $\beta$ at timestamp $T$ by $0.000000000000000$.

## 3. Position Lifecycle & Exit Rules

- **Non-Overlapping Control:** At most `max_concurrent_trades_per_pair = 1` position can be active for a given pair at any time.
- **Exit Triggers:** An open spread position exits at bar $k$ if any of the following occur:
  1. `MEAN_REVERSION_TARGET`: $Z_k \le Z_{\text{exit}}$ (for `SHORT_SPREAD`) or $Z_k \ge -Z_{\text{exit}}$ (for `LONG_SPREAD`).
  2. `STOP_LOSS_Z_THRESHOLD`: $|Z_k| \ge Z_{\text{stop}}$ (structural break guard).
  3. `MAX_HOLDING_PERIOD`: Bars held $\ge \text{max\_holding\_bars}$.
  4. `ROLLOVER_OR_EXPIRY_GUARD`: Near leg enters the tender/rollover freeze window.
  5. `END_OF_SERIES_CLOSE`: Final bar of the series reached.
- **Realized Two-Leg Costs:** Every completed trade deducts the full two-leg round-trip cost waterfall from gross spread convergence.

## 4. Baseline Comparison & `INSUFFICIENT_EVIDENCE` Governance

- **Naive Unconditional Carry Baseline:** Each split regime computes the net P&L (after two-leg round-trip costs) of a naive unconditional short-spread carry trade held from the start to the end of that split.
- **Evidence Sufficiency (Gate G6):** If total completed trades $< \text{min\_completed\_trades\_for\_evidence}$ (default $3$) or total aligned bars $< \text{min\_bars\_for\_backtest}$ (default $25$), the backtester returns `ReasonCode.INSUFFICIENT_EVIDENCE` and Gate G6 fails closed (`REJECTED`).
