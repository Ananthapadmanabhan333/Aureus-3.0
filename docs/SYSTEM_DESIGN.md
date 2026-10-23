# AUREUS-RV 3.0 — System Design & Module Responsibilities

## 1. Design Philosophy

1. **Zero Silent Imputation:** Missing prices, inverted quotes, unknown quotation units, and mismatched contract specifications are never filled or guessed. Invalid observations are quarantined with explicit machine-readable `ReasonCode` values.
2. **Physical Parity Before Statistical Comparison:** All gold quotations are normalized to **INR per 1 gram at 999 fineness** prior to spread construction, while raw contract lot size and multiplier are preserved separately for notional and P&L calculations.
3. **Chronological Integrity (Zero Look-Ahead):** Pair history alignment (`align_pair_history_up_to`) truncates data strictly at `timestamp <= T` before rolling statistics or regressions are computed.
4. **Fail-Closed Governance:** Any missing gate input or insufficient walk-forward sample size causes the decision engine to abstain (`REJECTED` or `NO-EDGE`), never defaulting to a permissive signal.
5. **Single Source of Truth:** The Streamlit interface (`src/aureus_rv/dashboard/`) delegates 100% of calculations to the backend modules via typed view models (`src/aureus_rv/dashboard/view_models.py`).

## 2. Module Responsibility Matrix

| Module Path | Primary Classes / Functions | Responsibility |
| :--- | :--- | :--- |
| `src/aureus_rv/models.py` | `DecisionState`, `ReasonCode`, `ContractInstanceId`, `PairId`, `DecisionRecord`, `QuarantinedRow` | Core domain enumerations, immutable identifiers, and structured error/audit schemas. |
| `src/aureus_rv/config/settings.py` | `AureusConfig`, `PairingConfig`, `LiquidityConfig`, `StatisticsConfig`, `CostsConfig`, `BacktestConfig` | Validated configuration hierarchy and deterministic SHA-256 configuration hashing. |
| `src/aureus_rv/contracts/registry.py` | `ContractSpec`, `ContractRegistry`, `DEFAULT_MCX_SPECS` | Effective-dated specification registry for `GOLD`, `GOLDM`, `GOLDPETAL`, and `GOLDGUINEA`. |
| `src/aureus_rv/ingestion/loader.py` | `load_raw_dataset`, `compute_file_sha256`, `IngestionManifest` | CSV/Parquet file ingestion, required column verification, and SHA-256 input hashing. |
| `src/aureus_rv/validation/validator.py` | `validate_dataset`, `ValidationReport` | Row-by-row validation, duplicate detection, provenance verification, and quarantine logging. |
| `src/aureus_rv/normalization/normalizer.py` | `normalize_price_to_inr_per_g_999`, `compute_normalized_breakdown`, `normalize_dataframe_observations` | Conversion of raw quotations to INR/g (999) and enrichment of validated DataFrames. |
| `src/aureus_rv/pairing/engine.py` | `evaluate_pair_eligibility`, `discover_candidate_pairs_at_timestamp`, `align_pair_history_up_to` | Expiry gap limits, tender-period rollover guards, and leakage-free time alignment. |
| `src/aureus_rv/liquidity/screener.py` | `screen_pair_liquidity`, `LiquidityScreenResult` | Historical volume, OI, bid-ask spread, freshness, and rolling bar-count screening. |
| `src/aureus_rv/statistics/spread.py` | `analyze_pair_spread_up_to`, `SpreadDiagnosticsResult` | Rolling mean/std, z-scores, OLS regression ($\alpha, \beta, R^2$), residuals, and optional ADF test. |
| `src/aureus_rv/costs/waterfall.py` | `compute_single_leg_round_trip_cost`, `evaluate_pair_costs`, `PairCostWaterfallResult` | Full two-leg Indian derivatives round-trip cost waterfall across `base`, `conservative`, and `stress` scenarios. |
| `src/aureus_rv/decisions/gates.py` | `evaluate_decision_gates` | Deterministic evaluation of gates G0–G6 and transition to `QUIET`, `REJECTED`, `NO-EDGE`, or `TRADE SIGNAL`. |
| `src/aureus_rv/backtesting/engine.py` | `run_pair_walk_forward_backtest`, `PairBacktestReport` | Chronological `TRAIN` / `VALIDATION` / `FROZEN_TEST` walk-forward simulation and `INSUFFICIENT_EVIDENCE` detection. |
| `src/aureus_rv/evidence/manifest.py` | `RunManifest`, `save_run_manifest`, `verify_run_manifest` | Self-hashed SHA-256 run manifests and post-run artifact tamper detection. |
| `src/aureus_rv/storage/duckdb_store.py` | `AureusStorage` | DuckDB relational tables (`research_runs`, `decisions`, `backtest_summaries`, `quarantined_rows`) and Parquet I/O. |
| `src/aureus_rv/reporting/generator.py` | `write_research_reports`, `generate_markdown_report`, `generate_html_report` | Export of JSON, Markdown, HTML, and CSV audit reports. |
| `src/aureus_rv/dashboard/` | `app.py`, `view_models.py`, `theme.py` | 8-page institutional Streamlit interface and testable pure-Python view models. |
