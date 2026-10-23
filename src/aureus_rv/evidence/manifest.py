"""SHA-256 evidence manifests, artifact hashing, and integrity verification for AUREUS-RV 3.0.

Explicitly states that cryptographic SHA-256 digests verify artifact immutability and
computational reproducibility, NOT market-data authenticity.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from aureus_rv import __methodology_version__, __version__
from aureus_rv.ingestion.loader import compute_file_sha256


class RunManifest(BaseModel):
    """Cryptographically verifiable manifest of a complete AUREUS-RV 3.0 research run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    created_at_utc: datetime
    software_version: str = Field(default=__version__)
    methodology_version: str = Field(default=__methodology_version__)
    dataset_source_path: str
    dataset_sha256: str
    config_version: str
    config_sha256: str
    is_synthetic_data: bool
    evaluation_period_start: str | None
    evaluation_period_end: str | None
    raw_observation_count: int
    valid_observation_count: int
    quarantined_observation_count: int
    evaluated_pair_count: int
    decision_count: int
    trade_signal_count: int
    warnings: list[str] = Field(default_factory=list)
    output_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    integrity_scope_disclaimer: str = Field(
        default=(
            "SHA-256 hashes verify computational reproducibility and artifact immutability only; "
            "they do NOT prove exchange market-data authenticity."
        )
    )
    manifest_self_sha256: str = Field(default="")

    def compute_canonical_digest(self) -> str:
        """Compute deterministic SHA-256 digest of the manifest fields (excluding `manifest_self_sha256`)."""
        payload = self.model_dump(mode="json", exclude={"manifest_self_sha256"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def with_sealed_digest(self) -> RunManifest:
        """Return a new RunManifest instance with `manifest_self_sha256` populated."""
        digest = self.compute_canonical_digest()
        return self.model_copy(update={"manifest_self_sha256": digest})


def save_run_manifest(manifest: RunManifest, output_path: str | Path) -> RunManifest:
    """Seal and write a RunManifest to disk as formatted JSON."""
    sealed = manifest.with_sealed_digest()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sealed.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return sealed


def verify_run_manifest(manifest_path: str | Path, base_dir: str | Path | None = None) -> tuple[bool, list[str]]:
    """Verify both the manifest self-digest and every referenced output artifact SHA-256 on disk."""
    path = Path(manifest_path)
    if not path.exists():
        return False, [f"Manifest file does not exist: {path}"]

    raw = json.loads(path.read_text(encoding="utf-8"))
    manifest = RunManifest.model_validate(raw)
    errors: list[str] = []

    expected_self = manifest.compute_canonical_digest()
    if manifest.manifest_self_sha256 != expected_self:
        errors.append(
            f"Manifest self-hash mismatch: recorded={manifest.manifest_self_sha256}, computed={expected_self}"
        )

    root = Path(base_dir) if base_dir is not None else path.parent
    for rel_name, recorded_hash in manifest.output_artifact_hashes.items():
        artifact_path = Path(rel_name) if Path(rel_name).is_absolute() else (root / rel_name)
        if not artifact_path.exists():
            errors.append(f"Referenced output artifact missing: {artifact_path}")
            continue
        actual_hash = compute_file_sha256(artifact_path)
        if actual_hash != recorded_hash:
            errors.append(
                f"Artifact hash mismatch for '{rel_name}': recorded={recorded_hash}, actual={actual_hash}"
            )

    return len(errors) == 0, errors
