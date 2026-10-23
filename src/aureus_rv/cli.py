"""Command-line entrypoints for AUREUS-RV 3.0."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aureus_rv.config.settings import AureusConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.evidence.manifest import verify_run_manifest
from aureus_rv.ingestion.loader import load_raw_dataset
from aureus_rv.pipeline import generate_synthetic_demo_dataset, run_research_pipeline
from aureus_rv.validation.validator import validate_dataset


def main_generate_demo(argv: list[str] | None = None) -> int:
    """CLI entrypoint to generate deterministic synthetic demo datasets (CSV + Parquet)."""
    parser = argparse.ArgumentParser(description="Generate AUREUS-RV 3.0 deterministic synthetic demo dataset.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/demo_data",
        help="Output directory for generated CSV and Parquet files",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--bars", type=int, default=48, help="Number of chronological bars")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = generate_synthetic_demo_dataset(seed=args.seed, n_bars=args.bars)

    csv_path = out_dir / "synthetic_mcx_gold.csv"
    pq_path = out_dir / "synthetic_mcx_gold.parquet"
    df.to_csv(csv_path, index=False)
    df.to_parquet(pq_path, index=False)

    print(f"[AUREUS-RV 3.0] Generated {len(df)} synthetic observations (labeled SYNTHETIC_DEMO):")
    print(f"  - CSV:     {csv_path}")
    print(f"  - Parquet: {pq_path}")
    return 0


def main_validate(argv: list[str] | None = None) -> int:
    """CLI entrypoint to validate a dataset and print quarantine details."""
    parser = argparse.ArgumentParser(description="Validate an AUREUS-RV 3.0 dataset (CSV or Parquet).")
    parser.add_argument("--input", type=str, required=True, help="Path to input CSV or Parquet dataset")
    parser.add_argument("--output-json", type=str, default=None, help="Optional path to write validation JSON report")
    args = parser.parse_args(argv)

    raw_df, manifest = load_raw_dataset(args.input)
    registry = ContractRegistry()
    _, report = validate_dataset(raw_df, registry)

    summary = {
        "source_path": manifest.source_path,
        "sha256_hash": manifest.sha256_hash,
        "total_rows": report.total_rows,
        "valid_rows": report.valid_rows,
        "quarantined_rows": report.quarantined_rows,
        "is_synthetic_dataset": report.is_synthetic_dataset,
        "reason_counts": report.reason_counts,
    }
    print(json.dumps(summary, indent=2))

    if args.output_json:
        out_p = Path(args.output_json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
    return 0


def main_research(argv: list[str] | None = None) -> int:
    """CLI entrypoint to run the full AUREUS-RV 3.0 research, decision, backtest, and manifest pipeline."""
    parser = argparse.ArgumentParser(description="Run full AUREUS-RV 3.0 quantitative research workflow.")
    parser.add_argument("--input", type=str, required=True, help="Input CSV or Parquet dataset path")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/research_run",
        help="Directory for DuckDB, Parquet artifacts, manifest, and reports",
    )
    parser.add_argument("--config", type=str, default=None, help="Optional YAML configuration file")
    args = parser.parse_args(argv)

    cfg = AureusConfig.from_yaml(args.config) if args.config else AureusConfig()
    result = run_research_pipeline(
        input_path=args.input,
        output_dir=args.output_dir,
        config=cfg,
    )
    verified, errors = verify_run_manifest(result.manifest_path)
    if not verified:
        raise RuntimeError(f"Manifest integrity check failed immediately after run: {errors}")

    print(f"[AUREUS-RV 3.0] Completed Research Run: {result.run_id}")
    print(f"  - Valid / Quarantined Rows: {result.validation_report.valid_rows} / {result.validation_report.quarantined_rows}")
    print(f"  - Evaluated Pairs:          {len(result.snapshot_decisions)}")
    print(f"  - Trade Signals:            {result.manifest.trade_signal_count}")
    print(f"  - Manifest Verified:        {verified} (SHA-256: {result.manifest.manifest_self_sha256[:16]}...)")
    print(f"  - Markdown Report:          {result.markdown_report_path}")
    print(f"  - JSON Report:              {result.json_report_path}")
    print(f"  - DuckDB Database:          {result.duckdb_path}")
    return 0
