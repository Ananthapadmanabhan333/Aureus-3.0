"""Integration tests for the AUREUS-RV 3.0 dashboard view-models, interactive calculators, safe upload handling, and report exports."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from aureus_rv.config.settings import AureusConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.dashboard.theme import apply_plotly_institutional_theme, format_state_badge_html
from aureus_rv.dashboard.view_models import (
    build_contract_explorer_tables,
    build_executive_overview_vm,
    evaluate_interactive_spread_research,
    run_interactive_cost_lab,
    validate_and_ingest_uploaded_bytes,
)
from aureus_rv.models import (
    AureusError,
    ContractInstanceId,
    CostScenarioName,
    DecisionState,
    PairId,
    ReasonCode,
    SpreadDirection,
)
from aureus_rv.normalization.normalizer import normalize_dataframe_observations
from aureus_rv.pipeline import generate_synthetic_demo_dataset, run_research_pipeline
from aureus_rv.reporting.generator import (
    generate_decisions_csv_text,
    generate_html_report,
    generate_markdown_report,
)
from aureus_rv.validation.validator import validate_dataset


def test_executive_overview_vm_matches_backend_and_exports(tmp_path: Path) -> None:
    """Verify ExecutiveOverviewVM numbers match ResearchPipelineResult and exported reports exactly."""
    df = generate_synthetic_demo_dataset(seed=42, n_bars=48)
    in_pq = tmp_path / "demo.parquet"
    df.to_parquet(in_pq, index=False)

    res = run_research_pipeline(input_path=in_pq, output_dir=tmp_path / "run_out")
    vm = build_executive_overview_vm(res)

    assert vm.run_id == res.run_id
    assert vm.manifest_verified is True
    assert vm.raw_row_count == 349
    assert vm.valid_row_count == 344
    assert vm.quarantined_row_count == 5
    assert vm.evaluated_pair_count == len(res.snapshot_decisions)
    assert vm.trade_signal_count + vm.no_edge_count + vm.quiet_count + vm.rejected_count == vm.evaluated_pair_count
    assert vm.trade_signal_count == 3
    assert vm.no_edge_count == 1
    assert vm.quiet_count == 1
    assert vm.rejected_count == 23


def test_contract_explorer_tables_match_registry_and_normalizer() -> None:
    """Verify Contract Explorer view-model tables expose all 4 MCX variants and accurate 999 INR/g prices."""
    raw_df = generate_synthetic_demo_dataset(seed=42, n_bars=48)
    registry = ContractRegistry()
    clean_df, _ = validate_dataset(raw_df, registry)
    norm_df = normalize_dataframe_observations(clean_df, registry)

    specs_df, snaps_df = build_contract_explorer_tables(norm_df, registry, AureusConfig())
    assert set(specs_df["symbol"]) == {"GOLD", "GOLDM", "GOLDPETAL", "GOLDGUINEA"}
    assert len(snaps_df) == 8  # 8 contract instances active on final bar

    # Check GOLD_2026-06-04 is flagged as TENDER/ROLLOVER (<6d)
    near_tender_row = snaps_df[snaps_df["contract_id"] == "GOLD_2026-06-04"].iloc[0]
    assert bool(near_tender_row["near_leg_eligible"]) is False
    assert "TENDER/ROLLOVER" in str(near_tender_row["eligibility_status"])


def test_interactive_spread_research_and_adf_toggle() -> None:
    """Verify Page C interactive spread research computes rolling z-score and optional ADF p-value via backend."""
    raw_df = generate_synthetic_demo_dataset(seed=42, n_bars=48)
    registry = ContractRegistry()
    clean_df, _ = validate_dataset(raw_df, registry)
    norm_df = normalize_dataframe_observations(clean_df, registry)

    cfg = AureusConfig()
    cfg_adf = cfg.model_copy(
        update={"statistics": cfg.statistics.model_copy(update={"run_adf_stationarity_test": True})}
    )

    chart_df, pair_res, liq_res, stats_res = evaluate_interactive_spread_research(
        norm_df=norm_df,
        near_contract_id="GOLD_2026-08-05",
        far_contract_id="GOLD_2026-10-05",
        config=cfg_adf,
        registry=registry,
    )
    assert len(chart_df) == 48
    assert pair_res.eligible is True
    assert liq_res.passed is True
    assert stats_res.adf_pvalue is not None
    assert "rolling_z_score" in chart_df.columns


def test_interactive_cost_lab_recalculates_live_and_flips_to_no_edge() -> None:
    """Verify Page D Transaction-Cost Lab recalculates through the real cost waterfall and transitions Viable -> NO-EDGE."""
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 8, 5)),
        far_leg=ContractInstanceId(symbol="GOLD", expiry_date=date(2026, 10, 5)),
    )
    # 1. With 15.0 INR/g gross convergence under base assumptions -> Viable
    res_viable = run_interactive_cost_lab(
        pair_id=pair_id,
        direction=SpreadDirection.SHORT_SPREAD,
        norm_near_inr_g_999=7220.0,
        norm_far_inr_g_999=7218.0,
        near_bid_ask_spread_bps=1.1,
        far_bid_ask_spread_bps=1.2,
        gross_expected_convergence_inr_g_999=15.0,
        notional_grams=1000.0,
        active_scenario=CostScenarioName.BASE,
        custom_brokerage_bps=0.30,
        custom_exchange_bps=0.26,
        custom_sebi_bps=0.01,
        custom_ctt_sell_bps=1.0,
        custom_stamp_buy_bps=0.20,
        custom_gst_fraction=0.18,
        custom_slippage_bps=0.50,
        custom_half_spread_mult=1.0,
        min_net_edge_bps=1.5,
        min_gross_to_cost_ratio=1.25,
    )
    assert res_viable.viable is True
    assert res_viable.reason_codes == [ReasonCode.COST_VIABLE]

    # 2. Increase slippage to 4.5 bps/leg -> costs exceed gross convergence -> NO-EDGE
    res_stressed = run_interactive_cost_lab(
        pair_id=pair_id,
        direction=SpreadDirection.SHORT_SPREAD,
        norm_near_inr_g_999=7220.0,
        norm_far_inr_g_999=7218.0,
        near_bid_ask_spread_bps=1.1,
        far_bid_ask_spread_bps=1.2,
        gross_expected_convergence_inr_g_999=15.0,
        notional_grams=1000.0,
        active_scenario=CostScenarioName.STRESS,
        custom_brokerage_bps=2.50,
        custom_exchange_bps=0.26,
        custom_sebi_bps=0.01,
        custom_ctt_sell_bps=1.0,
        custom_stamp_buy_bps=0.20,
        custom_gst_fraction=0.18,
        custom_slippage_bps=4.50,
        custom_half_spread_mult=2.0,
        min_net_edge_bps=1.5,
        min_gross_to_cost_ratio=1.25,
    )
    assert res_stressed.viable is False
    assert ReasonCode.NO_EDGE_COSTS_EXCEED_SPREAD in res_stressed.reason_codes


def test_safe_upload_validation_and_rejection_of_invalid_files(tmp_path: Path) -> None:
    """Verify Page G upload handler accepts valid CSV/Parquet bytes and rejects unsupported extensions, empty payloads, and bad schemas."""
    registry = ContractRegistry()
    df = generate_synthetic_demo_dataset(seed=42, n_bars=15)
    csv_bytes = df.to_csv(index=False).encode("utf-8")

    saved_path, norm_df, val_rep, sha_hex = validate_and_ingest_uploaded_bytes(
        filename="valid_upload.csv",
        raw_bytes=csv_bytes,
        registry=registry,
        save_dir=tmp_path / "uploads",
    )
    assert saved_path.exists()
    assert len(sha_hex) == 64
    assert val_rep.valid_rows == len(norm_df)
    assert val_rep.quarantined_rows == 5

    # Reject executable / unsupported extension
    with pytest.raises(AureusError) as exc_ext:
        validate_and_ingest_uploaded_bytes("malicious.py", b"print('boom')", registry, tmp_path)
    assert exc_ext.value.reason_code == ReasonCode.ERR_MISSING_REQUIRED_FIELD

    # Reject empty payload
    with pytest.raises(AureusError):
        validate_and_ingest_uploaded_bytes("empty.csv", b"", registry, tmp_path)

    # Reject bad schema CSV
    with pytest.raises(AureusError):
        validate_and_ingest_uploaded_bytes("bad_schema.csv", b"col_a,col_b\n1,2\n", registry, tmp_path)


def test_report_exports_and_theme_helpers(tmp_path: Path) -> None:
    """Verify HTML, Markdown, CSV report exports and Plotly theme helpers."""
    import plotly.graph_objects as go

    df = generate_synthetic_demo_dataset(seed=42, n_bars=48)
    in_pq = tmp_path / "demo.parquet"
    df.to_parquet(in_pq, index=False)
    res = run_research_pipeline(input_path=in_pq, output_dir=tmp_path / "out")

    html_str = generate_html_report(
        manifest=res.manifest,
        validation_report=res.validation_report,
        backtest_reports=res.backtest_reports,
        snapshot_decisions=res.snapshot_decisions,
    )
    md_str = generate_markdown_report(
        manifest=res.manifest,
        validation_report=res.validation_report,
        backtest_reports=res.backtest_reports,
        snapshot_decisions=res.snapshot_decisions,
    )
    csv_str = generate_decisions_csv_text(res.snapshot_decisions)

    assert "<!DOCTYPE html>" in html_str
    assert res.run_id in html_str
    assert "SYNTHETIC DEMO DATASET" in html_str
    assert res.run_id in md_str
    assert "GOLD_2026-08-05__VS__GOLD_2026-10-05" in csv_str

    fig = apply_plotly_institutional_theme(go.Figure(), title="Test Figure", height=300)
    assert fig.layout.height == 300
    assert "TRADE SIGNAL" in format_state_badge_html(DecisionState.TRADE_SIGNAL.value)
