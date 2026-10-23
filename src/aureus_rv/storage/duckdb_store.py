"""DuckDB persistence for research metadata, decisions, backtest summaries, and Parquet time-series artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from aureus_rv.backtesting.engine import PairBacktestReport
from aureus_rv.evidence.manifest import RunManifest
from aureus_rv.ingestion.loader import compute_file_sha256
from aureus_rv.models import DecisionRecord, QuarantinedRow


class AureusStorage:
    """Unified DuckDB and Parquet storage layer for AUREUS-RV 3.0."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path))

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS research_runs (
                    run_id VARCHAR PRIMARY KEY,
                    created_at_utc VARCHAR,
                    software_version VARCHAR,
                    methodology_version VARCHAR,
                    dataset_source_path VARCHAR,
                    dataset_sha256 VARCHAR,
                    config_version VARCHAR,
                    config_sha256 VARCHAR,
                    is_synthetic_data BOOLEAN,
                    raw_observation_count INTEGER,
                    valid_observation_count INTEGER,
                    quarantined_observation_count INTEGER,
                    evaluated_pair_count INTEGER,
                    decision_count INTEGER,
                    trade_signal_count INTEGER,
                    manifest_json VARCHAR,
                    manifest_self_sha256 VARCHAR
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id VARCHAR PRIMARY KEY,
                    run_id VARCHAR,
                    timestamp VARCHAR,
                    pair_id VARCHAR,
                    near_contract VARCHAR,
                    far_contract VARCHAR,
                    state VARCHAR,
                    direction VARCHAR,
                    primary_reason_code VARCHAR,
                    cost_scenario VARCHAR,
                    config_hash VARCHAR,
                    dataset_hash VARCHAR,
                    is_synthetic BOOLEAN,
                    z_score DOUBLE,
                    spread_bps DOUBLE,
                    net_expected_bps DOUBLE,
                    decision_json VARCHAR
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_summaries (
                    run_id VARCHAR,
                    pair_id VARCHAR,
                    cost_scenario VARCHAR,
                    evidence_status VARCHAR,
                    total_aligned_bars INTEGER,
                    total_completed_trades INTEGER,
                    gross_pnl_inr DOUBLE,
                    total_costs_inr DOUBLE,
                    net_pnl_inr DOUBLE,
                    max_drawdown_inr DOUBLE,
                    baseline_naive_net_pnl_inr DOUBLE,
                    report_json VARCHAR,
                    PRIMARY KEY (run_id, pair_id, cost_scenario)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS quarantined_rows (
                    run_id VARCHAR,
                    row_index INTEGER,
                    reason_codes VARCHAR,
                    explanation VARCHAR,
                    raw_payload_json VARCHAR
                );
                """
            )

    def save_run_manifest_record(self, manifest: RunManifest) -> None:
        """Upsert a sealed RunManifest into DuckDB `research_runs`."""
        sealed = manifest.with_sealed_digest()
        with self._connect() as con:
            con.execute("DELETE FROM research_runs WHERE run_id = ?", [sealed.run_id])
            con.execute(
                """
                INSERT INTO research_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    sealed.run_id,
                    sealed.created_at_utc.isoformat(),
                    sealed.software_version,
                    sealed.methodology_version,
                    sealed.dataset_source_path,
                    sealed.dataset_sha256,
                    sealed.config_version,
                    sealed.config_sha256,
                    sealed.is_synthetic_data,
                    sealed.raw_observation_count,
                    sealed.valid_observation_count,
                    sealed.quarantined_observation_count,
                    sealed.evaluated_pair_count,
                    sealed.decision_count,
                    sealed.trade_signal_count,
                    json.dumps(sealed.model_dump(mode="json"), sort_keys=True),
                    sealed.manifest_self_sha256,
                ],
            )

    def save_decisions(self, decisions: list[DecisionRecord]) -> None:
        """Persist DecisionRecord list into DuckDB `decisions`."""
        if not decisions:
            return
        rows = [
            (
                d.decision_id,
                d.run_id,
                d.timestamp.isoformat(),
                d.pair_id,
                d.near_contract,
                d.far_contract,
                d.state.value,
                d.direction.value,
                d.primary_reason_code.value,
                d.cost_scenario.value,
                d.config_hash,
                d.dataset_hash,
                d.is_synthetic,
                float(d.metrics["z_score"]) if d.metrics.get("z_score") is not None else None,
                float(d.metrics["spread_bps"]) if d.metrics.get("spread_bps") is not None else None,
                float(d.metrics["net_expected_bps"]) if d.metrics.get("net_expected_bps") is not None else None,
                json.dumps(d.model_dump(mode="json"), sort_keys=True),
            )
            for d in decisions
        ]
        with self._connect() as con:
            for r in rows:
                con.execute("DELETE FROM decisions WHERE decision_id = ?", [r[0]])
            con.executemany(
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def save_backtest_reports(self, reports: list[PairBacktestReport]) -> None:
        """Persist PairBacktestReport list into DuckDB `backtest_summaries`."""
        if not reports:
            return
        with self._connect() as con:
            for rep in reports:
                con.execute(
                    "DELETE FROM backtest_summaries WHERE run_id = ? AND pair_id = ? AND cost_scenario = ?",
                    [rep.run_id, rep.pair_id, rep.cost_scenario.value],
                )
                con.execute(
                    "INSERT INTO backtest_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        rep.run_id,
                        rep.pair_id,
                        rep.cost_scenario.value,
                        rep.evidence_status.value,
                        rep.total_aligned_bars,
                        rep.total_completed_trades,
                        rep.gross_pnl_inr,
                        rep.total_costs_inr,
                        rep.net_pnl_inr,
                        rep.max_drawdown_inr,
                        rep.baseline_naive_net_pnl_inr,
                        json.dumps(rep.model_dump(mode="json"), sort_keys=True),
                    ],
                )

    def save_quarantined_rows(self, run_id: str, quarantined: list[QuarantinedRow]) -> None:
        """Persist quarantined records into DuckDB `quarantined_rows`."""
        with self._connect() as con:
            con.execute("DELETE FROM quarantined_rows WHERE run_id = ?", [run_id])
            if not quarantined:
                return
            rows = [
                (
                    run_id,
                    q.row_index,
                    ",".join(r.value for r in q.reason_codes),
                    q.explanation,
                    json.dumps(q.raw_payload, sort_keys=True),
                )
                for q in quarantined
            ]
            con.executemany("INSERT INTO quarantined_rows VALUES (?, ?, ?, ?, ?)", rows)

    def query_decisions_df(self, run_id: str | None = None) -> pd.DataFrame:
        """Query stored decisions as a DataFrame (for CLI and Prompt 2 frontend integration)."""
        with self._connect() as con:
            if run_id:
                return con.execute("SELECT * FROM decisions WHERE run_id = ? ORDER BY timestamp, pair_id", [run_id]).df()
            return con.execute("SELECT * FROM decisions ORDER BY timestamp, pair_id").df()

    def query_runs_df(self) -> pd.DataFrame:
        """Query stored research runs as a DataFrame."""
        with self._connect() as con:
            return con.execute("SELECT * FROM research_runs ORDER BY created_at_utc DESC").df()

    def query_backtest_summaries_df(self, run_id: str | None = None) -> pd.DataFrame:
        """Query stored backtest summaries as a DataFrame."""
        with self._connect() as con:
            if run_id:
                return con.execute("SELECT * FROM backtest_summaries WHERE run_id = ? ORDER BY pair_id", [run_id]).df()
            return con.execute("SELECT * FROM backtest_summaries ORDER BY pair_id").df()

    @staticmethod
    def write_parquet_artifact(df: pd.DataFrame, path: str | Path) -> str:
        """Write a DataFrame to Parquet and return its SHA-256 hex digest."""
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)
        return compute_file_sha256(out_path)

    def get_run_detail(self, run_id: str) -> dict[str, Any] | None:
        """Retrieve parsed manifest JSON for `run_id`."""
        with self._connect() as con:
            res = con.execute("SELECT manifest_json FROM research_runs WHERE run_id = ?", [run_id]).fetchone()
            if not res:
                return None
            return json.loads(res[0])
