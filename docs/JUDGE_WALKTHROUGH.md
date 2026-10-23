# AUREUS-RV 3.0 — Hackathon Judge Walkthrough & Technical Q&A

## 1. Quick Verification Checklist for Judges

1. **Run the Automated Test Suite (32 Tests):**
   ```powershell
   uv run pytest -v
   ```
   Verifies physical normalization math, manual two-leg cost waterfall examples, zero look-ahead leakage, G0–G6 fail-closed gate transitions, DuckDB persistence, SHA-256 manifest tamper detection, dashboard view models, and safe upload validation.

2. **Launch the Institutional Dashboard:**
   ```powershell
   uv run streamlit run scripts/launch_dashboard.py
   ```

3. **Inspect Key Engineering Highlights:**
   - **No Hardcoded UI Numbers:** Every table, KPI card, and chart in `src/aureus_rv/dashboard/app.py` is computed by `src/aureus_rv/dashboard/view_models.py` calling the core backend modules.
   - **Explicit Abstention (`NO-EDGE` & `REJECTED`):** Rather than over-promising signals, the engine demonstrates how raw statistical anomalies are rejected when two-leg Indian transaction costs (CTT, Stamp Duty, Exchange/SEBI fees, 18% GST, bid-ask spread, slippage) exceed expected convergence (`GOLD_2026-08-05__VS__GOLDM_2026-08-28` $\rightarrow$ `NO-EDGE`) or when walk-forward sample sizes are insufficient (`INSUFFICIENT_EVIDENCE`).

---

## 2. Technical Questions & Concise Answers for Judges

**Q1: Why is purity and unit normalization mandatory before computing MCX gold spreads?**  
**A:** MCX Standard `GOLD` is quoted per 10 grams at **995 fineness** (1 kg lot), whereas `GOLDM` (10g quote), `GOLDGUINEA` (8g quote), and `GOLDPETAL` (1g quote) are **999 fineness**. Comparing raw prices without applying $\times (999/\text{fineness})/\text{grams}$ creates a $\sim 40.2\text{ bps}$ artificial purity bias and $10\times$ unit scale mismatch. `normalizer.py` normalizes all quotes to **INR per 1g at 999 fineness** while keeping contract lot multipliers separate.

**Q2: How does your transaction-cost engine avoid double-counting statutory Indian taxes?**  
**A:** In a two-leg round-trip (4 executions total), each leg executes exactly 1 Buy and 1 Sell. In `costs/waterfall.py`, Commodity Transaction Tax (`CTT = 0.01%`) is applied strictly to the **1 sell execution** per leg, Stamp Duty (`0.002%`) is applied strictly to the **1 buy execution** per leg, and `18% GST` is applied only to Brokerage + Exchange Transaction Fee + SEBI Turnover Fee (never on CTT or Stamp Duty).

**Q3: How do you guarantee zero look-ahead leakage in rolling statistics and backtesting?**  
**A:** `align_pair_history_up_to()` truncates the DataFrame at `timestamp <= as_of_timestamp` before any rolling window or OLS regression is computed. Our unit test `test_lookahead_leakage_prevention` multiplies all future prices ($t > T$) by $5\times$ and asserts that rolling mean, std, z-score, and OLS $\beta$ at time $T$ remain bit-for-bit identical (`rel=1e-15`).

**Q4: What happens when a pair has a strong statistical z-score, passes costs, but has too few historical trades?**  
**A:** Gate `G6` (`Research Evidence Sufficiency`) checks the walk-forward backtest's `evidence_status`. If completed trades fall below `min_completed_trades_for_evidence`, the backtester returns `INSUFFICIENT_EVIDENCE` and the decision engine fails closed to `REJECTED` with primary reason `INSUFFICIENT_EVIDENCE`.

**Q5: What does the SHA-256 hash in `run_manifest.json` prove — and what does it NOT prove?**  
**A:** It proves **computational reproducibility and post-run artifact immutability** (any modification to `research_report.md`, Parquet outputs, or manifest fields is caught by `verify_run_manifest`). As explicitly stated in our manifest disclaimer, it does **not** prove that an input file came from a live exchange feed.
