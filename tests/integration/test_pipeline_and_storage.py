"""Integration and regression tests for walk-forward backtesting, DuckDB storage, manifest verification, and reproducibility."""

from __future__ import annotations

from pathlib import Path

from aureus_rv.config.settings import AureusConfig, BacktestConfig
from aureus_rv.evidence.manifest import verify_run_manifest
from aureus_rv.models import DecisionState, ReasonCode
from aureus_rv.pipeline import generate_synthetic_demo_dataset, run_research_pipeline
from aureus_rv.storage.duckdb_store import AureusStorage


def test_end_to_end_pipeline_states_and_duckdb_persistence(tmp_path: Path) -> None:
    """Verify full pipeline produces QUIET, REJECTED, NO-EDGE, and TRADE SIGNAL states and stores in DuckDB."""
    df = generate_synthetic_demo_dataset(seed=42, n_bars=48)
    input_pq = tmp_path / "demo.parquet"
    df.to_parquet(input_pq, index=False)

    out_dir = tmp_path / "run_out"
    res = run_research_pipeline(input_path=input_pq, output_dir=out_dir)

    # Verify manifest integrity
    ok, errors = verify_run_manifest(res.manifest_path)
    assert ok is True, f"Manifest verification failed: {errors}"

    # Verify all 4 decision states are represented across the synthetic demo pairs
    states_present = {d.state for d in res.snapshot_decisions}
    assert DecisionState.TRADE_SIGNAL in states_present
    assert DecisionState.NO_EDGE in states_present
    assert DecisionState.QUIET in states_present
    assert DecisionState.REJECTED in states_present

    # Verify qualifying candidate GOLD_2026-08-05__VS__GOLD_2026-10-05 achieved TRADE SIGNAL & backtest trades
    qual_dec = next(
        d for d in res.snapshot_decisions if d.pair_id == "GOLD_2026-08-05__VS__GOLD_2026-10-05"
    )
    assert qual_dec.state == DecisionState.TRADE_SIGNAL
    assert qual_dec.is_synthetic is True

    qual_bt = next(
        b for b in res.backtest_reports if b.pair_id == "GOLD_2026-08-05__VS__GOLD_2026-10-05"
    )
    assert qual_bt.evidence_status == ReasonCode.EVIDENCE_SUFFICIENT
    assert qual_bt.total_completed_trades >= 3

    # Verify DuckDB tables populated
    store = AureusStorage(res.duckdb_path)
    runs_df = store.query_runs_df()
    decs_df = store.query_decisions_df(res.run_id)
    bt_df = store.query_backtest_summaries_df(res.run_id)

    assert len(runs_df) == 1
    assert len(decs_df) == len(res.snapshot_decisions)
    assert len(bt_df) == len(res.backtest_reports)


def test_insufficient_evidence_returned_when_sample_requirement_unmet(tmp_path: Path) -> None:
    """Verify backtester returns INSUFFICIENT_EVIDENCE and abstains when min_completed_trades_for_evidence is not met."""
    df = generate_synthetic_demo_dataset(seed=42, n_bars=48)
    input_pq = tmp_path / "demo_strict.parquet"
    df.to_parquet(input_pq, index=False)

    strict_cfg = AureusConfig(
        backtest=BacktestConfig(
            min_completed_trades_for_evidence=50,  # Unreachable in 48 bars
        )
    )
    res = run_research_pipeline(
        input_path=input_pq,
        output_dir=tmp_path / "strict_out",
        config=strict_cfg,
    )
    qual_bt = next(
        b for b in res.backtest_reports if b.pair_id == "GOLD_2026-08-05__VS__GOLD_2026-10-05"
    )
    assert qual_bt.evidence_status == ReasonCode.INSUFFICIENT_EVIDENCE

    # Because G6 failed, the decision engine must abstain (fail closed to REJECTED with INSUFFICIENT_EVIDENCE)
    qual_dec = next(
        d for d in res.snapshot_decisions if d.pair_id == "GOLD_2026-08-05__VS__GOLD_2026-10-05"
    )
    assert qual_dec.state == DecisionState.REJECTED
    assert qual_dec.primary_reason_code == ReasonCode.INSUFFICIENT_EVIDENCE


def test_deterministic_reproducibility_regression(tmp_path: Path) -> None:
    """Regression test: running the pipeline twice on identical inputs yields bit-identical decisions and hashes."""
    df1 = generate_synthetic_demo_dataset(seed=99, n_bars=48)
    df2 = generate_synthetic_demo_dataset(seed=99, n_bars=48)
    assert df1.equals(df2)

    in_path = tmp_path / "repro.parquet"
    df1.to_parquet(in_path, index=False)

    res1 = run_research_pipeline(input_path=in_path, output_dir=tmp_path / "run1")
    res2 = run_research_pipeline(input_path=in_path, output_dir=tmp_path / "run2")

    assert res1.run_id == res2.run_id
    assert res1.manifest.dataset_sha256 == res2.manifest.dataset_sha256
    assert res1.manifest.config_sha256 == res2.manifest.config_sha256
    assert [d.decision_id for d in res1.snapshot_decisions] == [d.decision_id for d in res2.snapshot_decisions]
    assert [d.state for d in res1.snapshot_decisions] == [d.state for d in res2.snapshot_decisions]
    assert [b.net_pnl_inr for b in res1.backtest_reports] == [b.net_pnl_inr for b in res2.backtest_reports]


def test_tampered_artifact_detected_by_manifest_verifier(tmp_path: Path) -> None:
    """Verify that modifying an output artifact after a run causes verify_run_manifest to fail."""
    df = generate_synthetic_demo_dataset(seed=42, n_bars=48)
    in_path = tmp_path / "tamper_in.parquet"
    df.to_parquet(in_path, index=False)

    out_dir = tmp_path / "tamper_out"
    res = run_research_pipeline(input_path=in_path, output_dir=out_dir)

    # Tamper with research_report.md
    md_path = Path(res.markdown_report_path)
    md_path.write_text(md_path.read_text(encoding="utf-8") + "\n<!-- tampered -->\n", encoding="utf-8")

    ok, errors = verify_run_manifest(res.manifest_path)
    assert ok is False
    assert any("research_report.md" in e for e in errors)
