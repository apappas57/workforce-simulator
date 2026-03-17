"""ui/charts.py

Shared chart utilities for the Workforce Simulator.

Single source of truth for:
  - Dark theme constants (background, grid, font)
  - Standard colour palette
  - apply_dark_theme(fig) — apply to any Plotly figure
  - px_line / px_bar / px_area helpers that bake in the theme

Usage
-----
from ui.charts import apply_dark_theme, PALETTE, px_line, px_bar

# Existing go.Figure:
fig = go.Figure(...)
fig.update_layout(...)
apply_dark_theme(fig)

# New px figure:
fig = px_line(df, x="interval", y="calls_offered", title="Calls offered")
"""

from __future__ import annotations

from typing import Optional

import plotly.express as px
import plotly.graph_objects as go


# ── Palette ───────────────────────────────────────────────────────────────────
# Primary → secondary → accent shades matching the zinc/indigo CSS theme
PALETTE = [
    "#6366F1",  # indigo
    "#22C55E",  # green
    "#F59E0B",  # amber
    "#EC4899",  # pink
    "#06B6D4",  # cyan
    "#EF4444",  # red
    "#818CF8",  # indigo-light
    "#4ADE80",  # green-light
]

# Semantic aliases used across tabs
C_REQUIREMENT = "#EF4444"   # red  — Erlang / requirement lines
C_ROSTER      = "#6366F1"   # indigo — roster net agents
C_SIMULATION  = "#22C55E"   # green  — simulated / DES output
C_FORECAST    = "#F59E0B"   # amber  — forecast lines
C_COST        = "#EC4899"   # pink   — cost traces

# ── Dark theme constants ──────────────────────────────────────────────────────
_PAPER_BG    = "rgba(0,0,0,0)"
_PLOT_BG     = "rgba(0,0,0,0)"
_GRID        = "#27272A"
_ZERO_LINE   = "#3F3F46"
_FONT_COLOUR = "#A1A1AA"
_TITLE_COLOUR = "#FAFAFA"
_FONT_FAMILY = "Inter, system-ui, -apple-system, sans-serif"
_LEGEND_BG   = "rgba(24,24,27,0.8)"   # bg2 semi-transparent


def apply_dark_theme(
    fig: go.Figure,
    *,
    height: Optional[int] = None,
    legend: bool = True,
    margin: Optional[dict] = None,
) -> go.Figure:
    """Apply the standard dark theme to *fig* in-place and return it.

    Parameters
    ----------
    fig:     Any Plotly Figure.
    height:  Optional fixed height in pixels.
    legend:  Whether to show and style the legend.
    margin:  Override default margin dict.
    """
    _margin = margin or dict(l=0, r=16, t=40, b=0)

    fig.update_layout(
        paper_bgcolor=_PAPER_BG,
        plot_bgcolor=_PLOT_BG,
        font=dict(family=_FONT_FAMILY, color=_FONT_COLOUR, size=11),
        title_font=dict(family=_FONT_FAMILY, color=_TITLE_COLOUR, size=13),
        margin=_margin,
        showlegend=legend,
        legend=dict(
            bgcolor=_LEGEND_BG,
            bordercolor=_GRID,
            borderwidth=1,
            font=dict(size=11, color=_FONT_COLOUR),
        ) if legend else {},
        **({"height": height} if height else {}),
    )
    fig.update_xaxes(
        gridcolor=_GRID,
        zerolinecolor=_ZERO_LINE,
        tickfont=dict(size=10, color=_FONT_COLOUR),
        title_font=dict(size=11, color=_FONT_COLOUR),
    )
    fig.update_yaxes(
        gridcolor=_GRID,
        zerolinecolor=_ZERO_LINE,
        tickfont=dict(size=10, color=_FONT_COLOUR),
        title_font=dict(size=11, color=_FONT_COLOUR),
    )
    return fig


# ── px wrappers ───────────────────────────────────────────────────────────────

def px_line(df, **kwargs) -> go.Figure:
    """px.line with the dark theme and standard palette applied."""
    kwargs.setdefault("color_discrete_sequence", PALETTE)
    fig = px.line(df, **kwargs)
    apply_dark_theme(fig)
    return fig


def px_bar(df, **kwargs) -> go.Figure:
    """px.bar with the dark theme and standard palette applied."""
    kwargs.setdefault("color_discrete_sequence", PALETTE)
    fig = px.bar(df, **kwargs)
    apply_dark_theme(fig)
    return fig


def px_area(df, **kwargs) -> go.Figure:
    """px.area with the dark theme and standard palette applied."""
    kwargs.setdefault("color_discrete_sequence", PALETTE)
    fig = px.area(df, **kwargs)
    apply_dark_theme(fig)
    return fig


# ── Operating hours shading ───────────────────────────────────────────────────

_INACTIVE_FILL = "rgba(9,9,11,0.55)"   # near-black zinc wash for off-hours bands


def add_operating_hours_vrect(
    fig: go.Figure,
    open_interval: int,
    close_interval: int,
    total_intervals: int,
) -> go.Figure:
    """Overlay dark bands on an interval-indexed chart to mark inactive hours.

    Bands are drawn *below* data traces (layer="below") so they don't obscure
    lines or bars.  Only applies when ``close_interval > open_interval``.

    Parameters
    ----------
    fig:             Plotly figure using a numeric interval x-axis.
    open_interval:   First active interval (inclusive).
    close_interval:  First inactive interval after close (exclusive).
    total_intervals: Total number of intervals (used to size the right band).
    """
    if close_interval <= open_interval:
        return fig

    # Pre-open band: [0, open_interval)
    if open_interval > 0:
        fig.add_vrect(
            x0=-0.5,
            x1=open_interval - 0.5,
            fillcolor=_INACTIVE_FILL,
            opacity=1.0,
            layer="below",
            line_width=0,
        )

    # Post-close band: [close_interval, total_intervals)
    if close_interval < total_intervals:
        fig.add_vrect(
            x0=close_interval - 0.5,
            x1=total_intervals - 0.5,
            fillcolor=_INACTIVE_FILL,
            opacity=1.0,
            layer="below",
            line_width=0,
        )

    return fig
