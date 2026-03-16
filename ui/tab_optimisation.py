"""ui/tab_optimisation.py

Phase 8 — Hiring Optimisation tab.

Self-contained: owns its own parameter inputs and required FTE CSV uploader.
Runs the LP optimiser, displays the optimal hiring plan and cost breakdown,
and compares results across three attrition scenarios.

Stores results in session state for tab_downloads to consume.
"""

import math
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from persistence import state_manager
from planning.workforce_planner import PlanningParams
from planning.hiring_loader import load_required_fte_plan
from optimisation.workforce_optimiser import (
    OptimisationParams,
    optimise_hiring_plan,
    optimise_scenarios,
)


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def _optimal_hires_chart(result_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=result_df["period_label"],
        y=result_df["optimal_hires"],
        name="Optimal hires",
        marker_color="#54A24B",
    ))
    fig.update_layout(
        xaxis_title="Period",
        yaxis_title="Hires",
        margin=dict(t=40),
    )
    return fig


def _fte_vs_required_chart(result_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    # Surplus/deficit band
    labels = list(result_df["period_label"])
    avail = list(result_df["available_fte"])
    req = list(result_df["required_fte"])

    fig.add_trace(go.Scatter(
        x=labels + labels[::-1],
        y=avail + req[::-1],
        fill="toself",
        fillcolor="rgba(76,120,168,0.12)",
        line=dict(color="rgba(255,255,255,0)"),
        name="Surplus / deficit band",
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=result_df["period_label"],
        y=result_df["required_fte"],
        name="Required FTE",
        mode="lines+markers",
        line=dict(color="#E45756", width=2, dash="dash"),
        marker=dict(size=5),
    ))
    fig.add_trace(go.Scatter(
        x=result_df["period_label"],
        y=result_df["available_fte"],
        name="Available FTE (optimal plan)",
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


def _cost_breakdown_chart(result_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=result_df["period_label"],
        y=result_df["hire_cost"],
        name="Hire cost",
        marker_color="#54A24B",
    ))
    fig.add_trace(go.Bar(
        x=result_df["period_label"],
        y=result_df["surplus_cost"],
        name="Surplus cost",
        marker_color="#F58518",
    ))
    fig.add_trace(go.Bar(
        x=result_df["period_label"],
        y=result_df["deficit_cost"],
        name="Deficit cost",
        marker_color="#E45756",
    ))
    fig.update_layout(
        barmode="stack",
        xaxis_title="Period",
        yaxis_title="Cost",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40),
    )
    return fig


def _scenario_comparison_chart(scenario_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=scenario_df["scenario"],
        y=scenario_df["total_hires"],
        name="Total hires",
        marker_color="#4C78A8",
        yaxis="y",
    ))
    fig.add_trace(go.Scatter(
        x=scenario_df["scenario"],
        y=scenario_df["total_cost"],
        name="Total cost",
        mode="lines+markers",
        line=dict(color="#E45756", width=2),
        marker=dict(size=8),
        yaxis="y2",
    ))
    fig.update_layout(
        yaxis=dict(title="Total hires"),
        yaxis2=dict(title="Total cost", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40),
    )
    return fig


# ---------------------------------------------------------------------------
# Public render function
# ---------------------------------------------------------------------------

def render_optimisation_tab(shrinkage_pct: float) -> None:
    """Render the Hiring Optimisation tab.

    Parameters
    ----------
    shrinkage_pct : float
        From SimConfig — kept consistent with operational model.
    """
    st.subheader("Hiring Optimisation")
    st.caption(
        "Finds the monthly hiring plan that minimises total cost across the planning horizon, "
        "subject to a per-month hiring capacity constraint. "
        "Compares the optimal plan across low / base / high attrition scenarios."
    )

    # -------------------------------------------------------------------
    # Parameters
    # -------------------------------------------------------------------
    with st.expander("Workforce parameters", expanded=True):
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            st.markdown("**Headcount & horizon**")
            planning_start = st.date_input(
                "Planning start date",
                value=pd.Timestamp("today").replace(day=1).date(),
                key="opt_planning_start",
            )
            horizon = st.number_input(
                "Planning horizon (months)",
                min_value=1, max_value=36, value=12, step=1,
                key="opt_horizon",
            )
            opening_hc = st.number_input(
                "Opening headcount",
                min_value=0, max_value=10000, value=100, step=1,
                key="opt_opening_hc",
            )

        with col_b:
            st.markdown("**Attrition**")
            attrition_rate = st.number_input(
                "Monthly attrition rate (%)",
                min_value=0.0, max_value=50.0, value=3.0, step=0.1, format="%.1f",
                key="opt_attrition_rate",
            )
            st.markdown("**Training**")
            training_duration = st.number_input(
                "Training duration (months)",
                min_value=0.0, max_value=12.0, value=2.0, step=0.5, format="%.1f",
                key="opt_training_duration",
            )
            training_productivity = st.number_input(
                "Productivity during training (%)",
                min_value=0.0, max_value=100.0, value=0.0, step=5.0, format="%.0f",
                key="opt_training_productivity",
            )

        with col_c:
            st.markdown("**Ramp**")
            ramp_duration = st.number_input(
                "Ramp duration (months)",
                min_value=0.0, max_value=12.0, value=3.0, step=0.5, format="%.1f",
                key="opt_ramp_duration",
            )
            ramp_start = st.number_input(
                "Productivity at ramp start (%)",
                min_value=0.0, max_value=100.0, value=60.0, step=5.0, format="%.0f",
                key="opt_ramp_start",
            )
            st.markdown("**Shrinkage**")
            st.info(f"Using **{shrinkage_pct:.1f} %** from the sidebar.", icon="ℹ️")

    with st.expander("Cost & constraint parameters", expanded=True):
        col_c1, col_c2, col_c3, col_c4 = st.columns(4)
        with col_c1:
            cost_hire = st.number_input(
                "Cost per hire",
                min_value=0.0, value=5000.0, step=100.0, format="%.0f",
                key="opt_cost_hire",
                help="One-off cost per new hire.",
            )
        with col_c2:
            cost_surplus = st.number_input(
                "Cost per surplus FTE-month",
                min_value=0.0, value=200.0, step=50.0, format="%.0f",
                key="opt_cost_surplus",
                help="Cost of carrying one FTE above target for one month.",
            )
        with col_c3:
            cost_deficit = st.number_input(
                "Cost per deficit FTE-month",
                min_value=0.0, value=1500.0, step=100.0, format="%.0f",
                key="opt_cost_deficit",
                help="Penalty for one FTE below target for one month. "
                     "Set higher than surplus cost to penalise understaffing.",
            )
        with col_c4:
            max_hires = st.number_input(
                "Max hires per month",
                min_value=0, max_value=500, value=20, step=1,
                key="opt_max_hires",
                help="Hard cap on hires per period (onboarding / recruiter capacity).",
            )

    with st.expander("Scenario parameters", expanded=False):
        attrition_variance = st.number_input(
            "Attrition variance (±pp)",
            min_value=0.0, max_value=10.0, value=2.0, step=0.5, format="%.1f",
            key="opt_attrition_variance",
            help="Scenarios run at base - variance, base, base + variance attrition rates.",
        )

    # -------------------------------------------------------------------
    # Required FTE CSV uploader
    # -------------------------------------------------------------------
    st.divider()
    st.markdown("**Required FTE plan** *(required to run optimiser)*")
    st.caption("CSV with columns: `period_start` (YYYY-MM-DD), `required_fte`")
    req_fte_file = st.file_uploader(
        "Upload required_fte_plan.csv", type=["csv"], key="opt_req_fte_upload"
    )

    req_fte_df: Optional[pd.DataFrame] = None
    if req_fte_file is not None:
        try:
            req_fte_df = load_required_fte_plan(req_fte_file)
            st.success(f"Required FTE plan loaded — {len(req_fte_df)} period(s).")
        except Exception as exc:
            st.error(f"Required FTE plan error: {exc}")

    if req_fte_df is None:
        st.info(
            "Upload a required FTE plan to run the optimiser. "
            "The optimiser will find the cheapest hiring plan to meet the FTE target."
        )
        return

    # -------------------------------------------------------------------
    # Build parameters and run optimiser
    # -------------------------------------------------------------------
    planning_params = PlanningParams(
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

    opt_params = OptimisationParams(
        planning=planning_params,
        required_fte_df=req_fte_df,
        cost_per_hire=float(cost_hire),
        cost_per_surplus_fte_month=float(cost_surplus),
        cost_per_deficit_fte_month=float(cost_deficit),
        max_hires_per_month=int(max_hires),
    )

    with st.spinner("Running LP optimiser…"):
        result_df, status = optimise_hiring_plan(opt_params)

    if status != "Optimal" or result_df.empty:
        st.error(
            f"Optimiser did not find an optimal solution (status: {status}). "
            "Check that max_hires_per_month is large enough to meet the FTE target."
        )
        return

    # Store in session state
    st.session_state["optimisation_result"] = result_df

    with st.spinner("Running scenario comparison…"):
        scenario_df = optimise_scenarios(opt_params, float(attrition_variance))

    st.session_state["optimisation_scenarios"] = scenario_df

    # Phase 9: persist results and current widget values to disk
    state_manager.save_dataframe("optimisation_result", result_df)
    state_manager.save_dataframe("optimisation_scenarios", scenario_df)
    state_manager.save_settings(st.session_state)

    # -------------------------------------------------------------------
    # Summary metrics
    # -------------------------------------------------------------------
    st.divider()
    st.subheader("Optimal plan summary")

    total_hires = int(result_df["optimal_hires"].sum())
    total_cost  = result_df["period_total_cost"].sum()
    total_h_cost = result_df["hire_cost"].sum()
    total_s_cost = result_df["surplus_cost"].sum()
    total_d_cost = result_df["deficit_cost"].sum()
    months_deficit = int((result_df["deficit"] > 0.05).sum())
    avg_surplus = result_df["surplus"].mean()

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total hires recommended", total_hires)
    m2.metric("Total cost", f"{total_cost:,.0f}")
    m3.metric("Hire cost", f"{total_h_cost:,.0f}")
    m4.metric("Months in deficit", months_deficit)
    m5.metric("Avg monthly surplus FTE", f"{avg_surplus:.1f}")

    # -------------------------------------------------------------------
    # Charts — base scenario
    # -------------------------------------------------------------------
    st.divider()
    st.subheader("Optimal hiring plan")
    st.plotly_chart(_optimal_hires_chart(result_df), use_container_width=True)

    st.subheader("Available FTE vs required FTE")
    st.plotly_chart(_fte_vs_required_chart(result_df), use_container_width=True)

    st.subheader("Cost breakdown by period")
    st.plotly_chart(_cost_breakdown_chart(result_df), use_container_width=True)

    # -------------------------------------------------------------------
    # Scenario comparison
    # -------------------------------------------------------------------
    st.divider()
    st.subheader("Scenario comparison")
    st.caption(
        f"Optimiser re-run under base ± {attrition_variance:.1f} pp attrition. "
        "Shows how much the hiring plan and cost change with different attrition assumptions."
    )

    if not scenario_df.empty:
        st.plotly_chart(_scenario_comparison_chart(scenario_df), use_container_width=True)
        display_scenario = scenario_df.copy()
        for col in ["total_hire_cost", "total_surplus_cost", "total_deficit_cost", "total_cost"]:
            if col in display_scenario.columns:
                display_scenario[col] = display_scenario[col].apply(
                    lambda x: f"{x:,.0f}" if pd.notna(x) else "—"
                )
        st.dataframe(display_scenario, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------
    # Data table — optimal plan detail
    # -------------------------------------------------------------------
    st.divider()
    st.subheader("Optimal plan — period detail")
    display_df = result_df.copy()
    display_df["period_start"] = display_df["period_start"].dt.strftime("%Y-%m-%d")
    for col in ["hire_cost", "surplus_cost", "deficit_cost", "period_total_cost"]:
        display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f}")
    st.dataframe(display_df, use_container_width=True, hide_index=True)
