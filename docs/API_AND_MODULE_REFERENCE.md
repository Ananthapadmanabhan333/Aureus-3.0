# AUREUS-RV 3.0 — API & Module Reference

## 1. CLI Entrypoints (`src/aureus_rv/cli.py` & `scripts/`)

### `scripts/generate_demo_data.py`
```bash
uv run python scripts/generate_demo_data.py --output-dir artifacts/demo_data --seed 42 --bars 48
```
Generates deterministic synthetic MCX Gold datasets (`synthetic_mcx_gold.csv` and `synthetic_mcx_gold.parquet`) explicitly labeled `SYNTHETIC_DEMO`.

### `scripts/validate_dataset.py`
```bash
uv run python scripts/validate_dataset.py --input artifacts/demo_data/synthetic_mcx_gold.parquet --output-json artifacts/validation.json
```
Runs Gate G0/G1 validation and outputs total, valid, and quarantined row counts plus reason-code histograms.

### `scripts/run_research.py`
```bash
uv run python scripts/run_research.py --input artifacts/demo_data/synthetic_mcx_gold.parquet --output-dir artifacts/research_run
```
Runs the full end-to-end research pipeline, persists to DuckDB and Parquet, writes JSON/Markdown/HTML/CSV reports, seals `run_manifest.json`, and verifies SHA-256 artifact integrity.

### `scripts/launch_dashboard.py`
```bash
uv run streamlit run scripts/launch_dashboard.py
```
Launches the 8-page institutional Streamlit research interface.

---

## 2. Core Python Public API

### `aureus_rv.pipeline.run_research_pipeline`
```python
def run_research_pipeline(
    input_path: str | Path,
    output_dir: str | Path,
    config: AureusConfig | None = None,
    duckdb_path: str | Path | None = None,
) -> ResearchPipelineResult
```

### `aureus_rv.normalization.normalizer.normalize_price_to_inr_per_g_999`
```python
def normalize_price_to_inr_per_g_999(
    raw_price: float,
    quotation_unit: str | QuotationUnit,
    purity_fineness: int,
) -> float
```

### `aureus_rv.costs.waterfall.evaluate_pair_costs`
```python
def evaluate_pair_costs(
    pair_id: PairId,
    direction: SpreadDirection,
    norm_near_inr_g_999: float,
    norm_far_inr_g_999: float,
    near_bid_ask_spread_bps: float,
    far_bid_ask_spread_bps: float,
    gross_expected_convergence_inr_g_999: float,
    notional_grams: float,
    costs_config: CostsConfig,
    scenario: CostScenarioName | None = None,
) -> PairCostWaterfallResult
```

### `aureus_rv.decisions.gates.evaluate_decision_gates`
```python
def evaluate_decision_gates(...) -> DecisionRecord
```

### `aureus_rv.evidence.manifest.verify_run_manifest`
```python
def verify_run_manifest(
    manifest_path: str | Path,
    base_dir: str | Path | None = None,
) -> tuple[bool, list[str]]
```
