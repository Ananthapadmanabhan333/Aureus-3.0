"""Deterministic synthetic demo dataset generator and end-to-end research pipeline orchestrator."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from aureus_rv import __methodology_version__, __version__
from aureus_rv.backtesting.engine import PairBacktestReport, run_pair_walk_forward_backtest
from aureus_rv.config.settings import AureusConfig
from aureus_rv.contracts.registry import ContractRegistry
from aureus_rv.costs.waterfall import evaluate_pair_costs
from aureus_rv.decisions.gates import evaluate_decision_gates
from aureus_rv.evidence.manifest import RunManifest, save_run_manifest
from aureus_rv.ingestion.loader import compute_file_sha256, load_raw_dataset
from aureus_rv.liquidity.screener import screen_pair_liquidity
from aureus_rv.models import (
    DecisionRecord,
    DecisionState,
    PairId,
    QuotationUnit,
    ReasonCode,
    SourceProvenance,
)
from aureus_rv.normalization.normalizer import normalize_dataframe_observations
from aureus_rv.pairing.engine import align_pair_history_up_to, discover_candidate_pairs_at_timestamp
from aureus_rv.reporting.generator import write_research_reports
from aureus_rv.statistics.spread import analyze_pair_spread_up_to
from aureus_rv.storage.duckdb_store import AureusStorage
from aureus_rv.validation.validator import ValidationReport, validate_dataset


class ResearchPipelineResult(BaseModel):
    """Complete result bundle returned by `run_research_pipeline`."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    manifest: RunManifest
    validation_report: ValidationReport
    snapshot_decisions: list[DecisionRecord]
    backtest_reports: list[PairBacktestReport]
    manifest_path: str
    json_report_path: str
    markdown_report_path: str
    duckdb_path: str


def generate_synthetic_demo_dataset(seed: int = 42, n_bars: int = 48) -> pd.DataFrame:
    """Generate a deterministic, explicitly labeled (`SYNTHETIC_DEMO`) multi-scenario dataset.

    Covers:
    1. Validated Normalization & Qualifying Candidate (`GOLD_2026-08-05` 995/10g vs `GOLD_2026-10-05` 995/10g)
       with recurring temporary dislocations (producing completed walk-forward trades) and a final bar
       dislocation (`TRADE SIGNAL`).
    2. Cross-variant 995 vs 999 Purity Pairing (`GOLD_2026-08-05` vs `GOLDM_2026-08-05`) that sits in `NO-EDGE`
       at the final bar (small statistical dislocation consumed by two-leg transaction costs).
    3. Normal Equilibrium Band Pair (`GOLD_2026-08-05` vs `GOLDPETAL_2026-08-31`) -> `QUIET`.
    4. Tender/Rollover Ineligible Contract (`GOLD_2026-06-05`, DTE=3 on final bar) -> `REJECTED` (G2).
    5. Expiry Distance Too Large Contract (`GOLD_2027-04-05`, gap > 135 days) -> `REJECTED` (G2).
    6. Illiquid / Wide Spread Contract (`GOLDGUINEA_2026-08-31`, low volume & wide spread) -> `REJECTED` (G3).
    7. Insufficient History Contract (`GOLDM_2026-10-05`, only 8 bars present) -> `REJECTED` (G4).
    8. Intentionally Malformed Rows for Quarantine (G0/G1):
       - Negative price row
       - Inverted bid > ask row
       - Unknown quotation unit (`USD_PER_OZ`)
       - Unmarked synthetic provenance (`is_synthetic=False` with `SYNTHETIC_DEMO`)
       - Duplicate observation row
    """
    rng = np.random.default_rng(seed)
    base_start = datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)
    timestamps = [base_start + timedelta(days=i) for i in range(n_bars)]
    # Final timestamp is 2026-06-01 (day 47)

    rows: list[dict[str, Any]] = []

    # Base 999 gold trajectory in INR/g around 7,200 INR/g
    base_999_path = 7200.0 + np.cumsum(rng.normal(0.0, 4.5, size=n_bars))

    for i, ts in enumerate(timestamps):
        p999 = float(base_999_path[i])
        # Convert 999 INR/g to 995 INR/10g equivalent: p_raw_995_10g = p999 * 10 * (995 / 999)
        p995_10g_base = p999 * 10.0 * (995.0 / 999.0)

        # 1. Near standard contract: GOLD_2026-08-05 (10g, 995 fineness, 1000g lot)
        # Inject periodic spikes at bars 21, 24, 27, 47 (outside the clean window 27..46 except 27 -> keep 28..46 clean!)
        # Specifically: spikes at bars 20, 23, 26 (which each revert at 21, 24, 27) and on the final bar (n_bars - 1 = 47).
        # Because bars 27..46 (19 bars) have zero spikes, the rolling 20-bar window at bar 47 has tight normal std (~0.32 INR/g),
        # so a +15.0 INR/g spike on bar 47 yields z ~ 4.1 (< 4.5 stop) and gross expected reversion ~13.8 INR/g (~19.1 bps) >> 9.2 bps cost!
        spike_inr_g = 0.0
        if i in {20, 23, 26, n_bars - 1}:
            spike_inr_g = 15.0  # +15.0 INR/g (~20.8 bps) above equilibrium carry
        noise_near_g = float(rng.normal(0.0, 0.22))
        near_999_g = p999 + spike_inr_g + noise_near_g
        near_raw_10g = round(near_999_g * 10.0 * (995.0 / 999.0), 2)

        rows.append(
            _make_obs(
                ts=ts,
                symbol="GOLD",
                expiry=date(2026, 8, 5),
                close_raw=near_raw_10g,
                half_spread_raw=4.0,  # ~1.1 bps total bid-ask spread
                volume=420,
                oi=1850,
                unit=QuotationUnit.INR_PER_10G.value,
                fineness=995,
                lot_grams=1000.0,
            )
        )

        # 2. Far standard contract: GOLD_2026-10-05 (10g, 995 fineness, 1000g lot)
        # Equilibrium carry +18 INR/g above base_999_path
        far_999_g = p999 + 18.0 + float(rng.normal(0.0, 0.20))
        far_raw_10g = round(far_999_g * 10.0 * (995.0 / 999.0), 2)
        rows.append(
            _make_obs(
                ts=ts,
                symbol="GOLD",
                expiry=date(2026, 10, 5),
                close_raw=far_raw_10g,
                half_spread_raw=4.5,
                volume=310,
                oi=1420,
                unit=QuotationUnit.INR_PER_10G.value,
                fineness=995,
                lot_grams=1000.0,
            )
        )

        # 3. Cross-variant contract: GOLDM_2026-08-28 (10g, 999 fineness, 100g lot)
        # Designed so that at the final bar, GOLD_2026-08-05 vs GOLDM_2026-08-28 has a modest z-score (>2.0)
        # due to tight spread std, where gross reversion (~2.8 bps) is LESS than round-trip costs (~9.2 bps) -> NO-EDGE!
        goldm_offset = (6.0 + spike_inr_g) if i < n_bars - 1 else (6.0 + spike_inr_g - 2.2)
        goldm_999_g = p999 + goldm_offset + float(rng.normal(0.0, 0.08))
        goldm_raw_10g = round(goldm_999_g * 10.0, 2)
        rows.append(
            _make_obs(
                ts=ts,
                symbol="GOLDM",
                expiry=date(2026, 8, 28),
                close_raw=goldm_raw_10g,
                half_spread_raw=5.0,
                volume=550,
                oi=2100,
                unit=QuotationUnit.INR_PER_10G.value,
                fineness=999,
                lot_grams=100.0,
            )
        )

        # 4. Quiet equilibrium contract: GOLDPETAL_2026-08-31 (1g, 999 fineness, 1g lot)
        # Tracks near_999_g closely on final bar so z-score is inside [-2, +2] -> QUIET
        petal_999_g = near_999_g + 3.0 + float(rng.normal(0.0, 0.45))
        rows.append(
            _make_obs(
                ts=ts,
                symbol="GOLDPETAL",
                expiry=date(2026, 8, 31),
                close_raw=round(petal_999_g, 2),
                half_spread_raw=0.5,
                volume=800,
                oi=3500,
                unit=QuotationUnit.INR_PER_1G.value,
                fineness=999,
                lot_grams=1.0,
            )
        )

        # 5. Rollover / Tender period contract: GOLD_2026-06-04 (DTE = 3 days on final bar 2026-06-01) -> REJECTED G2
        rows.append(
            _make_obs(
                ts=ts,
                symbol="GOLD",
                expiry=date(2026, 6, 4),
                close_raw=round(p995_10g_base - 40.0, 2),
                half_spread_raw=5.0,
                volume=180,
                oi=600,
                unit=QuotationUnit.INR_PER_10G.value,
                fineness=995,
                lot_grams=1000.0,
            )
        )

        # 6. Excessive Expiry Distance contract: GOLD_2027-04-05 (gap > 135 days) -> REJECTED G2
        rows.append(
            _make_obs(
                ts=ts,
                symbol="GOLD",
                expiry=date(2027, 4, 5),
                close_raw=round(p995_10g_base + 650.0, 2),
                half_spread_raw=8.0,
                volume=120,
                oi=500,
                unit=QuotationUnit.INR_PER_10G.value,
                fineness=995,
                lot_grams=1000.0,
            )
        )

        # 7. Poor liquidity contract: GOLDGUINEA_2026-08-31 (8g, 999 fineness, low volume=5 & wide spread) -> REJECTED G3
        guinea_raw_8g = round((p999 + 5.0) * 8.0, 2)
        rows.append(
            _make_obs(
                ts=ts,
                symbol="GOLDGUINEA",
                expiry=date(2026, 8, 31),
                close_raw=guinea_raw_8g,
                half_spread_raw=95.0,  # ~33 bps bid-ask spread (> 15 bps limit)
                volume=5,              # < 50 lots minimum
                oi=25,                 # < 100 lots minimum
                unit=QuotationUnit.INR_PER_8G.value,
                fineness=999,
                lot_grams=8.0,
            )
        )

        # 8. Short history contract: GOLDM_2026-10-05 (only present in last 8 bars) -> REJECTED G4
        if i >= n_bars - 8:
            rows.append(
                _make_obs(
                    ts=ts,
                    symbol="GOLDM",
                    expiry=date(2026, 10, 5),
                    close_raw=round((p999 + 19.0) * 10.0, 2),
                    half_spread_raw=5.0,
                    volume=220,
                    oi=900,
                    unit=QuotationUnit.INR_PER_10G.value,
                    fineness=999,
                    lot_grams=100.0,
                )
            )

    # 9. Append deliberate invalid rows for quarantine verification (G0 / G1)
    bad_ts = timestamps[10]
    # 9a. Negative close price
    bad_neg = _make_obs(
        ts=bad_ts,
        symbol="GOLD",
        expiry=date(2026, 12, 5),
        close_raw=-71000.0,
        half_spread_raw=5.0,
        volume=100,
        oi=500,
        unit=QuotationUnit.INR_PER_10G.value,
        fineness=995,
        lot_grams=1000.0,
    )
    rows.append(bad_neg)

    # 9b. Inverted bid > ask
    bad_ba = _make_obs(
        ts=bad_ts,
        symbol="GOLD",
        expiry=date(2026, 12, 15),
        close_raw=71500.0,
        half_spread_raw=5.0,
        volume=100,
        oi=500,
        unit=QuotationUnit.INR_PER_10G.value,
        fineness=995,
        lot_grams=1000.0,
    )
    bad_ba["bid"] = 71600.0
    bad_ba["ask"] = 71400.0
    rows.append(bad_ba)

    # 9c. Unknown quotation unit
    bad_unit = _make_obs(
        ts=bad_ts,
        symbol="GOLD",
        expiry=date(2026, 12, 20),
        close_raw=2300.0,
        half_spread_raw=1.0,
        volume=100,
        oi=500,
        unit="USD_PER_OZ",
        fineness=995,
        lot_grams=1000.0,
    )
    rows.append(bad_unit)

    # 9d. Dishonest synthetic provenance flag
    bad_prov = _make_obs(
        ts=bad_ts,
        symbol="GOLD",
        expiry=date(2026, 12, 24),
        close_raw=71500.0,
        half_spread_raw=5.0,
        volume=100,
        oi=500,
        unit=QuotationUnit.INR_PER_10G.value,
        fineness=995,
        lot_grams=1000.0,
    )
    bad_prov["is_synthetic"] = False
    rows.append(bad_prov)

    # 9e. Exact duplicate observation of row 0
    rows.append(dict(rows[0]))

    return pd.DataFrame(rows)


def _make_obs(
    ts: datetime,
    symbol: str,
    expiry: date,
    close_raw: float,
    half_spread_raw: float,
    volume: int,
    oi: int,
    unit: str,
    fineness: int,
    lot_grams: float,
) -> dict[str, Any]:
    return {
        "timestamp": ts.isoformat(),
        "symbol": symbol,
        "expiry_date": expiry.isoformat(),
        "open": round(close_raw - half_spread_raw * 0.5, 2),
        "high": round(close_raw + half_spread_raw * 1.5, 2),
        "low": round(close_raw - half_spread_raw * 1.5, 2),
        "close": close_raw,
        "bid": round(close_raw - half_spread_raw, 2),
        "ask": round(close_raw + half_spread_raw, 2),
        "volume_lots": volume,
        "open_interest_lots": oi,
        "quotation_unit": unit,
        "purity_fineness": fineness,
        "lot_size_grams": lot_grams,
        "quote_age_seconds": 12,
        "source_provenance": SourceProvenance.SYNTHETIC_DEMO.value,
        "is_synthetic": True,
    }


def run_research_pipeline(
    input_path: str | Path,
    output_dir: str | Path,
    config: AureusConfig | None = None,
    duckdb_path: str | Path | None = None,
) -> ResearchPipelineResult:
    """Execute the complete AUREUS-RV 3.0 backend research workflow end-to-end."""
    cfg = config or AureusConfig()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_file = Path(duckdb_path) if duckdb_path is not None else (out_dir / "aureus_rv.duckdb")

    registry = ContractRegistry()

    # 1. Ingest raw dataset
    raw_df, ing_manifest = load_raw_dataset(input_path)

    # 2. Validate & Quarantine
    clean_df, val_report = validate_dataset(raw_df, registry)

    # Deterministic run ID derived from dataset SHA256 + config SHA256
    cfg_hash = cfg.compute_hash()
    run_seed_str = f"{ing_manifest.sha256_hash}|{cfg_hash}|{__version__}"
    run_id = "RUN-" + hashlib.sha256(run_seed_str.encode("utf-8")).hexdigest()[:12].upper()

    # 3. Normalize valid observations to INR per gram at 999 fineness
    norm_df = normalize_dataframe_observations(clean_df, registry)

    # Persist normalized observations and quarantined rows as Parquet/JSON artifacts
    storage = AureusStorage(db_file)
    artifact_hashes: dict[str, str] = {}

    norm_parquet_path = out_dir / "normalized_observations.parquet"
    artifact_hashes["normalized_observations.parquet"] = storage.write_parquet_artifact(
        norm_df, norm_parquet_path
    )

    quarantine_df = pd.DataFrame([q.model_dump(mode="json") for q in val_report.quarantined_records])
    quarantine_parquet_path = out_dir / "quarantined_observations.parquet"
    artifact_hashes["quarantined_observations.parquet"] = storage.write_parquet_artifact(
        quarantine_df, quarantine_parquet_path
    )

    # 4. Evaluate pairs at the latest decision timestamp & run walk-forward backtests on eligible pairs
    snapshot_decisions: list[DecisionRecord] = []
    backtest_reports: list[PairBacktestReport] = []

    if not norm_df.empty:
        latest_ts = norm_df["timestamp"].max()
        df_at_latest = norm_df[norm_df["timestamp"] == latest_ts]
        pair_candidates = discover_candidate_pairs_at_timestamp(
            df_at_ts=df_at_latest,
            timestamp=latest_ts,
            config=cfg.pairing,
            registry=registry,
        )

        for pair_elig in pair_candidates:
            pair_id: PairId = pair_elig.pair_id
            aligned_hist = align_pair_history_up_to(norm_df, pair_id, latest_ts)

            liq_res = screen_pair_liquidity(aligned_hist, pair_id, cfg.liquidity)
            stats_res = analyze_pair_spread_up_to(aligned_hist, pair_id, cfg.statistics)

            if not aligned_hist.empty:
                last_row = aligned_hist.iloc[-1]
                cost_res = evaluate_pair_costs(
                    pair_id=pair_id,
                    direction=stats_res.suggested_direction,
                    norm_near_inr_g_999=float(last_row["norm_close_inr_g_999_near"]),
                    norm_far_inr_g_999=float(last_row["norm_close_inr_g_999_far"]),
                    near_bid_ask_spread_bps=float(last_row["bid_ask_spread_bps_near"]),
                    far_bid_ask_spread_bps=float(last_row["bid_ask_spread_bps_far"]),
                    gross_expected_convergence_inr_g_999=stats_res.expected_reversion_inr_g_999,
                    notional_grams=cfg.backtest.position_notional_grams,
                    costs_config=cfg.costs,
                )
            else:
                cost_res = None

            # Run chronological walk-forward backtest for pairs that pass G2 pairing eligibility
            bt_report: PairBacktestReport | None = None
            if pair_elig.eligible and len(aligned_hist) >= cfg.backtest.min_bars_for_backtest:
                bt_report = run_pair_walk_forward_backtest(
                    run_id=run_id,
                    aligned_df=aligned_hist,
                    pair_id=pair_id,
                    config=cfg,
                    registry=registry,
                    dataset_hash=ing_manifest.sha256_hash,
                    is_synthetic=val_report.is_synthetic_dataset,
                )
                backtest_reports.append(bt_report)

            ev_sufficient = True
            ev_reasons = [ReasonCode.EVIDENCE_SUFFICIENT]
            if bt_report is not None and bt_report.evidence_status == ReasonCode.INSUFFICIENT_EVIDENCE:
                ev_sufficient = False
                ev_reasons = [ReasonCode.INSUFFICIENT_EVIDENCE]

            dec = evaluate_decision_gates(
                run_id=run_id,
                timestamp=pd.Timestamp(latest_ts).to_pydatetime(),
                pair_id=pair_id,
                config=cfg,
                dataset_hash=ing_manifest.sha256_hash,
                is_synthetic=val_report.is_synthetic_dataset,
                g0_data_valid=True,
                g0_reasons=[ReasonCode.VALID_OK],
                g1_spec_valid=True,
                g1_reasons=[ReasonCode.VALID_OK],
                pairing_result=pair_elig,
                liquidity_result=liq_res,
                stats_result=stats_res,
                cost_result=cost_res,
                evidence_sufficient=ev_sufficient,
                evidence_reasons=ev_reasons,
            )
            snapshot_decisions.append(dec)

    # Save decisions & backtest summaries to DuckDB
    storage.save_quarantined_rows(run_id, val_report.quarantined_records)
    storage.save_decisions(snapshot_decisions)
    storage.save_backtest_reports(backtest_reports)

    eval_start = str(norm_df["timestamp"].min().isoformat()) if not norm_df.empty else None
    eval_end = str(norm_df["timestamp"].max().isoformat()) if not norm_df.empty else None
    trade_signals = sum(1 for d in snapshot_decisions if d.state == DecisionState.TRADE_SIGNAL)

    warnings_list: list[str] = []
    if val_report.is_synthetic_dataset:
        warnings_list.append("Dataset contains SYNTHETIC_DEMO observations; not actual MCX market data.")
    if val_report.quarantined_rows > 0:
        warnings_list.append(f"{val_report.quarantined_rows} invalid rows were quarantined during Gate G0/G1.")

    prelim_manifest = RunManifest(
        run_id=run_id,
        created_at_utc=datetime.now(UTC),
        software_version=__version__,
        methodology_version=__methodology_version__,
        dataset_source_path=ing_manifest.source_path,
        dataset_sha256=ing_manifest.sha256_hash,
        config_version=cfg.config_version,
        config_sha256=cfg_hash,
        is_synthetic_data=val_report.is_synthetic_dataset,
        evaluation_period_start=eval_start,
        evaluation_period_end=eval_end,
        raw_observation_count=val_report.total_rows,
        valid_observation_count=val_report.valid_rows,
        quarantined_observation_count=val_report.quarantined_rows,
        evaluated_pair_count=len(snapshot_decisions),
        decision_count=len(snapshot_decisions),
        trade_signal_count=trade_signals,
        warnings=warnings_list,
        output_artifact_hashes=artifact_hashes,
    )

    json_rep_path, md_rep_path = write_research_reports(
        output_dir=out_dir,
        manifest=prelim_manifest,
        validation_report=val_report,
        backtest_reports=backtest_reports,
        snapshot_decisions=snapshot_decisions,
    )
    artifact_hashes["research_report.json"] = compute_file_sha256(json_rep_path)
    artifact_hashes["research_report.md"] = compute_file_sha256(md_rep_path)
    html_rep_path = out_dir / "research_report.html"
    csv_dec_path = out_dir / "decisions_export.csv"
    if html_rep_path.exists():
        artifact_hashes["research_report.html"] = compute_file_sha256(html_rep_path)
    if csv_dec_path.exists():
        artifact_hashes["decisions_export.csv"] = compute_file_sha256(csv_dec_path)

    final_manifest = prelim_manifest.model_copy(update={"output_artifact_hashes": artifact_hashes}).with_sealed_digest()
    manifest_path = out_dir / "run_manifest.json"
    sealed_manifest = save_run_manifest(final_manifest, manifest_path)
    storage.save_run_manifest_record(sealed_manifest)

    return ResearchPipelineResult(
        run_id=run_id,
        manifest=sealed_manifest,
        validation_report=val_report,
        snapshot_decisions=snapshot_decisions,
        backtest_reports=backtest_reports,
        manifest_path=str(manifest_path),
        json_report_path=str(json_rep_path),
        markdown_report_path=str(md_rep_path),
        duckdb_path=str(db_file),
    )
