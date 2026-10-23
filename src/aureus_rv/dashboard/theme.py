"""Design tokens, institutional dark-charcoal/gold theme CSS, and Plotly styling for AUREUS-RV 3.0."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from aureus_rv.models import DecisionState

# Institutional Design Tokens
COLOR_BG_PRIMARY = "#0E1015"
COLOR_BG_PANEL = "#151922"
COLOR_BORDER = "#262B38"
COLOR_GOLD_PRIMARY = "#D4AF37"
COLOR_GOLD_MUTED = "#A6892B"
COLOR_TEXT_PRIMARY = "#F3F4F6"
COLOR_TEXT_SECONDARY = "#9CA3AF"
COLOR_SIGNAL = "#10B981"
COLOR_NO_EDGE = "#F59E0B"
COLOR_REJECTED = "#EF4444"
COLOR_QUIET = "#6B7280"
COLOR_BLUE_ACCENT = "#60A5FA"

STATE_COLOR_MAP: dict[str, str] = {
    DecisionState.TRADE_SIGNAL.value: COLOR_SIGNAL,
    DecisionState.NO_EDGE.value: COLOR_NO_EDGE,
    DecisionState.REJECTED.value: COLOR_REJECTED,
    DecisionState.QUIET.value: COLOR_QUIET,
}

INSTITUTIONAL_CSS = f"""
<style>
  .stApp {{
      background-color: {COLOR_BG_PRIMARY};
      color: {COLOR_TEXT_PRIMARY};
  }}
  [data-testid="stSidebar"] {{
      background-color: {COLOR_BG_PANEL};
      border-right: 1px solid {COLOR_BORDER};
  }}
  .aureus-header {{
      background-color: {COLOR_BG_PANEL};
      border: 1px solid {COLOR_BORDER};
      border-left: 4px solid {COLOR_GOLD_PRIMARY};
      padding: 16px 20px;
      border-radius: 6px;
      margin-bottom: 18px;
  }}
  .aureus-title {{
      color: {COLOR_GOLD_PRIMARY};
      font-size: 1.55rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      margin: 0;
  }}
  .aureus-subtitle {{
      color: {COLOR_TEXT_SECONDARY};
      font-size: 0.92rem;
      margin-top: 4px;
      margin-bottom: 0;
  }}
  .aureus-card {{
      background-color: {COLOR_BG_PANEL};
      border: 1px solid {COLOR_BORDER};
      border-radius: 6px;
      padding: 14px 16px;
      margin-bottom: 12px;
  }}
  .aureus-kpi-label {{
      color: {COLOR_TEXT_SECONDARY};
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 4px;
  }}
  .aureus-kpi-value {{
      color: {COLOR_TEXT_PRIMARY};
      font-size: 1.35rem;
      font-weight: 600;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .aureus-badge {{
      display: inline-block;
      padding: 3px 9px;
      border-radius: 4px;
      font-size: 0.76rem;
      font-weight: 600;
      letter-spacing: 0.03em;
  }}
  .badge-synth {{
      background-color: #3B2506;
      color: #FBBF24;
      border: 1px solid #D97706;
  }}
  .badge-verified {{
      background-color: #064E3B;
      color: #34D399;
      border: 1px solid #059669;
  }}
  .badge-signal {{
      background-color: rgba(16, 185, 129, 0.16);
      color: #34D399;
      border: 1px solid #10B981;
  }}
  .badge-noedge {{
      background-color: rgba(245, 158, 11, 0.16);
      color: #FBBF24;
      border: 1px solid #F59E0B;
  }}
  .badge-rejected {{
      background-color: rgba(239, 68, 68, 0.16);
      color: #F87171;
      border: 1px solid #EF4444;
  }}
  .badge-quiet {{
      background-color: rgba(107, 114, 128, 0.16);
      color: #D1D5DB;
      border: 1px solid #6B7280;
  }}
</style>
"""


def apply_plotly_institutional_theme(fig: go.Figure, title: str = "", height: int = 360) -> go.Figure:
    """Apply dark-charcoal institutional styling and restrained gold accents to a Plotly figure."""
    layout_kwargs: dict[str, Any] = {
        "template": "plotly_dark",
        "paper_bgcolor": COLOR_BG_PANEL,
        "plot_bgcolor": COLOR_BG_PRIMARY,
        "font": {"family": "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", "color": COLOR_TEXT_PRIMARY, "size": 12},
        "height": height,
        "margin": {"l": 48, "r": 24, "t": 44 if title else 24, "b": 40},
        "xaxis": {"gridcolor": "#1E2330", "zerolinecolor": "#262B38"},
        "yaxis": {"gridcolor": "#1E2330", "zerolinecolor": "#262B38"},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1.0},
    }
    if title:
        layout_kwargs["title"] = {"text": title, "font": {"color": COLOR_GOLD_PRIMARY, "size": 14}, "x": 0.01}
    fig.update_layout(**layout_kwargs)
    return fig


def format_state_badge_html(state_val: str) -> str:
    """Return HTML badge string for a DecisionState value."""
    css_cls = {
        DecisionState.TRADE_SIGNAL.value: "badge-signal",
        DecisionState.NO_EDGE.value: "badge-noedge",
        DecisionState.REJECTED.value: "badge-rejected",
        DecisionState.QUIET.value: "badge-quiet",
    }.get(state_val, "badge-quiet")
    return f"<span class='aureus-badge {css_cls}'>{state_val}</span>"
