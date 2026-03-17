"""ui/tab_cost.py

Cost Analytics tab — Phase 13.

Consumes CostConfig from the sidebar and the outputs of the Erlang C,
roster, DES, and planning engines to produce a financial view of the
simulation:

  • Per-interval labour, idle, and SLA breach cost
  • Cost-per-call trend
  • Idle / overstaffing breakdown
  • Monthly labour cost projection (if planning data is available)
"""

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from models.cost_model import (
    CostConfig,
    calculate_cost_summary,
    calculate_interval_costs,
    project_monthly_labour_cost,
)
from ui.date_view import apply_date_view, ensure_x_col, render_date_view_controls


# ---------------------------------------------------------------------------
# Colour constants (kept consistent with the rest of the app)
# ---------------------------------------------------------------------------
_NAVY   = "#1B2A4A"
_BLUE   = "#2C6FAC"
_RED    = "#E74C3C"
_AMBER  = "#E67E22"
_GREEN  = "#27AE60"
_LTBLUE = "#AED6F1"


def render_cost_tab(
    df_erlang: pd.DataFrame,
    cost_cfg: "CostConfig",
    cfg,
    roster_df: Optional[pd.DataFrame] = None,
) -> None:
    """Render the Cost Analytics tab.

    Parameters
    ----------
    df_erlang : pd.DataFrame
        Erlang C output from ``solve_staffing_erlang()``.
    cost_cfg : CostConfig
        Financial parameters built in ``app.py`` from sidebar inputs.
    cfg : SimConfig
        Simulation config — ``interval_minutes`` is used for cost calculations.
    roster_df : pd.DataFrame, optional
        Roster output.  When provided, actual rostered headcount drives labour
        cost.  Otherwise the Erlang net requirement is used as the basis.
    """
    st.header("Cost Analytics")

    des_daily = st.session_state.get("des_daily_summary",  pd.DataFrame())
    planning  = st.session_state.get("planning_projection", pd.DataFrame())

    # ------------------------------------------------------------------
    # Compute cost DataFrame
    # ------------------------------------------------------------------
    cost_df = calculate_interval_costs(
        df_erlang=df_erlang,
        cost_cfg=cost_cfg,
        interval_minutes=float(cfg.interval_minutes),
        roster_df=roster_df if isinstance(roster_df, pd.DataFrame) and not roster_df.empty else None,
        des_daily=des_daily if not des_daily.empty else None,
    )

    if cost_df.empty:
        st.warning("No Erlang data available — run the simulation before opening this tab.")
        return

    summary = calculate_cost_summary(cost_df)

    # Persist for PDF report and Downloads
    st.session_state["cost_interval_df"] = cost_df

    # ------------------------------------------------------------------
    # Top-line KPI metrics
    # ------------------------------------------------------------------
    st.subheader("Summary")

    basis_note = (
        "Staffing basis: **rostered headcount**"
        if isinstance(roster_df, pd.DataFrame) and not roster_df.empty
        else "Staffing basis: **Erlang C net requirement** (no roster loaded)"
    )
    abandon_note = (
        " · Abandoned calls: **DES simulation**"
        if not des_daily.empty
        else " · Abandoned calls: **Erlang SL proxy**"
    )
    st.caption(basis_note + abandon_note)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total labour cost",     f"${summary.get('total_labour_cost', 0):,.2f}")
    m2.metric("SLA breach cost",       f"${summary.get('total_sla_breach_cost', 0):,.2f}")
    m3.metric("Idle agent cost",       f"${summary.get('total_idle_cost', 0):,.2f}")
    m4.metric("Total cost",            f"${summary.get('total_cost', 0):,.2f}")
    m5.metric("Avg cost / call",       f"${summary.get('avg_cost_per_call', 0):,.4f}")
    m6.metric("Overstaffed intervals", f"{summary.get('overstaffed_intervals_pct', 0):.1f}%")

    st.divider()

    # ------------------------------------------------------------------
    # Date / interval view controls
    # ------------------------------------------------------------------
    has_dates = "date_local" in cost_df.columns and cost_df["date_local"].notna().any()

    if has_dates:
        view_mode, selected_day = render_date_view_controls(cost_df, key_prefix="cost")
        cost_view = apply_date_view(cost_df, view_mode, selected_day)
    else:
        cost_view = cost_df.copy()

    cost_view = ensure_x_col(cost_view, "x")

    # ------------------------------------------------------------------
    # Chart 1: Stacked cost breakdown per interval
    # ------------------------------------------------------------------
    st.subheader("Interval cost breakdown")

    fig_bar = go.Figure()
    x_vals = cost_view["x"].tolist()

    fig_bar.add_trace(go.Bar(
        name="Labour cost",
        x=x_vals,
        y=cost_view["labour_cost"].tolist(),
        marker_color=_BLUE,
        hovertemplate="Interval %{x}<br>Labour: $%{y:,.2f}<extra></extra>",
    ))
    fig_bar.add_trace(go.Bar(
        name="SLA breach cost",
        x=x_vals,
        y=cost_view["sla_breach_cost"].tolist(),
        marker_color=_RED,
        hovertemplate="Interval %{x}<br>Breach: $%{y:,.2f}<extra></extra>",
    ))

    fig_bar.update_layout(
        barmode="stack",
        xaxis_title="Interval",
        yaxis_title="Cost ($)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=320,
        margin=dict(t=10, b=40),
        plot_bgcolor="white",
        yaxis=dict(gridcolor="#F0F0F0"),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # ------------------------------------------------------------------
    # Chart 2: Cost per call + agent requirement dual-axis
    # ------------------------------------------------------------------
    st.subheader("Cost per call vs agent requirement")

    fig_cpc = go.Figure()
    fig_cpc.add_trace(go.Scatter(
        name="Cost / call ($)",
        x=x_vals,
        y=cost_view["cost_per_call"].tolist(),
        mode="lines",
        line=dict(color=_NAVY, width=1.8),
        hovertemplate="Interval %{x}<br>$%{y:,.4f} / call<extra></extra>",
    ))
    fig_cpc.add_trace(go.Scatter(
        name="Agents rostered",
        x=x_vals,
        y=cost_view["agents_rostered"].tolist(),
        mode="lines",
        line=dict(color=_LTBLUE, width=1.5, dash="dot"),
        yaxis="y2",
        hovertemplate="Interval %{x}<br>%{y:.0f} agents<extra></extra>",
    ))

    fig_cpc.update_layout(
        xaxis_title="Interval",
        yaxis=dict(title="Cost / call ($)", side="left",  gridcolor="#F0F0F0"),
        yaxis2=dict(title="Agents", side="right", overlaying="y", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=280,
        margin=dict(t=10, b=40),
        plot_bgcolor="white",
    )
    st.plotly_chart(fig_cpc, use_container_width=True)

    # ------------------------------------------------------------------
    # Chart 3: Idle cost & overstaffing detail
    # ------------------------------------------------------------------
    with st.expander("Idle agent cost & overstaffing detail"):
        idle_pct = summary.get("idle_cost_pct", 0.0)
        over_pct = summary.get("overstaffed_intervals_pct", 0.0)
        under_pct = summary.get("understaffed_intervals_pct", 0.0)

        i1, i2, i3 = st.columns(3)
        i1.metric("Idle cost as % of labour", f"{idle_pct:.1f}%")
        i2.metric("Intervals overstaffed",    f"{over_pct:.1f}%")
        i3.metric("Intervals understaffed",   f"{under_pct:.1f}%")

        fig_idle = go.Figure()
        fig_idle.add_trace(go.Bar(
            name="Idle cost",
            x=x_vals,
            y=cost_view["idle_cost"].tolist(),
            marker_color=_AMBER,
            hovertemplate="Interval %{x}<br>Idle: $%{y:,.2f}<extra></extra>",
        ))
        fig_idle.add_trace(go.Scatter(
            name="Surplus agents",
            x=x_vals,
            y=cost_view["overstaffing"].tolist(),
            mode="lines",
            line=dict(color=_NAVY, width=1.5),
            yaxis="y2",
            hovertemplate="Interval %{x}<br>%{y:.1f} surplus<extra></extra>",
        ))
        fig_idle.update_layout(
            xaxis_title="Interval",
            yaxis=dict(title="Idle cost ($)", gridcolor="#F0F0F0"),
            yaxis2=dict(title="Surplus agents", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=260,
            margin=dict(t=10, b=40),
            plot_bgcolor="white",
        )
        st.plotly_chart(fig_idle, use_container_width=True)
        st.caption(
            f"Idle cost is **{idle_pct:.1f}%** of total labour cost. "
            "Tighter shift scheduling (Phase 15 — roster auto-optimisation) "
            "is the primary lever for reducing this."
        )

    # ------------------------------------------------------------------
    # Monthly cost projection
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("Monthly labour cost projection")

    if not planning.empty and "available_fte" in planning.columns:
        monthly_df = project_monthly_labour_cost(planning, cost_cfg)

        label_vals = (
            monthly_df["period_label"].tolist()
            if "period_label" in monthly_df.columns
            else [str(i) for i in monthly_df.index]
        )

        fig_m = go.Figure()

        if "monthly_labour_cost" in monthly_df.columns:
            fig_m.add_trace(go.Bar(
                name="Projected labour cost",
                x=label_vals,
                y=monthly_df["monthly_labour_cost"].tolist(),
                marker_color=_BLUE,
                hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>",
            ))

        if "monthly_required_cost" in monthly_df.columns:
            fig_m.add_trace(go.Scatter(
                name="Required cost (target FTE)",
                x=label_vals,
                y=monthly_df["monthly_required_cost"].tolist(),
                mode="lines+markers",
                line=dict(color=_AMBER, width=2, dash="dash"),
                hovertemplate="%{x}<br>$%{y:,.0f} required<extra></extra>",
            ))

        if "monthly_cost_gap" in monthly_df.columns:
            fig_m.add_trace(go.Scatter(
                name="Cost gap (+over / −under)",
                x=label_vals,
                y=monthly_df["monthly_cost_gap"].tolist(),
                mode="lines+markers",
                line=dict(color=_RED, width=1.5, dash="dot"),
                yaxis="y2",
                hovertemplate="%{x}<br>Gap: $%{y:,.0f}<extra></extra>",
            ))

        fig_m.update_layout(
            xaxis_title="Period",
            yaxis=dict(title="Labour cost ($)", gridcolor="#F0F0F0"),
            yaxis2=dict(title="Cost gap ($)", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=320,
            margin=dict(t=10, b=40),
            plot_bgcolor="white",
            barmode="group",
        )
        st.plotly_chart(fig_m, use_container_width=True)

        total_proj = monthly_df.get("monthly_labour_cost", pd.Series([0])).sum()
        st.caption(
            f"Total projected labour cost over planning horizon: **${total_proj:,.0f}** "
            f"at ${cost_cfg.hourly_agent_cost:.2f}/hr effective rate."
        )

        # Monthly summary table
        with st.expander("Monthly cost table"):
            display_cols = [
                c for c in [
                    "period_label", "available_fte", "required_fte",
                    "monthly_labour_cost", "monthly_required_cost", "monthly_cost_gap",
                ] if c in monthly_df.columns
            ]
            st.dataframe(monthly_df[display_cols].round(2), use_container_width=True)

        # Store for downloads
        st.session_state["cost_monthly_df"] = monthly_df

    else:
        st.info(
            "Run a workforce projection in the **Workforce Planning** tab to see a "
            "monthly labour cost forecast here.",
            icon="ℹ️",
        )

    # ------------------------------------------------------------------
    # Raw interval data
    # ------------------------------------------------------------------
    with st.expander("Interval cost data (raw)"):
        show_cols = [
            c for c in [
                "x", "calls_offered", "agents_required", "agents_rostered",
                "overstaffing", "understaffing", "abandoned_calls",
                "labour_cost", "idle_cost", "sla_breach_cost",
                "total_cost", "cost_per_call",
            ] if c in cost_view.columns
        ]
        st.dataframe(cost_view[show_cols].round(4), use_container_width=True)
