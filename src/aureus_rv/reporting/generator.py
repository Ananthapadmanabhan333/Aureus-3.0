"""Structured Markdown and JSON research report generation for AUREUS-RV 3.0."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aureus_rv.backtesting.engine import PairBacktestReport
from aureus_rv.evidence.manifest import RunManifest
from aureus_rv.models import DecisionRecord, DecisionState
from aureus_rv.validation.validator import ValidationReport


def build_json_report_payload(
    manifest: RunManifest,
    validation_report: ValidationReport,
    backtest_reports: list[PairBacktestReport],
    snapshot_decisions: list[DecisionRecord],
) -> dict[str, Any]:
    """Build structured JSON dictionary summarizing the full research run."""
    state_counts = {s.value: 0 for s in DecisionState}
    for d in snapshot_decisions:
        state_counts[d.state.value] = state_counts.get(d.state.value, 0) + 1

    return {
        "manifest": manifest.model_dump(mode="json"),
        "validation_summary": {
            "total_rows": validation_report.total_rows,
            "valid_rows": validation_report.valid_rows,
            "quarantined_rows": validation_report.quarantined_rows,
            "reason_counts": validation_report.reason_counts,
            "is_synthetic_dataset": validation_report.is_synthetic_dataset,
        },
        "snapshot_decision_counts": state_counts,
        "snapshot_decisions": [d.model_dump(mode="json") for d in snapshot_decisions],
        "backtest_summaries": [
            {
                "pair_id": r.pair_id,
                "cost_scenario": r.cost_scenario.value,
                "evidence_status": r.evidence_status.value,
                "total_aligned_bars": r.total_aligned_bars,
                "total_completed_trades": r.total_completed_trades,
                "gross_pnl_inr": r.gross_pnl_inr,
                "total_costs_inr": r.total_costs_inr,
                "net_pnl_inr": r.net_pnl_inr,
                "max_drawdown_inr": r.max_drawdown_inr,
                "uncertainty_se_net_pnl_inr": r.uncertainty_se_net_pnl_inr,
                "baseline_naive_net_pnl_inr": r.baseline_naive_net_pnl_inr,
                "split_summaries": {k: v.model_dump(mode="json") for k, v in r.split_summaries.items()},
                "trades": [t.model_dump(mode="json") for t in r.trades],
            }
            for r in backtest_reports
        ],
    }


def generate_markdown_report(
    manifest: RunManifest,
    validation_report: ValidationReport,
    backtest_reports: list[PairBacktestReport],
    snapshot_decisions: list[DecisionRecord],
) -> str:
    """Render an auditable Markdown research report for a completed AUREUS-RV 3.0 run."""
    synth_banner = (
        "SYNTHETIC DEMO DATASET (Labeled `SYNTHETIC_DEMO` — Not Actual MCX Feed)"
        if manifest.is_synthetic_data
        else "VERIFIED HISTORICAL DATASET"
    )
    lines: list[str] = [
        "# AUREUS-RV 3.0 — Quantitative Research & Validation Report",
        "",
        "> **Principle:** `NORMALIZE → VALIDATE → PAIR → COST → ABSTAIN → PROVE`",
        f"> **Run ID:** `{manifest.run_id}` | **Software:** `{manifest.software_version}` | **Methodology:** `{manifest.methodology_version}`",
        f"> **Data Provenance:** **{synth_banner}**",
        f"> **Dataset SHA-256:** `{manifest.dataset_sha256}`",
        f"> **Config SHA-256:** `{manifest.config_sha256}`",
        "",
        "---",
        "",
        "## 1. Data Ingestion & Validation Summary (Gate G0 & G1)",
        "",
        f"- **Total Raw Rows Ingested:** `{validation_report.total_rows}`",
        f"- **Valid Normalized Rows:** `{validation_report.valid_rows}`",
        f"- **Quarantined (Rejected) Rows:** `{validation_report.quarantined_rows}`",
        "",
    ]

    if validation_report.reason_counts:
        lines.append("### Quarantine Rejection Breakdown")
        lines.append("")
        lines.append("| Reason Code | Count |")
        lines.append("| :--- | ---: |")
        for code, count in sorted(validation_report.reason_counts.items()):
            lines.append(f"| `{code}` | {count} |")
        lines.append("")

    lines.extend(
        [
            "## 2. Latest Snapshot Pair Decisions (Gates G0–G6)",
            "",
            "| Pair ID | State | Direction | Primary Reason | DTE (Near/Far) | Z-Score | Gross Edge (bps) | Cost (bps) | Net Edge (bps) |",
            "| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: |",
        ]
    )

    for d in snapshot_decisions:
        m = d.metrics
        dte_str = f"{m.get('dte_near', '-')}/{m.get('dte_far', '-')}"
        z_str = f"{float(m['z_score']):.2f}" if m.get("z_score") is not None else "-"
        g_str = f"{float(m['gross_expected_bps']):.2f}" if m.get("gross_expected_bps") is not None else "-"
        c_str = f"{float(m['total_cost_bps']):.2f}" if m.get("total_cost_bps") is not None else "-"
        n_str = f"{float(m['net_expected_bps']):.2f}" if m.get("net_expected_bps") is not None else "-"
        lines.append(
            f"| `{d.pair_id}` | **{d.state.value}** | `{d.direction.value}` | `{d.primary_reason_code.value}` | {dte_str} | {z_str} | {g_str} | {c_str} | {n_str} |"
        )

    lines.extend(
        [
            "",
            "## 3. Chronological Walk-Forward Backtest Summary",
            "",
            "| Pair ID | Scenario | Evidence Status | Bars | Trades | Gross P&L (INR) | Total Costs (INR) | Net P&L (INR) | Max DD (INR) | Naive Baseline (INR) |",
            "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for rep in backtest_reports:
        lines.append(
            f"| `{rep.pair_id}` | `{rep.cost_scenario.value}` | `{rep.evidence_status.value}` | "
            f"{rep.total_aligned_bars} | {rep.total_completed_trades} | "
            f"{rep.gross_pnl_inr:,.2f} | {rep.total_costs_inr:,.2f} | "
            f"**{rep.net_pnl_inr:,.2f}** | {rep.max_drawdown_inr:,.2f} | {rep.baseline_naive_net_pnl_inr:,.2f} |"
        )

    lines.extend(
        [
            "",
            "## 4. Integrity & Governance Notice",
            "",
            "- **Research Classification Disclaimer:** A `TRADE SIGNAL` is a statistical and cost-adjusted research classification, not an automated execution order or profitability guarantee.",
            f"- **Integrity Scope:** {manifest.integrity_scope_disclaimer}",
            "",
        ]
    )
    return "\n".join(lines)


def generate_decisions_csv_text(decisions: list[DecisionRecord]) -> str:
    """Serialize DecisionRecord list into a clean CSV table string."""
    import io

    import pandas as pd

    if not decisions:
        return "decision_id,run_id,timestamp,pair_id,near_contract,far_contract,state,direction,primary_reason_code,cost_scenario,z_score,spread_bps,gross_expected_bps,total_cost_bps,net_expected_bps,is_synthetic\n"

    rows = []
    for d in decisions:
        m = d.metrics
        rows.append(
            {
                "decision_id": d.decision_id,
                "run_id": d.run_id,
                "timestamp": d.timestamp.isoformat(),
                "pair_id": d.pair_id,
                "near_contract": d.near_contract,
                "far_contract": d.far_contract,
                "state": d.state.value,
                "direction": d.direction.value,
                "primary_reason_code": d.primary_reason_code.value,
                "cost_scenario": d.cost_scenario.value,
                "z_score": m.get("z_score"),
                "spread_bps": m.get("spread_bps"),
                "gross_expected_bps": m.get("gross_expected_bps"),
                "total_cost_bps": m.get("total_cost_bps"),
                "net_expected_bps": m.get("net_expected_bps"),
                "is_synthetic": d.is_synthetic,
                "dataset_hash": d.dataset_hash,
                "config_hash": d.config_hash,
            }
        )
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue()


def generate_html_report(
    manifest: RunManifest,
    validation_report: ValidationReport,
    backtest_reports: list[PairBacktestReport],
    snapshot_decisions: list[DecisionRecord],
) -> str:
    """Render a standalone institutional-grade HTML research report."""
    synth_badge = (
        "<span class='badge badge-synth'>SYNTHETIC DEMO DATASET (NOT LIVE MCX FEED)</span>"
        if manifest.is_synthetic_data
        else "<span class='badge badge-verified'>VERIFIED HISTORICAL DATASET</span>"
    )
    dec_rows = []
    for d in snapshot_decisions:
        m = d.metrics
        z_str = f"{float(m['z_score']):.2f}" if m.get("z_score") is not None else "-"
        g_str = f"{float(m['gross_expected_bps']):.2f}" if m.get("gross_expected_bps") is not None else "-"
        c_str = f"{float(m['total_cost_bps']):.2f}" if m.get("total_cost_bps") is not None else "-"
        n_str = f"{float(m['net_expected_bps']):.2f}" if m.get("net_expected_bps") is not None else "-"
        dec_rows.append(
            f"<tr><td><code>{d.pair_id}</code></td><td><strong>{d.state.value}</strong></td>"
            f"<td>{d.direction.value}</td><td><code>{d.primary_reason_code.value}</code></td>"
            f"<td>{z_str}</td><td>{g_str}</td><td>{c_str}</td><td>{n_str}</td></tr>"
        )

    bt_rows = []
    for r in backtest_reports:
        bt_rows.append(
            f"<tr><td><code>{r.pair_id}</code></td><td>{r.cost_scenario.value}</td>"
            f"<td><code>{r.evidence_status.value}</code></td><td>{r.total_aligned_bars}</td>"
            f"<td>{r.total_completed_trades}</td><td>{r.gross_pnl_inr:,.2f}</td>"
            f"<td>{r.total_costs_inr:,.2f}</td><td><strong>{r.net_pnl_inr:,.2f}</strong></td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>AUREUS-RV 3.0 — Research Report ({manifest.run_id})</title>
<style>
  body {{ background: #0f1115; color: #e5e7eb; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 32px; line-height: 1.5; }}
  h1, h2 {{ color: #d4af37; border-bottom: 1px solid #262930; padding-bottom: 6px; }}
  .meta {{ background: #161920; border: 1px solid #2a2e39; padding: 16px; border-radius: 6px; margin-bottom: 24px; }}
  .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }}
  .badge-synth {{ background: #422006; color: #fbbf24; border: 1px solid #d97706; }}
  .badge-verified {{ background: #064e3b; color: #34d399; border: 1px solid #059669; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; margin-bottom: 24px; font-size: 13px; }}
  th, td {{ border: 1px solid #2a2e39; padding: 8px 10px; text-align: left; }}
  th {{ background: #1a1d24; color: #d4af37; }}
  code {{ color: #93c5fd; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
</style>
</head>
<body>
  <h1>AUREUS-RV 3.0 — Quantitative Research &amp; Evidence Report</h1>
  <div class="meta">
    <p><strong>Run ID:</strong> <code>{manifest.run_id}</code> &nbsp;|&nbsp; <strong>Version:</strong> <code>{manifest.software_version}</code> &nbsp;|&nbsp; {synth_badge}</p>
    <p><strong>Dataset SHA-256:</strong> <code>{manifest.dataset_sha256}</code></p>
    <p><strong>Config SHA-256:</strong> <code>{manifest.config_sha256}</code></p>
    <p><strong>Manifest Self SHA-256:</strong> <code>{manifest.manifest_self_sha256}</code></p>
    <p><strong>Rows:</strong> Total={validation_report.total_rows}, Valid={validation_report.valid_rows}, Quarantined={validation_report.quarantined_rows}</p>
  </div>
  <h2>Latest Snapshot Pair Decisions (G0–G6)</h2>
  <table>
    <thead><tr><th>Pair ID</th><th>State</th><th>Direction</th><th>Primary Reason</th><th>Z-Score</th><th>Gross (bps)</th><th>Cost (bps)</th><th>Net (bps)</th></tr></thead>
    <tbody>{''.join(dec_rows)}</tbody>
  </table>
  <h2>Walk-Forward Backtest Summary</h2>
  <table>
    <thead><tr><th>Pair ID</th><th>Scenario</th><th>Evidence Status</th><th>Bars</th><th>Trades</th><th>Gross P&amp;L (INR)</th><th>Costs (INR)</th><th>Net P&amp;L (INR)</th></tr></thead>
    <tbody>{''.join(bt_rows)}</tbody>
  </table>
  <p><em>Disclaimer: A TRADE SIGNAL is a research classification only, not an automated order or guarantee of profitability. {manifest.integrity_scope_disclaimer}</em></p>
</body>
</html>"""


def write_research_reports(
    output_dir: str | Path,
    manifest: RunManifest,
    validation_report: ValidationReport,
    backtest_reports: list[PairBacktestReport],
    snapshot_decisions: list[DecisionRecord],
) -> tuple[Path, Path]:
    """Write `research_report.json`, `research_report.md`, `research_report.html`, and `decisions_export.csv` to `output_dir`."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "research_report.json"
    md_path = out / "research_report.md"
    html_path = out / "research_report.html"
    csv_path = out / "decisions_export.csv"

    payload = build_json_report_payload(
        manifest=manifest,
        validation_report=validation_report,
        backtest_reports=backtest_reports,
        snapshot_decisions=snapshot_decisions,
    )
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    md_text = generate_markdown_report(
        manifest=manifest,
        validation_report=validation_report,
        backtest_reports=backtest_reports,
        snapshot_decisions=snapshot_decisions,
    )
    md_path.write_text(md_text, encoding="utf-8")

    html_text = generate_html_report(
        manifest=manifest,
        validation_report=validation_report,
        backtest_reports=backtest_reports,
        snapshot_decisions=snapshot_decisions,
    )
    html_path.write_text(html_text, encoding="utf-8")

    csv_text = generate_decisions_csv_text(snapshot_decisions)
    csv_path.write_text(csv_text, encoding="utf-8")

    return json_path, md_path
