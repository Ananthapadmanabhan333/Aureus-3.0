#!/usr/bin/env python3
"""Execute the full AUREUS-RV 3.0 quantitative research workflow."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aureus_rv.cli import main_research

if __name__ == "__main__":
    raise SystemExit(main_research())
