# AUREUS-RV 3.0 — System Architecture

> **Core Engineering Principle:** `NORMALIZE → VALIDATE → PAIR → COST → ABSTAIN → PROVE`

## 1. Architectural Overview

**AUREUS-RV 3.0** is a deterministic, fail-closed quantitative research and decision-support instrument for relative-value opportunities across Indian MCX gold futures variants (`GOLD`, `GOLDM`, `GOLDPETAL`, `GOLDGUINEA`). It separates raw ingestion, data-quality quarantine, physical unit/purity normalization, expiry-aware pairing, liquidity screening, rolling past-only statistical diagnostics, two-leg Indian commodity derivatives transaction-cost waterfalls, G0–G6 decision gates, walk-forward backtesting, and SHA-256 verifiable DuckDB/Parquet evidence storage.

## 2. End-to-End Architecture Diagram

```mermaid
flowchart TD
    subgraph Input["1. Ingestion & Provenance"]
        CSV["CSV / Parquet Dataset"] --> Loader["ingestion/loader.py"]
        Synth["Deterministic Demo Generator"] --> Loader
    end

    subgraph QuarantineGate["2. Validation & Normalization (Gates G0 & G1)"]
        Loader --> Validator["validation/validator.py"]
        Registry["contracts/registry.py\n(Versioned MCX Specs)"] --> Validator
        Validator -- "Invalid / Malformed Rows" --> Quarantine["Quarantine Store\n(quarantined_observations.parquet)"]
        Validator -- "Valid Rows" --> Normalizer["normalization/normalizer.py\n(INR / 1g @ 999 Fineness)"]
        Registry --> Normalizer
    end

    subgraph QuantEngine["3. Lifecycle, Liquidity, Stats & Costs (Gates G2–G5)"]
        Normalizer --> Pairing["pairing/engine.py\n(DTE, Tender Freeze, Gap Bounds)"]
        Pairing --> Liquidity["liquidity/screener.py\n(Volume, OI, Spread, Quote Age)"]
        Pairing --> Stats["statistics/spread.py\n(Past-Only Z-Score, OLS Beta, ADF)"]
        Stats --> Costs["costs/waterfall.py\n(2-Leg CTT, Stamp, Exchange, SEBI, GST, Slippage)"]
    end

    subgraph Governance["4. Decision Gates, Walk-Forward & Evidence (Gate G6)"]
        Pairing --> Gates["decisions/gates.py\n(Fail-Closed G0–G6 State Machine)"]
        Liquidity --> Gates
        Stats --> Gates
        Costs --> Gates
        Backtest["backtesting/engine.py\n(Train / Validation / Frozen-Test)"] --> Gates
        Gates --> DuckDB["storage/duckdb_store.py\n(DuckDB + Parquet)"]
        Gates --> Manifest["evidence/manifest.py\n(SHA-256 Sealed RunManifest)"]
        Manifest --> Reports["reporting/generator.py\n(JSON, Markdown, HTML, CSV)"]
    end

    subgraph UI["5. Institutional Streamlit Interface"]
        DuckDB --> Dashboard["dashboard/app.py\n(Pages A–H via dashboard/view_models.py)"]
        Reports --> Dashboard
    end
```

## 3. Data Ingestion & Quarantine Flow

```mermaid
sequenceDiagram
    participant User as Researcher / CLI / UI
    participant Loader as ingestion.loader
    participant Val as validation.validator
    participant Reg as contracts.registry
    participant Norm as normalization.normalizer
    participant Store as storage.duckdb_store

    User->>Loader: load_raw_dataset(path)
    Loader->>Loader: Compute file SHA-256 & check required columns
    Loader-->>Val: raw_df + IngestionManifest
    loop Every Row in raw_df
        Val->>Val: Check nulls, timestamps, OHLC, bid <= ask, vol/OI >= 0
        Val->>Val: Check synthetic provenance honesty (SYNTHETIC_DEMO vs is_synthetic)
        Val->>Reg: validate_observation_against_spec(symbol, date, unit, fineness, lot)
        alt Row has >= 1 ReasonCode violation
            Val->>Store: Append QuarantinedRow with explicit ReasonCode & explanation
        else Row is valid
            Val->>Norm: Pass to normalize_dataframe_observations()
        end
    end
    Norm->>Store: Write normalized_observations.parquet + SHA-256 digest
```

## 4. Decision Gate State Machine (G0–G6)

```mermaid
stateDiagram-v2
    [*] --> G0_DataQuality
    G0_DataQuality --> REJECTED: Fail (Invalid / Missing / Unmarked Synthetic)
    G0_DataQuality --> G1_SpecValidity: Pass (VALID_OK)

    G1_SpecValidity --> REJECTED: Fail (Unknown Unit / Purity / Lot Mismatch)
    G1_SpecValidity --> G2_PairingEligibility: Pass (VALID_OK)

    G2_PairingEligibility --> REJECTED: Fail (Tender Period / DTE / Expiry Gap)
    G2_PairingEligibility --> G3_LiquidityScreen: Pass (PAIR_OK)

    G3_LiquidityScreen --> REJECTED: Fail (Low Vol / Low OI / Wide Bid-Ask / Stale)
    G3_LiquidityScreen --> G4_SpreadStatistics: Pass (LIQUIDITY_OK)

    G4_SpreadStatistics --> REJECTED: Fail (Insufficient History / Zero Var / |Z| >= Stop)
    G4_SpreadStatistics --> QUIET: Normal Band (|Z| < Entry Threshold)
    G4_SpreadStatistics --> G5_CostWaterfall: Anomaly Detected (|Z| >= Entry Threshold)

    G5_CostWaterfall --> NO_EDGE: Fail (Round-Trip Costs >= Gross Edge or Below Min Net bps)
    G5_CostWaterfall --> G6_EvidenceSufficiency: Pass (COST_VIABLE)

    G6_EvidenceSufficiency --> REJECTED: Fail (INSUFFICIENT_EVIDENCE in Walk-Forward)
    G6_EvidenceSufficiency --> TRADE_SIGNAL: Pass (EVIDENCE_SUFFICIENT)
```

## 5. Research-Run Lifecycle

```mermaid
flowchart LR
    A["1. Load & Hash Dataset"] --> B["2. Validate & Quarantine"]
    B --> C["3. Normalize to INR/g (999)"]
    C --> D["4. Discover & Align Pairs (<= T)"]
    D --> E["5. Screen Liquidity & Compute Stats"]
    E --> F["6. Evaluate 2-Leg Cost Waterfall"]
    F --> G["7. Run Walk-Forward Backtest"]
    G --> H["8. Emit G0–G6 Decisions"]
    H --> I["9. Write DuckDB, Reports & Verify SHA-256 Manifest"]
```
