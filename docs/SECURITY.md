# AUREUS-RV 3.0 — Security, Data Integrity & Operational Boundaries

## 1. No Live Execution or Credential Exposure

- AUREUS-RV 3.0 is strictly a **quantitative research and validation instrument**. It contains no order-routing, broker API keys, or automated trade execution hooks.
- `.env` is excluded via `.gitignore`; only `.env.example` with non-sensitive local paths is tracked.

## 2. Safe Dataset Upload Handling

When a researcher or judge uploads a `.csv` or `.parquet` file via Page G (`Data Management`):
1. **Extension Whitelist:** Only `.csv`, `.parquet`, and `.pq` extensions are accepted (`ALLOWED_UPLOAD_EXTENSIONS`).
2. **File Size Cap:** Uploads exceeding `25 MB` (`MAX_UPLOAD_BYTES`) or empty `0-byte` payloads are immediately rejected before parsing.
3. **Path Traversal Prevention:** File names are sanitized via `Path(filename).name` and prefixed with their SHA-256 hash (`upload_{sha256[:10]}_{safe_name}`).
4. **Never Executed:** Uploaded files are parsed exclusively as tabular data via `pandas.read_csv` or `pandas.read_parquet` and passed through `validate_dataset()`. Uploaded content is never executed as code.

## 3. Cryptographic Integrity Scope

- Every research run produces a `run_manifest.json` containing the SHA-256 digests of the input dataset, the canonical JSON configuration, all output Parquet/JSON/Markdown/HTML/CSV artifacts, and a self-sealing `manifest_self_sha256`.
- `verify_run_manifest()` recomputes every digest on disk and fails closed if any artifact or manifest field has been modified post-run.
- **Honest Scope Statement:** SHA-256 hashes prove computational reproducibility and artifact immutability; they do **not** prove that an external CSV/Parquet file originated from an authentic live MCX exchange feed.
