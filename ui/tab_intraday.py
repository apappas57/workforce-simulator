"""ui/tab_intraday.py — Intraday Reforecast tab (Phase 26).

Allows the user to input actual call volumes received so far today and
reproject staffing requirements for remaining intervals. Useful for
real-time operational decisions when actual demand deviates from plan.

Requires the Demand tab to have been run first (df_erlang in session state).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config.sim_config import SimConfig
from models.deterministic import deterministic_staffing
from models.erlang import solve_staffing_erlang
from ui.charts import PALETTE, apply_dark_theme

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    _plotly_ok = True
except ImportError:
    _plotly_ok = False


def _interval_to_hhmm(interval: int, interval_minutes: int) -> str:
    """Convert interval index to HH:MM string."""
    total_minutes = interval * interval_minutes
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}"


def _reforecast(
    df_erlang: pd.DataFrame,
    current_interval: int,
    actual_calls: float,
    actual_aht: float | None,
    cfg: SimConfig,
) -> pd.DataFrame:
    """Return a reforecast DataFrame merging actuals with scaled projections.

    Parameters
    ----------
    df_erlang : DataFrame
        Original Erlang C results from the Demand tab.
    current_interval : int
        Index of the current interval (intervals 0..current_interval-1 elapsed).
    actual_calls : float
        Total calls received across all elapsed intervals.
    actual_aht : float or None
        Observed AHT in seconds; None keeps the plan AHT.
    cfg : SimConfig
        Simulation config.

    Returns
    -------
    DataFrame
        One row per interval with original and reforecast columns.
    """
    df = df_erlang.copy().reset_index(drop=True)
    n = len(df)
    current_interval = max(1, min(current_interval, n))

    # ── Scale factor ──────────────────────────────────────────────────────────
    planned_so_far = df.loc[:current_interval - 1, "calls_offered"].sum()
    if planned_so_far > 0 and actual_calls >= 0:
        scale = actual_calls / planned_so_far
    else:
        scale = 1.0

    # ── Build reforecast calls_offered ───────────────────────────────────────
    reforecast_calls = df["calls_offered"].copy()
    # Elapsed intervals: replace with actuals spread proportionally
    if planned_so_far > 0:
        reforecast_calls.iloc[:current_interval] = (
            df["calls_offered"].iloc[:current_interval] * scale
        )
    # Remaining intervals: scale by same factor
    reforecast_calls.iloc[current_interval:] = (
        df["calls_offered"].iloc[current_interval:] * scale
    )

    # ── Build reforecast DataFrame ────────────────────────────────────────────
    df_rf = df[["calls_offered", "interval"]].copy()
    df_rf["calls_offered"] = reforecast_calls

    # Override AHT if provided
    if actual_aht is not None and actual_aht > 0:
        df_rf["aht_seconds"] = actual_aht

    # Re-run deterministic + Erlang C on reforecast demand
    df_rf_det = deterministic_staffing(df_rf, cfg)
    df_rf_erl = solve_staffing_erlang(df_rf_det, cfg)

    # ── Merge original and reforecast side by side ───────────────────────────
    result = df[["interval", "calls_offered",
                 "erlang_required_net_agents",
                 "erlang_pred_service_level",
                 "erlang_pred_occupancy"]].copy()
    result.columns = ["interval", "plan_calls", "plan_agents",
                      "plan_sl", "plan_occ"]
    result["rf_calls"]  = df_rf_erl["calls_offered"].values
    result["rf_agents"] = df_rf_erl["erlang_required_net_agents"].values
    result["rf_sl"]     = df_rf_erl["erlang_pred_service_level"].values
    result["rf_occ"]    = df_rf_erl["erlang_pred_occupancy"].values
    result["elapsed"]   = result["interval"] < current_interval
    result["agent_gap"] = result["rf_agents"] - result["plan_agents"]
    result["hhmm"]      = result["interval"].apply(
        lambda i: _interval_to_hhmm(i, cfg.interval_minutes)
    )
    result["scale_factor"] = scale
    return result


def render_intraday_tab(df_erlang: pd.DataFrame | None, cfg: SimConfig) -> None:
    """Render the Intraday Reforecast tab."""

    st.header("Intraday Reforecast")
    st.caption(
        "Input actual call volumes received so far today to reproject staffing "
        "requirements for the rest of the day. Run the Demand tab first to generate "
        "a plan."
    )

    if df_erlang is None or df_erlang.empty:
        st.info("Run the **Demand** tab first to generate a staffing plan.")
        return

    n_intervals = len(df_erlang)
    interval_minutes = cfg.interval_minutes

    # ── Inputs ────────────────────────────────────────────────────────────────
    st.subheader("Current position")

    col1, col2, col3 = st.columns(3)

    with col1:
        current_interval = st.slider(
            "Current interval",
            min_value=1,
            max_value=n_intervals - 1,
            value=min(int(n_intervals * 0.33), n_intervals - 1),
            help="How many intervals have elapsed so far today.",
            key="intraday_current_interval",
            format="%d",
        )
        elapsed_hhmm = _interval_to_hhmm(current_interval, interval_minutes)
        st.caption(f"Current time: **{elapsed_hhmm}**")

    with col2:
        planned_so_far = float(
            df_erlang["calls_offered"].iloc[:current_interval].sum()
        )
        actual_calls = st.number_input(
            "Actual calls received so far",
            min_value=0.0,
            value=round(planned_so_far, 1),
            step=1.0,
            help="Total calls handled/offered across all elapsed intervals.",
            key="intraday_actual_calls",
        )

    with col3:
        plan_aht = float(df_erlang.get("aht_seconds_used",
                         pd.Series([cfg.aht_seconds])).iloc[0])
        override_aht = st.checkbox(
            "Override AHT",
            value=False,
            key="intraday_override_aht",
        )
        actual_aht: float | None = None
        if override_aht:
            actual_aht = st.number_input(
                "Observed AHT (seconds)",
                min_value=30.0,
                value=plan_aht,
                step=5.0,
                key="intraday_actual_aht",
            )

    # ── Run reforecast ────────────────────────────────────────────────────────
    if st.button("⚡ Reforecast", type="primary", key="intraday_run"):
        with st.spinner("Reforecasting…"):
            result = _reforecast(
                df_erlang, current_interval, actual_calls, actual_aht, cfg
            )
            st.session_state["intraday_result"] = result

    result: pd.DataFrame | None = st.session_state.get("intraday_result")

    # Auto-run on first load with defaults
    if result is None:
        result = _reforecast(
            df_erlang, current_interval,
            float(df_erlang["calls_offered"].iloc[:current_interval].sum()),
            None, cfg
        )
        st.session_state["intraday_result"] = result

    # ── Summary metrics ───────────────────────────────────────────────────────
    st.divider()
    scale = float(result["scale_factor"].iloc[0])
    pct_diff = (scale - 1.0) * 100

    remaining = result[~result["elapsed"]]
    at_risk = int((remaining["agent_gap"] > 0).sum())
    peak_gap = int(remaining["agent_gap"].max()) if not remaining.empty else 0
    total_plan   = int(result["plan_calls"].sum())
    total_rf     = int(result["rf_calls"].sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Demand vs plan",
        f"{pct_diff:+.1f}%",
        delta=f"{pct_diff:+.1f}%",
        delta_color="inverse",
    )
    m2.metric("Projected day total", f"{total_rf:,}", delta=f"{total_rf - total_plan:+,}")
    m3.metric("At-risk intervals (remaining)", at_risk)
    m4.metric("Peak agent gap (remaining)", f"{peak_gap:+d}")

    # ── Charts ────────────────────────────────────────────────────────────────
    if not _plotly_ok:
        st.warning("Plotly not installed — charts unavailable.")
        st.dataframe(result)
        return

    st.divider()
    st.subheader("Demand: plan vs reforecast")

    fig_demand = go.Figure()
    fig_demand.add_trace(go.Bar(
        x=result["hhmm"],
        y=result["plan_calls"],
        name="Plan",
        marker_color=PALETTE[2],
        opacity=0.6,
    ))
    fig_demand.add_trace(go.Scatter(
        x=result["hhmm"],
        y=result["rf_calls"],
        name="Reforecast",
        mode="lines",
        line=dict(color=PALETTE[0], width=2),
    ))
    # Shade elapsed region
    if current_interval > 0:
        fig_demand.add_vrect(
            x0=result["hhmm"].iloc[0],
            x1=result["hhmm"].iloc[current_interval - 1],
            fillcolor="rgba(255,255,255,0.05)",
            layer="below", line_width=0,
            annotation_text="Elapsed", annotation_position="top left",
        )
    fig_demand.update_layout(
        xaxis_title="Interval",
        yaxis_title="Calls offered",
        legend=dict(orientation="h", y=1.1),
        height=320,
    )
    apply_dark_theme(fig_demand)
    st.plotly_chart(fig_demand, use_container_width=True)

    st.subheader("Agent requirement: plan vs reforecast")

    fig_agents = go.Figure()
    fig_agents.add_trace(go.Scatter(
        x=result["hhmm"],
        y=result["plan_agents"],
        name="Plan",
        mode="lines",
        line=dict(color=PALETTE[2], width=2, dash="dash"),
    ))
    fig_agents.add_trace(go.Scatter(
        x=result["hhmm"],
        y=result["rf_agents"],
        name="Reforecast",
        mode="lines",
        line=dict(color=PALETTE[0], width=2),
        fill="tonexty",
        fillcolor="rgba(99,102,241,0.15)",
    ))
    # Mark current time
    current_hhmm = _interval_to_hhmm(current_interval, interval_minutes)
    fig_agents.add_vline(
        x=current_hhmm,
        line_dash="dot",
        line_color=PALETTE[4],
        annotation_text="Now",
        annotation_position="top",
    )
    fig_agents.update_layout(
        xaxis_title="Interval",
        yaxis_title="Net agents required",
        legend=dict(orientation="h", y=1.1),
        height=320,
    )
    apply_dark_theme(fig_agents)
    st.plotly_chart(fig_agents, use_container_width=True)

    # ── At-risk intervals table ───────────────────────────────────────────────
    if at_risk > 0:
        st.subheader(f"⚠️ {at_risk} at-risk interval(s) in remaining day")
        at_risk_df = remaining[remaining["agent_gap"] > 0][
            ["hhmm", "plan_calls", "rf_calls", "plan_agents", "rf_agents", "agent_gap"]
        ].copy()
        at_risk_df.columns = [
            "Time", "Plan calls", "RF calls",
            "Plan agents", "RF agents", "Gap"
        ]
        st.dataframe(
            at_risk_df.style.background_gradient(
                subset=["Gap"], cmap="Reds"
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("No agent shortfalls projected for the remaining day.")

    # ── Projected SL ─────────────────────────────────────────────────────────
    with st.expander("Projected service level & occupancy (remaining intervals)"):
        fig_sl = go.Figure()
        fig_sl.add_trace(go.Scatter(
            x=remaining["hhmm"],
            y=(remaining["plan_sl"] * 100),
            name="Plan SL%",
            mode="lines",
            line=dict(color=PALETTE[2], dash="dash"),
        ))
        fig_sl.add_trace(go.Scatter(
            x=remaining["hhmm"],
            y=(remaining["rf_sl"] * 100),
            name="Reforecast SL%",
            mode="lines",
            line=dict(color=PALETTE[0]),
        ))
        fig_sl.add_hline(
            y=cfg.service_level_target * 100,
            line_dash="dot",
            line_color=PALETTE[4],
            annotation_text=f"Target {cfg.service_level_target*100:.0f}%",
        )
        fig_sl.update_layout(
            xaxis_title="Interval",
            yaxis_title="Service Level %",
            yaxis_range=[0, 105],
            legend=dict(orientation="h", y=1.1),
            height=280,
        )
        apply_dark_theme(fig_sl)
        st.plotly_chart(fig_sl, use_container_width=True)
