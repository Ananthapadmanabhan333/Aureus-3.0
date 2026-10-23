# Changelog

All notable changes to **AUREUS-RV 3.0** are documented in this file.

## [3.0.0] — 2026-10-23

### Added
- **Core Quantitative Engine (`src/aureus_rv/`):**
  - CSV and Parquet dataset ingestion with SHA-256 file hashing (`ingestion/loader.py`).
  - Zero-imputation row validation and quarantine engine with explicit `ReasonCode` classifications (`validation/validator.py`).
  - Versioned effective-dated MCX Gold contract specification registry (`contracts/registry.py`) supporting `GOLD`, `GOLDM`, `GOLDPETAL`, and `GOLDGUINEA`.
  - Physical unit and purity normalization to INR per gram at 999 fineness (`normalization/normalizer.py`).
  - Expiry-aware contract pairing, DTE calculation, and tender-period rollover freeze checks (`pairing/engine.py`).
  - Historical proxy liquidity screening across volume, open interest, bid-ask spread, freshness, and bar count (`liquidity/screener.py`).
  - Past-only statistical spread analysis with rolling z-scores, OLS regressions, standardized residuals, and optional ADF stationarity tests (`statistics/spread.py`).
  - Two-leg Indian commodity derivatives transaction-cost waterfall across `base`, `conservative`, and `stress` scenarios (`costs/waterfall.py`).
  - Fail-closed G0–G6 decision gate engine (`decisions/gates.py`) supporting `QUIET`, `REJECTED`, `NO-EDGE`, and `TRADE SIGNAL`.
  - Chronological walk-forward backtester (`backtesting/engine.py`) with `TRAIN` / `VALIDATION` / `FROZEN_TEST` splits, naive baseline comparison, and `INSUFFICIENT_EVIDENCE` abstention.
  - DuckDB relational storage (`storage/duckdb_store.py`), Parquet artifact export, and self-sealing SHA-256 run manifests (`evidence/manifest.py`).
  - JSON, Markdown, HTML, and CSV report generators (`reporting/generator.py`).
- **Institutional Streamlit Research Interface (`src/aureus_rv/dashboard/`):**
  - 8 functional pages (Executive Overview, Contract Explorer, Spread Research, Transaction-Cost Lab, Backtesting Workbench, Decision Audit, Data Management, Reports & Evidence) styled in dark charcoal and gold.
- **Documentation & DevOps:**
  - Complete 11-document architecture and quantitative specification suite under `docs/`.
  - `Dockerfile`, `Makefile`, GitHub Actions CI (`.github/workflows/ci.yml`), and comprehensive unit/integration/regression test suites.
