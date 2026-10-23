# AUREUS-RV 3.0 — Data Dictionary & DuckDB Schema

## 1. Input Market Dataset Schema (`REQUIRED_SCHEMA_COLUMNS`)

Both `.csv` and `.parquet` input files must contain the following 17 columns:

| Column Name | Type | Description | Validation Rule |
| :--- | :--- | :--- | :--- |
| `timestamp` | ISO-8601 String / Timestamp | Observation bar timestamp (UTC) | Must parse to valid timestamp; no duplicates per `(timestamp, symbol, expiry_date)` |
| `symbol` | String | Base contract symbol (`GOLD`, `GOLDM`, `GOLDPETAL`, `GOLDGUINEA`) | Must exist in `ContractRegistry` on observation date |
| `expiry_date` | ISO Date (`YYYY-MM-DD`) | Contract maturity / expiry date | Must parse to valid date and satisfy `expiry_date >= timestamp.date()` |
| `open` | Float | Bar open price in raw quotation unit | Must be $> 0$ and within `[low, high]` |
| `high` | Float | Bar high price in raw quotation unit | Must be $\ge \max(\text{open}, \text{close}, \text{low})$ |
| `low` | Float | Bar low price in raw quotation unit | Must be $> 0$ and $\le \min(\text{open}, \text{close}, \text{high})$ |
| `close` | Float | Bar close/settlement price in raw quotation unit | Must be $> 0$ and within `[low, high]` |
| `bid` | Float | Best closing bid price in raw quotation unit | Must be $> 0$ and $\le \text{ask}$ |
| `ask` | Float | Best closing ask price in raw quotation unit | Must be $> 0$ and $\ge \text{bid}$ |
| `volume_lots` | Integer / Float | Traded volume in contract lots | Must be $\ge 0$ |
| `open_interest_lots` | Integer / Float | Open interest in contract lots | Must be $\ge 0$ |
| `quotation_unit` | Enum (`INR_PER_10G`, `INR_PER_8G`, `INR_PER_1G`) | Raw price quotation basis | Must match `ContractSpec.quotation_unit` |
| `purity_fineness` | Integer (`995` or `999`) | Physical fineness in parts per thousand | Must match `ContractSpec.purity_fineness` |
| `lot_size_grams` | Float (`1000.0`, `100.0`, `8.0`, `1.0`) | Physical gold grams per 1 contract lot | Must match `ContractSpec.lot_size_grams` |
| `quote_age_seconds` | Integer / Float | Age of quote at bar snapshot in seconds | Must be $\ge 0$ |
| `source_provenance` | Enum (`MCX_HISTORICAL_VERIFIED`, `VENDOR_FEED`, `SYNTHETIC_DEMO`) | Provenance classification | Must be a valid `SourceProvenance` member |
| `is_synthetic` | Boolean | Explicit synthetic indicator | Must be `True` if `source_provenance == SYNTHETIC_DEMO`; cannot be `True` if `MCX_HISTORICAL_VERIFIED` |

## 2. Derived Normalized Columns (`normalized_observations.parquet`)

| Column Name | Type | Formula / Description |
| :--- | :--- | :--- |
| `contract_id` | String | `{SYMBOL}_{YYYY-MM-DD}` instance identifier |
| `spec_version` | String | Matched `ContractSpec.spec_version` |
| `price_multiplier_per_lot` | Float | `lot_size_grams / quotation_grams` |
| `norm_open_inr_g_999` | Float | `open * (999 / purity_fineness) / quotation_grams` |
| `norm_high_inr_g_999` | Float | `high * (999 / purity_fineness) / quotation_grams` |
| `norm_low_inr_g_999` | Float | `low * (999 / purity_fineness) / quotation_grams` |
| `norm_close_inr_g_999` | Float | `close * (999 / purity_fineness) / quotation_grams` |
| `norm_bid_inr_g_999` | Float | `bid * (999 / purity_fineness) / quotation_grams` |
| `norm_ask_inr_g_999` | Float | `ask * (999 / purity_fineness) / quotation_grams` |
| `norm_mid_inr_g_999` | Float | `0.5 * (norm_bid_inr_g_999 + norm_ask_inr_g_999)` |
| `raw_notional_per_lot_inr` | Float | `close * price_multiplier_per_lot` |
| `bid_ask_spread_bps` | Float | `((norm_ask_inr_g_999 - norm_bid_inr_g_999) / norm_mid_inr_g_999) * 10000` |

## 3. DuckDB Relational Tables (`aureus_rv.duckdb`)

1. **`research_runs`**: Stores run metadata, `dataset_sha256`, `config_sha256`, row counts, decision counts, full `manifest_json`, and `manifest_self_sha256`.
2. **`decisions`**: Stores every emitted `DecisionRecord` (`decision_id`, `run_id`, `timestamp`, `pair_id`, `state`, `direction`, `primary_reason_code`, `z_score`, `spread_bps`, `net_expected_bps`, and full `decision_json`).
3. **`backtest_summaries`**: Stores walk-forward backtest results per `(run_id, pair_id, cost_scenario)` including `evidence_status`, `total_completed_trades`, `gross_pnl_inr`, `total_costs_inr`, `net_pnl_inr`, `max_drawdown_inr`, `baseline_naive_net_pnl_inr`, and full `report_json`.
4. **`quarantined_rows`**: Stores every rejected input row (`run_id`, `row_index`, `reason_codes`, `explanation`, `raw_payload_json`).
