"""Premium Institutional Streamlit Research Instrument for AUREUS-RV 3.0.

All calculations, decisions, backtests, cost waterfalls, and manifests are driven
directly by the AUREUS-RV 3.0 quantitative backend.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from aureus_rv import __methodology_version__, __version__
from aureus_rv.backtesting.engine import run_pair_walk_forward_backtest
from aureus_rv.config.settings import (
    AureusConfig,
    BacktestConfig,
    StatisticsConfig,
)
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.dashboard.theme import (
    COLOR_BLUE_ACCENT,
    COLOR_GOLD_PRIMARY,
    COLOR_NO_EDGE,
    COLOR_QUIET,
    COLOR_REJECTED,
    COLOR_SIGNAL,
    INSTITUTIONAL_CSS,
    STATE_COLOR_MAP,
    apply_plotly_institutional_theme,
    format_state_badge_html,
)
from aureus_rv.dashboard.view_models import (
    build_contract_explorer_tables,
    build_executive_overview_vm,
    evaluate_interactive_spread_research,
    run_interactive_cost_lab,
    validate_and_ingest_uploaded_bytes,
)
from aureus_rv.evidence.manifest import verify_run_manifest
from aureus_rv.models import (
    ContractInstanceId,
    CostScenarioName,
    PairId,
    ReasonCode,
    SpreadDirection,
)
from aureus_rv.normalization.normalizer import normalize_dataframe_observations
from aureus_rv.pairing.engine import align_pair_history_up_to
from aureus_rv.pipeline import (
    ResearchPipelineResult,
    generate_synthetic_demo_dataset,
    run_research_pipeline,
)
from aureus_rv.reporting.generator import (
    generate_decisions_csv_text,
    generate_html_report,
    generate_markdown_report,
)
from aureus_rv.storage.duckdb_store import AureusStorage
from aureus_rv.validation.validator import validate_dataset

ARTIFACTS_ROOT = Path(os.environ.get("AUREUS_ARTIFACTS_DIR", "artifacts"))


def _ensure_session_initialized() -> None:
    """Initialize session state with deterministic synthetic demo dataset and a verified baseline run."""
    if "active_config" not in st.session_state:
        st.session_state["active_config"] = AureusConfig()
    if "import_history" not in st.session_state:
        st.session_state["import_history"] = []

    if "pipeline_result" not in st.session_state or "norm_df" not in st.session_state:
        demo_dir = ARTIFACTS_ROOT / "demo_data"
        demo_dir.mkdir(parents=True, exist_ok=True)
        demo_pq = demo_dir / "synthetic_mcx_gold.parquet"
        if not demo_pq.exists():
            df_synth = generate_synthetic_demo_dataset(seed=42, n_bars=48)
            df_synth.to_parquet(demo_pq, index=False)
            df_synth.to_csv(demo_dir / "synthetic_mcx_gold.csv", index=False)

        run_out_dir = ARTIFACTS_ROOT / "research_run"
        res = run_research_pipeline(
            input_path=demo_pq,
            output_dir=run_out_dir,
            config=st.session_state["active_config"],
        )
        raw_df = pd.read_parquet(demo_pq)
        reg = ContractRegistry()
        clean_df, _ = validate_dataset(raw_df, reg)
        norm_df = normalize_dataframe_observations(clean_df, reg)

        st.session_state["active_dataset_path"] = str(demo_pq)
        st.session_state["pipeline_result"] = res
        st.session_state["norm_df"] = norm_df
        st.session_state["import_history"].append(
            {
                "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source_file": demo_pq.name,
                "sha256": res.manifest.dataset_sha256[:16] + "...",
                "total_rows": res.validation_report.total_rows,
                "valid_rows": res.validation_report.valid_rows,
                "quarantined_rows": res.validation_report.quarantined_rows,
                "provenance": "SYNTHETIC_DEMO",
            }
        )


def _render_top_banner(res: ResearchPipelineResult) -> None:
    prov_badge = (
        "<span class='aureus-badge badge-synth'>SYNTHETIC DEMO DATASET (NOT LIVE MCX FEED)</span>"
        if res.manifest.is_synthetic_data
        else "<span class='aureus-badge badge-verified'>VERIFIED HISTORICAL DATASET</span>"
    )
    st.markdown(
        f"""
        <div class="aureus-header">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div>
              <h1 class="aureus-title">AUREUS-RV 3.0</h1>
              <p class="aureus-subtitle">Lifecycle-Aware MCX Gold Relative-Value Research Instrument &nbsp;·&nbsp; <code>NORMALIZE → VALIDATE → PAIR → COST → ABSTAIN → PROVE</code></p>
            </div>
            <div>
              {prov_badge}
              <span class="aureus-badge badge-quiet" style="margin-left:6px;">Run: {res.run_id}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _kpi_card(label: str, value: str, subtext: str = "") -> None:
    sub_html = f"<div style='color:#9CA3AF; font-size:0.75rem; margin-top:3px;'>{subtext}</div>" if subtext else ""
    st.markdown(
        f"""
        <div class="aureus-card">
          <div class="aureus-kpi-label">{label}</div>
          <div class="aureus-kpi-value">{value}</div>
          {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_executive_overview(res: ResearchPipelineResult) -> None:
    """Page A: Executive Overview."""
    vm = build_executive_overview_vm(res)

    st.subheader("A. Executive Research Overview")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_card("Latest Run ID", vm.run_id, f"v{vm.software_version}")
    with c2:
        _kpi_card("Valid / Raw Rows", f"{vm.valid_row_count} / {vm.raw_row_count}", f"{vm.quarantined_row_count} Quarantined")
    with c3:
        _kpi_card("Eligible / Total Pairs", f"{vm.eligible_pair_count} / {vm.evaluated_pair_count}", "Expiry & Spec Screened")
    with c4:
        _kpi_card("TRADE SIGNAL", str(vm.trade_signal_count), "Passed Gates G0–G6")
    with c5:
        _kpi_card("NO-EDGE / QUIET", f"{vm.no_edge_count} / {vm.quiet_count}", "Cost-Erased / Normal Band")
    with c6:
        _kpi_card("REJECTED", str(vm.rejected_count), "Failed G0–G4 or G6")

    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown("#### Snapshot Pair Decision Classification (Gates G0–G6)")
        dec_rows = []
        for d in res.snapshot_decisions:
            m = d.metrics
            dec_rows.append(
                {
                    "Decision ID": d.decision_id,
                    "Pair ID": d.pair_id,
                    "State": d.state.value,
                    "Direction": d.direction.value,
                    "Primary Reason": d.primary_reason_code.value,
                    "DTE (Near/Far)": f"{m.get('dte_near', '-')}/{m.get('dte_far', '-')}",
                    "Z-Score": round(float(m["z_score"]), 2) if m.get("z_score") is not None else None,
                    "Gross Edge (bps)": round(float(m["gross_expected_bps"]), 2) if m.get("gross_expected_bps") is not None else None,
                    "Cost (bps)": round(float(m["total_cost_bps"]), 2) if m.get("total_cost_bps") is not None else None,
                    "Net Edge (bps)": round(float(m["net_expected_bps"]), 2) if m.get("net_expected_bps") is not None else None,
                }
            )
        st.dataframe(pd.DataFrame(dec_rows), use_container_width=True, hide_index=True)

    with col_right:
        st.markdown("#### State Distribution & Evidence Status")
        state_labels = ["TRADE SIGNAL", "NO-EDGE", "QUIET", "REJECTED"]
        state_values = [vm.trade_signal_count, vm.no_edge_count, vm.quiet_count, vm.rejected_count]
        fig = go.Figure(
            data=[
                go.Bar(
                    x=state_labels,
                    y=state_values,
                    marker_color=[STATE_COLOR_MAP[s] for s in state_labels],
                    text=state_values,
                    textposition="auto",
                )
            ]
        )
        apply_plotly_institutional_theme(fig, title="Latest Decision State Counts", height=260)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown(
            f"""
            <div class="aureus-card">
              <div class="aureus-kpi-label">Provenance &amp; Integrity Hashes</div>
              <div style="font-size:0.82rem; line-height:1.6;">
                <b>Evaluation Window:</b> <code>{vm.evaluation_period_start}</code> → <code>{vm.evaluation_period_end}</code><br/>
                <b>Evidence Sufficiency:</b> <code>{vm.sufficient_evidence_pairs}</code> sufficient / <code>{vm.insufficient_evidence_pairs}</code> insufficient<br/>
                <b>Dataset SHA-256:</b> <code>{vm.dataset_sha256[:24]}...</code><br/>
                <b>Config SHA-256:</b> <code>{vm.config_sha256[:24]}...</code><br/>
                <b>Manifest Verified:</b> <code>{vm.manifest_verified}</code>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if vm.warnings:
        for w in vm.warnings:
            st.warning(w)


def render_contract_explorer(norm_df: pd.DataFrame, config: AureusConfig) -> None:
    """Page B: Contract Explorer."""
    st.subheader("B. Versioned Contract Registry & Normalization Explorer")
    registry = ContractRegistry()
    specs_df, snaps_df = build_contract_explorer_tables(norm_df, registry, config)

    st.markdown(
        """
        <div class="aureus-card">
          <b>Physical Normalization Formula (Target: INR per 1 gram at 999 fineness):</b><br/>
          <code>normalized_inr_per_g_999 = raw_quoted_price × (999 / purity_fineness) / quotation_grams</code><br/>
          <span style="color:#9CA3AF; font-size:0.84rem;">
            Illustrative MCX Standard GOLD (quoted per 10g at 995 fineness):
            <code>INR/g (999) = Quoted_INR_10g × (999 / 995) / 10</code>.
            Normalized unit prices are kept strictly separate from lot sizes (1,000g vs 100g vs 8g vs 1g) and contract notionals.
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### 1. Effective-Dated Contract Specification Registry")
    st.dataframe(specs_df, use_container_width=True, hide_index=True)

    if snaps_df.empty:
        st.info("No valid contract observations loaded.")
        return

    st.markdown("#### 2. Active Contract Instances (Raw vs Normalized 999 INR/g Quotations)")
    f1, f2, f3 = st.columns(3)
    with f1:
        symbols = sorted(snaps_df["symbol"].unique().tolist())
        sel_symbols = st.multiselect("Filter by Contract Symbol", options=symbols, default=symbols)
    with f2:
        purities = sorted(snaps_df["purity_fineness"].unique().tolist())
        sel_purities = st.multiselect("Filter by Purity Fineness", options=purities, default=purities)
    with f3:
        only_elig = st.checkbox("Show Only Near-Leg Rollover Eligible Contracts", value=False)

    filtered = snaps_df[
        snaps_df["symbol"].isin(sel_symbols) & snaps_df["purity_fineness"].isin(sel_purities)
    ]
    if only_elig:
        filtered = filtered[filtered["near_leg_eligible"]]

    st.dataframe(filtered, use_container_width=True, hide_index=True)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=filtered["contract_id"],
            y=filtered["norm_close_inr_g_999"],
            name="Normalized Close (INR/g @ 999)",
            marker_color=COLOR_GOLD_PRIMARY,
            text=[f"₹{v:,.2f}/g" for v in filtered["norm_close_inr_g_999"]],
            textposition="auto",
        )
    )
    apply_plotly_institutional_theme(fig, title="Normalized Term Structure Across Active Contracts (INR/g @ 999)", height=340)
    fig.update_yaxes(
        range=[
            float(filtered["norm_close_inr_g_999"].min()) - 25.0,
            float(filtered["norm_close_inr_g_999"].max()) + 25.0,
        ]
    )
    st.plotly_chart(fig, use_container_width=True)


def render_spread_research(norm_df: pd.DataFrame, base_config: AureusConfig) -> None:
    """Page C: Spread Research."""
    st.subheader("C. Expiry-Aware Spread Research & Statistical Diagnostics")
    if norm_df.empty:
        st.warning("No normalized observations available for spread research.")
        return

    registry = ContractRegistry()
    contracts = sorted(norm_df["contract_id"].unique().tolist())
    default_near = "GOLD_2026-08-05" if "GOLD_2026-08-05" in contracts else contracts[0]
    default_far = "GOLD_2026-10-05" if "GOLD_2026-10-05" in contracts else contracts[-1]

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        near_id = st.selectbox("Near / Primary Leg (Leg A)", options=contracts, index=contracts.index(default_near))
    with c2:
        far_id = st.selectbox("Far / Secondary Leg (Leg B)", options=contracts, index=contracts.index(default_far))
    with c3:
        lookback = st.slider("Rolling Window (Bars)", min_value=10, max_value=40, value=base_config.statistics.rolling_window)
    with c4:
        entry_z = st.slider("Entry |Z| Threshold", min_value=1.0, max_value=3.5, value=base_config.statistics.entry_z_threshold, step=0.1)
    with c5:
        run_adf = st.checkbox("Run ADF Stationarity Check", value=base_config.statistics.run_adf_stationarity_test)

    custom_stats_cfg = StatisticsConfig(
        rolling_window=lookback,
        min_observations=min(lookback, base_config.statistics.min_observations),
        entry_z_threshold=entry_z,
        exit_z_threshold=min(entry_z - 0.2, base_config.statistics.exit_z_threshold),
        stop_z_threshold=max(entry_z + 1.0, base_config.statistics.stop_z_threshold),
        min_correlation=base_config.statistics.min_correlation,
        run_adf_stationarity_test=run_adf,
    )
    custom_cfg = base_config.model_copy(update={"statistics": custom_stats_cfg})

    chart_df, pair_res, liq_res, stats_res = evaluate_interactive_spread_research(
        norm_df=norm_df,
        near_contract_id=near_id,
        far_contract_id=far_id,
        config=custom_cfg,
        registry=registry,
    )

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        _kpi_card(
            "Pairing Status (G2)",
            "ELIGIBLE" if pair_res.eligible else "INELIGIBLE",
            f"Gap: {pair_res.expiry_gap_days}d | Near DTE: {pair_res.days_to_expiry_near}d",
        )
    with k2:
        _kpi_card(
            "Liquidity Status (G3)",
            "PASS" if liq_res.passed else "FAIL",
            f"Obs: {liq_res.observation_count_window} | Vol: {int(liq_res.near_volume_lots)}/{int(liq_res.far_volume_lots)}",
        )
    with k3:
        _kpi_card(
            "Norm Spread (999)",
            f"₹{stats_res.norm_spread_inr_g_999:,.2f}/g",
            f"{stats_res.spread_bps:,.2f} bps ({stats_res.percentage_spread_pct:.3f}%)",
        )
    with k4:
        _kpi_card(
            "Rolling Z-Score",
            f"{stats_res.z_score:+.2f}σ",
            f"Mean: ₹{stats_res.rolling_mean_inr_g_999:.2f} | Std: ₹{stats_res.rolling_std_inr_g_999:.2f}",
        )
    with k5:
        _kpi_card(
            "OLS Beta & R²",
            f"β={stats_res.ols_beta:.3f}",
            f"R²={stats_res.ols_r_squared:.3f} | Corr={stats_res.correlation:.3f}",
        )
    with k6:
        adf_txt = f"p={stats_res.adf_pvalue:.4f}" if stats_res.adf_pvalue is not None else "Not Requested"
        _kpi_card(
            "Statistical Signal",
            stats_res.suggested_direction.value,
            f"ADF: {adf_txt}",
        )

    if not pair_res.eligible:
        st.error(f"Pairing Ineligible (G2): {pair_res.explanation} ({[r.value for r in pair_res.reason_codes]})")
    if not liq_res.passed:
        st.warning(f"Liquidity Screen Failure (G3): {liq_res.explanation} ({[r.value for r in liq_res.reason_codes]})")
    if not stats_res.valid_statistics:
        st.warning(f"Statistical Validity Warning (G4): {stats_res.explanation} ({[r.value for r in stats_res.reason_codes]})")

    if chart_df.empty:
        return

    col_a, col_b = st.columns(2)
    with col_a:
        fig_prices = go.Figure()
        fig_prices.add_trace(
            go.Scatter(
                x=chart_df["timestamp"],
                y=chart_df["norm_close_inr_g_999_near"],
                mode="lines",
                name=f"{near_id} (Norm 999 INR/g)",
                line={"color": COLOR_GOLD_PRIMARY, "width": 2},
            )
        )
        fig_prices.add_trace(
            go.Scatter(
                x=chart_df["timestamp"],
                y=chart_df["norm_close_inr_g_999_far"],
                mode="lines",
                name=f"{far_id} (Norm 999 INR/g)",
                line={"color": COLOR_BLUE_ACCENT, "width": 2},
            )
        )
        apply_plotly_institutional_theme(fig_prices, title="Normalized Price Comparison (INR/g @ 999 Fineness)", height=340)
        st.plotly_chart(fig_prices, use_container_width=True)

    with col_b:
        fig_spread = go.Figure()
        fig_spread.add_trace(
            go.Scatter(
                x=chart_df["timestamp"],
                y=chart_df["norm_spread_inr_g_999"],
                mode="lines+markers",
                name="Normalized Spread (INR/g)",
                line={"color": COLOR_GOLD_PRIMARY, "width": 2},
            )
        )
        fig_spread.add_trace(
            go.Scatter(
                x=chart_df["timestamp"],
                y=chart_df["rolling_mean_inr_g_999"],
                mode="lines",
                name=f"Rolling Mean ({lookback} bars)",
                line={"color": "#9CA3AF", "dash": "dash"},
            )
        )
        apply_plotly_institutional_theme(fig_spread, title="Normalized Spread & Rolling Equilibrium Mean (INR/g)", height=340)
        st.plotly_chart(fig_spread, use_container_width=True)

    fig_z = go.Figure()
    fig_z.add_trace(
        go.Scatter(
            x=chart_df["timestamp"],
            y=chart_df["rolling_z_score"],
            mode="lines+markers",
            name="Rolling Z-Score",
            line={"color": COLOR_SIGNAL, "width": 2},
        )
    )
    fig_z.add_hline(y=entry_z, line_dash="dash", line_color=COLOR_NO_EDGE, annotation_text=f"+Entry ({entry_z}σ)")
    fig_z.add_hline(y=-entry_z, line_dash="dash", line_color=COLOR_NO_EDGE, annotation_text=f"-Entry (-{entry_z}σ)")
    fig_z.add_hline(y=0.0, line_dash="dot", line_color=COLOR_QUIET)
    apply_plotly_institutional_theme(fig_z, title="Past-Only Rolling Spread Z-Score Trajectory", height=300)
    st.plotly_chart(fig_z, use_container_width=True)


def render_transaction_cost_lab(norm_df: pd.DataFrame, res: ResearchPipelineResult, base_config: AureusConfig) -> None:
    """Page D: Transaction-Cost Lab."""
    st.subheader("D. Two-Leg Indian Commodity Derivatives Transaction-Cost Lab")
    st.markdown(
        """
        <div class="aureus-card">
          <b>Cost Waterfall Governance:</b> Every spread trade executes 4 leg transactions (Entry &amp; Exit on Near Leg + Entry &amp; Exit on Far Leg).
          Statutory <b>CTT (0.01% = 1.0 bps)</b> applies strictly to the <b>sell execution</b> of each leg;
          <b>Stamp Duty (0.002% = 0.20 bps)</b> applies strictly to the <b>buy execution</b> of each leg;
          <b>18% GST</b> applies only to Brokerage + Exchange Transaction Fee + SEBI Turnover Fee.
        </div>
        """,
        unsafe_allow_html=True,
    )

    pair_options = [d.pair_id for d in res.snapshot_decisions]
    default_pair = "GOLD_2026-08-05__VS__GOLDM_2026-08-28"
    idx_default = pair_options.index(default_pair) if default_pair in pair_options else 0

    col_sel1, col_sel2, col_sel3 = st.columns(3)
    with col_sel1:
        sel_pair_str = st.selectbox("Select Candidate Pair to Stress-Test", options=pair_options, index=idx_default)
    with col_sel2:
        sel_scen_str = st.selectbox("Active Cost Scenario Preset", options=["base", "conservative", "stress"], index=0)
        active_scen = CostScenarioName(sel_scen_str)
    with col_sel3:
        notional_g = st.number_input("Target Position Notional (Grams @ 999)", min_value=1.0, max_value=10000.0, value=1000.0, step=100.0)

    preset = base_config.costs.scenarios[active_scen]
    dec_obj = next(d for d in res.snapshot_decisions if d.pair_id == sel_pair_str)
    near_id, far_id = sel_pair_str.split("__VS__")
    near_parts = near_id.split("_", 1)
    far_parts = far_id.split("_", 1)
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol=near_parts[0], expiry_date=pd.Timestamp(near_parts[1]).date()),
        far_leg=ContractInstanceId(symbol=far_parts[0], expiry_date=pd.Timestamp(far_parts[1]).date()),
    )

    aligned = align_pair_history_up_to(norm_df, pair_id, norm_df["timestamp"].max())
    last_row = aligned.iloc[-1]
    default_gross_bps = float(dec_obj.metrics.get("gross_expected_bps") or 5.0)
    ref_mid = 0.5 * (float(last_row["norm_close_inr_g_999_near"]) + float(last_row["norm_close_inr_g_999_far"]))
    default_gross_inr_g = (default_gross_bps / 10000.0) * ref_mid

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        brok_bps = st.slider("Brokerage (bps / leg)", 0.0, 3.0, float(preset.brokerage_bps_per_leg), 0.05)
        exch_bps = st.slider("MCX Exchange Fee (bps / leg)", 0.0, 1.0, float(preset.exchange_txn_bps_per_leg), 0.02)
    with s2:
        ctt_bps = st.slider("CTT Sell Side (bps)", 0.0, 2.0, float(preset.ctt_sell_bps), 0.1)
        stamp_bps = st.slider("Stamp Duty Buy Side (bps)", 0.0, 1.0, float(preset.stamp_duty_buy_bps), 0.05)
    with s3:
        slip_bps = st.slider("Execution Slippage (bps / leg)", 0.0, 5.0, float(preset.slippage_bps_per_leg), 0.1)
        ba_mult = st.slider("Half-Spread Multiplier", 0.5, 3.0, float(preset.half_spread_multiplier), 0.25)
    with s4:
        gross_conv_inr_g = st.number_input(
            "Gross Expected Convergence (INR/g)",
            min_value=0.0,
            max_value=100.0,
            value=round(float(default_gross_inr_g), 2),
            step=0.5,
        )
        min_net_bps = st.slider("Min Viable Net Edge (bps)", 0.0, 5.0, float(base_config.costs.min_net_edge_bps), 0.25)

    cost_res = run_interactive_cost_lab(
        pair_id=pair_id,
        direction=dec_obj.direction if dec_obj.direction != SpreadDirection.FLAT else SpreadDirection.SHORT_SPREAD,
        norm_near_inr_g_999=float(last_row["norm_close_inr_g_999_near"]),
        norm_far_inr_g_999=float(last_row["norm_close_inr_g_999_far"]),
        near_bid_ask_spread_bps=float(last_row["bid_ask_spread_bps_near"]),
        far_bid_ask_spread_bps=float(last_row["bid_ask_spread_bps_far"]),
        gross_expected_convergence_inr_g_999=gross_conv_inr_g,
        notional_grams=notional_g,
        active_scenario=active_scen,
        custom_brokerage_bps=brok_bps,
        custom_exchange_bps=exch_bps,
        custom_sebi_bps=preset.sebi_turnover_bps_per_leg,
        custom_ctt_sell_bps=ctt_bps,
        custom_stamp_buy_bps=stamp_bps,
        custom_gst_fraction=preset.gst_rate_fraction,
        custom_slippage_bps=slip_bps,
        custom_half_spread_mult=ba_mult,
        min_net_edge_bps=min_net_bps,
        min_gross_to_cost_ratio=base_config.costs.min_gross_to_cost_ratio,
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        _kpi_card("Economic Gate (G5)", "VIABLE" if cost_res.viable else "NO-EDGE", cost_res.reason_codes[0].value)
    with k2:
        _kpi_card("Gross Convergence", f"{cost_res.gross_expected_convergence_bps:.2f} bps", f"₹{cost_res.gross_expected_convergence_inr:,.2f}")
    with k3:
        _kpi_card("Two-Leg Round-Trip Cost", f"{cost_res.total_round_trip_cost_bps:.2f} bps", f"₹{cost_res.total_round_trip_cost_inr:,.2f}")
    with k4:
        _kpi_card("Net Expected Outcome", f"{cost_res.net_expected_convergence_bps:+.2f} bps", f"₹{cost_res.net_expected_convergence_inr:+,.2f}")
    with k5:
        _kpi_card("Gross / Cost Ratio", f"{cost_res.gross_to_cost_ratio:.2f}x", f"Breakeven: {cost_res.breakeven_convergence_bps:.2f} bps")

    col_w1, col_w2 = st.columns(2)
    with col_w1:
        leg_table = pd.DataFrame(
            [
                {
                    "Leg": f"Near ({near_id})",
                    "Norm Price (INR/g)": round(cost_res.near_leg_breakdown.norm_price_inr_g_999, 2),
                    "Brokerage (INR/g)": round(cost_res.near_leg_breakdown.brokerage_inr_g, 4),
                    "Exchange+SEBI (INR/g)": round(
                        cost_res.near_leg_breakdown.exchange_txn_inr_g + cost_res.near_leg_breakdown.sebi_fee_inr_g, 4
                    ),
                    "GST 18% (INR/g)": round(cost_res.near_leg_breakdown.gst_inr_g, 4),
                    "CTT Sell (INR/g)": round(cost_res.near_leg_breakdown.ctt_sell_side_inr_g, 4),
                    "Stamp Buy (INR/g)": round(cost_res.near_leg_breakdown.stamp_duty_buy_side_inr_g, 4),
                    "Spread+Slippage (INR/g)": round(
                        cost_res.near_leg_breakdown.spread_crossing_inr_g + cost_res.near_leg_breakdown.slippage_inr_g, 4
                    ),
                    "Leg Total (bps)": round(cost_res.near_leg_breakdown.total_leg_round_trip_bps, 2),
                    "Leg Total (INR)": round(cost_res.near_leg_breakdown.total_leg_round_trip_inr, 2),
                },
                {
                    "Leg": f"Far ({far_id})",
                    "Norm Price (INR/g)": round(cost_res.far_leg_breakdown.norm_price_inr_g_999, 2),
                    "Brokerage (INR/g)": round(cost_res.far_leg_breakdown.brokerage_inr_g, 4),
                    "Exchange+SEBI (INR/g)": round(
                        cost_res.far_leg_breakdown.exchange_txn_inr_g + cost_res.far_leg_breakdown.sebi_fee_inr_g, 4
                    ),
                    "GST 18% (INR/g)": round(cost_res.far_leg_breakdown.gst_inr_g, 4),
                    "CTT Sell (INR/g)": round(cost_res.far_leg_breakdown.ctt_sell_side_inr_g, 4),
                    "Stamp Buy (INR/g)": round(cost_res.far_leg_breakdown.stamp_duty_buy_side_inr_g, 4),
                    "Spread+Slippage (INR/g)": round(
                        cost_res.far_leg_breakdown.spread_crossing_inr_g + cost_res.far_leg_breakdown.slippage_inr_g, 4
                    ),
                    "Leg Total (bps)": round(cost_res.far_leg_breakdown.total_leg_round_trip_bps, 2),
                    "Leg Total (INR)": round(cost_res.far_leg_breakdown.total_leg_round_trip_inr, 2),
                },
            ]
        )
        st.markdown("#### Per-Leg Round-Trip Cost Breakdown")
        st.dataframe(leg_table, use_container_width=True, hide_index=True)
        st.caption(cost_res.rate_provenance_note)

    with col_w2:
        scen_names = list(cost_res.scenario_sensitivity_net_bps.keys())
        scen_vals = [cost_res.scenario_sensitivity_net_bps[k] for k in scen_names]
        fig_sens = go.Figure(
            data=[
                go.Bar(
                    x=[s.upper() for s in scen_names],
                    y=scen_vals,
                    marker_color=[COLOR_SIGNAL if v >= min_net_bps else COLOR_NO_EDGE for v in scen_vals],
                    text=[f"{v:+.2f} bps" for v in scen_vals],
                    textposition="auto",
                )
            ]
        )
        fig_sens.add_hline(y=0.0, line_dash="solid", line_color=COLOR_REJECTED)
        fig_sens.add_hline(y=min_net_bps, line_dash="dash", line_color=COLOR_GOLD_PRIMARY, annotation_text="Min Net Edge")
        apply_plotly_institutional_theme(fig_sens, title="Net Expected Edge Across Scenarios (bps)", height=300)
        st.plotly_chart(fig_sens, use_container_width=True)


def render_backtesting_workbench(norm_df: pd.DataFrame, res: ResearchPipelineResult, base_config: AureusConfig) -> None:
    """Page E: Backtesting Workbench."""
    st.subheader("E. Chronological Walk-Forward Backtesting Workbench")
    st.markdown(
        """
        <div class="aureus-card">
          <b>Chronological Leakage &amp; Frozen-Test Protection:</b> Every bar <code>t</code> is evaluated strictly on
          observations <code>≤ t</code>. Parameters are never tuned on the <b>FROZEN_TEST</b> split. When completed trade
          counts fall below the configured evidence minimum, the engine explicitly returns <code>INSUFFICIENT_EVIDENCE</code>.
        </div>
        """,
        unsafe_allow_html=True,
    )

    eligible_pairs = [
        d.pair_id for d in res.snapshot_decisions if d.gates.get("G2") and d.gates["G2"].passed
    ]
    if not eligible_pairs:
        st.warning("No expiry-eligible pairs available for walk-forward backtesting.")
        return

    default_bt_pair = "GOLD_2026-08-05__VS__GOLD_2026-10-05"
    idx_bt = eligible_pairs.index(default_bt_pair) if default_bt_pair in eligible_pairs else 0

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        bt_pair_str = st.selectbox("Select Eligible Pair", options=eligible_pairs, index=idx_bt)
        bt_scen_str = st.selectbox("Cost Scenario", options=["base", "conservative", "stress"], index=0)
    with b2:
        train_frac = st.slider("Train Split Fraction", 0.30, 0.70, float(base_config.backtest.train_fraction), 0.05)
        val_frac = st.slider("Validation Split Fraction", 0.15, 0.40, float(base_config.backtest.validation_fraction), 0.05)
    with b3:
        min_trades_req = st.slider(
            "Min Completed Trades for Evidence (G6)",
            min_value=1,
            max_value=15,
            value=int(base_config.backtest.min_completed_trades_for_evidence),
        )
        max_hold = st.slider("Max Holding Period (Bars)", 3, 25, int(base_config.backtest.max_holding_bars))
    with b4:
        bt_lookback = st.slider("Spread Lookback Window", 10, 30, int(base_config.statistics.rolling_window))
        bt_entry_z = st.slider("Walk-Forward Entry |Z|", 1.5, 3.5, float(base_config.statistics.entry_z_threshold), 0.1)

    frozen_frac = round(1.0 - train_frac - val_frac, 4)
    if frozen_frac <= 0.05:
        st.error("Train + Validation fraction leaves <= 5% for Frozen-Test split. Reduce Train or Validation fraction.")
        return

    bt_cfg = base_config.model_copy(
        update={
            "statistics": StatisticsConfig(
                rolling_window=bt_lookback,
                min_observations=min(bt_lookback, 15),
                entry_z_threshold=bt_entry_z,
                exit_z_threshold=0.5,
                stop_z_threshold=max(bt_entry_z + 1.0, 4.5),
            ),
            "backtest": BacktestConfig(
                train_fraction=train_frac,
                validation_fraction=val_frac,
                frozen_test_fraction=frozen_frac,
                max_holding_bars=max_hold,
                min_completed_trades_for_evidence=min_trades_req,
            ),
        }
    )

    near_id, far_id = bt_pair_str.split("__VS__")
    near_p = near_id.split("_", 1)
    far_p = far_id.split("_", 1)
    pair_id = PairId(
        near_leg=ContractInstanceId(symbol=near_p[0], expiry_date=pd.Timestamp(near_p[1]).date()),
        far_leg=ContractInstanceId(symbol=far_p[0], expiry_date=pd.Timestamp(far_p[1]).date()),
    )
    aligned = align_pair_history_up_to(norm_df, pair_id, norm_df["timestamp"].max())
    registry = ContractRegistry()

    bt_report = run_pair_walk_forward_backtest(
        run_id=res.run_id,
        aligned_df=aligned,
        pair_id=pair_id,
        config=bt_cfg,
        registry=registry,
        dataset_hash=res.manifest.dataset_sha256,
        is_synthetic=res.manifest.is_synthetic_data,
        scenario=CostScenarioName(bt_scen_str),
    )

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        _kpi_card("Evidence Status (G6)", bt_report.evidence_status.value, f"Min Req: {min_trades_req} trades")
    with k2:
        _kpi_card("Completed Trades", str(bt_report.total_completed_trades), f"Across {bt_report.total_aligned_bars} bars")
    with k3:
        _kpi_card("Gross P&L", f"₹{bt_report.gross_pnl_inr:,.2f}", "Pre-Cost Convergence")
    with k4:
        _kpi_card("Total Two-Leg Costs", f"₹{bt_report.total_costs_inr:,.2f}", f"Scenario: {bt_scen_str.upper()}")
    with k5:
        _kpi_card("Net Realized P&L", f"₹{bt_report.net_pnl_inr:+,.2f}", f"SE: ±₹{bt_report.uncertainty_se_net_pnl_inr:,.2f}")
    with k6:
        _kpi_card("Naive Hold Baseline", f"₹{bt_report.baseline_naive_net_pnl_inr:+,.2f}", f"Max DD: ₹{bt_report.max_drawdown_inr:,.2f}")

    if bt_report.evidence_status == ReasonCode.INSUFFICIENT_EVIDENCE:
        st.warning(
            f"ABSTAIN — INSUFFICIENT_EVIDENCE: Completed trades ({bt_report.total_completed_trades}) "
            f"< minimum required ({min_trades_req}). Research gate G6 fails closed."
        )

    st.markdown("#### Chronological Regime Breakdown (Train / Validation / Frozen-Test)")
    split_rows = []
    for reg_name, sm in bt_report.split_summaries.items():
        split_rows.append(
            {
                "Chronological Split": reg_name,
                "Bars": sm.bar_count,
                "Completed Trades": sm.trade_count,
                "Win Rate": f"{sm.win_rate * 100:.1f}%",
                "Gross P&L (INR)": round(sm.gross_pnl_inr, 2),
                "Total Costs (INR)": round(sm.total_costs_inr, 2),
                "Net P&L (INR)": round(sm.net_pnl_inr, 2),
                "Max Drawdown (INR)": round(sm.max_drawdown_inr, 2),
                "Exposure Fraction": f"{sm.exposure_bar_fraction * 100:.1f}%",
                "Naive Baseline Net (INR)": round(sm.baseline_naive_net_pnl_inr, 2),
            }
        )
    st.dataframe(pd.DataFrame(split_rows), use_container_width=True, hide_index=True)

    if bt_report.trades:
        st.markdown("#### Completed Walk-Forward Trade Ledger")
        st.dataframe(
            pd.DataFrame([t.model_dump(mode="json") for t in bt_report.trades]),
            use_container_width=True,
            hide_index=True,
        )


def render_decision_audit(res: ResearchPipelineResult) -> None:
    """Page F: Decision Audit."""
    st.subheader("F. Gate-by-Gate Decision Audit Trail (G0–G6)")
    decisions = res.snapshot_decisions
    if not decisions:
        st.info("No decisions recorded.")
        return

    options = [f"{d.pair_id}  [{d.state.value}]  ({d.decision_id})" for d in decisions]
    sel_label = st.selectbox("Select Decision Record to Audit", options=options, index=0)
    sel_idx = options.index(sel_label)
    dec = decisions[sel_idx]

    st.markdown(
        f"""
        <div class="aureus-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
              <b>Decision ID:</b> <code>{dec.decision_id}</code> &nbsp;|&nbsp;
              <b>Pair:</b> <code>{dec.pair_id}</code> &nbsp;|&nbsp;
              <b>Timestamp:</b> <code>{dec.timestamp.isoformat()}</code>
            </div>
            <div>{format_state_badge_html(dec.state.value)}</div>
          </div>
          <div style="margin-top:8px; font-size:0.84rem; color:#9CA3AF;">
            <b>Primary Reason Code:</b> <code>{dec.primary_reason_code.value}</code> &nbsp;|&nbsp;
            <b>Direction:</b> <code>{dec.direction.value}</code> &nbsp;|&nbsp;
            <b>Scenario:</b> <code>{dec.cost_scenario.value}</code> &nbsp;|&nbsp;
            <b>Dataset Hash:</b> <code>{dec.dataset_hash[:16]}...</code> &nbsp;|&nbsp;
            <b>Config Hash:</b> <code>{dec.config_hash[:16]}...</code>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    gate_rows = []
    for gid in ["G0", "G1", "G2", "G3", "G4", "G5", "G6"]:
        g = dec.gates.get(gid)
        if g:
            gate_rows.append(
                {
                    "Gate": g.gate_id,
                    "Gate Name": g.gate_name,
                    "Status": "PASS" if g.passed else "FAIL",
                    "Reason Codes": ", ".join(r.value for r in g.reason_codes),
                    "Explanation": g.explanation,
                    "Key Metrics": json.dumps(g.metrics),
                }
            )
    st.markdown("#### Deterministic Gate Evaluation Waterfall (G0 → G6)")
    st.dataframe(pd.DataFrame(gate_rows), use_container_width=True, hide_index=True)

    with st.expander("Inspect Raw Auditable Decision JSON Payload"):
        st.json(dec.model_dump(mode="json"))


def render_data_management(res: ResearchPipelineResult, config: AureusConfig) -> None:
    """Page G: Data Management."""
    st.subheader("G. Dataset Ingestion, Schema Validation & Quarantine Management")
    registry = ContractRegistry()

    col_u1, col_u2 = st.columns([2, 1])
    with col_u1:
        uploaded = st.file_uploader(
            "Upload Market Dataset (.csv or .parquet, max 25 MB)",
            type=["csv", "parquet", "pq"],
        )
        if uploaded is not None:
            if st.button("Validate & Run Research Pipeline on Uploaded Dataset", type="primary"):
                try:
                    uploads_dir = ARTIFACTS_ROOT / "uploads"
                    saved_path, norm_df, val_rep, sha_hex = validate_and_ingest_uploaded_bytes(
                        filename=uploaded.name,
                        raw_bytes=uploaded.getvalue(),
                        registry=registry,
                        save_dir=uploads_dir,
                    )
                    new_res = run_research_pipeline(
                        input_path=saved_path,
                        output_dir=ARTIFACTS_ROOT / "research_run",
                        config=config,
                    )
                    st.session_state["active_dataset_path"] = str(saved_path)
                    st.session_state["pipeline_result"] = new_res
                    st.session_state["norm_df"] = norm_df
                    st.session_state["import_history"].append(
                        {
                            "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "source_file": uploaded.name,
                            "sha256": sha_hex[:16] + "...",
                            "total_rows": val_rep.total_rows,
                            "valid_rows": val_rep.valid_rows,
                            "quarantined_rows": val_rep.quarantined_rows,
                            "provenance": "SYNTHETIC_DEMO" if val_rep.is_synthetic_dataset else "EXTERNAL_UPLOAD",
                        }
                    )
                    st.success(f"Validated and executed run {new_res.run_id} ({val_rep.valid_rows} valid rows).")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Dataset upload rejected by validation engine: {exc}")

    with col_u2:
        st.markdown("#### Deterministic Synthetic Demo Reset")
        st.write("Reload the built-in 48-bar multi-scenario synthetic MCX Gold futures dataset.")
        if st.button("Reload Synthetic Demo Dataset"):
            for k in ["pipeline_result", "norm_df"]:
                st.session_state.pop(k, None)
            _ensure_session_initialized()
            st.rerun()

    val_rep = res.validation_report
    st.markdown("#### Active Dataset Validation & Quarantine Summary")
    v1, v2, v3, v4 = st.columns(4)
    with v1:
        _kpi_card("Total Ingested Rows", str(val_rep.total_rows))
    with v2:
        _kpi_card("Valid Normalized Rows", str(val_rep.valid_rows))
    with v3:
        _kpi_card("Quarantined Rows", str(val_rep.quarantined_rows))
    with v4:
        _kpi_card("Synthetic Flag", "TRUE (SYNTHETIC_DEMO)" if val_rep.is_synthetic_dataset else "FALSE")

    if val_rep.quarantined_records:
        st.markdown("#### Quarantined Observations & Rejection Explanations")
        q_rows = [
            {
                "Row Index": q.row_index,
                "Reason Codes": ", ".join(r.value for r in q.reason_codes),
                "Explanation": q.explanation,
                "Symbol": q.raw_payload.get("symbol"),
                "Expiry": q.raw_payload.get("expiry_date"),
                "Close": q.raw_payload.get("close"),
                "Bid": q.raw_payload.get("bid"),
                "Ask": q.raw_payload.get("ask"),
                "Unit": q.raw_payload.get("quotation_unit"),
            }
            for q in val_rep.quarantined_records
        ]
        q_df = pd.DataFrame(q_rows)
        st.dataframe(q_df, use_container_width=True, hide_index=True)
        st.download_button(
            label="Download Quarantined Rows (CSV)",
            data=q_df.to_csv(index=False).encode("utf-8"),
            file_name=f"quarantined_rows_{res.run_id}.csv",
            mime="text/csv",
        )

    st.markdown("#### Dataset Import History")
    st.dataframe(pd.DataFrame(st.session_state["import_history"]), use_container_width=True, hide_index=True)


def render_reports_and_evidence(res: ResearchPipelineResult) -> None:
    """Page H: Reports and Evidence."""
    st.subheader("H. Reproducible Evidence Manifests, DuckDB Storage & Report Exports")

    ok, errors = verify_run_manifest(res.manifest_path)
    if ok:
        st.success(
            f"SHA-256 Run Manifest Integrity Verified (`{res.manifest.manifest_self_sha256[:24]}...`). "
            "All output artifacts match recorded hashes."
        )
    else:
        st.error(f"Manifest Integrity Verification Failed: {errors}")

    json_bytes = Path(res.json_report_path).read_bytes()
    md_text = generate_markdown_report(
        manifest=res.manifest,
        validation_report=res.validation_report,
        backtest_reports=res.backtest_reports,
        snapshot_decisions=res.snapshot_decisions,
    )
    html_text = generate_html_report(
        manifest=res.manifest,
        validation_report=res.validation_report,
        backtest_reports=res.backtest_reports,
        snapshot_decisions=res.snapshot_decisions,
    )
    csv_text = generate_decisions_csv_text(res.snapshot_decisions)
    manifest_bytes = Path(res.manifest_path).read_bytes()
    val_json_bytes = json.dumps(res.validation_report.model_dump(mode="json"), indent=2).encode("utf-8")

    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(
            "1. Download Run Manifest (JSON)",
            data=manifest_bytes,
            file_name=f"run_manifest_{res.run_id}.json",
            mime="application/json",
            use_container_width=True,
        )
        st.download_button(
            "2. Download Full Research Summary (JSON)",
            data=json_bytes,
            file_name=f"research_report_{res.run_id}.json",
            mime="application/json",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "3. Download Decision Audit Export (CSV)",
            data=csv_text.encode("utf-8"),
            file_name=f"decisions_{res.run_id}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.download_button(
            "4. Download Validation & Quarantine Report (JSON)",
            data=val_json_bytes,
            file_name=f"validation_report_{res.run_id}.json",
            mime="application/json",
            use_container_width=True,
        )
    with d3:
        st.download_button(
            "5. Download Markdown Research Report (.md)",
            data=md_text.encode("utf-8"),
            file_name=f"research_report_{res.run_id}.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.download_button(
            "6. Download Standalone HTML Research Report (.html)",
            data=html_text.encode("utf-8"),
            file_name=f"research_report_{res.run_id}.html",
            mime="text/html",
            use_container_width=True,
        )

    st.markdown("#### DuckDB Evidence Store Inspection")
    store = AureusStorage(res.duckdb_path)
    st.dataframe(store.query_runs_df(), use_container_width=True, hide_index=True)

    with st.expander("Preview Markdown Research Report", expanded=True):
        st.markdown(md_text)


def main() -> None:
    """Launch the AUREUS-RV 3.0 Streamlit application."""
    st.set_page_config(
        page_title="AUREUS-RV 3.0 — MCX Gold Relative-Value Research Instrument",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(INSTITUTIONAL_CSS, unsafe_allow_html=True)
    _ensure_session_initialized()

    res: ResearchPipelineResult = st.session_state["pipeline_result"]
    norm_df: pd.DataFrame = st.session_state["norm_df"]
    cfg: AureusConfig = st.session_state["active_config"]

    with st.sidebar:
        st.markdown(
            f"<h2 style='color:{COLOR_GOLD_PRIMARY}; margin-bottom:0;'>AUREUS-RV 3.0</h2>"
            "<p style='color:#9CA3AF; font-size:0.8rem; margin-top:2px;'>Global Focus Innovators</p>",
            unsafe_allow_html=True,
        )
        nav_page = st.radio(
            "Research Navigation",
            options=[
                "A. Executive Overview",
                "B. Contract Explorer",
                "C. Spread Research",
                "D. Transaction-Cost Lab",
                "E. Backtesting Workbench",
                "F. Decision Audit",
                "G. Data Management",
                "H. Reports & Evidence",
            ],
            index=0,
        )
        st.divider()
        st.caption(f"Engine Version: `{__version__}`")
        st.caption(f"Methodology: `{__methodology_version__}`")
        st.caption("Principle: `NORMALIZE → VALIDATE → PAIR → COST → ABSTAIN → PROVE`")

    _render_top_banner(res)

    if nav_page == "A. Executive Overview":
        render_executive_overview(res)
    elif nav_page == "B. Contract Explorer":
        render_contract_explorer(norm_df, cfg)
    elif nav_page == "C. Spread Research":
        render_spread_research(norm_df, cfg)
    elif nav_page == "D. Transaction-Cost Lab":
        render_transaction_cost_lab(norm_df, res, cfg)
    elif nav_page == "E. Backtesting Workbench":
        render_backtesting_workbench(norm_df, res, cfg)
    elif nav_page == "F. Decision Audit":
        render_decision_audit(res)
    elif nav_page == "G. Data Management":
        render_data_management(res, cfg)
    elif nav_page == "H. Reports & Evidence":
        render_reports_and_evidence(res)


if __name__ == "__main__":
    main()
