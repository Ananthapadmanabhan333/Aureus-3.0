# AUREUS-RV 3.0 — Five-Minute Reproducible Demonstration Guide

## Single-Command Launch

```powershell
# Windows PowerShell (with D:\ cache/venv configured if C:\ is low on space)
$env:UV_CACHE_DIR="D:\.uv_cache"; $env:UV_PROJECT_ENVIRONMENT="D:\.aureus_rv_venv"; uv run streamlit run scripts/launch_dashboard.py
```

---

## Step-by-Step 10-Point Demonstration Script (5 Minutes)

### Step 1 — Load Synthetic Data with Visible Provenance (0:00 – 0:30)
- Open **A. Executive Overview**.
- Point out the top gold-accented header badge: `SYNTHETIC DEMO DATASET (NOT LIVE MCX FEED)` and the deterministic Run ID (`RUN-C614D5278D45`).
- Show the KPI cards: `344 / 349` valid rows, `5` quarantined rows, `28` evaluated pairs, `3` `TRADE SIGNAL` (synthetic demonstration cases), `1` `NO-EDGE`, `1` `QUIET`, and `23` `REJECTED`.

### Step 2 — Compare Raw and Normalized Quotations (0:30 – 1:00)
- Navigate to **B. Contract Explorer**.
- Show the **Effective-Dated Contract Specification Registry** (`GOLD` at 995 fineness / 10g quote / 1,000g lot vs `GOLDM` at 999 fineness / 10g quote / 100g lot vs `GOLDGUINEA` 8g vs `GOLDPETAL` 1g).
- Point out how raw `GOLD` prices (`~71,900 INR/10g`) are converted via $\times (999/995)/10$ to `~7,219 INR/g (999)`, keeping normalized unit prices separate from lot size (`1,000g`) and raw contract notional (`~Rs 71.9 Lakhs`).

### Step 3 — Select an Expiry-Compatible Contract Pair (1:00 – 1:30)
- Navigate to **C. Spread Research**.
- Select Near Leg `GOLD_2026-08-05` and Far Leg `GOLD_2026-10-05`.
- Point out the `Pairing Status (G2): ELIGIBLE` card (`Gap: 61d | Near DTE: 65d`).

### Step 4 — Inspect Historical Spreads & Statistical Diagnostics (1:30 – 2:00)
- On **C. Spread Research**, examine the **Normalized Price Comparison**, **Normalized Spread & Rolling Equilibrium Mean**, and **Past-Only Rolling Spread Z-Score Trajectory**.
- Toggle **Run ADF Stationarity Check** to compute the Augmented Dickey-Fuller $p$-value in real time through the backend.

### Step 5 — Calculate Base, Conservative, and Stress Costs (2:00 – 2:30)
- Navigate to **D. Transaction-Cost Lab**.
- Select `GOLD_2026-08-05__VS__GOLD_2026-10-05` and inspect the **Per-Leg Round-Trip Cost Breakdown** table (Brokerage, MCX Exchange + SEBI fee, 18% GST, sell-side CTT, buy-side Stamp Duty, and Spread+Slippage) alongside the **Net Expected Edge Across Scenarios** chart (`BASE`, `CONSERVATIVE`, `STRESS`).

### Step 6 — Show a Candidate Becoming `NO-EDGE` When Costs Erase Its Opportunity (2:30 – 3:00)
- In **D. Transaction-Cost Lab**, select `GOLD_2026-08-05__VS__GOLDM_2026-08-28` (or reduce the Gross Expected Convergence slider on any pair).
- Show that although the pair has a statistical z-score anomaly ($Z = +3.75\sigma$), its gross expected convergence (`2.09 bps`) is smaller than the two-leg round-trip cost (`9.58 bps`), resulting in `-7.50 bps` net edge and automatic `NO-EDGE` classification (`NO_EDGE_COSTS_EXCEED_SPREAD`).

### Step 7 — Inspect a `REJECTED` Candidate and Its Precise Failure Reasons (3:00 – 3:30)
- Navigate to **F. Decision Audit**.
- Select `GOLD_2026-06-04__VS__GOLD_2026-08-05 [REJECTED]` to show Gate `G2` failing with `ERR_NEAR_LEG_IN_TENDER_OR_ROLLOVER` (`dte_near = 3 < 6`).
- Select `GOLD_2026-08-05__VS__GOLDGUINEA_2026-08-31 [REJECTED]` to show Gate `G3` failing with `ERR_LOW_VOLUME`, `ERR_LOW_OPEN_INTEREST`, and `ERR_WIDE_BID_ASK_SPREAD`.
- Also visit **G. Data Management** to show the 5 quarantined raw rows (`ERR_NON_POSITIVE_PRICE`, `ERR_BID_ASK_INVERTED`, `ERR_UNKNOWN_QUOTATION_UNIT`, `ERR_UNMARKED_SYNTHETIC_SOURCE`, `ERR_DUPLICATE_OBSERVATION`).

### Step 8 — Run Chronological Walk-Forward Validation (3:30 – 4:00)
- Navigate to **E. Backtesting Workbench**.
- Inspect `GOLD_2026-08-05__VS__GOLD_2026-10-05` across the chronological `TRAIN`, `VALIDATION`, and `FROZEN_TEST` splits, comparing Gross P&L, Total Two-Leg Costs, Net Realized P&L, and the Naive Hold Baseline.

### Step 9 — Demonstrate `INSUFFICIENT_EVIDENCE` When Test Sample Is Inadequate (4:00 – 4:30)
- On **E. Backtesting Workbench**, move the **Min Completed Trades for Evidence (G6)** slider from `3` up to `6`.
- Immediately observe the status banner flip to `ABSTAIN — INSUFFICIENT_EVIDENCE: Completed trades (3) < minimum required (6). Research gate G6 fails closed.`

### Step 10 — Verify Run Manifest and Export Research Reports (4:30 – 5:00)
- Navigate to **H. Reports & Evidence**.
- Point out the green verification banner confirming the SHA-256 self-digest and all artifact hashes on disk.
- Click the download buttons for the **Run Manifest (JSON)**, **Decision Audit Export (CSV)**, **Markdown Research Report (.md)**, and **Standalone HTML Research Report (.html)**.
