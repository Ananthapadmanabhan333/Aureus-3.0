#!/usr/bin/env python3
"""Launch the AUREUS-RV 3.0 Streamlit Institutional Dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aureus_rv.dashboard.app import main

if __name__ == "__main__":
    main()
