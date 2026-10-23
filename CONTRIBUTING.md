# Contributing to AUREUS-RV 3.0

## Development Workflow

1. **Install Dependencies (Python 3.11+ with `uv`):**
   ```bash
   uv sync --python 3.11
   ```
2. **Code Style & Linting:**
   All code under `src/`, `tests/`, and `scripts/` must pass Ruff with zero warnings:
   ```bash
   uv run ruff check src tests scripts
   ```
3. **Automated Testing:**
   Every new feature or bugfix must include unit, integration, or regression tests:
   ```bash
   uv run pytest -v
   ```
4. **Core Engineering Rules:**
   - Never silently impute missing market data; quarantine invalid rows with an explicit `ReasonCode`.
   - Keep normalized unit prices (`INR/g @ 999`) separate from contract lot sizes and multipliers.
   - Ensure all historical calculations filter `timestamp <= decision_timestamp`.
   - Never hardcode frontend metrics or bypass backend gates.
