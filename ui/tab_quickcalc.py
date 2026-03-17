"""ui/tab_quickcalc.py

Phase 22 — Quick Erlang C Calculator.

Lightweight single-interval calculator — enter calls, AHT, SL target and
threshold, get agents required instantly.  No CSV, no simulation, no sidebar
dependency.  Useful for rapid "what does Monday morning need?" lookups.
"""

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from models.erlang import (
    erlang_c_service_level,
    erlang_c_asa_seconds,
    solve_staffing_erlang_for_interval,
)
from ui.charts import apply_dark_theme, C_REQUIREMENT, PALETTE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _traffic_intensity(calls: float, interval_seconds: float, aht: float) -> float:
    lam = calls / max(interval_seconds, 1.0)
    mu = 1.0 / max(aht, 1e-9)
    return lam / mu


def _sensitivity_table(
    calls: float,
    interval_seconds: float,
    aht: float,
    sl_target: float,
    sl_threshold: float,
    net_agents: int,
    window: int = 8,
) -> pd.DataFrame:
    """Sweep ±window agents around net_agents; return SL/ASA/occ per agent count."""
    a = _traffic_intensity(calls, interval_seconds, aht)
    rows = []
    lo = max(1, net_agents - window)
    hi = net_agents + window + 1
    for c in range(lo, hi):
        if a >= c:
            rows.append(
                dict(agents=c, occupancy_pct=None, sl_pct=None, asa_seconds=None, meets_target=False)
            )
        else:
            sl = erlang_c_service_level(a, c, aht, sl_threshold)
            asa = erlang_c_asa_seconds(a, c, aht)
            occ = a / c
            rows.append(
                dict(
                    agents=c,
                    occupancy_pct=round(occ * 100, 1),
                    sl_pct=round(sl * 100, 1),
                    asa_seconds=round(asa, 1),
                    meets_target=sl >= sl_target,
                )
            )
    return pd.DataFrame(rows)


def _sensitivity_chart(sens_df: pd.DataFrame, sl_target: float, net_agents: int) -> go.Figure:
    valid = sens_df.dropna(subset=["sl_pct"])
    fig = go.Figure()

    # SL% area
    fig.add_trace(
        go.Scatter(
            x=valid["agents"],
            y=valid["sl_pct"],
            mode="lines+markers",
            name="Predicted SL %",
            line=dict(color=PALETTE[0], width=2),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor=f"rgba(99,102,241,0.08)",
        )
    )

    # Occupancy % on secondary y-axis
    fig.add_trace(
        go.Scatter(
            x=valid["agents"],
            y=valid["occupancy_pct"],
            mode="lines+markers",
            name="Occupancy %",
            line=dict(color=PALETTE[2], width=2, dash="dot"),
            marker=dict(size=5),
            yaxis="y2",
        )
    )

    # SL target reference line
    fig.add_hline(
        y=sl_target * 100,
        line_dash="dot",
        line_color=C_REQUIREMENT,
        annotation_text=f"Target {sl_target*100:.0f}%",
        annotation_position="top right",
        annotation_font_size=11,
    )

    # Required agents marker
    fig.add_vline(
        x=net_agents,
        line_dash="dash",
        line_color=PALETTE[1],
        annotation_text=f"Required: {net_agents}",
        annotation_position="top left",
        annotation_font_size=11,
    )

    fig.update_layout(
        title="Service level & occupancy vs agents",
        xaxis_title="Net agents",
        yaxis=dict(title="Service level %", range=[0, 105]),
        yaxis2=dict(title="Occupancy %", overlaying="y", side="right", range=[0, 105]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    apply_dark_theme(fig)
    return fig


# ---------------------------------------------------------------------------
# Tab renderer
# ---------------------------------------------------------------------------

def render_quickcalc_tab() -> None:
    """Render the Quick Erlang C Calculator tab (Phase 22)."""
    st.subheader("Quick Erlang C calculator")
    st.caption(
        "Single-interval calculator — enter your demand and service parameters "
        "to get an instant staffing estimate. No data upload required."
    )

    # ── Inputs ──────────────────────────────────────────────────────────────
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.markdown("**Demand**")
        calls = float(
            st.number_input(
                "Calls per interval",
                min_value=1,
                max_value=50_000,
                value=150,
                step=5,
                key="qc_calls",
            )
        )
        aht = float(
            st.number_input(
                "AHT (seconds)",
                min_value=1,
                max_value=7_200,
                value=300,
                step=10,
                key="qc_aht",
            )
        )
        interval_min = int(
            st.selectbox(
                "Interval length",
                [15, 30, 60],
                index=0,
                key="qc_interval_min",
                format_func=lambda x: f"{x} min",
            )
        )

    with col_b:
        st.markdown("**Service level**")
        sl_target_pct = st.slider(
            "SL target %", min_value=50, max_value=99, value=80, step=1, key="qc_sl_target"
        )
        sl_threshold_sec = float(
            st.number_input(
                "Answer within (seconds)",
                min_value=1,
                max_value=600,
                value=20,
                step=5,
                key="qc_sl_threshold",
            )
        )

    with col_c:
        st.markdown("**Staffing**")
        shrinkage_pct = st.slider(
            "Shrinkage %", min_value=0, max_value=60, value=20, step=1, key="qc_shrinkage"
        )
        occupancy_cap_pct = st.slider(
            "Max occupancy %", min_value=50, max_value=99, value=85, step=1, key="qc_occ_cap"
        )

    # ── Compute ─────────────────────────────────────────────────────────────
    interval_seconds = interval_min * 60.0
    sl_target = sl_target_pct / 100.0
    occupancy_cap = occupancy_cap_pct / 100.0
    shrinkage = shrinkage_pct / 100.0

    net_agents, pred_sl, pred_asa, pred_occ = solve_staffing_erlang_for_interval(
        calls_offered=calls,
        interval_seconds=interval_seconds,
        aht_seconds=aht,
        sl_target=sl_target,
        sl_threshold_seconds=sl_threshold_sec,
        occupancy_cap=occupancy_cap,
    )

    paid_agents = math.ceil(net_agents / max(1.0 - shrinkage, 1e-9))
    a = _traffic_intensity(calls, interval_seconds, aht)

    # ── Results ─────────────────────────────────────────────────────────────
    st.divider()
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Net agents", net_agents, help="Minimum agents to meet SL and occupancy target")
    m2.metric("Paid agents", paid_agents, help="Net agents grossed up for shrinkage")
    m3.metric("Predicted SL", f"{pred_sl * 100:.1f}%")
    m4.metric("Predicted ASA", f"{pred_asa:.1f}s")
    m5.metric("Predicted occupancy", f"{pred_occ * 100:.1f}%")
    m6.metric("Traffic intensity", f"{a:.2f} E", help="Offered load in Erlangs (calls × AHT / interval)")

    # ── Sensitivity chart ───────────────────────────────────────────────────
    st.divider()
    sens_df = _sensitivity_table(
        calls=calls,
        interval_seconds=interval_seconds,
        aht=aht,
        sl_target=sl_target,
        sl_threshold=sl_threshold_sec,
        net_agents=net_agents,
        window=8,
    )
    st.plotly_chart(_sensitivity_chart(sens_df, sl_target, net_agents), use_container_width=True)

    with st.expander("Sensitivity table", expanded=False):
        display_df = sens_df.rename(
            columns={
                "agents": "Agents",
                "occupancy_pct": "Occupancy %",
                "sl_pct": "SL %",
                "asa_seconds": "ASA (s)",
                "meets_target": "Meets target",
            }
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
