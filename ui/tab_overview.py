"""ui/tab_overview.py

Phase 18 — Overview dashboard tab.

A read-only landing page showing headline KPIs and mini trend charts across all
active simulation modules.  Data is pulled from session state — each section
shows a gentle prompt if the relevant tab has not yet been run.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def _hex_to_rgba(hex_colour: str, alpha: float) -> str:
    """Convert a 6-char hex colour to an rgba() string Plotly accepts."""
    h = hex_colour.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ── Colour palette (matches global CSS) ───────────────────────────────────────
_INDIGO   = "#6366F1"
_INDIGO_L = "#818CF8"
_GREEN    = "#22C55E"
_RED      = "#EF4444"
_AMBER    = "#F59E0B"
_MUTED    = "#A1A1AA"
_BG2      = "#18181B"
_BORDER   = "#3F3F46"
_TEXT     = "#FAFAFA"

_CHART_BG   = "rgba(0,0,0,0)"
_GRID_COLOR = "#27272A"


# ── Mini chart helpers ────────────────────────────────────────────────────────

def _base_fig(height: int = 180) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor=_CHART_BG,
        plot_bgcolor=_CHART_BG,
        margin=dict(l=8, r=8, t=28, b=8),
        height=height,
        font=dict(family="Inter, system-ui, sans-serif", size=11, color=_MUTED),
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showline=False, tickfont=dict(size=10)),
        yaxis=dict(
            showgrid=True,
            gridcolor=_GRID_COLOR,
            zeroline=False,
            showline=False,
            tickfont=dict(size=10),
        ),
    )
    return fig


def _sparkline(x, y, colour: str, title: str, yformat: str = "") -> go.Figure:
    fig = _base_fig(height=160)
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines",
        line=dict(color=colour, width=2),
        fill="tozeroy",
        fillcolor=_hex_to_rgba(colour, 0.12),
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color=_MUTED), x=0, pad=dict(l=4)),
        yaxis=dict(tickformat=yformat, showgrid=True, gridcolor=_GRID_COLOR),
    )
    return fig


# ── Section renderers ─────────────────────────────────────────────────────────

def _status_badge(ready: bool) -> str:
    return "🟢" if ready else "⚪"


def _render_demand_section(df_erlang: pd.DataFrame) -> None:
    st.markdown("#### Demand & Staffing")
    cols = st.columns(4)

    total_calls = int(df_erlang["calls_offered"].sum()) if "calls_offered" in df_erlang.columns else None
    peak_req    = int(df_erlang["agents_required"].max()) if "agents_required" in df_erlang.columns else None

    avg_sl  = None
    avg_occ = None
    if "erlang_sl_pct" in df_erlang.columns:
        avg_sl = df_erlang["erlang_sl_pct"].mean()
    if "erlang_occupancy" in df_erlang.columns:
        avg_occ = df_erlang["erlang_occupancy"].mean()

    with cols[0]:
        st.metric("Total calls", f"{total_calls:,}" if total_calls is not None else "—")
    with cols[1]:
        st.metric("Peak agents required", f"{peak_req:,}" if peak_req is not None else "—")
    with cols[2]:
        st.metric("Avg SL % (Erlang C)", f"{avg_sl:.1%}" if avg_sl is not None else "—")
    with cols[3]:
        st.metric("Avg occupancy %", f"{avg_occ:.1%}" if avg_occ is not None else "—")


def _render_roster_section(roster_df: Optional[pd.DataFrame], df_erlang: pd.DataFrame) -> None:
    st.markdown("#### Roster & Coverage")

    if roster_df is None or roster_df.empty:
        st.caption("Run the Roster tab to populate roster metrics.")
        return

    cols = st.columns(4)
    peak_roster = int(roster_df["roster_net_agents"].max()) if "roster_net_agents" in roster_df.columns else None

    # Coverage ratio vs Erlang requirement
    coverage = None
    if peak_roster is not None and "agents_required" in df_erlang.columns:
        peak_req = df_erlang["agents_required"].max()
        if peak_req > 0:
            coverage = peak_roster / peak_req

    # Under-staffed intervals
    understaffed_pct = None
    if "roster_net_agents" in roster_df.columns and "agents_required" in df_erlang.columns:
        n_intervals = len(roster_df)
        if n_intervals > 0:
            erlang_req = df_erlang["agents_required"].values[:n_intervals]
            roster_net = roster_df["roster_net_agents"].values[:n_intervals]
            understaffed_pct = (roster_net < erlang_req).mean()

    paid_hours = roster_df.attrs.get("roster_paid_hours_total", None)

    with cols[0]:
        st.metric("Peak roster (net)", f"{peak_roster:,}" if peak_roster is not None else "—")
    with cols[1]:
        st.metric("Coverage vs requirement", f"{coverage:.0%}" if coverage is not None else "—")
    with cols[2]:
        st.metric("Under-staffed intervals", f"{understaffed_pct:.1%}" if understaffed_pct is not None else "—")
    with cols[3]:
        st.metric("Total paid hours", f"{paid_hours:.1f}h" if paid_hours is not None else "—")


def _render_simulation_section() -> None:
    st.markdown("#### Simulation")

    des_daily = st.session_state.get("des_daily_summary", pd.DataFrame())

    if not isinstance(des_daily, pd.DataFrame) or des_daily.empty:
        st.caption("Run a simulation in the Simulation tab to populate DES metrics.")
        return

    cols = st.columns(4)
    sim_sl      = des_daily["service_level_pct"].mean()    if "service_level_pct" in des_daily.columns else None
    sim_aband   = des_daily["abandon_rate"].mean()         if "abandon_rate" in des_daily.columns else None
    sim_util    = des_daily["avg_utilisation"].mean()      if "avg_utilisation" in des_daily.columns else None
    sim_calls   = des_daily["calls_handled"].sum()         if "calls_handled" in des_daily.columns else None

    with cols[0]:
        st.metric("Simulated SL %", f"{sim_sl:.1%}" if sim_sl is not None else "—")
    with cols[1]:
        st.metric("Abandon rate", f"{sim_aband:.1%}" if sim_aband is not None else "—")
    with cols[2]:
        st.metric("Avg agent utilisation", f"{sim_util:.1%}" if sim_util is not None else "—")
    with cols[3]:
        st.metric("Calls handled", f"{int(sim_calls):,}" if sim_calls is not None else "—")


def _render_cost_section() -> None:
    st.markdown("#### Cost")

    cost_df = st.session_state.get("cost_interval_df", pd.DataFrame())

    if not isinstance(cost_df, pd.DataFrame) or cost_df.empty:
        st.caption("Run the Cost tab to populate financial metrics.")
        return

    cols = st.columns(4)

    total_labour = cost_df["labour_cost"].sum()  if "labour_cost" in cost_df.columns else None
    total_idle   = cost_df["idle_cost"].sum()    if "idle_cost"   in cost_df.columns else None
    total_breach = cost_df["breach_cost"].sum()  if "breach_cost" in cost_df.columns else None

    total_all = (
        (total_labour or 0) + (total_idle or 0) + (total_breach or 0)
        if any(v is not None for v in [total_labour, total_idle, total_breach])
        else None
    )

    calls = cost_df["calls_offered"].sum() if "calls_offered" in cost_df.columns else None
    cpc   = (total_all / calls) if (total_all and calls and calls > 0) else None

    with cols[0]:
        st.metric("Total labour cost", f"${total_labour:,.0f}" if total_labour is not None else "—")
    with cols[1]:
        st.metric("Idle cost", f"${total_idle:,.0f}" if total_idle is not None else "—")
    with cols[2]:
        st.metric("SLA breach cost", f"${total_breach:,.0f}" if total_breach is not None else "—")
    with cols[3]:
        st.metric("Cost per call", f"${cpc:.4f}" if cpc is not None else "—")


def _render_planning_section() -> None:
    st.markdown("#### Workforce Planning")

    plan_df = st.session_state.get("planning_projection", pd.DataFrame())
    opt_df  = st.session_state.get("optimisation_result", pd.DataFrame())

    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        st.caption("Run the Planning tab to populate workforce metrics.")
        return

    cols = st.columns(4)

    opening_hc = int(plan_df["opening_hc"].iloc[0])  if "opening_hc" in plan_df.columns else None
    closing_hc = int(plan_df["closing_hc"].iloc[-1]) if "closing_hc" in plan_df.columns else None
    deficit_mo = int((plan_df["capacity_gap"] < 0).sum()) if "capacity_gap" in plan_df.columns else None
    total_hires = None
    if isinstance(opt_df, pd.DataFrame) and not opt_df.empty and "hires" in opt_df.columns:
        total_hires = int(opt_df["hires"].sum())

    with cols[0]:
        st.metric("Opening headcount", f"{opening_hc:,}" if opening_hc is not None else "—")
    with cols[1]:
        st.metric("Closing headcount", f"{closing_hc:,}" if closing_hc is not None else "—")
    with cols[2]:
        st.metric("Months in deficit", str(deficit_mo) if deficit_mo is not None else "—")
    with cols[3]:
        st.metric("Total hires (optimised)", f"{total_hires:,}" if total_hires is not None else "—")


# ── Trend charts ─────────────────────────────────────────────────────────────

def _render_trend_charts(df_erlang: pd.DataFrame) -> None:
    st.markdown("#### Interval trends")

    has_sl  = "erlang_sl_pct" in df_erlang.columns
    has_occ = "erlang_occupancy" in df_erlang.columns
    has_req = "agents_required" in df_erlang.columns

    cost_df = st.session_state.get("cost_interval_df", pd.DataFrame())
    has_cost = isinstance(cost_df, pd.DataFrame) and not cost_df.empty and "labour_cost" in cost_df.columns

    # Build x axis — prefer labels, fall back to integer index
    if "start_ts_local" in df_erlang.columns and df_erlang["start_ts_local"].notna().any():
        x = df_erlang["start_ts_local"].dt.strftime("%H:%M").tolist()
    else:
        x = df_erlang["interval"].tolist()

    n_charts = sum([has_req, has_sl, has_cost])
    if n_charts == 0:
        st.caption("No interval data available for charts.")
        return

    chart_cols = st.columns(max(n_charts, 1))
    col_idx = 0

    if has_req:
        with chart_cols[col_idx]:
            fig = _sparkline(x, df_erlang["agents_required"], _INDIGO, "Agents required", ",.0f")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        col_idx += 1

    if has_sl:
        with chart_cols[col_idx]:
            fig = _sparkline(x, df_erlang["erlang_sl_pct"], _GREEN, "SL % (Erlang C)", ".0%")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        col_idx += 1

    if has_cost:
        with chart_cols[col_idx]:
            # Aggregate by interval if multi-day
            if "interval_in_day" in cost_df.columns:
                cost_agg = cost_df.groupby("interval_in_day")["labour_cost"].sum().reset_index()
                cx = cost_agg["interval_in_day"].tolist()
                cy = cost_agg["labour_cost"].tolist()
            else:
                cx = cost_df.index.tolist()
                cy = cost_df["labour_cost"].tolist()
            fig = _sparkline(cx, cy, _AMBER, "Labour cost by interval", ",.0f")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Module status strip ───────────────────────────────────────────────────────

def _render_status_strip() -> None:
    des_ready  = not st.session_state.get("des_daily_summary", pd.DataFrame()).empty
    cost_ready = not st.session_state.get("cost_interval_df", pd.DataFrame()).empty
    plan_ready = not st.session_state.get("planning_projection", pd.DataFrame()).empty
    opt_ready  = not st.session_state.get("optimisation_result", pd.DataFrame()).empty
    fore_ready = st.session_state.get("forecast_demand_df") is not None

    items = [
        ("Demand", True),
        ("Roster", True),
        ("Simulation", des_ready),
        ("Forecast", fore_ready),
        ("Planning", plan_ready),
        ("Optimisation", opt_ready),
        ("Cost", cost_ready),
    ]

    parts = "  ·  ".join(
        f"{_status_badge(ready)} {name}" for name, ready in items
    )
    st.caption(f"Module status:   {parts}")


# ── Public entry point ────────────────────────────────────────────────────────

def render_overview_tab(
    df_inputs: pd.DataFrame,
    df_erlang: pd.DataFrame,
    roster_df: Optional[pd.DataFrame] = None,
) -> None:
    """Render the Overview dashboard tab."""

    st.subheader("Overview")
    st.caption("Live snapshot across all simulation modules. Open a tab to generate its data.")

    _render_status_strip()

    st.divider()
    _render_demand_section(df_erlang)

    st.divider()
    _render_roster_section(roster_df, df_erlang)

    st.divider()
    _render_simulation_section()

    st.divider()
    _render_cost_section()

    st.divider()
    _render_planning_section()

    st.divider()
    _render_trend_charts(df_erlang)
