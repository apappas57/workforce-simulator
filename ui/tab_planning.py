"""ui/tab_planning.py

Phase 7 — Strategic Workforce Planning tab.

Renders planning parameter inputs, CSV uploaders, and the projection output
(summary metrics, charts, and data table).  Stores results in session state
for tab_downloads to consume.

Design rules (consistent with rest of app)
-------------------------------------------
- This tab owns its own inputs (file uploaders + planning params).
- It writes to session state keys registered in _init_session_state().
- The projection engine (planning/workforce_planner.py) is pure Python;
  no Streamlit calls live there.
- Shrinkage is passed in from the top-level SimConfig so the planning FTE
  basis is consistent with the operational model.
"""

import math
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from persistence import state_manager
from planning.workforce_planner import PlanningParams, project_workforce

try:
    from planning.hiring_loader import load_hiring_plan, load_required_fte_plan
    _loader_available = True
except ImportError:
    _loader_available = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_metric(value, fmt="{:.1f}", fallback="—"):
    """Format a float metric, returning fallback if NaN."""
    try:
        if math.isnan(float(value)):
            return fallback
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return fallback


def _headcount_chart(projection: pd.DataFrame) -> go.Figure:
    """Closing headcount line + new hires / attrition bars."""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=projection["period_label"],
        y=projection["closing_headcount"],
        name="Closing headcount",
        mode="lines+markers",
        line=dict(color="#4C78A8", width=2),
        marker=dict(size=6),
    ))
    fig.add_trace(go.Scatter(
        x=projection["period_label"],
        y=projection["opening_headcount"],
        name="Opening headcount",
        mode="lines",
        line=dict(color="#9ECAE9", width=1.5, dash="dot"),
    ))
    fig.add_trace(go.Bar(
        x=projection["period_label"],
        y=projection["new_hires"],
        name="New hires",
        marker_color="#54A24B",
        opacity=0.75,
        yaxis="y",
    ))
    fig.add_trace(go.Bar(
        x=projection["period_label"],
        y=[-v for v in projection["attrition"]],
        name="Attrition",
        marker_color="#E45756",
        opacity=0.75,
    ))

    fig.update_layout(
        barmode="overlay",
        xaxis_title="Period",
        yaxis_title="Headcount",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40),
    )
    return fig


def _pipeline_chart(projection: pd.DataFrame) -> go.Figure:
    """Stacked bar: productive / in ramp / in training breakdown."""
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=projection["period_label"],
        y=projection["productive_headcount"],
        name="Productive",
        marker_color="#4C78A8",
    ))
    fig.add_trace(go.Bar(
        x=projection["period_label"],
        y=projection["in_ramp"],
        name="In ramp",
        marker_color="#F58518",
    ))
    fig.add_trace(go.Bar(
        x=projection["period_label"],
        y=projection["in_training"],
        name="In training",
        marker_color="#E45756",
    ))

    fig.update_layout(
        barmode="stack",
        xaxis_title="Period",
        yaxis_title="Headcount",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40),
    )
    return fig


def _fte_capacity_chart(projection: pd.DataFrame) -> go.Figure:
    """Available FTE vs required FTE, with surplus/deficit band."""
    fig = go.Figure()

    has_req = not projection["required_fte"].isna().all()

    if has_req:
        # Surplus/deficit filled band
        labels = list(projection["period_label"])
        avail = list(projection["available_fte"])
        req = list(projection["required_fte"].fillna(method="ffill").fillna(0))

        fig.add_trace(go.Scatter(
            x=labels + labels[::-1],
            y=avail + req[::-1],
            fill="toself",
            fillcolor="rgba(76,120,168,0.12)",
            line=dict(color="rgba(255,255,255,0)"),
            name="Surplus / deficit band",
            showlegend=True,
            hoverinfo="skip",
        ))

        fig.add_trace(go.Scatter(
            x=projection["period_label"],
            y=projection["required_fte"],
            name="Required FTE",
            mode="lines+markers",
            line=dict(color="#E45756", width=2, dash="dash"),
            marker=dict(size=5),
        ))

    fig.add_trace(go.Scatter(
        x=projection["period_label"],
        y=projection["available_fte"],
        name="Available FTE",
        mode="lines+markers",
        line=dict(color="#4C78A8", width=2),
        marker=dict(size=6),
    ))

    fig.update_layout(
        xaxis_title="Period",
        yaxis_title="FTE",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40),
    )
    return fig


# ---------------------------------------------------------------------------
# Public render function
# ---------------------------------------------------------------------------

def render_planning_tab(shrinkage_pct: float) -> None:
    """Render the Workforce Planning tab.

    Parameters
    ----------
    shrinkage_pct : float
        Shrinkage percentage from the main SimConfig (e.g. 35.0 for 35 %).
        Applied to effective_fte to produce available_fte, keeping the planning
        FTE basis consistent with the operational model.
    """
    st.subheader("Strategic Workforce Planning")
    st.caption(
        "Projects headcount and effective FTE over a multi-month planning horizon, "
        "modelling monthly attrition, hire cohorts, training pipelines, and ramp-up periods."
    )

    if not _loader_available:
        st.error("Planning loader module could not be imported. Check planning/hiring_loader.py.")
        return

    # -----------------------------------------------------------------------
    # Planning parameters
    # -----------------------------------------------------------------------
    with st.expander("Planning parameters", expanded=True):
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            st.markdown("**Headcount & horizon**")
            planning_start = st.date_input(
                "Planning start date",
                value=pd.Timestamp("today").replace(day=1).date(),
                key="planning_start_date",
            )
            horizon = st.number_input(
                "Planning horizon (months)",
                min_value=1, max_value=36, value=12, step=1,
                key="planning_horizon_months",
            )
            opening_hc = st.number_input(
                "Opening headcount",
                min_value=0, max_value=10000, value=100, step=1,
                key="planning_opening_hc",
                help="Total headcount at the start of the first planning period.",
            )

        with col_b:
            st.markdown("**Attrition**")
            attrition_rate = st.number_input(
                "Monthly attrition rate (%)",
                min_value=0.0, max_value=50.0, value=3.0, step=0.1,
                format="%.1f",
                key="planning_attrition_rate",
                help="Percentage of total headcount that leaves each month.",
            )
            st.markdown("**Training**")
            training_duration = st.number_input(
                "Training duration (months)",
                min_value=0.0, max_value=12.0, value=2.0, step=0.5,
                format="%.1f",
                key="planning_training_duration",
                help="Months before a new hire graduates from training.",
            )
            training_productivity = st.number_input(
                "Productivity during training (%)",
                min_value=0.0, max_value=100.0, value=0.0, step=5.0,
                format="%.0f",
                key="planning_training_productivity",
                help="FTE contribution during training (0 = invisible to FTE count).",
            )

        with col_c:
            st.markdown("**Post-training ramp**")
            ramp_duration = st.number_input(
                "Ramp duration (months)",
                min_value=0.0, max_value=12.0, value=3.0, step=0.5,
                format="%.1f",
                key="planning_ramp_duration",
                help="Months of productivity ramp after training graduation.",
            )
            ramp_start = st.number_input(
                "Productivity at ramp start (%)",
                min_value=0.0, max_value=100.0, value=60.0, step=5.0,
                format="%.0f",
                key="planning_ramp_start_pct",
                help="FTE % on the first month post-training; linearly ramps to 100 %.",
            )
            st.markdown("**Shrinkage**")
            st.info(
                f"Using **{shrinkage_pct:.1f} %** from the sidebar.  "
                "Applied to effective FTE to compute available FTE.",
                icon="ℹ️",
            )

    # -----------------------------------------------------------------------
    # CSV uploaders
    # -----------------------------------------------------------------------
    st.divider()
    col_up1, col_up2 = st.columns(2)

    with col_up1:
        st.markdown("**Hiring plan** *(optional)*")
        st.caption("CSV with columns: `period_start` (YYYY-MM-DD), `planned_hires`")
        hiring_file = st.file_uploader(
            "Upload hiring_plan.csv", type=["csv"], key="planning_hiring_upload"
        )

    with col_up2:
        st.markdown("**Required FTE plan** *(optional)*")
        st.caption("CSV with columns: `period_start` (YYYY-MM-DD), `required_fte`")
        req_fte_file = st.file_uploader(
            "Upload required_fte_plan.csv", type=["csv"], key="planning_req_fte_upload"
        )

    # -----------------------------------------------------------------------
    # Load CSVs
    # -----------------------------------------------------------------------
    hiring_df: Optional[pd.DataFrame] = None
    req_fte_df: Optional[pd.DataFrame] = None

    if hiring_file is not None:
        try:
            hiring_df = load_hiring_plan(hiring_file)
            st.success(f"Hiring plan loaded — {len(hiring_df)} period(s).")
        except Exception as exc:
            st.error(f"Hiring plan error: {exc}")

    if req_fte_file is not None:
        try:
            req_fte_df = load_required_fte_plan(req_fte_file)
            st.success(f"Required FTE plan loaded — {len(req_fte_df)} period(s).")
        except Exception as exc:
            st.error(f"Required FTE plan error: {exc}")

    # -----------------------------------------------------------------------
    # Run projection
    # -----------------------------------------------------------------------
    params = PlanningParams(
        planning_start_date=pd.Timestamp(planning_start),
        planning_horizon_months=int(horizon),
        opening_headcount=int(opening_hc),
        monthly_attrition_rate_pct=float(attrition_rate),
        training_duration_months=float(training_duration),
        training_productivity_pct=float(training_productivity),
        ramp_duration_months=float(ramp_duration),
        ramp_start_pct=float(ramp_start),
        shrinkage_pct=float(shrinkage_pct),
    )

    try:
        projection = project_workforce(params, hiring_df, req_fte_df)
    except Exception as exc:
        st.error(f"Projection error: {exc}")
        return

    # Persist to session state for downloads tab
    st.session_state["planning_projection"] = projection
    if hiring_df is not None:
        st.session_state["planning_hiring_plan"] = hiring_df
    if req_fte_df is not None:
        st.session_state["planning_required_fte"] = req_fte_df

    # Phase 9: persist results and current widget values to disk
    state_manager.save_dataframe("planning_projection", projection)
    if hiring_df is not None:
        state_manager.save_dataframe("planning_hiring_plan", hiring_df)
    if req_fte_df is not None:
        state_manager.save_dataframe("planning_required_fte", req_fte_df)
    state_manager.save_settings(st.session_state)

    # -----------------------------------------------------------------------
    # Summary metrics
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("Summary")

    closing_final = projection["closing_headcount"].iloc[-1] if not projection.empty else 0
    total_hires   = int(projection["new_hires"].sum()) if not projection.empty else 0
    peak_attr     = int(projection["attrition"].max()) if not projection.empty else 0

    valid_surplus = projection["surplus_deficit"].dropna()
    avg_surplus   = valid_surplus.mean() if not valid_surplus.empty else float("nan")
    months_below  = int((valid_surplus < 0).sum()) if not valid_surplus.empty else 0
    has_req_data  = req_fte_df is not None

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Closing headcount",      int(closing_final))
    m2.metric("Total hires planned",    total_hires)
    m3.metric("Peak monthly attrition", peak_attr)
    m4.metric("Avg monthly surplus FTE", _safe_metric(avg_surplus, fmt="{:+.1f}") if has_req_data else "—")
    m5.metric("Months below FTE target", months_below if has_req_data else "—")

    if not has_req_data:
        st.caption(
            "Upload a required FTE plan to see surplus/deficit metrics and the capacity chart."
        )

    # -----------------------------------------------------------------------
    # Charts
    # -----------------------------------------------------------------------
    st.divider()

    st.subheader("Headcount over time")
    st.plotly_chart(_headcount_chart(projection), use_container_width=True)

    st.subheader("Workforce pipeline breakdown")
    st.caption(
        "Stacked headcount by state each month.  "
        "Training and ramp agents contribute partial FTE — see available FTE chart for the net effect."
    )
    st.plotly_chart(_pipeline_chart(projection), use_container_width=True)

    st.subheader("Available FTE vs required FTE")
    if not has_req_data:
        st.caption("Upload a required FTE plan to overlay the FTE target on this chart.")
    st.plotly_chart(_fte_capacity_chart(projection), use_container_width=True)

    # -----------------------------------------------------------------------
    # Data table
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("Projection table")

    display_df = projection.copy()
    display_df["period_start"] = display_df["period_start"].dt.strftime("%Y-%m-%d")
    st.dataframe(display_df, use_container_width=True, hide_index=True)
